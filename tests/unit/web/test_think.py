"""/think over HTTP: the steps as stream events, and what it keeps in the conversation."""
import json

from sensai.chat.reasoning import Check
from sensai.core.errors import LLMError
from sensai.llm.structured import StructuredOutputError

RATE = '{"tool":"calculate","arguments":{"expression":"630 / 4200 * 100"}}'


class Checker:
    def __init__(self, *results):
        self.results = list(results)

    def complete(self, model, messages, schema):
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def think(page, text="Summarize", checker=None):
    page.app.checker = checker or Checker(Check(ok=True))
    return page.stream({"text": text}, path="/api/think")


def reply(events):
    return "".join(e["delta"] for e in events if e["type"] == "text")


def test_think_streams_the_steps_and_keeps_only_the_request_and_the_answer(web):
    page = web(["1. Say hello"], ["Hello Nadia!"])
    status, events = think(page)
    assert status == 200 and events[-1] == {"type": "done", "status": "completed", "turn_id": events[0]["turn_id"]}
    text = reply(events)
    assert [h for h in ("**Plan**", "**Draft**", "**Check — ok**", "**Final answer (1 round, 0 tool calls)**") if h in text] == \
        ["**Plan**", "**Draft**", "**Check — ok**", "**Final answer (1 round, 0 tool calls)**"]
    assert "1. Say hello" in text and text.rstrip().endswith("Hello Nadia!")
    assert [(m.role, m.content) for m in page.app.active.session.messages[1:]] == [
        ("user", "Summarize"), ("assistant", "Hello Nadia!")]
    assert any(e["type"] == "saved" for e in events)
    stored = page.call("GET", "/api/session")[1]["items"]
    assert [i["text"] for i in stored] == ["Summarize", "Hello Nadia!"]


def test_think_shows_tool_calls_as_cards_not_as_act_and_observe_text(web):
    page = web(["1. Compute"], ["Computing.\n", RATE], ["It is 15.0%"])
    status, events = think(page)
    calls = [e for e in events if e["type"] in ("tool_call", "tool_result")]
    assert [e["type"] for e in calls] == ["tool_call", "tool_result"] and calls[1]["output"] == "15.0"
    text = reply(events)
    assert "**Act**" not in text and "**Observe**" not in text and "calculate(" not in text
    assert "Computing." in text and "(1 round, 1 tool call)" in text


def test_a_problem_found_by_the_check_is_revised_in_the_stream(web):
    page = web(["1. Write"], ["Off-brand slang!"], ["Hydrates."])
    checker = Checker(Check(ok=False, problems=["not an approved claim"]), Check(ok=True))
    text = reply(think(page, checker=checker)[1])
    assert "**Check — 1 problem**" in text and "- not an approved claim" in text and "**Revise**" in text
    assert page.app.active.session.messages[-1].content == "Hydrates."


def test_an_unreadable_check_is_reported_as_unavailable(web):
    page = web(["1. Write"], ["Fine."])
    text = reply(think(page, checker=Checker(StructuredOutputError("bad json")))[1])
    assert "**Check unavailable**" in text and "**Check — ok**" not in text


def test_a_failed_think_adds_nothing_to_the_conversation(web):
    page = web(["1. Write"], ["Fine."])
    status, events = think(page, checker=Checker(LLMError("Ollama went away")))
    assert status == 200 and events[-1]["type"] == "error" and not any(e["type"] == "done" for e in events)
    assert len(page.app.active.session.messages) == 1 and page.app.turn is None
    assert page.call("GET", "/api/session")[1]["items"] == []


def test_think_needs_a_request(web):
    page = web()
    for body in ({"text": " "}, {"text": 3}, {}):
        status, data = page.stream(body, path="/api/think")
        assert status == 400 and data["error"]["code"] == "empty_input"


def test_think_is_a_capability(web):
    assert web().call("GET", "/api/config")[1]["capabilities"]["think"] is True
