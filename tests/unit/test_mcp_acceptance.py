"""Independent acceptance: real stdio peers, approval, isolation, and metrics."""
from functools import partial
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from sensai.core.ports import ToolCall, ToolDefinition
from sensai.core.cancellation import CancellationToken, OperationCancelled
from sensai.mcp_client import EXAMPLE_CONFIG, GUIDE_URL, Catalogue, Server, exchange
from sensai.tools import ToolRegistry
from .web.conftest import web

ROOT = Path(__file__).resolve().parents[2]
PEER = ROOT / "tests/helpers/mcp_acceptance_server.py"


@pytest.fixture(autouse=True)
def trusted_config(monkeypatch):
    """These tests are about servers; the trust question has its own tests."""
    monkeypatch.setattr(Catalogue, "_trusted", lambda self, digest: True)


def config(path, **env):
    path.write_text(json.dumps({"mcpServers": {"fixture": {
        "command": sys.executable, "args": [str(PEER)], "env": env}}}), encoding="utf-8")


def test_paginated_discovery_and_approval_refusal_prevent_execution(tmp_path):
    path, marker = tmp_path / "mcp.json", tmp_path / "called"
    config(path, MCP_TEST_MARKER=str(marker))
    catalogue = Catalogue(path)
    assert catalogue.reload()
    assert [d.name for d in catalogue.definitions()] == ["fixture.first", "fixture.second"]
    registry = ToolRegistry(read=lambda _: "no")
    catalogue.register(registry)
    assert registry.execute(ToolCall("fixture.first", {})).error == "tool approval refused"
    assert not marker.exists()
    approved = ToolRegistry(read=lambda _: "yes")
    catalogue.register(approved)
    assert approved.execute(ToolCall("fixture.second", {})).output == "fixture value"
    assert marker.read_text() == "called"


def test_invalid_config_retains_catalogue_but_missing_config_clears(tmp_path):
    path = tmp_path / "mcp.json"
    config(path)
    catalogue = Catalogue(path)
    assert catalogue.reload()
    path.write_text('{"mcpServers": []}', encoding="utf-8")
    assert not catalogue.reload()
    assert len(catalogue.definitions()) == 2
    path.unlink()
    assert catalogue.reload()
    assert catalogue.definitions() == ()


def test_valid_nullable_mcp_input_schema_can_be_called(tmp_path):
    path = tmp_path / "mcp.json"
    config(path, MCP_TEST_MODE="nullable")
    catalogue = Catalogue(path)
    assert catalogue.reload()
    registry = ToolRegistry(read=lambda _: "yes")
    catalogue.register(registry)
    result = registry.execute(ToolCall("fixture.first", {"value": None}))
    assert result.error is None
    assert result.output == "fixture value"


def test_malformed_schema_does_not_break_chat(tmp_path):
    path = tmp_path / "mcp.json"
    config(path, MCP_TEST_MODE="malformed-schema")
    catalogue = Catalogue(path)
    assert catalogue.reload()
    registry = ToolRegistry(read=lambda _: "yes")
    catalogue.register(registry)
    if catalogue.definitions():
        result = registry.execute(ToolCall("fixture.first", {}))
        assert result.error is not None
    else:
        assert catalogue.servers[0]["error"]


def test_boolean_property_schemas_accept_and_refuse_values(tmp_path):
    path = tmp_path / "mcp.json"
    config(path, MCP_TEST_MODE="boolean-schema")
    catalogue = Catalogue(path)
    assert catalogue.reload()
    assert len(catalogue.definitions()) == 2
    registry = ToolRegistry(read=lambda _: "yes")
    catalogue.register(registry)
    assert registry.execute(ToolCall("fixture.first", {"allowed": [1, None]})).error is None
    assert registry.execute(ToolCall("fixture.first", {"forbidden": "x"})).error is not None


@pytest.mark.parametrize("mode,expected", [
    ("version", "unsupported MCP protocol version"),
    ("closed", "closed"),
    ("malformed-schema", "schema"),
])
def test_discovery_errors_identify_failure_category_without_echoing_env(tmp_path, mode, expected):
    path = tmp_path / "mcp.json"
    config(path, MCP_TEST_MODE=mode, SECRET="do-not-show-this-value")
    catalogue = Catalogue(path)
    assert catalogue.reload()
    assert catalogue.definitions() == ()
    error = catalogue.servers[0]["error"]
    assert expected.lower() in error.lower()
    assert "do-not-show-this-value" not in error


def test_missing_executable_discovery_reports_reason(tmp_path):
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"mcpServers": {"missing": {"command": str(tmp_path / "absent")}}}))
    catalogue = Catalogue(path)
    assert catalogue.reload()
    assert "executable not found" in catalogue.servers[0]["error"]
    assert catalogue.servers[0]["error"].count("reload MCP") == 1


def test_web_reload_refreshes_tools_prompt_and_preserves_history(web, tmp_path):
    path = tmp_path / "mcp.json"
    page = web(["hello"])
    assert page.stream({"text": "hi"})[0] == 200
    before = page.call("GET", "/api/session")[1]["items"]
    config(path)
    status, body = page.call("POST", "/api/tools/reload")
    assert status == 200
    assert "fixture.first" in [item["name"] for item in body["items"]]
    assert "fixture.first" in page.app.active.session.messages[0].content
    assert page.call("GET", "/api/session")[1]["items"] == before
    path.unlink()
    assert page.call("POST", "/api/tools/reload")[0] == 200
    assert "fixture.first" not in page.app.active.session.messages[0].content
    assert page.call("GET", "/api/session")[1]["items"] == before


@pytest.mark.parametrize("thinking", [False, True])
def test_web_mcp_calls_use_approval_and_reload_is_busy_during_turn(web, tmp_path, thinking):
    from sensai.chat.reasoning import Check

    config(tmp_path / "mcp.json")
    replies = [['{"tool":"fixture.first","arguments":{}}'], ["fixture answer"]]
    page = web(*([["1. Look up the fixture"]] if thinking else []), *replies)
    page.app.checker = SimpleNamespace(complete=lambda *args: Check(ok=True))
    reload_statuses = []

    def approve(event):
        if event["type"] == "approval_request":
            reload_statuses.append(page.call("POST", "/api/tools/reload")[0])
            assert page.call("POST", f'/api/approvals/{event["id"]}', {"approved": True})[0] == 200

    status, events = page.stream({"text": "call the fixture"}, on_event=approve,
                                 path="/api/think" if thinking else "/api/chat")
    assert status == 200
    assert reload_statuses == [429]
    results = [event for event in events if event["type"] == "tool_result"]
    assert len(results) == 1 and results[0]["ok"] is True
    assert results[0]["output"] == "fixture value"


def test_cli_reload_replaces_tools_without_losing_history(tmp_path):
    from fakes import FakeClient
    from sensai.chat.session import ChatSession
    from sensai.cli.main import repl

    path = tmp_path / "mcp.json"
    config(path)
    catalogue = Catalogue(path)
    assert catalogue.reload()
    registry = ToolRegistry(read=lambda _: "yes")
    catalogue.register(registry)
    client = FakeClient(["first answer"], ["second answer"])
    session = ChatSession(client, "fake", "Shared rules")
    inputs = iter(["first", "/mcp reload", "/tools", "second", "exit"])
    output = []

    def read(_):
        text = next(inputs)
        if text == "/mcp reload":
            path.unlink()
        return text

    repl(session, read=read, write=lambda text="", **_: output.append(text), tool_registry=registry, mcp=catalogue)
    assert len(client.requests) == 2
    assert "fixture.first" in client.requests[0][1][0].content
    assert "fixture.first" not in client.requests[1][1][0].content
    assert [m.content for m in session.messages[1:]] == ["first", "first answer", "second", "second answer"]


def run_commands(tmp_path, *commands):
    from fakes import FakeClient
    from sensai.chat.session import ChatSession
    from sensai.cli.main import repl

    catalogue = Catalogue(tmp_path / "mcp.json")
    catalogue.reload()
    client = FakeClient()
    session = ChatSession(client, "fake", "Shared rules")
    inputs, output = iter([*commands, "exit"]), []
    repl(session, read=lambda _: next(inputs), write=lambda text="", **_: output.append(text),
         tool_registry=ToolRegistry(read=lambda _: "yes"), mcp=catalogue)
    assert client.requests == []  # None of these reach the model.
    assert session.messages[1:] == []
    return "\n".join(output)


def test_cli_mcp_explains_setup_when_nothing_is_configured(tmp_path):
    output = run_commands(tmp_path, "/mcp")
    assert f"MCP config: {(tmp_path / 'mcp.json').resolve()} (not found" in output
    assert EXAMPLE_CONFIG.rstrip() in output
    assert "/mcp reload" in output and GUIDE_URL in output


def test_cli_mcp_shows_server_status_and_points_failures_at_mcp_reload(tmp_path):
    path = tmp_path / "mcp.json"
    config(path)
    path.write_text(json.dumps({"mcpServers": {**json.loads(path.read_text())["mcpServers"],
                                               "broken": {"command": str(tmp_path / "absent")}}}))
    output = run_commands(tmp_path, "/mcp")
    assert "not found" not in output.splitlines()[0]
    assert "MCP: fixture (2 tools)" in output
    assert "MCP server broken unavailable: MCP executable not found; fix configuration and use /mcp reload" in output


def test_cli_mcp_rejects_unknown_argument(tmp_path):
    assert run_commands(tmp_path, "/mcp nonsense").endswith("usage: /mcp [reload]")


def test_old_reload_command_is_gone(tmp_path):
    from fakes import FakeClient
    from sensai.chat.session import ChatSession
    from sensai.cli.main import repl

    client = FakeClient(["an answer"])
    session = ChatSession(client, "fake", "Shared rules")
    inputs = iter(["/reload", "exit"])
    repl(session, read=lambda _: next(inputs), write=lambda *_, **__: None,
         tool_registry=ToolRegistry(read=lambda _: "yes"), mcp=Catalogue(tmp_path / "mcp.json"))
    assert session.messages[1].content == "/reload"


def test_example_config_matches_the_committed_example():
    assert (ROOT / "mcp.example.json").read_text() == EXAMPLE_CONFIG


def test_web_tools_reports_config_location_and_setup(web, tmp_path):
    page = web(["hello"])
    body = page.call("GET", "/api/tools")[1]
    assert (body["config"], body["found"]) == (str((tmp_path / "mcp.json").resolve()), False)
    assert body["example"] == EXAMPLE_CONFIG and body["guide"] == GUIDE_URL
    config(tmp_path / "mcp.json")
    body = page.call("POST", "/api/tools/reload")[1]
    assert body["found"] is True and body["servers"][0]["name"] == "fixture"


@pytest.mark.parametrize("mode", ["older", "ping"])
def test_older_protocol_and_server_ping_keep_a_server_usable(tmp_path, mode):
    path = tmp_path / "mcp.json"
    config(path, MCP_TEST_MODE=mode)
    catalogue = Catalogue(path)
    assert catalogue.reload()
    assert catalogue.servers[0]["error"] is None and catalogue.definitions()


def test_long_tool_output_is_cut(tmp_path):
    path = tmp_path / "mcp.json"
    config(path, MCP_TEST_MODE="large")
    catalogue = Catalogue(path)
    assert catalogue.reload()
    registry = ToolRegistry(read=lambda _: "yes")
    catalogue.register(registry)
    output = registry.execute(ToolCall("fixture.first", {})).output
    assert output == "x" * 10_000 + "\n(output truncated)"


def test_web_reload_discovers_outside_the_app_lock(web, tmp_path):
    page = web(["hello"])
    acquired = []

    def reload():
        def probe():
            acquired.append(page.app.mutex.acquire(timeout=1))
            page.app.mutex.release()
        thread = threading.Thread(target=probe)
        thread.start()
        thread.join()
        return True

    page.app.mcp.reload = reload
    assert page.call("POST", "/api/tools/reload")[0] == 200
    assert acquired == [True]


def test_web_registry_lists_tools_in_prompt_order_with_documents(web, tmp_path):
    from sensai.tools import tool_instructions
    from sensai_web.tools import ObservedRegistry

    config(tmp_path / "mcp.json")
    (tmp_path / "docs").mkdir()
    page = web(["hello"], docs_dir=str(tmp_path / "docs"))
    assert page.call("POST", "/api/tools/reload")[0] == 200
    app = page.app
    assert app.docs.enabled and app.mcp.definitions()
    registry = ObservedRegistry(None, lambda event: None, app.data.path, app.meta_dir, app.docs, app.mcp)
    assert tool_instructions(registry.definitions()) == app.tools_text()


def dead(pid):
    try:
        state = Path(f"/proc/{pid}/stat").read_text().split()[2]
        return state == "Z"
    except FileNotFoundError:
        return True


@pytest.mark.parametrize("mode", ["descendant", "hang"])
def test_mcp_descendant_stops_after_success_or_timeout(tmp_path, mode):
    pidfile = tmp_path / "pid"
    server = Server("fixture", sys.executable, (str(PEER),),
                    {"MCP_TEST_MODE": mode, "MCP_TEST_PID": str(pidfile)})
    registry = ToolRegistry()
    registry.register(ToolDefinition("fixture.first", "", {}), partial(exchange, server, "first"),
                      timeout=1.5)
    result = registry.execute(ToolCall("fixture.first", {}))
    assert result.error == "tool timed out" if mode == "hang" else result.error is None
    pid = int(pidfile.read_text())
    deadline = time.monotonic() + 2
    while not dead(pid) and time.monotonic() < deadline:
        time.sleep(.02)
    assert dead(pid), f"MCP descendant {pid} survived {mode}"


def test_cancelled_mcp_call_cleans_its_descendant(tmp_path):
    pidfile = tmp_path / "pid"
    server = Server("fixture", sys.executable, (str(PEER),),
                    {"MCP_TEST_MODE": "hang", "MCP_TEST_PID": str(pidfile)})
    registry = ToolRegistry()
    registry.register(ToolDefinition("fixture.first", "", {}), partial(exchange, server, "first"), timeout=3)
    token = CancellationToken(time.monotonic() + 3, cancel_requested=pidfile.exists)
    with pytest.raises(OperationCancelled):
        registry.execute(ToolCall("fixture.first", {}), token)
    pid = int(pidfile.read_text())
    deadline = time.monotonic() + 2
    while not dead(pid) and time.monotonic() < deadline:
        time.sleep(.02)
    assert dead(pid), f"MCP descendant {pid} survived cancellation"


def metrics(csv_path, arguments):
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "weekly_engagement", "arguments": arguments}},
    ]
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "SENSAI_ENGAGEMENT_CSV": str(csv_path)}
    run = subprocess.run([sys.executable, "-m", "sensai.mcp_server"],
                         input="".join(json.dumps(m) + "\n" for m in messages), text=True,
                         capture_output=True, timeout=5, env=env)
    assert run.returncode == 0, run.stderr
    responses = {m["id"]: m for m in map(json.loads, run.stdout.splitlines()) if "id" in m}
    return responses[2]["result"]


def test_environment_csv_override_and_weekly_row_precedence(tmp_path):
    csv = tmp_path / "metrics.csv"
    csv.write_text("date,channel,accounts_reached,accounts_engaged,engagement_rate,source\n"
                   "2026-09-21,Instagram,100,90,90,daily\n"
                   "2026-09-21/2026-09-27,Instagram,200,20,10,weekly\n", encoding="utf-8")
    result = metrics(csv, {"week_start": "2026-09-21"})
    assert not result.get("isError", False)
    text = "\n".join(part["text"] for part in result["content"])
    assert "200" in text and "20" in text and "10" in text
    assert "90" not in text


@pytest.mark.parametrize("reached,engaged", [("-1", "0"), ("10", "11"), ("NaN", "2"), ("1.5", "1")])
def test_invalid_metrics_counts_are_errors(tmp_path, reached, engaged):
    csv = tmp_path / "metrics.csv"
    csv.write_text("date,channel,accounts_reached,accounts_engaged,engagement_rate,source\n"
                   f"2026-09-21,Instagram,{reached},{engaged},n/a,daily\n", encoding="utf-8")
    assert metrics(csv, {"week_start": "2026-09-21"})["isError"] is True


def test_csv_with_a_byte_order_mark_is_read(tmp_path):
    from sensai.mcp_server import weekly_engagement

    path = tmp_path / "metrics.csv"
    path.write_text("date,channel,accounts_reached,accounts_engaged\n2026-09-21,Instagram,10,2\n", encoding="utf-8-sig")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("SENSAI_ENGAGEMENT_CSV", str(path))
        assert json.loads(weekly_engagement("2026-09-21"))[0]["engagement_rate"] == 20


def test_csv_parser_error_is_a_tool_error_not_a_dead_server(tmp_path):
    path = tmp_path / "mcp.json"
    metrics = tmp_path / "metrics.csv"
    metrics.write_text("date,channel,accounts_reached,accounts_engaged\n" + "x" * 200_000 + ",a,1,1\n", encoding="utf-8")
    path.write_text(json.dumps({"mcpServers": {"sensai": {
        "command": sys.executable, "args": ["-m", "sensai.mcp_server"],
        "env": {"SENSAI_ENGAGEMENT_CSV": str(metrics), "PYTHONPATH": str(ROOT / "src")}}}}), encoding="utf-8")
    catalogue = Catalogue(path)
    assert catalogue.reload()
    registry = ToolRegistry(read=lambda _: "yes")
    catalogue.register(registry)
    result = registry.execute(ToolCall("sensai.weekly_engagement", {"week_start": "2026-09-21"}))
    assert "Cannot read engagement" in result.error
