import os
import json
import random
import string
import hashlib
import base64
import logging
import datetime

from flask import render_template, request, redirect, url_for, Blueprint, session
from CTFd.models import Users, db
from CTFd.utils import validators, get_config, set_config
from CTFd.utils.crypto import verify_password
from CTFd.utils.helpers import get_errors
from CTFd.utils.plugins import override_template
from CTFd.utils.config import is_teams_mode
from CTFd.utils.logging import log
from CTFd.utils.security.auth import login_user
from CTFd.utils.decorators import admins_only

try:
    from cryptography.fernet import Fernet
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

# dnspython for custom DNS resolution (BUG 3)
try:
    import dns.resolver as _dns_resolver  # noqa: F401
    HAS_DNS = True
except ImportError:
    HAS_DNS = False

import ldap3
import ldap3.utils.conv

# ── Логгер ──────────────────────────────────────────────────────────────────
logger = logging.getLogger("ctfd.ldap_plugin")
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("[LDAP-PLUGIN] %(levelname)s - %(message)s"))
    logger.addHandler(_h)

# ── Ключи конфига ────────────────────────────────────────────────────────────
CFG_ENABLED       = "ldap_enabled"
CFG_HOST          = "ldap_host"
CFG_PORT          = "ldap_port"
CFG_USE_SSL       = "ldap_use_ssl"
CFG_USE_TLS       = "ldap_use_tls"
CFG_BASE_DN       = "ldap_base_dn"
CFG_DOMAIN        = "ldap_domain"
CFG_SEARCH_FILTER = "ldap_search_filter"
CFG_ATTR_EMAIL    = "ldap_attr_email"
CFG_LOCAL_ENABLED = "ldap_local_enabled"
CFG_DEBUG         = "ldap_debug"
CFG_CACHE_ENABLED = "ldap_cache_enabled"
CFG_CACHE_TTL     = "ldap_cache_ttl"
CFG_DNS           = "ldap_dns_server"  # BUG 3 — custom DNS for hostname resolution


def _default_settings():
    defaults = {
        CFG_ENABLED:       "true",
        CFG_HOST:          "winserv.ctfd.loc",
        CFG_PORT:          "389",
        CFG_USE_SSL:       "false",
        CFG_USE_TLS:       "false",
        CFG_BASE_DN:       "DC=ctfd,DC=loc",
        CFG_DOMAIN:        "ctfd.loc",
        CFG_SEARCH_FILTER: "(sAMAccountName={})",
        CFG_ATTR_EMAIL:    "mail",
        CFG_LOCAL_ENABLED: "true",
        CFG_DEBUG:         "false",
        CFG_CACHE_ENABLED: "true",
        CFG_CACHE_TTL:     "72",
        CFG_DNS:           "192.168.1.1",  # IMP-2 — DNS default
    }
    for key, val in defaults.items():
        if get_config(key) is None:
            set_config(key, val)


def _cfg(key, default=""):
    v = get_config(key)
    return v if v is not None else default


def _bool(key, default=False):
    """
    Read a config value as a boolean.

    BUG 1: When the DB is not yet initialized (first boot, defaults not committed),
    `get_config(key)` returns None. Callers that pass `default=True` will treat the
    feature as enabled to avoid a blank login page.
    """
    v = get_config(key)
    if v is None or v == "":
        return default
    return str(v).lower() in ("true", "1", "yes")


def _dbg(msg):
    if _bool(CFG_DEBUG):
        logger.debug(msg)


# ── DNS ─────────────────────────────────────────────────────────────────────
# BUG 3 — resolve LDAP hostname through a custom DNS server when system
# DNS can't resolve internal AD names like winserv.ctfd.loc.

def _resolve_host(hostname: str) -> str:
    dns_server = _cfg(CFG_DNS, "").strip()
    if not dns_server:
        return hostname
    # If hostname is already an IP, skip resolution
    parts = hostname.split(".")
    if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        return hostname
    if not HAS_DNS:
        logger.warning(
            "dnspython not installed; cannot resolve %s via custom DNS %s. "
            "Run: pip install dnspython",
            hostname, dns_server,
        )
        return hostname
    try:
        import dns.resolver
        r = dns.resolver.Resolver(configure=False)
        r.nameservers = [dns_server]
        r.lifetime = 4
        r.timeout = 4
        answers = r.resolve(hostname, "A")
        ip = str(answers[0])
        _dbg(f"DNS resolved {hostname} -> {ip} via {dns_server}")
        return ip
    except Exception as e:
        logger.warning(
            f"DNS resolve failed for {hostname} via {dns_server}: {e}; "
            f"falling back to system DNS"
        )
        return hostname


# ── Шифрование кэша ─────────────────────────────────────────────────────────

def _get_fernet():
    if not HAS_CRYPTO:
        return None
    key_cfg = get_config("ldap_cache_key")
    if not key_cfg:
        key = Fernet.generate_key().decode()
        set_config("ldap_cache_key", key)
    else:
        key = key_cfg
    return Fernet(key.encode())


def _encrypt(data: str) -> str:
    f = _get_fernet()
    if f is None:
        return base64.b64encode(data.encode()).decode()
    return f.encrypt(data.encode()).decode()


def _decrypt(token: str) -> str:
    f = _get_fernet()
    if f is None:
        return base64.b64decode(token.encode()).decode()
    return f.decrypt(token.encode()).decode()


# ── Кэш учётных данных ───────────────────────────────────────────────────────

def _cache_key(username: str) -> str:
    h = hashlib.sha256(username.lower().encode()).hexdigest()[:16]
    return f"ldap_cache_{h}"


def _cache_store(username: str, password: str, email: str, display_name: str = ""):
    """
    Сохраняет кэш учётных данных LDAP-пользователя.
    username — sAMAccountName
    display_name — полное имя из LDAP (опционально)
    """
    if not _bool(CFG_CACHE_ENABLED, default=True):
        return
    try:
        from werkzeug.security import generate_password_hash
        payload = json.dumps({
            "pw_hash": generate_password_hash(password),
            "email":   email,
            "display_name": display_name,
            "ts":      datetime.datetime.utcnow().isoformat(),
            "user":    username,
        })
        set_config(_cache_key(username), _encrypt(payload))
        _dbg(f"Cache stored for {username}")
    except Exception as e:
        logger.warning(f"Cache store error: {e}")


def _cache_verify(username: str, password: str):
    """
    Проверяет кэш учётных данных.
    Возвращает (email, display_name) или (None, None) при ошибке.
    """
    if not _bool(CFG_CACHE_ENABLED, default=True):
        return None, None
    try:
        from werkzeug.security import check_password_hash
        raw = get_config(_cache_key(username))
        if not raw:
            _dbg(f"Cache miss: {username}")
            return None, None
        payload = json.loads(_decrypt(raw))
        ttl_h = int(_cfg(CFG_CACHE_TTL, "72"))
        ts = datetime.datetime.fromisoformat(payload["ts"])
        age = datetime.datetime.utcnow() - ts
        if age.total_seconds() > ttl_h * 3600:
            _dbg(f"Cache expired for {username}")
            return None, None
        if check_password_hash(payload["pw_hash"], password):
            _dbg(f"Cache hit: {username}")
            return payload.get("email", ""), payload.get("display_name", "")
        _dbg(f"Cache wrong password: {username}")
        return None, None
    except Exception as e:
        logger.warning(f"Cache verify error: {e}")
        return None, None


# ── LDAP ─────────────────────────────────────────────────────────────────────

def _ldap_connect(username: str, password: str):
    raw_host = _cfg(CFG_HOST, "localhost")
    host     = _resolve_host(raw_host)  # BUG 3 — custom DNS resolution
    port     = int(_cfg(CFG_PORT, "389"))
    use_ssl  = _bool(CFG_USE_SSL)
    use_tls  = _bool(CFG_USE_TLS)
    domain   = _cfg(CFG_DOMAIN, "")
    upn      = f"{username}@{domain}" if domain else username
    _dbg(f"LDAP connect: host={raw_host} -> {host} port={port} ssl={use_ssl} "
         f"tls={use_tls} upn={upn}")
    try:
        server = ldap3.Server(host, port=port, use_ssl=use_ssl,
                              get_info=ldap3.ALL, connect_timeout=5)
        conn = ldap3.Connection(server, user=upn, password=password,
                                authentication=ldap3.SIMPLE,
                                client_strategy=ldap3.SYNC,
                                auto_referrals=False,
                                raise_exceptions=False)
        if use_tls:
            conn.start_tls()
        if not conn.bind():
            desc = conn.result.get("description", "unknown")
            code = conn.result.get("result", "?")
            _dbg(f"LDAP bind failed code={code}: {conn.result}")
            return None, f"Bind failed [{code}]: {desc}"
        _dbg("LDAP bind OK")
        return conn, None
    except ldap3.core.exceptions.LDAPSocketOpenError as e:
        return None, f"Cannot connect to {raw_host} ({host}):{port}: {e}"
    except Exception as e:
        return None, f"LDAP error: {type(e).__name__}: {e}"


def _get_user_info(conn, username: str):
    """
    Возвращает (email, display_name, error).
    display_name — полное имя из атрибута displayName или cn.
    """
    base_dn = _cfg(CFG_BASE_DN)
    filt    = _cfg(CFG_SEARCH_FILTER, "(sAMAccountName={})")
    attr_em = _cfg(CFG_ATTR_EMAIL, "mail")
    safe    = ldap3.utils.conv.escape_filter_chars(username)
    sf      = filt.format(safe)
    _dbg(f"LDAP search: base={base_dn} filter={sf} attr={attr_em}")
    try:
        conn.search(base_dn, sf, search_scope=ldap3.SUBTREE,
                    attributes=[attr_em, "displayName", "cn"])
    except Exception as e:
        return None, None, f"Search error: {e}"

    for entry in conn.response:
        if entry.get("type") != "searchResEntry":
            continue
        attrs = entry.get("attributes", {})

        # Email
        mail = attrs.get(attr_em)
        if isinstance(mail, list):
            mail = mail[0] if mail else None

        # Display Name (приоритет: displayName → cn)
        display_name = attrs.get("displayName")
        if isinstance(display_name, list):
            display_name = display_name[0] if display_name else None
        if not display_name:
            display_name = attrs.get("cn")
            if isinstance(display_name, list):
                display_name = display_name[0] if display_name else None

        if display_name:
            display_name = str(display_name).strip()

        _dbg(f"Found email: {mail}, displayName: {display_name}")
        return mail, display_name, None

    return None, None, (f"Attribute '{attr_em}' not found. Entries found: "
                        f"{len([e for e in conn.response if e.get('type')=='searchResEntry'])}")


def _random_password(n=32):
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(random.SystemRandom().choice(chars) for _ in range(n))


def _is_superadmin(user) -> bool:
    """Superadmin = first user (id=1) with admin type. Always allowed local login."""
    return user is not None and user.id == 1 and user.type == "admin"


def _generate_unique_name(base_name: str) -> str:
    """
    Генерирует уникальное имя пользователя.
    Если base_name занято — добавляет суффикс _2, _3 и т.д.
    Например: "Иванов Иван Иванович" → "Иванов Иван Иванович_2"
    """
    candidate = base_name
    counter = 2
    while Users.query.filter_by(name=candidate).first() is not None:
        candidate = f"{base_name}_{counter}"
        counter += 1
        if counter > 100:  # защита от бесконечного цикла
            candidate = f"{base_name}_{random.randint(1000, 9999)}"
            break
    _dbg(f"Generated unique name: {base_name} → {candidate}")
    return candidate


def _store_ldap_username(user_id: int, ldap_username: str):
    """
    Сохраняет связь CTFd user.id ↔ LDAP sAMAccountName в конфиге.
    Формат: ldap_user_map = {"user_id": "sAMAccountName"}
    """
    try:
        key = "ldap_user_map"
        mapping = _json_cfg(key)
        mapping[str(user_id)] = ldap_username
        set_config(key, json.dumps(mapping, ensure_ascii=False))
        _dbg(f"Stored LDAP mapping: user_id={user_id} → {ldap_username}")
    except Exception as e:
        logger.warning(f"Failed to store LDAP username mapping: {e}")


def _get_ldap_username(user_id: int) -> str:
    """Возвращает LDAP sAMAccountName по CTFd user.id."""
    try:
        mapping = _json_cfg("ldap_user_map")
        return mapping.get(str(user_id), "")
    except Exception:
        return ""


def _find_user_by_ldap_username(ldap_username: str):
    """Ищет пользователя CTFd по его LDAP sAMAccountName."""
    try:
        mapping = _json_cfg("ldap_user_map")
        for user_id_str, sam in mapping.items():
            if sam.lower() == ldap_username.lower():
                user = Users.query.filter_by(id=int(user_id_str)).first()
                if user:
                    return user
    except Exception as e:
        logger.warning(f"Error finding user by LDAP username: {e}")
    return None


# ── ГЛАВНАЯ ФУНКЦИЯ ЗАГРУЗКИ ─────────────────────────────────────────────────

def load(app):
    app.db.create_all()
    _default_settings()
    _teams_default_settings()

    dir_path = os.path.dirname(os.path.realpath(__file__))

    # Переопределяем шаблоны
    for tpl in ("login.html",):
        p = os.path.join(dir_path, "modified_templates", tpl)
        if os.path.exists(p):
            override_template(tpl, open(p, encoding="utf-8").read())
            logger.info(f"Template overridden: {tpl}")

    ldap_bp = Blueprint("ldap_plugin", __name__,
                        template_folder=os.path.join(dir_path, "templates"))

    # ── Страница настроек ────────────────────────────────────────────────────

    @ldap_bp.route("/admin/ldap-settings", methods=["GET"])
    @admins_only
    def ldap_admin_settings():
        return render_template("ldap_admin.html", cfg=_get_cfg_vals())

    @ldap_bp.route("/admin/ldap-settings/save", methods=["POST"])
    @admins_only
    def ldap_admin_save():
        data = request.get_json() if request.is_json else request.form
        # String fields (BUG 3 Fix 4 — CFG_DNS persisted)
        for key in (CFG_HOST, CFG_PORT, CFG_BASE_DN, CFG_DOMAIN,
                    CFG_SEARCH_FILTER, CFG_ATTR_EMAIL, CFG_CACHE_TTL, CFG_DNS):
            if key in data:
                val = (data.get(key) or "").strip()
                set_config(key, val)
        # Boolean fields
        for key in (CFG_ENABLED, CFG_USE_SSL, CFG_USE_TLS,
                    CFG_LOCAL_ENABLED, CFG_DEBUG, CFG_CACHE_ENABLED):
            set_config(key, "true" if data.get(key) else "false")
        logger.info("LDAP settings saved")
        return {"success": True, "message": "Settings saved"}

    @ldap_bp.route("/admin/ldap-settings/ping", methods=["POST"])
    @admins_only
    def ldap_admin_ping():
        raw_host = _cfg(CFG_HOST, "localhost")
        host = _resolve_host(raw_host)
        port = int(_cfg(CFG_PORT, "389"))
        try:
            s = ldap3.Server(host, port=port, connect_timeout=4)
            c = ldap3.Connection(s, client_strategy=ldap3.SYNC, raise_exceptions=False)
            c.open()
            c.unbind()
            msg = f"Server {raw_host} ({host}):{port} reachable (TCP open)"
            return {"success": True, "message": msg}
        except Exception as e:
            return {"success": False,
                    "message": f"{raw_host} ({host}):{port} unreachable: "
                               f"{type(e).__name__}: {e}"}

    @ldap_bp.route("/admin/ldap-settings/save-teams", methods=["POST"])
    @admins_only
    def ldap_admin_save_teams():
        """Сохраняет маппинг групп→команды и команды→категории."""
        data = request.get_json() if request.is_json else request.form

        set_config(CFG_CATS_ENABLED, "true" if data.get(CFG_CATS_ENABLED) else "false")

        # group_map
        ad_groups  = data.getlist("ad_group")     if hasattr(data, "getlist") else data.get("ad_group", [])
        team_names = data.getlist("team_name_map") if hasattr(data, "getlist") else data.get("team_name_map", [])
        if isinstance(ad_groups, str):  ad_groups  = [ad_groups]
        if isinstance(team_names, str): team_names = [team_names]
        group_map = {g.strip(): t.strip() for g, t in zip(ad_groups, team_names) if g.strip() and t.strip()}
        set_config(CFG_GROUP_MAP, json.dumps(group_map, ensure_ascii=False))

        # team_cats
        cat_teams = data.getlist("cat_team")   if hasattr(data, "getlist") else data.get("cat_team", [])
        cat_vals  = data.getlist("cat_values") if hasattr(data, "getlist") else data.get("cat_values", [])
        if isinstance(cat_teams, str): cat_teams = [cat_teams]
        if isinstance(cat_vals, str):  cat_vals  = [cat_vals]
        team_cats = {
            t.strip(): [c.strip().lower() for c in v.split(",") if c.strip()]
            for t, v in zip(cat_teams, cat_vals) if t.strip()
        }
        set_config(CFG_TEAM_CATS, json.dumps(team_cats, ensure_ascii=False))

        logger.info(f"Teams mapping saved: groups={group_map} cats={team_cats}")
        return {"success": True, "message": "Team settings saved"}

    @ldap_bp.route("/admin/ldap-settings/test", methods=["POST"])
    @admins_only
    def ldap_admin_test():
        data = request.get_json() if request.is_json else request.form
        tu = (data.get("test_user") or "").strip()
        tp = (data.get("test_pass") or "").strip()
        if not tu or not tp:
            return {"success": False, "steps": ["Enter username and password"]}

        steps = []
        raw_host = _cfg(CFG_HOST, "localhost")
        host = _resolve_host(raw_host)
        port = int(_cfg(CFG_PORT, "389"))

        # Step 0: DNS
        if raw_host != host:
            steps.append(f"DNS {raw_host} -> {host} via {_cfg(CFG_DNS)}")
        elif _cfg(CFG_DNS):
            steps.append(f"DNS {raw_host} kept as-is (already IP or resolution skipped)")

        # Step 1: TCP
        try:
            s = ldap3.Server(host, port=port, connect_timeout=4)
            c = ldap3.Connection(s, client_strategy=ldap3.SYNC, raise_exceptions=False)
            c.open()
            c.unbind()
            steps.append(f"OK TCP {host}:{port} reachable")
        except Exception as e:
            steps.append(f"FAIL TCP {host}:{port} unreachable: {e}")
            return {"success": False, "steps": steps}

        # Step 2: Bind
        conn, err = _ldap_connect(tu, tp)
        if err:
            steps.append(f"FAIL Bind: {err}")
            return {"success": False, "steps": steps}
        steps.append(f"OK Bind (UPN: {tu}@{_cfg(CFG_DOMAIN)})")

        # Step 3: User info search (email + displayName)
        email, display_name, eerr = _get_user_info(conn, tu)
        conn.unbind()
        if eerr:
            steps.append(f"WARN User info search: {eerr}")
            return {"success": True, "steps": steps}
        steps.append(f"OK Email found: {email}")
        if display_name:
            steps.append(f"OK Display Name found: {display_name}")
        else:
            steps.append(f"WARN Display Name not found (will use sAMAccountName)")
        return {"success": True, "steps": steps}

    def _get_cfg_vals():
        return {
            "host":          _cfg(CFG_HOST),
            "port":          _cfg(CFG_PORT),
            "base_dn":       _cfg(CFG_BASE_DN),
            "domain":        _cfg(CFG_DOMAIN),
            "search_filter": _cfg(CFG_SEARCH_FILTER),
            "attr_email":    _cfg(CFG_ATTR_EMAIL),
            "cache_ttl":     _cfg(CFG_CACHE_TTL),
            "dns_server":    _cfg(CFG_DNS, "192.168.1.1"),  # BUG 3 Fix 5
            # Booleans default to True so a partially-initialized DB doesn't
            # render the login page in a broken state (BUG 1).
            "ldap_enabled":  _bool(CFG_ENABLED, default=True),
            "use_ssl":       _bool(CFG_USE_SSL),
            "use_tls":       _bool(CFG_USE_TLS),
            "local_enabled": _bool(CFG_LOCAL_ENABLED, default=True),
            "debug":         _bool(CFG_DEBUG),
            "cache_enabled": _bool(CFG_CACHE_ENABLED, default=True),
            "has_crypto":    HAS_CRYPTO,
            "has_dns":       HAS_DNS,
            # Teams & categories
            "cats_enabled":  _bool(CFG_CATS_ENABLED),
            "group_map":     _json_cfg(CFG_GROUP_MAP),
            "team_cats":     _json_cfg(CFG_TEAM_CATS),
        }

    # ── Хелперы входа ────────────────────────────────────────────────────────

    def _render_login(errors):
        # BUG 1 — pass safe defaults so the form is usable on first cold boot
        db.session.close()
        return render_template(
            "login.html",
            errors=errors,
            ldap_enabled=_bool(CFG_ENABLED, default=True),
            local_enabled=_bool(CFG_LOCAL_ENABLED, default=True),
        )

    def _finish_login(user, source="local"):
        login_user(user)
        logger.info(f"Login success: user={user.name!r} id={user.id} source={source}")
        log("logins", "[{date}] {ip} - {name} logged in (" + source + ")", name=user.name)
        db.session.close()
        nxt = request.args.get("next")
        if nxt and validators.is_safe_url(nxt):
            return redirect(nxt)
        try:
            return redirect(url_for("challenges.listing"))
        except Exception:
            return redirect("/")

    # ── Локальный вход ───────────────────────────────────────────────────────

    def _do_local_login(username_raw, password, errors):
        logger.info(f"Local login attempt: {username_raw!r}")

        if validators.validate_email(username_raw):
            user = Users.query.filter_by(email=username_raw).first()
        else:
            user = Users.query.filter_by(name=username_raw).first()

        if not user:
            logger.info(f"Local: user not found: {username_raw!r}")
            errors.append("Your username or password is incorrect")
            return _render_login(errors)

        is_super = _is_superadmin(user)
        logger.info(f"Local: found id={user.id} type={user.type} superadmin={is_super}")

        if not _bool(CFG_LOCAL_ENABLED, default=True) and not is_super:
            errors.append("Local login is disabled by administrator")
            return _render_login(errors)

        if user.password is None:
            errors.append(
                "Your account was registered with a 3rd party authentication provider. "
                "Please try logging in with a configured authentication provider."
            )
            return _render_login(errors)

        if not verify_password(password, user.password):
            logger.info(f"Local: wrong password for {username_raw!r}")
            log("logins", "[{date}] {ip} - submitted invalid password for {name}", name=user.name)
            errors.append("Your username or password is incorrect")
            return _render_login(errors)

        logger.info(f"Local: success for {username_raw!r}")
        return _finish_login(user, "local")

    # ── Доменный вход ────────────────────────────────────────────────────────

    def _do_ldap_login(username_raw, password, errors):
        """
        LDAP-вход с использованием displayName как основного имени пользователя.

        Логика:
        1. username_raw = sAMAccountName (логин в AD, например "i.ivanov")
        2. Ищем существующего пользователя по LDAP-маппингу (user_id ↔ sAMAccountName)
        3. Если не найден — создаём нового с именем = displayName из LDAP
        4. При коллизии имён добавляем суффикс _2, _3 и т.д.
        5. Обновляем displayName при каждом входе (если изменился в AD)
        """
        if not _bool(CFG_ENABLED, default=True):
            errors.append("Domain login is disabled")
            return _render_login(errors)

        # username_raw — это sAMAccountName (логин в AD)
        ldap_username = username_raw.strip()

        # Проверяем, не ввели ли email вместо username
        if validators.validate_email(ldap_username):
            errors.append("Enter your domain username (not email)")
            return _render_login(errors)

        logger.info(f"LDAP login attempt: sAMAccountName={ldap_username!r}")

        # Ищем существующего пользователя по LDAP-маппингу
        user = _find_user_by_ldap_username(ldap_username)
        logger.info(f"LDAP user lookup: existing={user is not None}")

        # Подключаемся к LDAP
        conn, ldap_err = _ldap_connect(ldap_username, password)
        email = None
        display_name = None
        ldap_ok = conn is not None

        ad_groups = []
        if conn:
            # Получаем email и displayName из LDAP
            email_ldap, display_name_ldap, search_err = _get_user_info(conn, ldap_username)
            ad_groups = _get_user_groups(conn, ldap_username)
            conn.unbind()

            if email_ldap:
                email = email_ldap
            else:
                logger.warning(f"LDAP bind OK but no email: {search_err}")
                domain = _cfg(CFG_DOMAIN, "")
                email = f"{ldap_username}@{domain}" if domain else None
                if email:
                    logger.warning(f"Email fallback: {email}")

            # displayName — это то, что будет отображаться как имя пользователя
            if display_name_ldap:
                display_name = display_name_ldap
            else:
                logger.warning(f"No displayName found, using sAMAccountName: {ldap_username}")
                display_name = ldap_username

            if email:
                _cache_store(ldap_username, password, email, display_name)
        else:
            logger.warning(f"LDAP unavailable: {ldap_err}")
            email_cached, display_name_cached = _cache_verify(ldap_username, password)
            if email_cached is not None:
                logger.warning(f"Cache fallback for {ldap_username!r}")
                email = email_cached
                display_name = display_name_cached if display_name_cached else (user.name if user else ldap_username)
            else:
                errors.append(f"Domain connection error: {ldap_err}")
                if _bool(CFG_CACHE_ENABLED, default=True):
                    errors.append("Cache: credentials not found or expired.")
                return _render_login(errors)

        # Если пользователь существует — обновляем его displayName (если изменился)
        if user:
            if display_name and user.name != display_name:
                # Проверяем, не занято ли новое имя другим пользователем
                existing = Users.query.filter_by(name=display_name).first()
                if existing and existing.id != user.id:
                    # Имя занято — генерируем уникальное
                    new_name = _generate_unique_name(display_name)
                    logger.info(f"Updating user name: {user.name!r} → {new_name!r} (collision)")
                    user.name = new_name
                else:
                    logger.info(f"Updating user name: {user.name!r} → {display_name!r}")
                    user.name = display_name
                db.session.commit()

            if ad_groups and ldap_ok:
                _assign_team(app, user, ad_groups)
            return _finish_login(user, "LDAP" if ldap_ok else "cache")

        # Auto-registration — создаём нового пользователя
        if not email:
            errors.append("Cannot get email — auto-registration impossible")
            return _render_login(errors)

        if not display_name:
            display_name = ldap_username

        # Проверяем коллизию email
        if Users.query.filter_by(email=email).first():
            errors.append(f"Email {email} is already used by another account")
            return _render_login(errors)

        # Генерируем уникальное имя (на случай коллизии displayName)
        unique_name = _generate_unique_name(display_name)

        new_user = Users(name=unique_name, email=email, password=_random_password())
        db.session.add(new_user)
        db.session.commit()

        # Сохраняем маппинг user_id ↔ sAMAccountName
        _store_ldap_username(new_user.id, ldap_username)

        logger.info(f"Auto-registered LDAP user: sAMAccountName={ldap_username!r} "
                   f"displayName={display_name!r} → CTFd name={unique_name!r} ({email})")
        log("registrations", "[{date}] {ip} - {name} registered via LDAP", name=unique_name)

        if ad_groups:
            _assign_team(app, new_user, ad_groups)

        return _finish_login(new_user, "LDAP-new")

    # ── login view ───────────────────────────────────────────────────────────
    # CTFd's before_request csrf hook validates nonce BEFORE this view runs.
    # The template uses {{ form.nonce() }} via Forms.auth.LoginForm() which
    # renders session["nonce"] as a hidden input.

    def login():
        errors = get_errors()
        logger.info(f"Login handler: method={request.method}")

        if request.method == "POST":
            username_raw = request.form.get("name", "").strip()
            password     = request.form.get("password", "")
            login_mode   = request.form.get("login_mode", "domain")

            logger.info(f"Login POST: user={username_raw!r} mode={login_mode!r}")

            if not username_raw or not password:
                errors.append("Your username or password is incorrect")
                return _render_login(errors)

            if login_mode == "local":
                return _do_local_login(username_raw, password, errors)

            # BUG 2 — superadmin must always be allowed to log in via the local
            # path even when Domain tab was used and LDAP is unreachable.
            candidate = (
                Users.query.filter_by(name=username_raw).first()
                or Users.query.filter_by(email=username_raw).first()
            )
            if _is_superadmin(candidate):
                # IMP-4 — make the bypass visible in logs
                logger.info(
                    f"Superadmin detected — forcing local login path for {username_raw!r}"
                )
                return _do_local_login(username_raw, password, errors)

            return _do_ldap_login(username_raw, password, errors)

        # GET
        db.session.close()
        return _render_login(errors)

    # Override the auth.login view function
    app.view_functions["auth.login"] = login

    # Patch challenge list API for team-based category filtering
    _patch_challenge_api()

    # Patch challenge view pages
    _patch_challenge_views(app)

    app.register_blueprint(ldap_bp)

    try:
        from CTFd.utils.plugins import register_admin_plugin_menu_bar
        register_admin_plugin_menu_bar(title="LDAP Settings", href="/admin/ldap-settings")
    except Exception:
        pass

    logger.info(
        "LDAP plugin v2.4 loaded — local=%s ldap=%s dns=%s crypto=%s",
        _bool(CFG_LOCAL_ENABLED, default=True),
        _bool(CFG_ENABLED, default=True),
        HAS_DNS, HAS_CRYPTO,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# TEAMS & CATEGORY FILTER — добавлено поверх v2.4
# ═══════════════════════════════════════════════════════════════════════════════

# Ключи конфига для команд
CFG_GROUP_MAP    = "ldap_group_map"       # JSON {"ad-cn": "CTFd Team Name"}
CFG_TEAM_CATS    = "ldap_team_categories" # JSON {"CTFd Team Name": ["web","crypto"]}
CFG_CATS_ENABLED = "ldap_cats_enabled"   # "true"/"false"


def _json_cfg(key):
    """Читает JSON из конфига CTFd. Возвращает {} при ошибке."""
    try:
        return json.loads(get_config(key) or "{}")
    except Exception:
        return {}


def _teams_default_settings():
    for key, val in {
        CFG_GROUP_MAP:    "{}",
        CFG_TEAM_CATS:    "{}",
        CFG_CATS_ENABLED: "false",
        "ldap_user_map":  "{}",  # user_id → sAMAccountName mapping
    }.items():
        if get_config(key) is None:
            set_config(key, val)


def _assign_team(app, user, ad_group_cns: list):
    """
    Назначает пользователя в команду CTFd по его AD-группам.
    Маппинг: ldap_group_map = {"ad-cn": "CTFd Team Name"}
    Если команды нет — создаёт её.
    """
    if not is_teams_mode():
        return

    group_map = _json_cfg(CFG_GROUP_MAP)
    if not group_map:
        return

    target_team_name = None
    for cn in ad_group_cns:
        if cn in group_map:
            target_team_name = group_map[cn]
            _dbg(f"AD group {cn!r} → team {target_team_name!r}")
            break

    if not target_team_name:
        _dbg(f"No AD group matched in group_map: {ad_group_cns}")
        return

    try:
        from CTFd.models import Teams
        team = Teams.query.filter_by(name=target_team_name).first()
        if not team:
            logger.info(f"Creating CTFd team: {target_team_name!r}")
            team = Teams(
                name=target_team_name,
                password=_random_password(16),
            )
            db.session.add(team)
            db.session.flush()

        if user not in team.members:
            team.members.append(user)
            db.session.commit()
            _dbg(f"User {user.name!r} added to team {target_team_name!r}")
        else:
            _dbg(f"User {user.name!r} already in team {target_team_name!r}")
    except Exception as e:
        logger.error(f"Team assignment error: {e}")


def _get_user_groups(conn, username: str):
    """
    Возвращает список CN групп из атрибута memberOf пользователя.
    Используется отдельно от _get_user_email чтобы не ломать существующий код.
    """
    base_dn = _cfg(CFG_BASE_DN)
    filt    = _cfg(CFG_SEARCH_FILTER, "(sAMAccountName={})")
    safe    = ldap3.utils.conv.escape_filter_chars(username)
    sf      = filt.format(safe)
    try:
        conn.search(base_dn, sf, search_scope=ldap3.SUBTREE, attributes=["memberOf"])
    except Exception as e:
        logger.warning(f"memberOf search error: {e}")
        return []

    for entry in conn.response:
        if entry.get("type") != "searchResEntry":
            continue
        member_of = entry.get("attributes", {}).get("memberOf", [])
        if isinstance(member_of, str):
            member_of = [member_of]
        # "CN=team-web,OU=CTF,DC=..." → "team-web"
        cns = [dn.split(",")[0].split("=", 1)[-1].strip() for dn in member_of]
        _dbg(f"memberOf CNs for {username!r}: {cns}")
        return cns
    return []


def _check_challenge_access(challenge_id):
    """
    Проверяет доступ текущего пользователя/команды к челленджу.
    Возвращает (allowed: bool, reason: str).
    """
    try:
        if not _bool(CFG_CATS_ENABLED):
            return True, "filtering disabled"

        team_cats = _json_cfg(CFG_TEAM_CATS)
        if not team_cats:
            return True, "no team mapping"

        from CTFd.utils.user import get_current_team, get_current_user
        from CTFd.models import Challenges, Tags

        if is_teams_mode():
            team = get_current_team()
            team_name = team.name if team else None
        else:
            user = get_current_user()
            team_name = user.name if user else None

        if not team_name or team_name not in team_cats:
            return True, "team not in mapping"

        allowed_cats = [c.lower() for c in team_cats[team_name]]

        chall = Challenges.query.filter_by(id=challenge_id).first()
        if not chall:
            return False, "challenge not found"

        # Проверяем теги team:*
        tags = Tags.query.filter_by(challenge_id=challenge_id).all()
        team_tags = [
            t.value[5:].lower() for t in tags
            if t.value.lower().startswith("team:")
        ]

        if team_tags:
            if team_name.lower() in team_tags:
                _dbg(f"Access ✅ chall={challenge_id} — tag team:{team_name}")
                return True, f"explicit tag team:{team_name}"
            else:
                _dbg(f"Access ❌ chall={challenge_id} — team tags {team_tags}, no match")
                return False, f"team tags {team_tags} do not match {team_name}"

        # Проверяем категорию
        cat = (chall.category or "").lower()
        if cat in allowed_cats:
            _dbg(f"Access ✅ chall={challenge_id} — category {cat!r} allowed")
            return True, f"category {cat} allowed"
        else:
            _dbg(f"Access ❌ chall={challenge_id} — category {cat!r} not in {allowed_cats}")
            return False, f"category {cat} not allowed for {team_name}"

    except Exception as e:
        logger.error(f"Challenge access check error (failing open): {e}")
        return True, f"error: {e}"


def _patch_challenge_api():
    """
    Патчит API челленджей — фильтрует задания по команде участника.

    Логика фильтрации задания:
    1. Есть теги team:X → показываем ТОЛЬКО если team:МояКоманда присутствует.
       (тег перекрывает правило категории — можно открыть одно задание из чужой категории)
    2. Нет тегов team:* → смотрим категорию: входит ли в разрешённые для команды?
    3. Если фильтрация выключена или команда не в маппинге → всё видно.
    """
    try:
        from CTFd.api.v1.challenges import ChallengeList, Challenge
        from CTFd.utils.user import get_current_team, get_current_user
        from flask import abort

        # ── Патч списка челленджей ──────────────────────────────────────────
        original_list_get = ChallengeList.get

        def filtered_list_get(self, *args, **kwargs):
            resp = original_list_get(self, *args, **kwargs)

            try:
                if not _bool(CFG_CATS_ENABLED):
                    return resp

                if not isinstance(resp, dict) or "data" not in resp:
                    return resp

                team_cats = _json_cfg(CFG_TEAM_CATS)
                if not team_cats:
                    return resp

                if is_teams_mode():
                    team = get_current_team()
                    team_name = team.name if team else None
                else:
                    user = get_current_user()
                    team_name = user.name if user else None

                if not team_name or team_name not in team_cats:
                    return resp

                allowed_cats = [c.lower() for c in team_cats[team_name]]
                _dbg(f"Challenge filter: team={team_name!r} cats={allowed_cats}")

                filtered = []
                for chall in resp["data"]:
                    raw_tags = chall.get("tags", [])
                    tags = [
                        (t if isinstance(t, str) else t.get("value", "")).lower()
                        for t in raw_tags
                    ]
                    team_tags = [t[5:] for t in tags if t.startswith("team:")]

                    if team_tags:
                        if team_name.lower() in team_tags:
                            filtered.append(chall)
                            _dbg(f"  ✅ {chall.get('name')} — explicit tag team:{team_name}")
                        else:
                            _dbg(f"  ❌ {chall.get('name')} — team tags {team_tags}, no match")
                    else:
                        cat = chall.get("category", "").lower()
                        if cat in allowed_cats:
                            filtered.append(chall)
                            _dbg(f"  ✅ {chall.get('name')} — category {cat!r} allowed")
                        else:
                            _dbg(f"  ❌ {chall.get('name')} — category {cat!r} not in {allowed_cats}")

                resp["data"] = filtered
                return resp
            except Exception as e:
                logger.error(f"Challenge list filter error (failing open): {e}")
                return resp

        ChallengeList.get = filtered_list_get

        # ── Патч отдельного челленджа ───────────────────────────────────────
        original_challenge_get = Challenge.get

        def filtered_challenge_get(self, challenge_id):
            allowed, reason = _check_challenge_access(challenge_id)
            if not allowed:
                logger.warning(f"Challenge access denied: id={challenge_id} reason={reason}")
                abort(403)
            return original_challenge_get(self, challenge_id)

        Challenge.get = filtered_challenge_get

        # ── Патч попыток решения ────────────────────────────────────────────
        original_challenge_post = Challenge.post

        def filtered_challenge_post(self, challenge_id):
            allowed, reason = _check_challenge_access(challenge_id)
            if not allowed:
                logger.warning(f"Challenge attempt denied: id={challenge_id} reason={reason}")
                abort(403)
            return original_challenge_post(self, challenge_id)

        Challenge.post = filtered_challenge_post

        logger.info("Challenge API patched — team category filter active (list + detail + attempts)")
    except Exception as e:
        logger.error(f"Failed to patch Challenge API: {e}")


def _patch_challenge_views(app):
    """
    Патчит view-функции для страниц челленджей, чтобы блокировать прямой доступ
    через веб-интерфейс к челленджам, недоступным команде.
    """
    try:
        from flask import abort

        # Патчим страницу отдельного челленджа (если она есть)
        original_challenge_view = app.view_functions.get("challenges.challenge_view")
        if original_challenge_view:
            def filtered_challenge_view(challenge_id):
                allowed, reason = _check_challenge_access(challenge_id)
                if not allowed:
                    logger.warning(f"Challenge view denied: id={challenge_id} reason={reason}")
                    abort(403)
                return original_challenge_view(challenge_id)

            app.view_functions["challenges.challenge_view"] = filtered_challenge_view
            logger.info("Challenge view patched — team category filter active")

    except Exception as e:
        logger.error(f"Failed to patch challenge views: {e}")
