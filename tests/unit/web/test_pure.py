"""Security checks, tab lock, static files, configuration and session display (no server)."""
import pytest

from sensai.core.messages import Message
from sensai.settings import Settings
from sensai_web import session_view, static_files
from sensai_web.config import parser, resolve
from sensai_web.errors import ApiError
from sensai_web.security import allowed_hosts, check_request
from sensai_web.tabs import TabLock

HOSTS = allowed_hosts("127.0.0.1", 8765)


def check(method="GET", headers=None, body=False):
    check_request(method, {"Host": "localhost:8765", **(headers or {})}, HOSTS, body)


def refused(**kwargs):
    with pytest.raises(ApiError) as caught:
        check(**kwargs)
    return caught.value


def test_loopback_names_share_a_port():
    assert HOSTS == {"127.0.0.1:8765", "localhost:8765"}
    assert allowed_hosts("::1", 1) == {"[::1]:1"}


@pytest.mark.parametrize("bind", ["0.0.0.0", "192.168.1.5", "example.com", ""])
def test_only_loopback_addresses_are_accepted(bind):
    with pytest.raises(ValueError):
        allowed_hosts(bind, 8765)


def test_checks_pass_for_the_page_itself():
    check()
    check("POST", {"Origin": "http://localhost:8765", "Content-Type": "application/json; charset=utf-8"}, True)
    check("POST")  # No body: stop and takeover need no content type.


@pytest.mark.parametrize("host", ["evil.com", "localhost:9999", "", "localhost"])
def test_other_hosts_are_refused_against_dns_rebinding(host):
    assert refused(headers={"Host": host}).code == "forbidden_host"


def test_cross_site_requests_are_refused():
    check(headers={"Sec-Fetch-Site": "cross-site"})  # Following a link to the page is fine.
    assert refused(method="POST", headers={"Sec-Fetch-Site": "cross-site"}).code == "forbidden_origin"
    assert refused(method="POST", headers={"Origin": "http://evil.com"}, body=True).code == "forbidden_origin"
    assert refused(method="PUT", headers={"Origin": "null"}, body=True).code == "forbidden_origin"


def test_a_body_must_be_json():
    error = refused(method="POST", headers={"Content-Type": "text/plain"}, body=True)
    assert (error.status, error.code) == (415, "unsupported_media_type")
    assert refused(method="PUT", body=True).status == 415


def test_the_first_tab_owns_the_session_and_others_get_409():
    clock = [0.0]
    lock = TabLock(idle_seconds=10, clock=lambda: clock[0])
    lock.check("a")
    lock.check("a")
    lock.check(None)  # Scripts without a tab id are never locked.
    with pytest.raises(ApiError) as caught:
        lock.check("b")
    assert (caught.value.status, caught.value.code) == (409, "tab_locked")


def test_takeover_and_idle_expiry_hand_the_session_over():
    clock = [0.0]
    lock = TabLock(idle_seconds=10, clock=lambda: clock[0])
    lock.check("a")
    lock.takeover("b")
    lock.check("b")
    with pytest.raises(ApiError):
        lock.check("a")
    clock[0] = 11.0  # b went quiet: a may claim the session again.
    lock.check("a")


def test_static_files_are_served_with_their_type():
    kind, data = static_files.read("/")
    assert kind.startswith("text/html") and b"<html" in data.lower()
    assert static_files.read("/js/main.js")[0].startswith("text/javascript")
    assert static_files.read("/css/base.css")[0].startswith("text/css")


@pytest.mark.parametrize("path", ["/../static_files.py", "/js/../../app.py", "/%2e%2e/app.py", "/js//main.js",
                                  "/js/nope.js", "/js", "/..%2fapp.py", "/js\\main.js", "/a\x00.js", "/js/main.js/",
                                  "/data.sqlite3", "/index.html.py"])
def test_static_paths_cannot_leave_the_page_folder(path):
    with pytest.raises(ApiError) as caught:
        static_files.read(path)
    assert caught.value.status == 404


def test_configuration_records_where_each_value_came_from():
    settings = Settings(_env_file=None, SENSAI_TIMEOUT="9", SENSAI_CREATOR="amy")
    args = parser(settings).parse_args(["gemma3:1b", "--db", "x.db"])
    cfg = resolve(args, settings, env={"SENSAI_TIMEOUT": "9", "SENSAI_CREATOR": "amy"}, dotenv={"OLLAMA_HOST"})
    sources = {key: entry["source"] for key, entry in cfg.effective.items()}
    assert sources["model"] == sources["database_path"] == "cli"
    assert sources["request_timeout"] == sources["creator"] == "env"
    assert sources["ollama_host"] == "dotenv"
    assert sources["turn_budget"] == "default"
    assert (cfg.model, cfg.db_path, cfg.creator, cfg.timeout, cfg.port) == ("gemma3:1b", "x.db", "amy", 9.0, 8765)


def test_flags_beat_the_environment_and_defaults_apply(monkeypatch):
    monkeypatch.delenv("SENSAI_DB", raising=False)
    settings = Settings(_env_file=None)
    args = parser(settings).parse_args(["m", "--operation-timeout", "5", "--port", "0"])
    cfg = resolve(args, settings, env={}, dotenv=set())
    assert (cfg.operation_timeout, cfg.db_path, cfg.bind) == (5.0, "sensai.sqlite3", "127.0.0.1")
    assert cfg.effective["turn_budget"] == {"value": 5.0, "source": "cli"}


@pytest.mark.parametrize("argv", [["m", "--port", "70000"], ["m", "--port", "x"], ["m", "--operation-timeout", "0"],
                                  ["m", "--operation-timeout", "nan"]])
def test_bad_numbers_are_rejected(argv):
    with pytest.raises(SystemExit):
        parser(Settings(_env_file=None)).parse_args(argv)


def msgs(*pairs):
    return [Message(role=role, content=content) for role, content in pairs]


def test_display_items_number_user_messages_and_join_the_visible_reply():
    items = session_view.display_items(msgs(("user", "hi"), ("assistant", "hello"), ("user", "bye"),
                                            ("assistant", "ciao\n")), "redaction")
    assert [(i["kind"], i.get("n"), i["text"]) for i in items] == [
        ("user", 1, "hi"), ("assistant", None, "hello"), ("user", 2, "bye"), ("assistant", None, "ciao")]
    assert items[1]["persona"] == "redaction" and items[1]["usage"] is None and items[1]["tools"] == []


def test_a_tool_round_is_part_of_the_assistant_item():
    call = '{"tool": "calculate", "arguments": {"expression": "6*7"}}'
    items = session_view.display_items(msgs(
        ("user", "6*7?"), ("assistant", f"Let me check.\n{call}"),
        ("user", "Tool result from calculate:\n42"), ("assistant", "It is 42.")), None)
    assert len(items) == 2
    assert items[1]["text"] == "Let me check.\nIt is 42."
    assert items[1]["tools"] == [{"kind": "tool", "id": "c1", "name": "calculate", "round": 1, "ok": True,
                                  "arguments": {"expression": "6*7"}, "output": "42"}]


def test_tool_errors_refusals_and_the_round_limit_note_are_recognised():
    call = '{"tool": "run_python", "arguments": {"code": "1"}}'
    note = "\nTool round limit reached. Give a final answer without tools."
    items = session_view.display_items(msgs(
        ("user", "go"), ("assistant", call), ("user", "Tool error from run_python:\ntool approval refused"),
        ("assistant", call), ("user", f"Tool error from run_python:\nboom{note}"), ("assistant", "done")), None)
    first, second = items[1]["tools"]
    assert first["ok"] is False and first["refused"] is True and first["error"] == "tool approval refused"
    assert second["error"] == "boom" and second["refused"] is False and second["round"] == 2


def test_tool_protocol_messages_are_not_counted_as_the_creators_words():
    messages = msgs(("user", "q"), ("assistant", '{"tool": "x", "arguments": {}}'),
                    ("user", "Tool result from x:\nok"), ("assistant", "a"))
    assert [i["n"] for i in session_view.display_items(messages, None) if i["kind"] == "user"] == [1]
    assert session_view.history(messages) == [{"n": 1, "text": "q"}]


def test_history_lines_are_cut_like_the_terminal():
    long = "x" * 150
    assert session_view.history(msgs(("user", long)))[0]["text"] == "x" * 100 + " …"
    assert session_view.history(msgs(("user", "a\nb")))[0]["text"] == "a …"
