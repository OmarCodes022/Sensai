"""File access rules (T4) in the page: show them, propose new ones (checked, nothing written), save on a yes.

The model never reaches these routes; the page shows the before and after so the creator approves the change.
"""
import json
import os
import secrets
import tempfile

from sensai.core.ports import PolicyDenied
from sensai.security.file_tools import open_project
from sensai.security.filesystem import SETTINGS, parse_permissions
from sensai_web.errors import ApiError


def _current() -> dict:
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            permissions = json.load(f).get("permissions", {})
    except (OSError, ValueError, AttributeError):
        return {"allow": [], "deny": []}
    return {kind: [r for r in permissions.get(kind, []) if isinstance(r, str)] for kind in ("allow", "deny")}


def rules(app) -> dict:
    return {"on": app.files is not None, "file": SETTINGS, **_current()}


def propose(app, allow: object, deny: object) -> dict:
    after = {"allow": allow, "deny": deny}
    if not all(isinstance(v, list) and all(isinstance(r, str) for r in v) for v in after.values()):
        raise ApiError(400, "bad_rules", "allow and deny must be lists of rules.")
    after = {kind: [r.strip() for r in v if r.strip()] for kind, v in after.items()}
    try:
        parse_permissions(os.getcwd(), after, app.cfg.creator)
    except PolicyDenied as exc:
        raise ApiError(400, "bad_rules", str(exc)) from None
    token = secrets.token_urlsafe(8)
    with app.mutex:
        app.pending_rules = (token, after)
    return {"token": token, "before": _current(), "after": after}


def confirm(app, token: object, approved: object) -> dict:
    with app.mutex:
        pending, app.pending_rules = app.pending_rules, None
    if pending is None or pending[0] != token:
        raise ApiError(409, "no_pending_rules", "There is no rule change waiting for confirmation.")
    if approved is not True:
        return {"status": "discarded", **rules(app)}
    os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=os.path.dirname(SETTINGS), prefix=".settings-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"permissions": pending[1]}, f, indent=2)
        f.write("\n")
    os.replace(temporary, SETTINGS)
    try:
        app.files = open_project(os.getcwd(), app.cfg.creator)  # A folder removed since the proposal fails here.
    except PolicyDenied as exc:
        app.files = None
        raise ApiError(400, "bad_rules", str(exc)) from None
    return {"status": "saved", **rules(app)}
