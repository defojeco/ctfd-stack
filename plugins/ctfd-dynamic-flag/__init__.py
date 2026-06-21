"""
CTFd plugin: dynamic_formula flag type (Variant A — parameterized generator).

Per-user / per-team flags are computed deterministically from a fixed set of
schemes (sha256, hmac-sha256, base64). The admin never supplies executable
code — only a scheme, a secret, a source template and an output format. This
avoids exec()/eval() entirely (no CWE-95 code-injection surface).

The "Flag value" stored in the database is a small JSON document:

    {
      "scheme": "hmac-sha256",   # one of SCHEMES
      "secret": "S3CR3T",        # key material / salt (str)
      "source": "{team_name}",   # template, placeholders substituted at compare
      "format": "FLAG{%s}",      # output wrapper, %s = digest (optional)
      "length": 32               # truncate hex/b64 digest to N chars (0 = full)
    }

Placeholders available in `source` and `secret`:
  {user_name} {user_email} {user_id} {team_name} {team_id} {challenge_id}

Optional integration: if the ctfd-dynamic-values plugin is installed, source and
secret may also reference its {{variable}} tokens — they are resolved first via
the app.dynamic_values_substitute hook, then the {placeholder} tokens above.

Compatible with CTFd 3.x and 4.x.
"""

import base64
import hashlib
import hmac
import json
import logging

from CTFd.plugins import register_plugin_assets_directory
from CTFd.plugins.flags import FLAG_CLASSES, BaseFlag
from CTFd.utils.user import get_current_team, get_current_user

logger = logging.getLogger("dynamic_formula")

# Whitelisted hashing schemes. The value is the implementation; adding a new
# scheme here is the ONLY supported extension point — no admin-supplied code.
SCHEMES = ("sha256", "hmac-sha256", "base64", "simple")

# Hard caps to keep a malformed config from producing absurd output.
MAX_LENGTH = 256
MAX_SOURCE_LEN = 4096


class FlagException(Exception):
    """Raised for malformed flag configuration; surfaced to the admin UI."""


def _render_template(template, context):
    """Substitute {placeholder} tokens using a fixed, known-key context.

    We deliberately use str.replace per known key rather than str.format so
    that stray braces in user/team names can never trigger format-string
    evaluation (str.format is itself an injection vector — CWE-134).
    """
    if template is None:
        return ""
    out = str(template)
    if len(out) > MAX_SOURCE_LEN:
        raise FlagException("source template too long")
    for key, value in context.items():
        out = out.replace("{" + key + "}", str(value))
    return out


def _build_context():
    """Collect substitution variables for the current submitter.

    get_current_user()/get_current_team() return None in edge cases (e.g.
    admin preview, user-mode events). We degrade gracefully to safe defaults.
    """
    user = get_current_user()
    team = None
    try:
        team = get_current_team()
    except Exception:
        # get_current_team() can raise in user-mode CTFs; treat as no team.
        team = None

    return {
        "user_name": getattr(user, "name", "") or "",
        "user_email": getattr(user, "email", "") or "",
        "user_id": getattr(user, "id", 0) or 0,
        "team_name": getattr(team, "name", "") or "",
        "team_id": getattr(team, "id", 0) or 0,
    }


def _digest(scheme, secret, source, length):
    """Compute the raw flag body from whitelisted primitives only."""
    source_bytes = source.encode("utf-8")
    secret_bytes = (secret or "").encode("utf-8")

    if scheme == "sha256":
        body = hashlib.sha256(secret_bytes + source_bytes).hexdigest()
    elif scheme == "hmac-sha256":
        body = hmac.new(secret_bytes, source_bytes, hashlib.sha256).hexdigest()
    elif scheme == "base64":
        body = base64.b64encode(secret_bytes + source_bytes).decode("ascii")
    else:
        raise FlagException("unknown scheme: %r" % scheme)

    if length and length > 0:
        body = body[: min(length, MAX_LENGTH)]
    return body


def _parse_config(data):
    """Validate and normalize the stored JSON config."""
    if not data:
        raise FlagException("empty flag configuration")
    try:
        cfg = json.loads(data)
    except (ValueError, TypeError) as exc:
        raise FlagException("flag config is not valid JSON: %s" % exc)
    if not isinstance(cfg, dict):
        raise FlagException("flag config must be a JSON object")

    scheme = cfg.get("scheme")
    if scheme not in SCHEMES:
        raise FlagException(
            "scheme must be one of %s, got %r" % (", ".join(SCHEMES), scheme)
        )

    length_raw = cfg.get("length", 0)
    try:
        length = int(length_raw)
    except (ValueError, TypeError):
        raise FlagException("length must be an integer")

    return {
        "scheme": scheme,
        "secret": str(cfg.get("secret", "")),
        "source": str(cfg.get("source", "")),
        "format": str(cfg.get("format", "%s")),
        "length": length,
    }


def _apply_dynamic_values(text, challenge_id):
    """Optional integration with ctfd-dynamic-values.

    If that plugin is installed it publishes app.dynamic_values_substitute,
    letting flag source/secret reference {{var}} variables. If it is absent
    (or anything goes wrong) we return the text unchanged — the two plugins
    stay independent.
    """
    if not text or challenge_id is None or "{{" not in text:
        return text
    try:
        from flask import current_app

        dv = getattr(current_app, "dynamic_values_substitute", None)
        if dv:
            return dv(text, challenge_id)
    except Exception as exc:
        logger.warning("dynamic_formula: dynamic_values substitution failed: %s", exc)
    return text


def compute_flag(data, challenge_id=None):
    """Pure-ish function: stored config JSON -> expected flag for current user.

    challenge_id enables optional {{var}} resolution via ctfd-dynamic-values
    and also feeds the {challenge_id} placeholder.
    """
    cfg = _parse_config(data)
    context = _build_context()
    context["challenge_id"] = challenge_id if challenge_id is not None else ""

    # First resolve {{var}} from ctfd-dynamic-values (if installed), then the
    # built-in {placeholder} tokens. Order matters: dynamic values may expand
    # into text that itself contains no placeholders.
    source = _apply_dynamic_values(cfg["source"], challenge_id)
    secret = _apply_dynamic_values(cfg["secret"], challenge_id)
    source = _render_template(source, context)
    secret = _render_template(secret, context)

    # "simple" scheme: no hashing — the resolved source IS the expected flag.
    # Returned verbatim; case/whitespace normalization happens in compare().
    if cfg["scheme"] == "simple":
        return source

    body = _digest(cfg["scheme"], secret, source, cfg["length"])

    fmt = cfg["format"] or "%s"
    if "%s" in fmt:
        return fmt % body
    # No %s placeholder: treat format as a literal prefix wrapper.
    return fmt + body


class DynamicFormulaFlag(BaseFlag):
    name = "dynamic_formula"
    # Nunjucks templates rendered client-side by CTFd's admin Flag forms.
    # Paths are served by register_plugin_assets_directory() in load().
    templates = {
        "create": "/plugins/ctfd-dynamic-flag/assets/create.html",
        "update": "/plugins/ctfd-dynamic-flag/assets/edit.html",
    }

    @staticmethod
    def compare(chal_key_obj, provided):
        """Return True iff `provided` matches the per-user computed flag.

        chal_key_obj is the Flags row; its `.data` holds our JSON config and
        `.content` holds the stored value. CTFd persists the admin-entered
        "Flag value" into `.content`; some versions also mirror it to `.data`.
        We accept whichever is populated.
        """
        config = getattr(chal_key_obj, "content", None) or getattr(
            chal_key_obj, "data", None
        )
        challenge_id = getattr(chal_key_obj, "challenge_id", None)
        try:
            expected = compute_flag(config, challenge_id=challenge_id)
        except FlagException as exc:
            logger.warning("dynamic_formula: bad config: %s", exc)
            return False
        except Exception as exc:  # defensive: never let a flag crash submission
            logger.exception("dynamic_formula: unexpected error: %s", exc)
            return False

        if provided is None:
            return False

        expected_s = str(expected)
        provided_s = str(provided)

        # "simple" scheme: case-insensitive, whitespace-trimmed comparison.
        try:
            scheme = json.loads(config).get("scheme")
        except Exception:
            scheme = None
        if scheme == "simple":
            expected_s = expected_s.strip().lower()
            provided_s = provided_s.strip().lower()

        # Constant-time comparison to avoid leaking the flag via timing.
        return hmac.compare_digest(expected_s, provided_s)


def load(app):
    # Register the new flag type.
    FLAG_CLASSES["dynamic_formula"] = DynamicFormulaFlag

    # Serve the create/edit templates from assets/ at
    # /plugins/ctfd-dynamic-flag/assets/... — same mechanism CTFd's built-in
    # flags use. The directory name inside CTFd/plugins MUST be
    # "ctfd-dynamic-flag" so the asset URLs above resolve.
    register_plugin_assets_directory(
        app, base_path="/plugins/ctfd-dynamic-flag/assets/"
    )
    logger.info("ctfd-dynamic-flag (dynamic_formula) plugin loaded")
