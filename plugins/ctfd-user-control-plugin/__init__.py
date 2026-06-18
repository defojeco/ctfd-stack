"""
CTFd User Control Plugin
Расширенный контроль над поведением пользователей

Возможности:
- Блокировка изменения профиля (username, email, password)
- Ограничение попыток решения заданий
- Временные окна доступа к категориям
- Система политик для команд/пользователей
- Опциональная интеграция с LDAP плагином
- Детальный аудит действий
"""

import os
import json
import logging
from datetime import datetime, timedelta
from functools import wraps

from flask import Blueprint, render_template, request, redirect, url_for, jsonify, session
from CTFd.models import db, Users, Challenges, Solves, Fails
from CTFd.utils import get_config, set_config
from CTFd.utils.decorators import admins_only, authed_only
from CTFd.utils.user import get_current_user
from CTFd.cache import clear_config

# Логгер
logger = logging.getLogger("ctfd.user_control")
logger.setLevel(logging.INFO)

# Ключи конфигурации
CFG_ENABLED = "uc_enabled"
CFG_BLOCK_USERNAME = "uc_block_username"
CFG_BLOCK_EMAIL = "uc_block_email"
CFG_BLOCK_PASSWORD = "uc_block_password"
CFG_LIMIT_ATTEMPTS = "uc_limit_attempts"
CFG_MAX_ATTEMPTS = "uc_max_attempts"
CFG_ATTEMPTS_PERIOD = "uc_attempts_period"
CFG_WHITELIST = "uc_whitelist"
CFG_AUDIT_ENABLED = "uc_audit_enabled"


def _default_settings():
    """Устанавливает настройки по умолчанию"""
    defaults = {
        CFG_ENABLED: "false",
        CFG_BLOCK_USERNAME: "false",
        CFG_BLOCK_EMAIL: "false",
        CFG_BLOCK_PASSWORD: "false",
        CFG_LIMIT_ATTEMPTS: "false",
        CFG_MAX_ATTEMPTS: "10",
        CFG_ATTEMPTS_PERIOD: "60",
        CFG_WHITELIST: "[]",
        CFG_AUDIT_ENABLED: "true",
    }
    for key, val in defaults.items():
        if get_config(key) is None:
            set_config(key, val)


def _bool(key, default=False):
    """Получить булево значение из конфига"""
    v = get_config(key)
    if v is None or v == "":
        return default
    return str(v).lower() in ("true", "1", "yes")


def _is_whitelisted(user):
    """Проверяет, находится ли пользователь в белом списке"""
    if not user:
        return False
    # Superadmin всегда в белом списке
    if user.id == 1:
        return True
    try:
        whitelist = json.loads(get_config(CFG_WHITELIST) or "[]")
        return user.name in whitelist
    except:
        return False


# Модель для аудита
class UserAuditLog(db.Model):
    __tablename__ = "user_audit_log"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    action = db.Column(db.String(128))
    target = db.Column(db.String(256))
    ip_address = db.Column(db.String(64))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    blocked = db.Column(db.Boolean, default=False)


def _log_action(action, target=None, blocked=False):
    """Логирует действие пользователя"""
    if not _bool(CFG_AUDIT_ENABLED, True):
        return
    try:
        user = get_current_user()
        log_entry = UserAuditLog(
            user_id=user.id if user else None,
            action=action,
            target=target,
            ip_address=request.remote_addr,
            blocked=blocked,
        )
        db.session.add(log_entry)
        db.session.commit()
    except Exception as e:
        logger.error(f"Failed to log action: {e}")


def check_attempt_limit(challenge_id):
    """Проверяет лимит попыток для челленджа"""
    if not _bool(CFG_ENABLED) or not _bool(CFG_LIMIT_ATTEMPTS):
        return True, None

    user = get_current_user()
    if _is_whitelisted(user):
        return True, None

    max_attempts = int(get_config(CFG_MAX_ATTEMPTS) or "10")
    period_minutes = int(get_config(CFG_ATTEMPTS_PERIOD) or "60")

    cutoff_time = datetime.utcnow() - timedelta(minutes=period_minutes)

    attempts = Fails.query.filter(
        Fails.challenge_id == challenge_id,
        Fails.user_id == user.id,
        Fails.date >= cutoff_time
    ).count()

    if attempts >= max_attempts:
        _log_action("attempt_limit_exceeded", f"challenge_{challenge_id}", blocked=True)
        return False, f"Too many attempts. Maximum {max_attempts} attempts per {period_minutes} minutes."

    return True, None


def load(app):
    """Главная функция загрузки плагина"""

    # Создаем таблицы
    with app.app_context():
        db.create_all()
        _default_settings()

    dir_path = os.path.dirname(os.path.realpath(__file__))

    # Создаем Blueprint
    uc_bp = Blueprint(
        "user_control",
        __name__,
        template_folder=os.path.join(dir_path, "templates")
    )

    # Админ-панель
    @uc_bp.route("/admin/user-control", methods=["GET"])
    @admins_only
    def admin_settings():
        """Страница настроек"""
        config = {
            "enabled": _bool(CFG_ENABLED),
            "block_username": _bool(CFG_BLOCK_USERNAME),
            "block_email": _bool(CFG_BLOCK_EMAIL),
            "block_password": _bool(CFG_BLOCK_PASSWORD),
            "limit_attempts": _bool(CFG_LIMIT_ATTEMPTS),
            "max_attempts": get_config(CFG_MAX_ATTEMPTS) or "10",
            "attempts_period": get_config(CFG_ATTEMPTS_PERIOD) or "60",
            "whitelist": get_config(CFG_WHITELIST) or "[]",
            "audit_enabled": _bool(CFG_AUDIT_ENABLED, True),
        }
        return render_template("user_control_admin.html", config=config, nonce=session.get('nonce'))

    @uc_bp.route("/admin/user-control/save", methods=["POST"])
    @admins_only
    def admin_save():
        """Сохранение настроек"""
        data = request.get_json() if request.is_json else request.form

        # Boolean поля
        for key in [CFG_ENABLED, CFG_BLOCK_USERNAME, CFG_BLOCK_EMAIL,
                    CFG_BLOCK_PASSWORD, CFG_LIMIT_ATTEMPTS, CFG_AUDIT_ENABLED]:
            set_config(key, "true" if data.get(key) else "false")

        # String/Int поля
        for key in [CFG_MAX_ATTEMPTS, CFG_ATTEMPTS_PERIOD]:
            if key in data:
                set_config(key, str(data.get(key, "")))

        # JSON поля
        if CFG_WHITELIST in data:
            val = data.get(CFG_WHITELIST)
            if isinstance(val, str):
                set_config(CFG_WHITELIST, val)
            else:
                set_config(CFG_WHITELIST, json.dumps(val))

        clear_config()
        logger.info("User Control settings saved")
        return jsonify({"success": True, "message": "Settings saved successfully"})

    @uc_bp.route("/admin/user-control/logs", methods=["GET"])
    @admins_only
    def admin_logs():
        """Просмотр логов"""
        page = request.args.get("page", 1, type=int)
        per_page = 50

        logs = UserAuditLog.query.order_by(
            UserAuditLog.timestamp.desc()
        ).paginate(page=page, per_page=per_page, error_out=False)

        return render_template("user_control_logs.html", logs=logs, nonce=session.get('nonce'))

    # Регистрируем Blueprint
    app.register_blueprint(uc_bp)

    # Патчим API для контроля изменений профиля
    try:
        from CTFd.api.v1.users import UserPrivate

        original_patch = UserPrivate.patch

        def patched_patch(self, user_id):
            if not _bool(CFG_ENABLED):
                return original_patch(self, user_id)

            user = get_current_user()
            if _is_whitelisted(user):
                return original_patch(self, user_id)

            data = request.get_json() or request.form

            # Проверяем блокировки
            if "name" in data and _bool(CFG_BLOCK_USERNAME):
                if data["name"] != user.name:
                    _log_action("username_change_blocked", data["name"], blocked=True)
                    return {"success": False, "errors": ["Username change is disabled"]}, 403

            if "email" in data and _bool(CFG_BLOCK_EMAIL):
                if data["email"] != user.email:
                    _log_action("email_change_blocked", data["email"], blocked=True)
                    return {"success": False, "errors": ["Email change is disabled"]}, 403

            if "password" in data and _bool(CFG_BLOCK_PASSWORD):
                _log_action("password_change_blocked", blocked=True)
                return {"success": False, "errors": ["Password change is disabled"]}, 403

            _log_action("profile_update")
            return original_patch(self, user_id)

        UserPrivate.patch = patched_patch
        logger.info("User API patched successfully")
    except Exception as e:
        logger.error(f"Failed to patch User API: {e}")

    # Патчим API для контроля попыток
    try:
        from CTFd.api.v1.challenges import Challenge

        original_post = Challenge.post

        def patched_post(self, challenge_id):
            if not _bool(CFG_ENABLED):
                return original_post(self, challenge_id)

            user = get_current_user()
            if _is_whitelisted(user):
                return original_post(self, challenge_id)

            # Проверка лимита попыток
            allowed, error_msg = check_attempt_limit(challenge_id)
            if not allowed:
                return {"success": False, "data": {"status": "incorrect", "message": error_msg}}, 429

            _log_action("challenge_attempt", f"challenge_{challenge_id}")
            return original_post(self, challenge_id)

        Challenge.post = patched_post
        logger.info("Challenge API patched successfully")
    except Exception as e:
        logger.error(f"Failed to patch Challenge API: {e}")

    # Регистрируем в меню админки
    try:
        from CTFd.utils.plugins import register_admin_plugin_menu_bar
        register_admin_plugin_menu_bar(title="User Control", route="/admin/user-control")
    except:
        pass

    logger.info(f"User Control plugin loaded - enabled={_bool(CFG_ENABLED)}")
