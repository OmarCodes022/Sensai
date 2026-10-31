"""The trust question: nothing from mcp.json runs until the user accepts that exact file."""
import json
import os
from pathlib import Path
import sys

import pytest

from fakes import FakeClient
from sensai.chat.session import ChatSession
from sensai.cli.main import repl
from sensai.mcp_client import Catalogue
from sensai.tools import ToolRegistry
from .web.conftest import web

PEER = Path(__file__).resolve().parents[1] / "helpers/mcp_acceptance_server.py"
# Leaves a marker as soon as it is started, then acts as a normal server.
STARTER = "import pathlib, runpy, sys; pathlib.Path(sys.argv[1]).touch(); sys.argv = sys.argv[1:]; runpy.run_path(sys.argv[1], run_name='__main__')"


@pytest.fixture
def setup(tmp_path):
    path, marker = tmp_path / "mcp.json", tmp_path / "started"
    write_config(path, marker)
    return path, marker


def write_config(path, marker, **extra):
    path.write_text(json.dumps({"mcpServers": {"fixture": {
        "command": sys.executable, "args": ["-c", STARTER, str(marker), str(PEER)], **extra}}}), encoding="utf-8")


def test_unknown_config_runs_nothing_and_shows_what_would_run(setup):
    path, marker = setup
    catalogue = Catalogue(path)
    assert catalogue.reload()
    assert catalogue.definitions() == () and not marker.exists()
    assert catalogue.untrusted["commands"][0].startswith(f"fixture: {sys.executable} -c")


def test_accepting_runs_it_and_is_remembered_for_that_content(setup):
    path, marker = setup
    catalogue = Catalogue(path)
    catalogue.reload()
    assert catalogue.trust(catalogue.untrusted["digest"])
    catalogue.reload()
    assert marker.exists() and catalogue.definitions() and catalogue.untrusted is None
    marker.unlink()
    later = Catalogue(path)
    later.reload()
    assert later.untrusted is None and marker.exists()


def test_editing_a_trusted_file_asks_again_and_drops_its_tools(setup):
    path, marker = setup
    catalogue = Catalogue(path)
    catalogue.reload()
    catalogue.trust(catalogue.untrusted["digest"])
    catalogue.reload()
    marker.unlink()
    write_config(path, marker, env={"A": "1"})
    catalogue.reload()
    assert catalogue.untrusted and catalogue.definitions() == () and not marker.exists()


def test_same_content_at_another_path_asks_again(setup, tmp_path):
    path, marker = setup
    catalogue = Catalogue(path)
    catalogue.reload()
    catalogue.trust(catalogue.untrusted["digest"])
    other = tmp_path / "other"
    other.mkdir()
    (other / "mcp.json").write_bytes(path.read_bytes())
    copy = Catalogue(other / "mcp.json")
    copy.reload()
    assert copy.untrusted and not marker.exists()


def test_a_digest_other_than_the_one_shown_trusts_nothing(setup):
    path, marker = setup
    catalogue = Catalogue(path)
    catalogue.reload()
    assert not catalogue.trust("0" * 64)
    catalogue.reload()
    assert catalogue.untrusted and not marker.exists()


def test_damaged_answers_file_asks_again(setup):
    path, marker = setup
    store = Path(os.environ["XDG_CONFIG_HOME"]) / "sensai" / "trusted-mcp.json"
    store.parent.mkdir(parents=True)
    store.write_text("[not json", encoding="utf-8")
    catalogue = Catalogue(path)
    catalogue.reload()
    assert catalogue.untrusted and not marker.exists()


def test_unsaved_answer_still_works_for_this_run_and_says_so(setup, monkeypatch):
    path, marker = setup
    config_home = Path(os.environ["XDG_CONFIG_HOME"]) / "blocked"
    config_home.write_text("a file, not a folder", encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    catalogue = Catalogue(path)
    catalogue.reload()
    catalogue.trust(catalogue.untrusted["digest"])
    catalogue.reload()
    assert marker.exists() and "Could not save" in catalogue.notices()[0]


def test_question_escapes_tricks_and_hides_env_values(tmp_path):
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"mcpServers": {"a\nb": {
        "command": "sh", "args": ["-c", "evil\n\x1b[2Khidden\u202e"], "env": {"TOKEN": "do-not-show"}}, "bad": 3}}), encoding="utf-8")
    catalogue = Catalogue(path)
    catalogue.reload()
    first, second = catalogue.untrusted["commands"]
    assert "\n" not in first and "\x1b" not in first and "\u202e" not in first
    assert "TOKEN=<hidden>" in first and "do-not-show" not in first
    assert second == "bad: (invalid entry)"


def accept(path):
    catalogue = Catalogue(path)
    catalogue.reload()
    assert catalogue.trust(catalogue.untrusted["digest"])
    return catalogue


def test_accepted_file_used_from_another_folder_asks_again(setup, tmp_path, monkeypatch):
    path, marker = setup
    accept(path)
    evil = tmp_path / "evil"
    evil.mkdir()
    monkeypatch.chdir(evil)  # As with SENSAI_MCP_CONFIG=../mcp.json in that folder's .env.
    catalogue = Catalogue(path)
    catalogue.reload()
    assert catalogue.untrusted["folder"] == str(evil) and not marker.exists()


def test_a_folders_symlink_to_an_accepted_file_asks_again(setup, tmp_path, monkeypatch):
    path, marker = setup
    monkeypatch.chdir(tmp_path)
    accept(path)
    link = tmp_path / "link.json"
    link.symlink_to(path)
    catalogue = Catalogue(link)
    catalogue.reload()
    assert catalogue.untrusted and not marker.exists()


def test_same_folder_and_file_are_remembered(setup, tmp_path, monkeypatch):
    path, marker = setup
    monkeypatch.chdir(tmp_path)
    accept(path)
    catalogue = Catalogue(path)
    catalogue.reload()
    assert catalogue.untrusted is None and marker.exists()


def test_question_shows_values_that_decide_what_runs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "bin").mkdir()
    program = tmp_path / "bin" / "uvx"
    program.write_text("#!/bin/sh\n", encoding="utf-8")
    program.chmod(0o755)
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"mcpServers": {"time": {"command": "uvx", "args": ["mcp-server-time"], "env": {
        "PATH": "./bin", "LD_PRELOAD": "./x.so", "API_KEY": "do-not-show", "GIT_ASKPASS": "./ask"}}}}), encoding="utf-8")
    catalogue = Catalogue(path)
    catalogue.reload()
    line = catalogue.untrusted["commands"][0]
    assert f"(program: {program})" in line
    assert "PATH=./bin" in line and "LD_PRELOAD=./x.so" in line and "GIT_ASKPASS=./ask" in line
    assert "API_KEY=<hidden>" in line and "do-not-show" not in line


def test_empty_or_missing_config_needs_no_question(tmp_path):
    path = tmp_path / "mcp.json"
    catalogue = Catalogue(path)
    catalogue.reload()
    assert catalogue.untrusted is None
    path.write_text('{"mcpServers": {}}', encoding="utf-8")
    catalogue.reload()
    assert catalogue.untrusted is None


def cli(path, answers, *commands):
    catalogue = Catalogue(path)
    catalogue.reload()  # As at startup; a refused or unknown file has run nothing.
    registry = ToolRegistry(read=lambda _: "yes")
    client = FakeClient()
    session = ChatSession(client, "fake", "Shared rules")
    inputs, output = iter([*commands, "exit"]), []
    answers = iter(answers)

    def read(prompt):
        if "Trust" not in prompt:
            return next(inputs)
        answer = next(answers)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    repl(session, read=read, write=lambda text="", **_: output.append(text), tool_registry=registry, mcp=catalogue)
    return "\n".join(output), registry, session


@pytest.mark.parametrize("answer", ["n", "", "nope", EOFError(), KeyboardInterrupt()])
def test_cli_reload_refused_runs_nothing(setup, answer):
    path, marker = setup
    output, registry, _ = cli(path, [answer], "/mcp reload")
    assert not marker.exists()
    assert "fixture:" in output and "MCP tools stay off" in output
    assert f"in {os.getcwd()}" in output and "load code from that folder" in output
    assert "reloaded" not in output and not any("." in d.name for d in registry.definitions())


@pytest.mark.parametrize("answer", ["y", "YES", "oui"])
def test_cli_reload_accepted_loads_tools_into_the_prompt(setup, answer):
    path, marker = setup
    output, registry, session = cli(path, [answer], "/mcp reload")
    assert marker.exists() and "MCP configuration reloaded." in output
    assert "fixture.first" in [d.name for d in registry.definitions()]
    assert "fixture.first" in session.messages[0].content


def test_cli_mcp_status_says_nothing_ran_and_does_not_ask(setup):
    path, marker = setup
    output, _, _ = cli(path, [], "/mcp")
    assert "Not trusted yet, so nothing has run" in output and not marker.exists()


def test_cli_startup_asks_before_running(setup, monkeypatch, tmp_path, capsys):
    import sensai.cli.main as main
    from tests.unit.cli.test_history import scripted_terminal

    path, marker = setup
    (tmp_path / "prompt.txt").write_text("system", encoding="utf-8")
    monkeypatch.setenv("SENSAI_MCP_CONFIG", str(path))
    monkeypatch.setattr(main, "create_client", lambda settings: FakeClient())
    monkeypatch.setattr(main, "TerminalInput", scripted_terminal(["n", "exit"]))
    main.main(["model", "--prompt", str(tmp_path / "prompt.txt"), "--db", str(tmp_path / "s.db")])
    assert not marker.exists()
    assert "not trusted yet" in capsys.readouterr().out


def test_web_keeps_an_unknown_config_off_until_trusted(web, setup, tmp_path):
    path, marker = setup
    assert path == tmp_path / "mcp.json"
    page = web(["hello"])
    body = page.call("GET", "/api/tools")[1]
    assert body["untrusted"]["commands"] and not marker.exists()
    assert "fixture.first" not in page.app.active.session.messages[0].content
    assert page.call("POST", "/api/tools/reload")[1]["untrusted"] and not marker.exists()
    assert page.call("POST", "/api/tools/trust", {"digest": "0" * 64})[1]["untrusted"] and not marker.exists()
    assert page.call("POST", "/api/tools/trust", {"digest": 3})[0] == 400
    body = page.call("POST", "/api/tools/trust", {"digest": body["untrusted"]["digest"]})[1]
    assert body["untrusted"] is None and marker.exists()
    assert "fixture.first" in [item["name"] for item in body["items"]]
    assert "fixture.first" in page.app.active.session.messages[0].content


def test_web_refuses_trust_from_another_site(web, setup):
    path, marker = setup
    page = web(["hello"])
    digest = page.call("GET", "/api/tools")[1]["untrusted"]["digest"]
    evil = {"Origin": "http://evil.example"}
    assert page.call("POST", "/api/tools/trust", {"digest": digest}, headers=evil)[0] == 403
    assert not marker.exists()


def test_web_startup_line_points_at_the_question(web, setup, capsys):
    from types import SimpleNamespace
    from sensai_web.cli import serve

    app = web(["hello"]).app
    serve(SimpleNamespace(app=app, server_address=("", 1), serve_forever=lambda: None))
    assert "MCP config not trusted yet" in capsys.readouterr().out


def test_servers_are_discovered_in_parallel(tmp_path, monkeypatch):
    from time import monotonic, sleep
    from sensai import mcp_client

    def slow(name, spec):
        sleep(0.5)
        return [], {"name": name, "count": 0, "error": None}

    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"mcpServers": {f"s{i}": {"command": "x"} for i in range(4)}}), encoding="utf-8")
    monkeypatch.setattr(mcp_client, "_discover", slow)
    catalogue = Catalogue(path)
    catalogue.reload()
    catalogue.trust(catalogue.untrusted["digest"])
    started = monotonic()
    catalogue.reload()
    assert monotonic() - started < 1.5  # One wait, not four.
    assert [s["name"] for s in catalogue.servers] == ["s0", "s1", "s2", "s3"]  # Config order is kept.


def test_unreadable_answers_file_is_kept_not_wiped(setup):
    path, marker = setup
    store = Path(os.environ["XDG_CONFIG_HOME"]) / "sensai" / "trusted-mcp.json"
    store.parent.mkdir(parents=True)
    store.write_text("[not json", encoding="utf-8")
    catalogue = Catalogue(path)
    catalogue.reload()
    catalogue.trust(catalogue.untrusted["digest"])
    assert store.read_text(encoding="utf-8") == "[not json"  # Other folders' answers may be in there.
    assert "Could not save" in catalogue.notices()[0]


def test_save_error_clears_once_saving_works_again(setup):
    path, marker = setup
    store = Path(os.environ["XDG_CONFIG_HOME"]) / "sensai" / "trusted-mcp.json"
    store.parent.mkdir(parents=True)
    store.write_text("[not json", encoding="utf-8")
    catalogue = Catalogue(path)
    catalogue.reload()
    catalogue.trust(catalogue.untrusted["digest"])
    store.unlink()  # The user fixed the file.
    catalogue.reload()
    assert not any("Could not save" in line for line in catalogue.notices())
    assert Catalogue(path).reload() and json.loads(store.read_text(encoding="utf-8"))


def test_answers_saved_at_the_same_time_are_all_kept(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    store = Path(os.environ["XDG_CONFIG_HOME"]) / "sensai" / "trusted-mcp.json"
    catalogue = Catalogue(tmp_path / "mcp.json")
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda n: catalogue._save(f"folder{n}", "digest"), range(16)))
    assert len(json.loads(store.read_text(encoding="utf-8"))) == 16
