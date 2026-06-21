"""
CTFd plugin: ctfd-dynamic-values.

Lets admins define named, per-challenge variables that are generated
deterministically from the current participant's identity + an optional salt,
using a token mask (e.g. an IP, a port, a hex id). Values are stateless: the
same participant always sees the same value (stable across page refreshes).

Variables are referenced as {{name}} in the challenge description; each
participant sees their own generated value substituted in.

Optional integration: if ctfd-dynamic-flag is also installed, it can pull the
same {{name}} variables into its flag source/secret via the loosely-coupled
hook published on the Flask app (app.dynamic_values_substitute). No imports
between plugin packages are required.

The directory MUST be mounted as "ctfd-dynamic-values" inside CTFd/plugins so
the asset URLs /plugins/ctfd-dynamic-values/assets/... resolve.
"""

import logging
import re

from flask import Blueprint, request
from sqlalchemy.exc import IntegrityError

from CTFd.models import db
from CTFd.plugins import (
    register_admin_plugin_script,
    register_plugin_assets_directory,
)
from CTFd.utils.decorators import admins_only
from CTFd.utils.user import get_current_team, get_current_user

from .generator import generate, scope_key_for

logger = logging.getLogger("dynamic_values")

# {{var_name}} reference inside descriptions / flag fields.
_REF_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")

VALID_SCOPES = ("user", "team", "global")
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MAX_NAME = 64
MAX_MASK = 512
MAX_SALT = 256


# --------------------------------------------------------------------------- #
# Model
# --------------------------------------------------------------------------- #
class DynamicValue(db.Model):
    __tablename__ = "dynamic_values"

    id = db.Column(db.Integer, primary_key=True)
    challenge_id = db.Column(
        db.Integer,
        db.ForeignKey("challenges.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(MAX_NAME), nullable=False)
    mask = db.Column(db.String(MAX_MASK), nullable=False, default="")
    salt = db.Column(db.String(MAX_SALT), nullable=True)
    scope = db.Column(db.String(16), nullable=False, default="user")

    __table_args__ = (
        db.UniqueConstraint("challenge_id", "name", name="uq_dv_chal_name"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "challenge_id": self.challenge_id,
            "name": self.name,
            "mask": self.mask,
            "salt": self.salt or "",
            "scope": self.scope,
        }


# --------------------------------------------------------------------------- #
# Core: deterministic value for current participant
# --------------------------------------------------------------------------- #
def _current_identity():
    """Return (user_id, team_id) for the current request, with safe defaults."""
    user = get_current_user()
    user_id = getattr(user, "id", 0) or 0
    team_id = 0
    try:
        team = get_current_team()
        team_id = getattr(team, "id", 0) or 0
    except Exception:
        team_id = 0
    return user_id, team_id


def value_for(variable, user_id=None, team_id=None):
    """Compute the concrete value of a DynamicValue row for an identity.

    If user_id/team_id are not given, they are resolved from the current
    request context.
    """
    if user_id is None and team_id is None:
        user_id, team_id = _current_identity()
    key = scope_key_for(variable.scope, user_id, team_id)
    return generate(
        variable.mask, key, variable.salt, variable.challenge_id, variable.name
    )


def substitute(text, challenge_id, user_id=None, team_id=None):
    """Replace {{name}} references in `text` with generated values.

    Used both by the description monkey-patch and (optionally) by
    ctfd-dynamic-flag. Unknown names are left untouched. Never raises.
    """
    if not text or "{{" not in text:
        return text
    try:
        rows = DynamicValue.query.filter_by(challenge_id=challenge_id).all()
    except Exception as exc:
        logger.warning("dynamic_values: lookup failed for chal %s: %s", challenge_id, exc)
        return text
    if not rows:
        return text
    by_name = {r.name: r for r in rows}

    def repl(match):
        name = match.group(1)
        var = by_name.get(name)
        if var is None:
            return match.group(0)  # leave unknown {{name}} as-is
        try:
            return value_for(var, user_id, team_id)
        except Exception as exc:
            logger.warning("dynamic_values: gen failed for %s: %s", name, exc)
            return match.group(0)

    return _REF_RE.sub(repl, text)


# --------------------------------------------------------------------------- #
# Description substitution via challenge-class read() monkey-patch
# --------------------------------------------------------------------------- #
def _patch_challenge_classes():
    """Wrap read() on every registered challenge class so descriptions get
    {{var}} substituted in-memory (never persisted) for the current user.
    """
    from CTFd.plugins.challenges import CHALLENGE_CLASSES

    for cls in list(CHALLENGE_CLASSES.values()):
        if getattr(cls, "_dv_patched", False):
            continue
        original_read = cls.read

        def make_wrapper(orig):
            def read(cls_inner, challenge):
                # Substitute {{var}} on the challenge object BEFORE read() runs,
                # so both the returned "description" AND the server-rendered
                # "view" HTML (which CTFd builds separately from challenge.*)
                # pick up the per-user values.
                #
                # GET /challenges is a read-only request: CTFd does not commit
                # the session for it, so mutating challenge.description in-memory
                # does not persist to the database. The server-rendered "view"
                # HTML is built by the API *after* read() returns, from this same
                # challenge object — so leaving the substituted value in place is
                # what makes {{var}} show up for participants.
                try:
                    desc = getattr(challenge, "description", None)
                    if desc and "{{" in desc:
                        challenge.description = substitute(desc, challenge.id)
                except Exception as exc:
                    logger.warning("dynamic_values: read patch failed: %s", exc)
                return orig(challenge=challenge)

            return classmethod(read)

        cls.read = make_wrapper(original_read)
        cls._dv_patched = True
        logger.info("dynamic_values: patched read() on %s", cls.__name__)


# --------------------------------------------------------------------------- #
# Admin REST API
# --------------------------------------------------------------------------- #
def _validate_payload(payload, partial=False):
    """Validate/normalize a create/update payload. Returns (data, error)."""
    data = {}

    if not partial or "name" in payload:
        name = (payload.get("name") or "").strip()
        if not NAME_RE.match(name or "") or len(name) > MAX_NAME:
            return None, "name must match [A-Za-z_][A-Za-z0-9_]* (<= 64 chars)"
        data["name"] = name

    if not partial or "mask" in payload:
        mask = payload.get("mask") or ""
        if len(mask) > MAX_MASK:
            return None, "mask too long"
        data["mask"] = mask

    if "salt" in payload:
        salt = payload.get("salt") or ""
        if len(salt) > MAX_SALT:
            return None, "salt too long"
        data["salt"] = salt or None

    if not partial or "scope" in payload:
        scope = (payload.get("scope") or "user").strip()
        if scope not in VALID_SCOPES:
            return None, "scope must be one of %s" % ", ".join(VALID_SCOPES)
        data["scope"] = scope

    return data, None


def load(app):
    app.db.create_all()

    # Publish the loosely-coupled substitution hook for other plugins
    # (e.g. ctfd-dynamic-flag). No cross-package import needed.
    app.dynamic_values_substitute = substitute

    blueprint = Blueprint("ctfd_dynamic_values", __name__)

    @blueprint.route("/api/v1/plugins/dynamic_values", methods=["GET"])
    @admins_only
    def list_values():
        challenge_id = request.args.get("challenge_id", type=int)
        q = DynamicValue.query
        if challenge_id is not None:
            q = q.filter_by(challenge_id=challenge_id)
        return {"success": True, "data": [v.to_dict() for v in q.all()]}

    @blueprint.route("/api/v1/plugins/dynamic_values", methods=["POST"])
    @admins_only
    def create_value():
        payload = request.get_json(force=True, silent=True) or {}
        challenge_id = payload.get("challenge_id")
        if not challenge_id:
            return {"success": False, "errors": {"challenge_id": "required"}}, 400
        data, err = _validate_payload(payload)
        if err:
            return {"success": False, "errors": {"": err}}, 400
        row = DynamicValue(challenge_id=challenge_id, **data)
        db.session.add(row)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return {
                "success": False,
                "errors": {"name": "a variable with this name already exists"},
            }, 400
        return {"success": True, "data": row.to_dict()}

    @blueprint.route("/api/v1/plugins/dynamic_values/<int:value_id>", methods=["PATCH"])
    @admins_only
    def update_value(value_id):
        row = DynamicValue.query.filter_by(id=value_id).first()
        if not row:
            return {"success": False, "errors": {"": "not found"}}, 404
        payload = request.get_json(force=True, silent=True) or {}
        data, err = _validate_payload(payload, partial=True)
        if err:
            return {"success": False, "errors": {"": err}}, 400
        for k, v in data.items():
            setattr(row, k, v)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return {
                "success": False,
                "errors": {"name": "a variable with this name already exists"},
            }, 400
        return {"success": True, "data": row.to_dict()}

    @blueprint.route("/api/v1/plugins/dynamic_values/<int:value_id>", methods=["DELETE"])
    @admins_only
    def delete_value(value_id):
        row = DynamicValue.query.filter_by(id=value_id).first()
        if row:
            db.session.delete(row)
            db.session.commit()
        return {"success": True}

    @blueprint.route("/api/v1/plugins/dynamic_values/preview", methods=["GET"])
    @admins_only
    def preview_value():
        """Render a mask for a sample identity so admins can see the output."""
        mask = request.args.get("mask", "")
        salt = request.args.get("salt", "") or None
        scope = request.args.get("scope", "user")
        challenge_id = request.args.get("challenge_id", default=0, type=int)
        name = request.args.get("name", "preview")
        # Use the current admin's identity as the sample.
        user_id, team_id = _current_identity()
        key = scope_key_for(scope, user_id, team_id)
        try:
            sample = generate(mask, key, salt, challenge_id, name)
        except Exception as exc:
            return {"success": False, "errors": {"mask": str(exc)}}, 400
        return {"success": True, "data": {"value": sample}}

    app.register_blueprint(blueprint)

    # Serve admin assets (variables.js / .css).
    register_plugin_assets_directory(
        app, base_path="/plugins/ctfd-dynamic-values/assets/"
    )
    # Inject the Variables tab on the admin challenge page.
    register_admin_plugin_script(
        "/plugins/ctfd-dynamic-values/assets/variables.js"
    )

    # Substitute {{var}} into challenge descriptions for participants.
    _patch_challenge_classes()

    logger.info("ctfd-dynamic-values plugin loaded")
