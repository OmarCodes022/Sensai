"""The /api endpoints. Each handler takes (app, request) and returns a JSON object or a Stream."""
import re
from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata
from time import monotonic
from urllib.parse import unquote

from sensai.core.cancellation import CancellationToken
from sensai.core.errors import LLMError
from sensai.memory.vector_index import VectorIndexError
from sensai.rag import MAX_FILE_BYTES, MAX_TOTAL_BYTES, TYPES, DocError
from sensai.sandbox import SandboxLimits
from sensai.tools import MAX_TOOL_CALLS
from sensai_web import sandbox, session_view
from sensai_web.app import WebApp
from sensai_web.errors import ApiError, llm_failure
from sensai_web.tools import tool_list
from sensai_web.turn import run_turn

MAX_TEXT_CHARS = 200_000
CAPABILITIES = ("chat", "personas", "sessions", "profile", "usage", "tools", "approval", "sandbox",
                "run_script", "history")
STARTED = monotonic()
ROUTES: list[tuple[str, re.Pattern, Callable]] = []


@dataclass
class Stream:
    """Answer as newline-delimited JSON: play(emit) runs while the response is open."""
    play: Callable[[Callable[[dict], None]], None]
    cancel: Callable[[], None]


def route(method: str, pattern: str):
    def register(handler):
        ROUTES.append((method, re.compile(pattern + r"\Z"), handler))
        return handler
    return register


def _version() -> str:
    try:
        return metadata.version("sensai")
    except metadata.PackageNotFoundError:
        return "0.1.0"


@route("GET", r"/api/health")
def health(app: WebApp, request):
    return {"ok": True, "version": _version(), "remote": bool(app.cfg.ssh_host), "uptime_s": round(monotonic() - STARTED),
            **app.health.check()}


@route("GET", r"/api/config")
def config(app: WebApp, request):
    cfg, limits = app.cfg, SandboxLimits()
    return {
        "capabilities": {name: True for name in (*CAPABILITIES, *(("documents",) if app.docs.enabled else ()))},
        "draft_personas": app.catalogue.drafts(),
        "context_length": cfg.context_length, "creator": cfg.creator, "model": cfg.model,
        "effective": cfg.effective,
        "limits": {"turn_seconds": cfg.operation_timeout, "tool_rounds": MAX_TOOL_CALLS,
                   "sandbox": {"wall_seconds": limits.wall_seconds, "cpu_seconds": limits.cpu_seconds,
                               "memory_mb": limits.memory_bytes // 2**20, "file_mb": limits.file_bytes // 2**20,
                               "output_chars": limits.output_chars, "data_mb": limits.data_bytes // 2**20}},
    }


@route("GET", r"/api/personas")
def personas(app: WebApp, request):
    return {"active": app.active.persona_id, "source": app.catalogue.source, "items": app.catalogue.describe()}


@route("PUT", r"/api/personas/(?P<id>[^/]+)")
def save_persona(app: WebApp, request, id: str):
    result = app.save_persona(unquote(id), request.json())
    return {"result": result, "active": app.active.persona_id, "items": app.catalogue.describe()}


@route("DELETE", r"/api/personas/(?P<id>[^/]+)")
def delete_persona(app: WebApp, request, id: str):
    app.delete_persona(unquote(id))
    return {"active": app.active.persona_id, "items": app.catalogue.describe()}


@route("POST", r"/api/persona")
def set_persona(app: WebApp, request):
    return {"active": app.set_persona(request.json().get("id"))}


@route("GET", r"/api/session")
def session(app: WebApp, request):
    with app.mutex:
        return app.session_json(app.active)


@route("POST", r"/api/sessions")
def new_session(app: WebApp, request):
    return app.new_session()


@route("GET", r"/api/sessions")
def sessions(app: WebApp, request):
    return {"items": app.session_list()}


@route("GET", r"/api/sessions/(?P<id>[^/]+)")
def get_session(app: WebApp, request, id: str):
    return app.stored_session_json(id)


@route("POST", r"/api/sessions/(?P<id>[^/]+)/resume")
def resume(app: WebApp, request, id: str):
    return app.resume(id)


@route("GET", r"/api/history")
def history(app: WebApp, request):
    with app.mutex:
        return {"items": session_view.history(app.active.session.messages)}


@route("POST", r"/api/chat")
def chat(app: WebApp, request):
    text = request.json().get("text")
    if not isinstance(text, str) or not text.strip():
        raise ApiError(400, "empty_input", "Please type something.")
    if len(text) > MAX_TEXT_CHARS:
        raise ApiError(413, "too_large", "The message is too long.")
    stop, active = app.begin_turn()

    def play(emit):
        try:
            run_turn(app, active, stop, text, emit)
        finally:
            app.end_turn()

    return Stream(play, stop.set)


@route("POST", r"/api/chat/stop")
def stop_chat(app: WebApp, request):
    return {"stopped": app.stop_turn()}


@route("POST", r"/api/approvals/(?P<id>[^/]+)")
def approve(app: WebApp, request, id: str):
    approved = request.json().get("approved")
    if not isinstance(approved, bool):
        raise ApiError(400, "bad_request", "approved must be true or false.")
    if not app.approvals.decide(id, approved):
        raise ApiError(404, "not_found", "No approval is waiting under that id.")
    return {"ok": True}


@route("GET", r"/api/tools")
def tools(app: WebApp, request):
    return {"items": tool_list(documents=app.docs.enabled)}


@route("POST", r"/api/run")
def run(app: WebApp, request):
    code = request.json().get("code")
    if not app.run_lock.acquire(blocking=False):
        raise ApiError(429, "busy", "A run is already in progress.")
    try:
        token = CancellationToken(monotonic() + app.cfg.operation_timeout)
        return sandbox.run_code(code, app.data.path, token, app.meta_dir)
    finally:
        app.run_lock.release()


@route("GET", r"/api/run/data")
def run_data(app: WebApp, request):
    return app.data.listing()


@route("POST", r"/api/run/data/example")
def add_example_data(app: WebApp, request):
    return app.data.add_example()


@route("PUT", r"/api/run/data/(?P<name>[^/]+)")
def put_data(app: WebApp, request, name: str):
    return app.data.put(unquote(name), request.json().get("text"))


@route("GET", r"/api/run/data/(?P<name>[^/]+)")
def read_data(app: WebApp, request, name: str):
    return app.data.read(unquote(name))


@route("DELETE", r"/api/run/data/(?P<name>[^/]+)")
def delete_data(app: WebApp, request, name: str):
    return app.data.delete(unquote(name))


@route("GET", r"/api/profile")
def profile(app: WebApp, request):
    return {"id": "default", "preferences": dict(app.preferences)}


@route("PUT", r"/api/profile")
def put_profile(app: WebApp, request):
    return {"id": "default", "preferences": app.save_profile(request.json().get("preferences"))}


@route("POST", r"/api/session/takeover")
def takeover(app: WebApp, request):
    app.tabs.takeover(request.tab)
    return {"ok": True}


def _docs_listing(app: WebApp) -> dict:
    app.docs.sync()
    return {**app.docs.status(), "items": app.docs.documents(),
            "limits": {"file_mb": MAX_FILE_BYTES // 2**20, "total_mb": MAX_TOTAL_BYTES // 2**20, "types": list(TYPES)}}


def _doc_error(error: DocError) -> ApiError:
    return ApiError(413 if "MB" in str(error) else 400, "bad_document", str(error))


@route("GET", r"/api/docs")
def docs(app: WebApp, request):
    return _docs_listing(app)


@route("PUT", r"/api/docs/(?P<name>[^/]+)")
def put_doc(app: WebApp, request, name: str):
    try:
        app.docs.put(unquote(name), request.json().get("text"))
    except DocError as error:
        raise _doc_error(error) from None
    return _docs_listing(app)


@route("DELETE", r"/api/docs/(?P<name>[^/]+)")
def delete_doc(app: WebApp, request, name: str):
    try:
        app.docs.remove(unquote(name))
    except DocError as error:
        raise ApiError(404 if str(error).startswith("No document") else 400, "bad_document", str(error)) from None
    return _docs_listing(app)


@route("POST", r"/api/docs/reindex")
def reindex_docs(app: WebApp, request):
    if not app.docs.enabled:
        raise ApiError(400, "bad_document", "Document search is switched off (SENSAI_DOCS is empty).")
    app.docs.reindex()
    return _docs_listing(app)


@route("GET", r"/api/docs/search")
def search_docs(app: WebApp, request):
    query = (request.query.get("q") or [""])[0].strip()
    if not query:
        raise ApiError(400, "bad_request", "Type something to search for.")
    try:
        hits = app.docs.search(query, 5)
    except LLMError as error:
        raise ApiError(503, **{k: v for k, v in llm_failure(error, app.docs.model).items()}) from None
    except VectorIndexError as error:
        raise ApiError(400, "bad_request", str(error)) from None
    return {"items": [{"source": h.source, "score": round(h.score, 3), "text": h.text} for h in hits],
            "state": app.docs.status()["state"]}


@route("GET", r"/api/docs/(?P<name>[^/]+)")
def get_doc(app: WebApp, request, name: str):
    """One document's text for the page's viewer (registered after /api/docs/search, which it would shadow)."""
    try:
        return app.docs.read(unquote(name))
    except DocError as error:
        raise ApiError(404 if str(error).startswith("No document") else 400, "bad_document", str(error)) from None
