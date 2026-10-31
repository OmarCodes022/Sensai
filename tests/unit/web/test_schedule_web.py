"""Scheduling in the page: the background tasks, run now, the drafts, and switched off without a tasks file."""
import json

import pytest


@pytest.fixture
def scheduled(web, tmp_path, monkeypatch):
    tasks = tmp_path / "tasks.json"
    tasks.write_text(json.dumps([{"name": "post-ideas", "prompt": "Three ideas", "every_minutes": 1440, "persona": "redaction"}]))
    monkeypatch.setenv("SENSAI_SCHEDULE_FILE", str(tasks))
    monkeypatch.setenv("SENSAI_DRAFTS_DIR", str(tmp_path / "drafts"))
    return web


def test_tasks_run_in_the_background_and_on_demand(scheduled, monkeypatch):
    from sensai_web import app as web_app
    from fakes import FakeClient
    page = scheduled(client=FakeClient(["Idea A"], ["Idea B"], ["Idea C"]))
    for _ in range(50):  # The first run happens at start, in the background.
        if page.app.scheduler.status()[0]["last"]:
            break
        import time
        time.sleep(0.05)
    body = page.call("GET", "/api/schedule")[1]
    assert body["on"] and body["tasks"][0]["name"] == "post-ideas" and body["tasks"][0]["last"]["ok"]
    assert page.call("GET", "/api/config")[1]["capabilities"]["schedule"] is True
    result = page.call("POST", "/api/schedule/post-ideas/run")[1]
    assert result["ok"] and result["draft"].endswith("-post-ideas.md")
    draft = page.call("GET", "/api/schedule")[1]["drafts"][0]["name"]
    text = page.call("GET", f"/api/drafts/{draft}")[1]["text"]
    assert "Nothing was posted or sent." in text
    assert page.call("POST", "/api/schedule/ghost/run")[0] == 404
    assert page.call("GET", "/api/drafts/nope.md")[0] == 404


def test_without_a_tasks_file_scheduling_is_off(web):
    page = web()
    assert page.call("GET", "/api/schedule")[1] == {"on": False}
    assert page.call("POST", "/api/schedule/x/run")[1]["error"]["code"] == "schedule_off"
    assert "schedule" not in page.call("GET", "/api/config")[1]["capabilities"]


def test_a_scheduled_run_knows_the_products_claims_and_saved_facts(scheduled, tmp_path, monkeypatch):
    from fakes import FakeClient
    brand = tmp_path / "brand.json"
    brand.write_text(json.dumps({"products": [{"name": "Calm Barrier Cream", "claims": [
        {"id": "C03", "text": "Reduces redness in 4 weeks", "valid_from": "2020-01-01", "valid_until": "2999-01-01", "approved": True}]}]}))
    monkeypatch.setenv("SENSAI_BRAND_FILE", str(brand))
    client = FakeClient(["Idea A"], ["Idea B"])
    page = scheduled(client=client)
    assert page.call("PUT", "/api/facts/launch.date", {"text": "Launch on 3 December"})[0] == 200
    assert page.call("POST", "/api/schedule/post-ideas/run")[1]["ok"]
    prompt = client.requests[-1][1][0].content
    assert '- Calm Barrier Cream: "Reduces redness in 4 weeks"' in prompt
    assert "launch.date: Launch on 3 December" in prompt and "Never invent products" in prompt
