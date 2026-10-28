"""A real HTTP server on a free port, backed by a scripted model client and a temp database."""
import http.client
import json
import threading

import pytest

from fakes import FakeClient
from sensai.settings import Settings
from sensai_web import app as web_app
from sensai_web.config import WebConfig
from sensai_web.server import WebServer


def make_config(tmp_path, **overrides) -> WebConfig:
    values = dict(model="fake", host="http://localhost:1", timeout=5.0, operation_timeout=30.0,
                  context_length=None, db_path=str(tmp_path / "web.sqlite3"), creator="default",
                  prompt_path=None, persona=None, personas_file=None, profile_file=None,
                  data_dir=None, session=None, bind="127.0.0.1", port=0, effective={})
    values.update(overrides)
    return WebConfig(**values)


class Page:
    """What the browser would do: JSON calls and an NDJSON stream, with the right Host header."""

    def __init__(self, server, app, client):
        self.server, self.app, self.client = server, app, client
        self.port = server.server_address[1]
        self.tab = None

    def _connection(self):
        return http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)

    def _headers(self, extra):
        headers = {"Host": f"localhost:{self.port}", "Content-Type": "application/json"}
        if self.tab:
            headers["X-Sensai-Tab"] = self.tab
        return {**headers, **(extra or {})}

    def call(self, method, path, body=None, headers=None, raw=None):
        connection = self._connection()
        try:
            raw = raw if raw is not None else json.dumps(body) if body is not None else None
            connection.request(method, path, raw, self._headers(headers))
            response = connection.getresponse()
            data = response.read()
        finally:
            connection.close()
        kind = response.getheader("Content-Type", "")
        return response.status, (json.loads(data) if "json" in kind else data)

    def stream(self, body, on_event=None, path="/api/chat"):
        """POST and read events until the stream closes; `on_event(event)` may act mid-stream."""
        connection = self._connection()
        events = []
        try:
            connection.request("POST", path, json.dumps(body), self._headers(None))
            response = connection.getresponse()
            if response.status != 200:
                return response.status, json.loads(response.read())
            for line in response:
                event = json.loads(line)
                events.append(event)
                if on_event:
                    on_event(event)
        finally:
            connection.close()
        return 200, events


@pytest.fixture
def web(tmp_path, monkeypatch):
    started = []

    def start(*replies, client=None, **overrides):
        client = client or FakeClient(*replies)
        monkeypatch.setattr(web_app, "make_client", lambda settings, usage_sink=None: client)
        app = web_app.WebApp(make_config(tmp_path, **overrides), Settings(_env_file=None))
        server = WebServer(app)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        started.append(server)
        return Page(server, app, client)

    yield start
    for server in started:
        server.shutdown()
        server.shutdown_all()
