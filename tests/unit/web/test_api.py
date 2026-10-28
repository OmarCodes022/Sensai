"""The JSON endpoints over real HTTP, with a scripted model."""
import pytest

from sensai.core.errors import LLMConnectionError, LLMError, ModelNotFoundError
from sensai_web.health import Health


def kinds(events):
    return [event["type"] for event in events]


def test_health_reports_ollama_and_the_model(web):
    page = web()
    page.app.health = Health("localhost:11434", "fake", fetch=lambda host: (True, 4.2, ["fake:latest"]))
    status, body = page.call("GET", "/api/health")
    assert status == 200 and body["ok"] is True and body["remote"] is False
    assert body["ollama"] == {"reachable": True, "host": "http://localhost:11434", "latency_ms": 4}
    assert body["model"] == {"name": "fake", "available": True}


def test_health_says_so_when_ollama_is_down(web):
    page = web()
    page.app.health = Health("http://x", "fake", fetch=lambda host: (False, 0.0, []))
    body = page.call("GET", "/api/health")[1]
    assert body["ollama"]["reachable"] is False and body["model"]["available"] is False


def test_config_lists_capabilities_and_limits(web):
    page = web(context_length=2048, effective={"model": {"value": "fake", "source": "cli"}})
    body = page.call("GET", "/api/config")[1]
    assert body["capabilities"]["chat"] and body["capabilities"]["run_script"]
    assert "campaign" not in body["capabilities"]
    assert body["context_length"] == 2048 and body["model"] == "fake" and body["creator"] == "default"
    assert body["limits"]["tool_rounds"] == 5 and body["limits"]["sandbox"]["wall_seconds"] == 15
    assert body["effective"]["model"]["source"] == "cli"
    assert body["draft_personas"] == ["redaction", "communaute"]


def test_personas_can_be_listed_and_switched(web):
    page = web()
    body = page.call("GET", "/api/personas")[1]
    assert body["active"] is None and body["source"] == "builtin"
    assert {p["id"] for p in body["items"]} == {"redaction", "communaute", "analyse"}
    assert body["items"][0]["starters"]
    assert page.call("POST", "/api/persona", {"id": "analyse"}) == (200, {"active": "analyse"})
    assert page.call("GET", "/api/personas")[1]["active"] == "analyse"
    assert "Persona: Analyse" in page.app.active.session.messages[0].content


def test_an_unknown_persona_is_a_404_with_a_stable_code(web):
    page = web()
    status, body = page.call("POST", "/api/persona", {"id": "marketing"})
    assert status == 404 and body["error"]["code"] == "persona_unknown"
    assert page.call("POST", "/api/persona", {"id": 3})[0] == 404


def test_the_configured_persona_is_active_from_the_start(web):
    assert web(persona="communaute").call("GET", "/api/session")[1]["persona"] == "communaute"


def test_tools_lists_both_tools_with_their_rules(web):
    items = web().call("GET", "/api/tools")[1]["items"]
    assert [(t["name"], t["confirm"], t["timeout"]) for t in items] == [("calculate", False, 30), ("run_python", True, 30)]
    assert items[1]["parameters"]["required"] == ["code"]


def test_the_profile_is_stored_validated_and_used_in_the_prompt(web):
    page = web()
    assert page.call("GET", "/api/profile")[1] == {"id": "default", "preferences": {}}
    status, body = page.call("PUT", "/api/profile", {"preferences": {" name ": " Nadia ", "ton": "direct"}})
    assert status == 200 and body["preferences"] == {"name": "Nadia", "ton": "direct"}
    assert page.call("GET", "/api/profile")[1]["preferences"] == {"name": "Nadia", "ton": "direct"}
    assert "- name : Nadia" in page.app.active.session.messages[0].content


@pytest.mark.parametrize("preferences", [[], "x", {"a": 1}, {"": "x"}, {"a": " "}, {"a": "x", " a": "y"}])
def test_an_invalid_profile_is_refused_and_nothing_is_saved(web, preferences):
    page = web()
    status, body = page.call("PUT", "/api/profile", {"preferences": preferences})
    assert status == 400 and body["error"]["code"] == "profile_invalid"
    assert page.call("GET", "/api/profile")[1]["preferences"] == {}


def test_a_stored_profile_survives_a_restart(web, tmp_path):
    web().call("PUT", "/api/profile", {"preferences": {"ton": "direct"}})
    assert web().call("GET", "/api/profile")[1]["preferences"] == {"ton": "direct"}


def test_bad_requests_get_json_errors(web):
    page = web()
    assert page.call("GET", "/api/nope")[0] == 404
    status, body = page.call("DELETE", "/api/health")
    assert status == 405 and body["error"]["code"] == "method_not_allowed"
    status, body = page.call("POST", "/api/persona", raw="{nope")
    assert status == 400 and body["error"]["code"] == "bad_request"
    status, body = page.call("POST", "/api/persona", [1, 2])
    assert status == 400 and body["error"]["code"] == "bad_request"


def test_the_page_is_served_and_unknown_files_are_404(web):
    page = web()
    status, body = page.call("GET", "/")
    assert status == 200 and b"<html" in body.lower()
    assert page.call("GET", "/js/main.js")[0] == 200
    assert page.call("GET", "/js/nothing.js")[0] == 404
    assert page.call("POST", "/")[0] == 405


def test_requests_for_other_hosts_are_refused(web):
    page = web()
    status, body = page.call("GET", "/api/config", headers={"Host": "evil.example"})
    assert status == 403 and body["error"]["code"] == "forbidden_host"
    assert page.call("POST", "/api/run", {"code": "print(1)"}, headers={"Origin": "http://evil.example"})[0] == 403


def test_a_second_tab_is_locked_out_until_it_takes_over(web):
    page = web()
    page.tab = "first"
    assert page.call("GET", "/api/config")[0] == 200
    page.tab = "second"
    status, body = page.call("GET", "/api/config")
    assert status == 409 and body["error"]["code"] == "tab_locked"
    assert page.call("POST", "/api/session/takeover") == (200, {"ok": True})
    assert page.call("GET", "/api/config")[0] == 200
    page.tab = "first"
    assert page.call("GET", "/api/config")[0] == 409


def test_each_endpoint_error_is_a_clean_failure_not_a_crash(web):
    page = web()
    assert page.call("GET", "/api/sessions/nope")[0] == 404
    assert page.call("POST", "/api/sessions/nope/resume")[0] == 404
    assert page.call("POST", "/api/approvals/nope", {"approved": True})[0] == 404
    assert page.call("POST", "/api/approvals/x", {"approved": "yes"})[0] == 400
    assert page.call("POST", "/api/chat/stop") == (200, {"stopped": False})


def test_model_failures_become_error_events_with_hints(web):
    failures = [(ModelNotFoundError("model 'fake' not found"), "model_not_found", "ollama pull fake"),
                (LLMConnectionError("cannot reach Ollama"), "connection", "ollama serve"),
                (LLMError("Ollama timed out"), "timeout", None),
                (LLMError("invalid response from Ollama"), "invalid_response", None),
                (LLMError("boom"), "llm_error", None)]
    page = web(*[failure[0] for failure in failures])
    for _, code, hint in failures:
        status, events = page.stream({"text": "hi"})
        error = events[-1]
        assert (status, kinds(events)) == (200, ["turn_start", "error"])
        assert (error["code"], error["hint"]) == (code, hint)
    assert page.call("GET", "/api/session")[1]["items"] == []  # Failed turns leave no trace.
    assert page.call("POST", "/api/chat/stop") == (200, {"stopped": False})  # And the slot is free again.
