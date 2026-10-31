"""Listing the installed models and switching the chat to one."""
import threading

from sensai_web import models


def test_the_model_can_be_listed_and_switched_to_an_installed_one(web, monkeypatch):
    page = web()
    monkeypatch.setattr(models, "fetch_tags", lambda host: (True, 1.0, ["gemma3:1b", "qwen2.5:latest"]))
    assert page.call("GET", "/api/models")[1] == {"current": "fake", "reachable": True, "installed": ["gemma3:1b", "qwen2.5:latest"]}
    assert page.call("POST", "/api/model", {"name": "qwen2.5"}) == (200, {"model": "qwen2.5"})
    assert page.app.active.session.model == "qwen2.5" and page.call("GET", "/api/config")[1]["model"] == "qwen2.5"
    status, body = page.call("POST", "/api/model", {"name": "missing"})
    assert status == 404 and body["error"]["code"] == "model_unknown" and page.app.model == "qwen2.5"
    assert page.call("POST", "/api/model", {"name": " "})[0] == 400


def test_the_model_cannot_change_when_ollama_is_down_or_during_a_reply(web, monkeypatch):
    page = web()
    monkeypatch.setattr(models, "fetch_tags", lambda host: (False, 0.0, []))
    assert page.call("POST", "/api/model", {"name": "x"})[0] == 503
    monkeypatch.setattr(models, "fetch_tags", lambda host: (True, 1.0, ["x:latest"]))
    page.app.turn = threading.Event()
    assert page.call("POST", "/api/model", {"name": "x"})[0] == 429
