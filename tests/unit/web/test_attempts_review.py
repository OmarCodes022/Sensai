"""T21 web review: attempts across turns, refusals, restored states, data line edge cases, card text."""
import json
import os

import pytest

from sensai.core.messages import Message
from sensai.sandbox import FIX_IT
from sensai_web import session_view

STOP = "Stopped after 3 attempts: answer with the last result or error, without calling run_python again."
LAST = "This was the last attempt: answer with this result or error, without calling run_python again."
ROUND_NOTE = "\nTool round limit reached. Give a final answer without tools."
DATA_LINE = "Data files available to run_python: "


def py(code):
    return [json.dumps({"tool": "run_python", "arguments": {"code": code}})]


def of_type(events, kind):
    return [event for event in events if event["type"] == kind]


def answer(page, decisions):
    """Approves or refuses each approval in order; records the call ids that asked."""
    asked = []

    def on_event(event):
        if event["type"] == "approval_request":
            asked.append(event["call_id"])
            approved = decisions[len(asked) - 1] if len(asked) <= len(decisions) else True
            page.call("POST", f"/api/approvals/{event['id']}", {"approved": approved})
    return on_event, asked


def attempts(events, kind):
    return [(e.get("attempt"), e.get("max_attempts")) for e in of_type(events, kind)]


def test_attempts_restart_at_one_on_the_next_turn(web):
    page = web(*([py("print(1 / 0)")] * 4), ["Turn one failed."], py("print(2)"), ["Two."])
    on_event, _ = answer(page, [])
    _, first = page.stream({"text": "one"}, on_event)
    assert attempts(first, "tool_result") == [(1, 3), (2, 3), (3, 3), (4, 3)]
    on_event, asked = answer(page, [])
    _, second = page.stream({"text": "two"}, on_event)
    assert asked == ["c1"]
    assert attempts(second, "tool_call") == attempts(second, "tool_result") == [(1, 3)]
    assert of_type(second, "tool_result")[0]["ok"] is True
    assert page.client.calls[-1][-1].startswith("Tool result from run_python:\nAttempt 1 of 3 · Exit code 0")


def test_a_refused_run_uses_an_attempt_and_the_fourth_call_never_asks(web):
    page = web(py("print(1)"), py("print(2)"), py("print(3)"), py("print(4)"), ["Done."])
    on_event, asked = answer(page, [False, True, True])
    _, events = page.stream({"text": "go"}, on_event)
    assert asked == ["c1", "c2", "c3"]
    assert attempts(events, "tool_call") == [(1, 3), (2, 3), (3, 3), (4, 3)]
    results = of_type(events, "tool_result")
    assert [(r["ok"], r["error"]) for r in results[::3]] == [(False, "tool approval refused"), (False, STOP)]
    assert "meta" not in results[0] and "meta" not in results[3] and "meta" in results[1]
    assert page.client.calls[1][-1] == "Tool error from run_python:\nAttempt 1 of 3 · tool approval refused"
    assert [e["call_id"] for e in of_type(events, "approval_request")] == ["c1", "c2", "c3"]
    tools = page.call("GET", "/api/session")[1]["items"][1]["tools"]
    assert [(t["attempt"], t.get("refused")) for t in tools] == [(1, True), (2, None), (3, None), (4, False)]


def test_a_refusal_on_the_last_attempt_is_still_refused_after_restore(web):
    page = web(py("print(1)"), py("print(2)"), py("print(3)"), ["No run."])
    on_event, _ = answer(page, [True, True, False])
    _, events = page.stream({"text": "go"}, on_event)
    assert page.client.calls[3][-1] == f"Tool error from run_python:\nAttempt 3 of 3 · tool approval refused\n{LAST}"
    last = page.call("GET", "/api/session")[1]["items"][1]["tools"][2]
    assert (last["attempt"], last["max_attempts"], last["refused"], last["error"]) == (3, 3, True, "tool approval refused")


def test_invalid_arguments_count_as_an_attempt_without_asking(web):
    bad = [json.dumps({"tool": "run_python", "arguments": {"code": 5}})]
    page = web(bad, py("print(1)"), ["Ok."])
    on_event, asked = answer(page, [])
    _, events = page.stream({"text": "go"}, on_event)
    assert asked == ["c2"]
    assert attempts(events, "tool_result") == [(1, 3), (2, 3)]
    assert page.client.calls[1][-1].startswith("Tool error from run_python:\nAttempt 1 of 3 · invalid arguments")


def test_a_stopped_turn_does_not_carry_its_attempts_into_the_next_one(web):
    page = web(py("print(1 / 0)"), py("print(1 / 0)"), py("print(1)"), ["Fine."])
    def on_event(event):
        if event["type"] == "approval_request":
            if event["call_id"] == "c2":
                page.call("POST", "/api/chat/stop")
            else:
                page.call("POST", f"/api/approvals/{event['id']}", {"approved": True})
    _, events = page.stream({"text": "go"}, on_event)
    assert events[-1]["status"] == "interrupted"
    assert attempts(events, "tool_call") == [(1, 3), (2, 3)] and attempts(events, "tool_result") == [(1, 3)]
    on_event, asked = answer(page, [])
    _, again = page.stream({"text": "again"}, on_event)
    assert asked == ["c1"] and attempts(again, "tool_result") == [(1, 3)]


def test_a_saved_session_resumes_with_attempts_refusals_and_the_stop(web):
    page = web(py("print(1)"), py("print(1 / 0)"), py("print(3)"), py("print(4)"), ["Answer."], ["title"])
    on_event, _ = answer(page, [False, True, True])
    _, events = page.stream({"text": "go"}, on_event)
    session_id = next(e["session_id"] for e in events if e["type"] == "saved")
    page.call("POST", "/api/sessions")
    tools = page.call("POST", f"/api/sessions/{session_id}/resume")[1]["items"][1]["tools"]
    assert [(t["attempt"], t["max_attempts"], t["ok"], t["refused"] if "refused" in t else None) for t in tools] == [
        (1, 3, False, True), (2, 3, False, False), (3, 3, True, None), (4, 3, False, False)]
    assert tools[3]["error"] == STOP and LAST not in tools[2]["output"]


def msgs(*pairs):
    return [Message(role=role, content=content) for role, content in pairs]


def test_the_round_limit_note_and_the_last_attempt_line_both_come_off():
    call = py("1")[0]
    items = session_view.display_items(msgs(
        ("user", "go"), ("assistant", call),
        ("user", f"Tool error from run_python:\nAttempt 3 of 3 · tool approval refused\n{LAST}{ROUND_NOTE}"),
        ("assistant", "done")), None)
    tool = items[1]["tools"][0]
    assert (tool["attempt"], tool["refused"], tool["error"]) == (3, True, "tool approval refused")


def test_restored_sessions_from_before_t21_have_no_attempt_fields():
    items = session_view.display_items(msgs(
        ("user", "go"), ("assistant", py("1")[0]), ("user", "Tool result from run_python:\nExit code 0 · 0.1 s"),
        ("assistant", "done")), None)
    tool = items[1]["tools"][0]
    assert "attempt" not in tool and "max_attempts" not in tool and tool["output"] == "Exit code 0 · 0.1 s"


def test_restored_run_python_items_do_not_show_the_model_facing_fix_it_line():
    items = session_view.display_items(msgs(
        ("user", "go"), ("assistant", py("1")[0]),
        ("user", f"Tool error from run_python:\nAttempt 1 of 3 · Exit code 1 · 0.1 s\nstderr:\nboom\n{FIX_IT}"),
        ("assistant", py("2")[0]),
        ("user", f"Tool result from run_python:\nAttempt 2 of 3 · Exit code 0 · 0.1 s\nstdout:\n42\n{FIX_IT}"),
        ("assistant", "done")), None)
    failed, ok = items[1]["tools"]
    assert failed["error"] == "Exit code 1 · 0.1 s\nstderr:\nboom"
    assert ok["output"] == "Exit code 0 · 0.1 s\nstdout:\n42"


def system(page):
    return page.app.active.session.messages[0].content


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any folder")
def test_a_really_unreadable_folder_starts_runs_a_turn_and_reports_the_run_error(web, tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    (folder / "a.csv").write_text("1")
    folder.chmod(0)
    try:
        page = web(py("print(1)"), ["The data folder could not be read."], data_dir=str(folder))
        assert "run_python can use" not in system(page) and DATA_LINE not in system(page)
        on_event, asked = answer(page, [])
        _, events = page.stream({"text": "go"}, on_event)
        assert events[-1]["status"] == "completed" and of_type(events, "warning") == []
        result = of_type(events, "tool_result")[0]
        assert result["ok"] is False and result["error"].startswith("cannot read data folder")
        assert (result["attempt"], result["max_attempts"]) == (1, 3)
        assert DATA_LINE not in system(page)
    finally:
        folder.chmod(0o755)


def test_the_data_line_disappears_when_the_folder_is_removed(web, tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    (folder / "a.csv").write_text("1")
    page = web(["one"], ["title"], ["two"], data_dir=str(folder))
    page.stream({"text": "hi"})
    assert f"{DATA_LINE}a.csv." in system(page)
    (folder / "a.csv").unlink()
    folder.rmdir()
    _, events = page.stream({"text": "again"})
    assert events[-1]["status"] == "completed" and "run_python can use" not in system(page)


def test_the_data_line_sits_before_profile_persona_and_tools(web, tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    (folder / "a.csv").write_text("1")
    page = web(["one"], data_dir=str(folder))
    page.call("PUT", "/api/profile", {"preferences": {"name": "Nadia"}})
    page.stream({"text": "hi"})
    prompt = system(page)
    data = prompt.index(f"{DATA_LINE}a.csv.")
    assert prompt.count(DATA_LINE) == 1
    assert len(page.app.base_prompt) + 2 == data < prompt.index("- name : Nadia") < prompt.index("Available tools")
    assert page.client.calls[0][0] == prompt


def test_the_data_card_listing_and_the_prompt_name_the_same_files(web, tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    for name in ("b.csv", "a.json", ".env", "x.py"):
        (folder / name).write_text("1")
    (folder / "sub").mkdir()
    page = web(["one"], data_dir=str(folder))
    page.stream({"text": "hi"})
    listed = [f["name"] for f in page.call("GET", "/api/run/data")[1]["files"]]
    assert f"{DATA_LINE}{', '.join(listed)}." in system(page) and listed == ["a.json", "b.csv"]


def test_a_fifth_call_in_a_turn_is_numbered_five_live(web):
    page = web(*([py("print(1)")] * 5), ["Done."])
    on_event, asked = answer(page, [])
    _, events = page.stream({"text": "go"}, on_event)
    assert asked == ["c1", "c2", "c3"]
    assert attempts(events, "tool_result") == [(1, 3), (2, 3), (3, 3), (4, 3), (5, 3)]


def test_a_restored_fifth_call_keeps_its_number(web):
    page = web(*([py("print(1)")] * 5), ["Done."])
    on_event, _ = answer(page, [])
    page.stream({"text": "go"}, on_event)
    tools = page.call("GET", "/api/session")[1]["items"][1]["tools"]
    assert [t["attempt"] for t in tools] == [1, 2, 3, 4, 5]


def test_the_model_gets_the_end_of_stderr_and_the_page_keeps_all_of_it(web):
    page = web(py("import sys\nsys.stderr.write('e' * 3000 + 'LAST')\nraise SystemExit(1)"), ["Failed."])
    on_event, _ = answer(page, [])
    _, events = page.stream({"text": "go"}, on_event)
    result = of_type(events, "tool_result")[0]
    assert result["ok"] is False and "stderr (last 2000 characters):" in result["error"]
    assert result["error"].endswith("LAST") and FIX_IT not in result["error"]  # Fix round 1: the page never shows it.
    assert len(result["meta"]["stderr"]) == 3004 and "report" not in result["meta"]
    sent = page.client.calls[1][-1]
    assert sent.startswith("Tool error from run_python:\nAttempt 1 of 3 · Exit code 1") and "e" * 2500 not in sent


def test_the_tools_list_and_the_chat_registry_share_one_limit(tmp_path):
    from sensai.sandbox import PYTHON_ATTEMPTS
    from sensai_web.tools import ObservedRegistry, tool_list

    class Approval:
        call_id, waited = None, 0.0

    registry = ObservedRegistry(Approval(), lambda event: None, None, str(tmp_path))
    listed = {t["name"]: t["max_calls"] for t in tool_list()}
    assert registry.usage("run_python") == (0, PYTHON_ATTEMPTS) == (0, listed["run_python"]) == (0, 3)
    assert registry.usage("calculate")[1] is None is listed["calculate"]


def test_the_cli_uses_the_shared_constants_unchanged():
    from sensai import sandbox
    from sensai.cli import main as cli
    assert cli.PYTHON_ATTEMPTS is sandbox.PYTHON_ATTEMPTS == 3 and cli.data_prompt is sandbox.data_prompt
    assert not hasattr(cli, "_data_prompt")
    assert sandbox.data_prompt([]) == "The data folder has no files run_python can use."
    assert sandbox.data_prompt(["a.csv", "b.json"]) == "Data files available to run_python: a.csv, b.json."
    registry = cli._tools(lambda prompt: "y")
    assert registry.usage("run_python") == (0, 3)


STRINGS = os.path.join(os.path.dirname(__file__), "..", "..", "..", "web", "sensai_web", "static", "js")
NEW_KEYS = ("tool.status.stopped", "tool.attempt", "tool.attemptLast", "tool.stopped")


def test_the_new_strings_exist_in_both_languages_with_the_same_placeholders():
    import re
    with open(os.path.join(STRINGS, "strings.en.json"), encoding="utf-8") as f:
        en = json.load(f)
    with open(os.path.join(STRINGS, "strings.fr.json"), encoding="utf-8") as f:
        fr = json.load(f)
    assert set(en) == set(fr)
    for key in NEW_KEYS:
        assert set(re.findall(r"\{(\w+)\}", en[key])) == set(re.findall(r"\{(\w+)\}", fr[key]))
    assert {"n", "max"} <= set(re.findall(r"\{(\w+)\}", en["tool.attempt"]))
    with open(os.path.join(STRINGS, "..", "..", "..", "web-ui.md"), encoding="utf-8") as f:
        inventory = next(line for line in f if line.startswith("- `tool` ("))
    for key in NEW_KEYS:
        assert f"`{key.removeprefix('tool.')}`" in inventory
