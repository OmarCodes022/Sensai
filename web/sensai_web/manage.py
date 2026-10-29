"""Housekeeping the page offers for saved sessions: rename, delete and export."""
import re

from sensai.core.errors import SensaiError
from sensai_web import session_view
from sensai_web.errors import ApiError

MAX_TITLE = 100
UNSAFE = re.compile(r"[^\w.-]+")


def _missing(session_id: str) -> ApiError:
    return ApiError(404, "not_found", f"unknown session: {session_id}")


def rename_session(app, session_id: str, title: object) -> str:
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > MAX_TITLE or not title.isprintable():
        raise ApiError(400, "bad_title", f"Give a title of 1 to {MAX_TITLE} characters on one line.")
    title = " ".join(title.split())
    with app.mutex:
        with app.creator_storage() as creator:
            try:
                creator.sessions.set_title(session_id, title)
            except SensaiError:
                raise _missing(session_id) from None
        if session_id == app.active.recorder.session_id:
            app.active.recorder.title, app.active.recorder.titled = title, True
    return title


def delete_session(app, session_id: str) -> None:
    with app.mutex:
        if session_id == app.active.recorder.session_id:
            raise ApiError(409, "session_open", "Open another conversation (or start a new one) before deleting this one.")
        with app.creator_storage() as creator:
            if all(s.id != session_id for s in creator.sessions.list()):
                raise _missing(session_id)
            creator.sessions.delete(session_id)
    app.times.forget(session_id)


def export_session(app, session_id: str) -> dict:
    """The conversation as Markdown, ready for the page to save as a file."""
    data = app.stored_session_json(session_id)
    lines = [f"# {data.get('title') or session_id}", ""]
    for item in data["items"]:
        if item["kind"] in ("user", "assistant"):
            who = "You" if item["kind"] == "user" else "Sensai"
            lines += [f"**{who}**", "", item["text"], ""]
    return {"filename": f"sensai-{UNSAFE.sub('-', session_id)}.md", "markdown": "\n".join(lines).rstrip() + "\n"}
