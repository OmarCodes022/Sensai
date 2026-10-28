"""HTTP plumbing: parse a request, run the security checks, dispatch, write the answer."""
import json
import socket
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from sensai.core.errors import SensaiError
from sensai_web import routes, security, static_files
from sensai_web.app import WebApp
from sensai_web.errors import ApiError

MAX_BODY = 8 * 1024 * 1024
HEADERS = {
    "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                               "frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
}


class Request:
    def __init__(self, method: str, path: str, query: dict, headers, body: bytes):
        self.method, self.path, self.query, self.headers, self.body = method, path, query, headers, body
        tab = headers.get("X-Sensai-Tab")
        self.tab = tab if tab and len(tab) <= 64 and tab.isprintable() else None

    def json(self) -> dict:
        try:
            data = json.loads(self.body or b"{}")
        except (ValueError, RecursionError):
            raise ApiError(400, "bad_request", "The request body is not valid JSON.") from None
        if not isinstance(data, dict):
            raise ApiError(400, "bad_request", "The request body must be a JSON object.")
        return data


class Handler(BaseHTTPRequestHandler):
    server_version = "Sensai"
    sys_version = ""
    timeout = 60  # Reading a request; waiting for a reply or an approval never touches the socket.

    def log_message(self, format, *args):  # Quiet by default: requests carry people's messages.
        pass

    do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = do_PATCH = lambda self: self._handle()

    def _handle(self) -> None:
        app: WebApp = self.server.app
        started = False
        try:
            url = urlsplit(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            if length < 0 or length > MAX_BODY:
                raise ApiError(413, "too_large", "The request is too large.")
            body = self.rfile.read(length) if length else b""
            security.check_request(self.command, self.headers, self.server.hosts, bool(body))
            request = Request(self.command, url.path, parse_qs(url.query), self.headers, body)
            if not url.path.startswith("/api/"):
                return self._static(request)
            outcome = self._dispatch(app, request)
            if isinstance(outcome, routes.Stream):
                started = True
                return self._stream(outcome)
            self._send_json(200, outcome)
        except ApiError as exc:
            if not started:
                self._send_json(exc.status, {"error": exc.payload()})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        except Exception:  # Never show internals to the page; the console has the details.
            traceback.print_exc(file=sys.stderr)
            if not started:
                self._send_json(500, {"error": {"code": "internal", "message": "Internal error.", "hint": None}})

    def _dispatch(self, app: WebApp, request: Request):
        allowed = False
        for method, pattern, handler in routes.ROUTES:
            match = pattern.match(request.path)
            if match is None:
                continue
            allowed = True
            if method != request.method:
                continue
            if request.path != "/api/session/takeover":
                app.tabs.check(request.tab)
            return handler(app, request, **match.groupdict())
        raise ApiError(405 if allowed else 404, "method_not_allowed" if allowed else "not_found",
                       "Method not allowed." if allowed else "Not found.")

    def _static(self, request: Request) -> None:
        if request.method not in ("GET", "HEAD"):
            raise ApiError(405, "method_not_allowed", "Method not allowed.")
        if request.path == "/favicon.ico":
            return self._send(204, "image/x-icon", b"")
        kind, data = static_files.read(request.path)
        self._send(200, kind, data, {"Cache-Control": "no-cache"})

    def _send_json(self, status: int, payload: dict) -> None:
        self._send(status, "application/json; charset=utf-8",
                   json.dumps(payload, ensure_ascii=False).encode("utf-8"), {"Cache-Control": "no-store"})

    def _send(self, status: int, kind: str, data: bytes, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        for name, value in {**HEADERS, **(extra or {})}.items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _stream(self, stream: routes.Stream) -> None:
        """Write one JSON object per line as the turn produces them; a lost client stops the turn."""
        alive = True

        def emit(event: dict) -> None:
            nonlocal alive
            if not alive:
                return
            try:
                self.wfile.write(json.dumps(event, ensure_ascii=False).encode("utf-8") + b"\n")
                self.wfile.flush()
            except OSError:
                alive = False
                stream.cancel()

        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Connection", "close")
            for name, value in HEADERS.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.flush()
        except OSError:
            alive = False
            stream.cancel()
        try:
            stream.play(emit)
        except SensaiError as exc:
            emit({"type": "error", "code": "error", "message": str(exc), "hint": None})
        except Exception:
            traceback.print_exc(file=sys.stderr)
            emit({"type": "error", "code": "internal", "message": "Internal error.", "hint": None})
        self.close_connection = True


class WebServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, app: WebApp):
        self.app = app
        security.allowed_hosts(app.cfg.bind, app.cfg.port)  # Refuses a non-loopback address.
        if app.cfg.bind == "::1":
            self.address_family = socket.AF_INET6
        super().__init__((app.cfg.bind, app.cfg.port), Handler)
        # Port 0 asks the system for a free port; the Host header must then match the real one.
        self.hosts = security.allowed_hosts(app.cfg.bind, self.server_address[1])

    def shutdown_all(self) -> None:
        """Stop a running turn, close the socket and remove temporary files."""
        self.server_close()
        self.app.close()
