"""Turn timestamps and the remote Ollama tunnel of sensai-web."""
import sqlite3
from contextlib import contextmanager

import pytest

from sensai.cli.remote import RemoteError
from sensai.core.messages import Message
from sensai_web import cli, session_view
from sensai_web.times import TurnTimes


def test_times_are_stored_per_creator_and_session(tmp_path):
    path = str(tmp_path / "t.sqlite3")
    amy, ben = TurnTimes(path, "amy"), TurnTimes(path, "ben")
    assert amy.load("s1") == {}  # Nothing recorded yet, and not even a table.
    amy.record("s1", 1, "2026-10-28T10:00:00+00:00", "2026-10-28T10:00:05+00:00")
    amy.record("s1", 2, "2026-10-28T10:01:00+00:00", "2026-10-28T10:01:03+00:00")
    amy.record("s1", 2, "2026-10-28T10:01:00+00:00", "2026-10-28T10:01:09+00:00")  # Replaced.
    assert amy.load("s1") == {1: ("2026-10-28T10:00:00+00:00", "2026-10-28T10:00:05+00:00"),
                              2: ("2026-10-28T10:01:00+00:00", "2026-10-28T10:01:09+00:00")}
    assert ben.load("s1") == {} and amy.load("other") == {}


def test_an_unwritable_database_costs_a_timestamp_not_a_crash(tmp_path):
    times = TurnTimes(str(tmp_path / "missing-folder" / "t.sqlite3"), "amy")
    times.record("s", 1, "a", "b")
    assert times.load("s") == {}


def test_display_items_carry_the_turn_times():
    messages = [Message(role="user", content="q1"), Message(role="assistant", content="a1"),
                Message(role="user", content="q2"), Message(role="assistant", content="a2")]
    items = session_view.display_items(messages, None, {1: ("s1", "f1")})
    assert [item.get("at") for item in items] == ["s1", "f1", None, None]


def test_restored_sessions_show_when_each_turn_happened(web):
    page = web(["a1"], ["a2"])
    page.stream({"text": "q1"})
    page.stream({"text": "q2"})
    sid = page.call("GET", "/api/session")[1]["id"]
    again = web(session=sid)  # A new process over the same database.
    items = again.call("GET", "/api/session")[1]["items"]
    assert [i["kind"] for i in items] == ["user", "assistant", "user", "assistant"]
    assert all("T" in i["at"] for i in items)
    assert items[0]["at"] <= items[1]["at"] <= items[2]["at"] <= items[3]["at"]
    assert again.call("GET", f"/api/sessions/{sid}")[1]["items"][0]["at"] == items[0]["at"]


def test_terminal_turns_without_times_still_load(web, tmp_path):
    page = web(["a1"])
    page.stream({"text": "q1"})
    sid = page.call("GET", "/api/session")[1]["id"]
    with sqlite3.connect(tmp_path / "web.sqlite3") as connection:
        connection.execute("DELETE FROM web_turn_times")  # As if the turn came from the CLI.
    items = web(session=sid).call("GET", "/api/session")[1]["items"]
    assert [i["text"] for i in items] == ["q1", "a1"] and all("at" not in i for i in items)


def test_the_times_table_does_not_disturb_the_session_store(web, tmp_path):
    from sensai.memory.sqlite_store import StorageRepository
    page = web(["a1"])
    page.stream({"text": "q1"})
    with StorageRepository(tmp_path / "web.sqlite3") as repository:  # What the terminal CLI opens.
        assert len(repository.for_creator("default").sessions.list()) == 1


@pytest.fixture
def remote_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # No .env here.
    for name in ("SENSAI_PROMPT", "SENSAI_MODEL", "SENSAI_PERSONA"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SENSAI_DB", str(tmp_path / "r.sqlite3"))
    monkeypatch.setenv("SENSAI_SSH_HOST", "gpu-box")
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11435")
    return monkeypatch


def test_a_remote_server_needs_the_tunnel_port(remote_env):
    remote_env.setenv("OLLAMA_HOST", "http://localhost:11434")
    with pytest.raises(SystemExit, match="11435"):
        cli.build(["m", "--port", "0"])


@pytest.mark.parametrize("alias", ["-oProxyCommand=x", "two words", "a\tb"])
def test_a_remote_alias_must_be_a_plain_ssh_alias(remote_env, alias):
    remote_env.setenv("SENSAI_SSH_HOST", alias)
    with pytest.raises(SystemExit, match="SSH alias"):
        cli.build(["m", "--port", "0"])


def test_the_tunnel_wraps_the_server_and_health_says_remote(remote_env):
    calls = []

    @contextmanager
    def tunnel(alias):
        calls.append(("open", alias))
        yield
        calls.append(("close", alias))

    remote_env.setattr(cli, "ssh_tunnel", tunnel)
    remote_env.setattr(cli, "serve", lambda server: calls.append(("serve", server.app.cfg.ssh_host)))
    assert cli.main(["m", "--port", "0"]) == 0
    assert calls == [("open", "gpu-box"), ("serve", "gpu-box"), ("close", "gpu-box")]


def test_a_failing_tunnel_is_reported_and_exits_nonzero(remote_env, capsys):
    @contextmanager
    def tunnel(alias):
        raise RemoteError("SSH failed")
        yield

    remote_env.setattr(cli, "ssh_tunnel", tunnel)
    assert cli.main(["m", "--port", "0"]) == 1
    assert "error: SSH failed" in capsys.readouterr().err


def test_without_ssh_no_tunnel_is_opened(remote_env):
    remote_env.delenv("SENSAI_SSH_HOST")
    remote_env.setenv("OLLAMA_HOST", "http://localhost:11434")
    remote_env.setattr(cli, "ssh_tunnel", lambda alias: pytest.fail("no tunnel expected"))
    remote_env.setattr(cli, "serve", lambda server: None)
    assert cli.main(["m", "--port", "0"]) == 0


def test_health_reports_remote(web):
    page = web(ssh_host="gpu-box")
    assert page.call("GET", "/api/health")[1]["remote"] is True
    assert web().call("GET", "/api/health")[1]["remote"] is False
