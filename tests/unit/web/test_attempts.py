"""T21 in the web chat: three numbered run_python attempts, the short model report, data file names."""
import json

from sensai.core.messages import Message
from sensai.core.ports import PermissionDecision
from sensai.sandbox import FIX_IT, SandboxError, format_run
from sensai_web import app as web_app, sandbox, session_view

STOP = "Stopped after 3 attempts: answer with the last result or error, without calling run_python again."
LAST = "This was the last attempt: answer with this result or error, without calling run_python again."
DATA_LINE = "Data files available to run_python: "


def py(code):
    return json.dumps({"tool": "run_python", "arguments": {"code": code}})


def approve_all(page, asked=None):
    def on_event(event):
        if event["type"] == "approval_request":
            if asked is not None:
                asked.append(event["call_id"])
            page.call("POST", f"/api/approvals/{event['id']}", {"approved": True})
    return on_event


def of_type(events, kind):
    return [event for event in events if event["type"] == kind]


def test_a_failed_run_goes_back_to_the_model_which_fixes_its_code(web):
    page = web([py("print(1 / 0)")], [py("print(6 * 7)")], ["It is 42."])
    asked = []
    _, events = page.stream({"text": "6*7?"}, approve_all(page, asked))
    assert asked == ["c1", "c2"]  # Every run is approved on its own.
    calls, results = of_type(events, "tool_call"), of_type(events, "tool_result")
    assert [(e["attempt"], e["max_attempts"]) for e in calls] == [(1, 3), (2, 3)]
    assert [(e["attempt"], e["max_attempts"], e["ok"]) for e in results] == [(1, 3, False), (2, 3, True)]
    sent = page.client.calls[1][-1]
    assert sent.startswith("Tool error from run_python:\nAttempt 1 of 3 · Exit code 1 · ")
    assert "ZeroDivisionError" in sent and sent.endswith(FIX_IT)
    assert page.client.calls[2][-1].startswith("Tool result from run_python:\nAttempt 2 of 3 · Exit code 0 · ")
    assert results[1]["output"].startswith("Exit code 0") and results[1]["output"].endswith("stdout:\n42")
    assert results[0]["meta"]["exit_code"] == 1 and "ZeroDivisionError" in results[0]["meta"]["stderr"]
    assert results[1]["meta"]["denied"] == []
    assert events[-1]["status"] == "completed" and "It is 42." in "".join(e["delta"] for e in of_type(events, "text"))


def test_after_three_runs_the_fourth_call_is_stopped_without_running(web):
    page = web(*([py("print(1 / 0)")] * 4), ["The last run failed with ZeroDivisionError."])
    asked = []
    _, events = page.stream({"text": "go"}, approve_all(page, asked))
    assert asked == ["c1", "c2", "c3"]  # The stopped call never asks.
    calls, results = of_type(events, "tool_call"), of_type(events, "tool_result")
    assert [(e["attempt"], e["max_attempts"]) for e in calls] == [(1, 3), (2, 3), (3, 3), (4, 3)]
    assert [e["attempt"] for e in results] == [1, 2, 3, 4]
    stopped = results[3]
    assert (stopped["ok"], stopped["error"], stopped["max_attempts"]) == (False, STOP, 3) and "meta" not in stopped
    assert page.client.calls[3][-1].endswith(f"{FIX_IT}\n{LAST}")
    assert page.client.calls[4][-1].startswith(f"Tool error from run_python:\n{STOP}")
    assert events[-1]["status"] == "completed"
    tools = page.call("GET", "/api/session")[1]["items"][1]["tools"]
    assert [(t["attempt"], t["max_attempts"]) for t in tools] == [(1, 3), (2, 3), (3, 3), (4, 3)]
    assert "ZeroDivisionError" in tools[2]["error"] and FIX_IT not in tools[2]["error"] and tools[3]["error"] == STOP


def test_the_page_never_gets_the_fix_it_line_the_model_gets(web):
    page = web([py("print(1 / 0)")], [py("print(42)")], ["42."])
    _, events = page.stream({"text": "go"}, approve_all(page))
    failed, ok = of_type(events, "tool_result")
    assert page.client.calls[1][-1].endswith(FIX_IT) and page.client.calls[2][-1].endswith(FIX_IT)
    assert failed["error"].startswith("Exit code 1 · ") and failed["error"].endswith("ZeroDivisionError: division by zero")
    assert failed["output"] == failed["error"] and ok["output"].endswith("stdout:\n42") and ok["error"] is None
    assert all(FIX_IT not in json.dumps(event) for event in events)


def test_the_model_gets_the_end_of_the_output_and_the_page_gets_all_of_it(web):
    page = web([py("print('a' * 3000 + 'END')")], ["Done."])
    _, events = page.stream({"text": "go"}, approve_all(page))
    result = of_type(events, "tool_result")[0]
    assert "stdout (last 2000 characters):" in result["output"] and "END" in result["output"]
    assert len(result["meta"]["stdout"]) == 3004 and result["meta"]["stdout"].startswith("aaa")
    assert "aaa" * 1000 not in page.client.calls[1][-1]


def test_other_tools_carry_no_attempt_fields(web):
    page = web(['{"tool": "calculate", "arguments": {"expression": "1+1"}}'], ["2."])
    _, events = page.stream({"text": "x"})
    for event in of_type(events, "tool_call") + of_type(events, "tool_result"):
        assert "attempt" not in event and "max_attempts" not in event


def test_the_tools_list_reports_the_run_python_limit(web):
    items = web().call("GET", "/api/tools")[1]["items"]
    assert {t["name"]: t["max_calls"] for t in items} == {"calculate": None, "run_python": 3, "save_fact": None,
                                                             "delete_fact": None, "ask_user": None}


class Refuse:
    def check(self, request):
        return PermissionDecision(False)


def test_the_chat_tool_sends_the_model_report_and_the_runner_keeps_format_run(tmp_path):
    (tmp_path / "a.csv").write_text("1")
    meta = str(tmp_path / "meta.json")
    result = sandbox.web_python_tool({"code": "print(2)"}, data_dir=str(tmp_path), meta_path=meta,
                                     permission=Refuse())
    assert result.error is None and result.output.endswith(FIX_IT)
    assert "Not available (not allowed): a.csv" in result.output
    assert sandbox.take_record(meta)["denied"] == ["a.csv"]
    plain = sandbox.web_python_tool({"code": "print(2)"}, report=format_run)
    assert plain.output.startswith("Exit code 0") and FIX_IT not in plain.output


def test_the_run_endpoint_registers_format_run(web, monkeypatch):
    page = web()
    seen = []
    original = sandbox.run_handler
    monkeypatch.setattr(sandbox, "run_handler", lambda *a, **k: seen.append(k.get("report")) or original(*a, **k))
    body = page.call("POST", "/api/run", {"code": "print(1)"})[1]
    assert seen == [format_run] and FIX_IT not in body["report"] and body["denied"] == []


def system(page):
    """The system prompt of the last turn, as sent to the model."""
    prompt = page.app.active.session.messages[0].content
    assert any(call[0] == prompt for call in page.client.calls)
    return prompt


def test_data_file_names_follow_the_shared_rules_and_the_data_page(web, tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    (folder / "a.csv").write_text("1")
    page = web(["one"], ["two"], ["three"], ["four"], data_dir=str(folder))
    page.call("PUT", "/api/profile", {"preferences": {"name": "Nadia"}})
    page.stream({"text": "hi"})
    prompt = system(page)
    assert prompt.startswith(f"{page.app.base_prompt}\n\n{DATA_LINE}a.csv.\n\n")
    assert prompt.index(DATA_LINE) < prompt.index("- name : Nadia")
    page.call("PUT", "/api/run/data/b.csv", {"text": "2"})
    page.stream({"text": "again"})
    assert f"{DATA_LINE}a.csv, b.csv." in system(page)
    page.call("DELETE", "/api/run/data/a.csv")
    page.stream({"text": "and"})
    assert f"{DATA_LINE}b.csv." in system(page) and "a.csv" not in system(page)
    page.call("DELETE", "/api/run/data/b.csv")
    page.stream({"text": "last"})
    assert "The data folder has no files run_python can use." in system(page)


def test_no_data_line_until_the_data_page_creates_the_folder(web):
    page = web(["one"], ["two"])
    page.stream({"text": "hi"})
    assert "run_python can use" not in system(page) and DATA_LINE not in system(page)
    page.call("PUT", "/api/run/data/notes.txt", {"text": "x"})
    page.stream({"text": "again"})
    assert f"{DATA_LINE}notes.txt." in system(page)


def test_an_unreadable_data_folder_leaves_the_line_out_and_the_turn_runs(web, tmp_path, monkeypatch):
    folder = tmp_path / "data"
    folder.mkdir()
    page = web(["fine"], data_dir=str(folder))

    def unreadable(path, permission=None):
        raise SandboxError("cannot read data folder: [Errno 13] Permission denied")

    monkeypatch.setattr(web_app, "data_file_names", unreadable)
    _, events = page.stream({"text": "hi"})
    assert events[-1]["status"] == "completed" and of_type(events, "warning") == []
    assert "data folder" not in system(page)


def msgs(*pairs):
    return [Message(role=role, content=content) for role, content in pairs]


def test_restored_tool_items_keep_the_attempt_and_lose_the_protocol_text():
    call = py("1")
    items = session_view.display_items(msgs(
        ("user", "go"), ("assistant", call), ("user", "Tool error from run_python:\nAttempt 1 of 3 · tool approval refused"),
        ("assistant", call), ("user", f"Tool result from run_python:\nAttempt 3 of 3 · Exit code 0 · 0.1 s\n{LAST}"),
        ("assistant", call), ("user", f"Tool error from run_python:\n{STOP}"), ("assistant", "done")), None)
    first, last, stopped = items[1]["tools"]
    assert (first["attempt"], first["refused"], first["error"]) == (1, True, "tool approval refused")
    assert (last["attempt"], last["max_attempts"], last["output"]) == (3, 3, "Exit code 0 · 0.1 s")
    assert (stopped["attempt"], stopped["max_attempts"], stopped["refused"]) == (4, 3, False)
