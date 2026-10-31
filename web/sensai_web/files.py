"""File access within permissions (T4) in the page: /read, /save and the status, through the same check."""
from sensai.chat.blocks import split_block
from sensai.core.ports import PolicyDenied, PortError
from sensai_web.errors import ApiError


def _files(app):
    if app.files is None:
        raise ApiError(409, "file_access_off", "File access is off: there is no .sensai/settings.json where Sensai was started.")
    return app.files


def _fail(exc: PortError, path) -> ApiError:
    if isinstance(exc, PolicyDenied):
        return ApiError(403, "permission_denied", f"Permission denied: {exc} ({path})")
    return ApiError(400, "file_error", f"{exc} ({path})")


def status(app) -> dict:
    if app.files is None:
        return {"on": False}
    allow, deny = app.files.fs.summary
    return {"on": True, "allow": allow, "deny": deny, "settings": ".sensai/settings.json"}


def read(app, path: object) -> dict:
    try:
        text = _files(app).read(path)
    except PortError as exc:
        raise _fail(exc, path) from None
    return {"path": path, "chars": len(text), "text": text}


def save(app, path: object) -> dict:
    """Save the last reply of the open conversation to `path` (created, or replaced when allowed)."""
    files = _files(app)
    with app.mutex:
        reply = next((split_block(m.content)[0].strip() for m in reversed(app.active.session.messages)
                      if m.role == "assistant"), "")
    if not reply:
        raise ApiError(400, "nothing_to_save", "Nothing to save yet: no reply in this conversation.")
    try:
        result = files.save(path, reply + "\n")
    except PortError as exc:
        raise _fail(exc, path) from None
    return {"path": path, "result": result}
