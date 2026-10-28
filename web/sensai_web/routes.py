"""The /api endpoints. Each handler takes (app, request) and returns a JSON object or a Stream."""
import re
from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata
from time import monotonic

from sensai.core.cancellation import CancellationToken
from sensai.sandbox import SandboxLimits
from sensai.tools import MAX_TOOL_CALLS
from sensai_web import sandbox, session_view
from sensai_web.app import WebApp
from sensai_web.errors import ApiError
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
        "capabilities": {name: True for name in CAPABILITIES}, "draft_personas": app.catalogue.drafts(),
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
    return {"items": tool_list()}


@route("POST", r"/api/run")
def run(app: WebApp, request):
    code = request.json().get("code")
    if not app.run_lock.acquire(blocking=False):
        raise ApiError(429, "busy", "A run is already in progress.")
    try:
        token = CancellationToken(monotonic() + app.cfg.operation_timeout)
        return sandbox.run_code(code, app.cfg.data_dir, token, app.meta_dir)
    finally:
        app.run_lock.release()


@route("GET", r"/api/run/data")
def run_data(app: WebApp, request):
    return sandbox.data_files(app.cfg.data_dir)


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
