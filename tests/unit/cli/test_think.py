"""/think in the REPL: labelled steps, what joins the chat and is saved, and failures."""

import pytest

from fakes import FakeClient, FakeSessionStore, scripted_terminal
from sensai.chat import saved_sessions
from sensai.chat.reasoning import Check
from sensai.chat.saved_sessions import SessionRecorder
from sensai.chat.session import ChatSession
from sensai.cli import main as cli
from sensai.core.cancellation import OperationCancelled, OperationTimedOut
from sensai.core.errors import LLMError
from sensai.core.ports import ToolDefinition, ToolResult
from sensai.tools import ToolRegistry

pytestmark = pytest.mark.usefixtures("isolated_settings")
LOOKUP = '{"tool":"lookup","arguments":{"q":"rate"}}'


class FakeChecker:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = 0

    def complete(self, model, messages, schema):
        self.calls += 1
        result = self.results.pop(0) if self.results else Check(ok=True)
        if isinstance(result, BaseException):
            raise result
        return result


class Store(FakeSessionStore):
    def set_title(self, session_id, title):
        pass


def chat(client, inputs, checker=..., *, output="15.0", error=None, confirm=False,
         recorder=None):
    lines = iter(inputs)

    def read(prompt):
        value = next(lines)
        if isinstance(value, BaseException):
            raise value
        return value

    def lookup(arguments, cancellation):
        if isinstance(error, BaseException):
            raise error
        return ToolResult(output)

    tools = ToolRegistry(read=read)
    tools.register(ToolDefinition("lookup", "Look up."), lookup, timeout=None, confirm=confirm)
    written = []

    def write(*args, end="\n", flush=False):
        written.append("".join(map(str, args)) + end)

    session = ChatSession(client, "model", "sys")
    if checker is ...:
        checker = FakeChecker()
    cli.repl(session, read=read, write=write, tool_registry=tools, checker=checker,
             recorder=recorder)
    return session, "".join(written)


def contents(session):
    return [(m.role, m.content) for m in session.messages[1:]]


def test_think_shows_labelled_steps_and_adds_only_request_and_final_answer():
    client = FakeClient(["1. Look it up"], [LOOKUP], ["Rate is 15%."], ["Shorter: 15%."])
    session, output = chat(client, ["/think  Summarize the week", "make it shorter", "exit"])
    assert output == ("Plan\n1. Look it up\n"
                      'Act\nlookup({"q":"rate"})\nObserve\n15.0\n'
                      "Draft\nRate is 15%.\nCheck — ok\n"
                      "Final answer (1 round, 1 tool call)\nRate is 15%.\n"
                      "Shorter: 15%.\n")
    assert contents(session) == [("user", "Summarize the week"), ("assistant", "Rate is 15%."),
                                 ("user", "make it shorter"), ("assistant", "Shorter: 15%.")]
    # The follow-up sees the request and the final answer, not the plan or the tool rounds.
    assert client.calls[-1][1:] == ["Summarize the week", "Rate is 15%.", "make it shorter"]


def test_saved_session_holds_only_the_request_and_the_final_answer():
    store = Store()
    recorder = SessionRecorder(store, "k7f2qa", titler=lambda *args: "T")
    client = FakeClient(["Plan"], [LOOKUP], ["Rate is 15%."])
    chat(client, ["/think Summarize", "exit"], recorder=recorder)
    saved = store.sessions["k7f2qa"].messages
    assert [(m.role, m.content) for m in saved] == [("user", "Summarize"),
                                                    ("assistant", "Rate is 15%.")]


@pytest.mark.parametrize("line", ["/think", "/think   "])
def test_think_without_a_request_prints_usage(line):
    client = FakeClient()
    checker = FakeChecker()
    session, output = chat(client, [line, "exit"], checker)
    assert output == "usage: /think <request>\n"
    assert client.requests == [] and checker.calls == 0 and contents(session) == []


def test_think_without_a_checker_is_unavailable():
    client = FakeClient()
    session, output = chat(client, ["/think Summarize", "exit"], None)
    assert output == "error: /think is unavailable\n"
    assert client.requests == [] and contents(session) == []


@pytest.mark.parametrize("case", ["plan", "tool", "check", "timeout", "error"])
def test_stopped_think_adds_and_saves_nothing_and_the_next_message_works(case):
    replies = {"plan": [["1.", OperationCancelled("Esc")]],
               "timeout": [["1.", OperationTimedOut("late")]],
               "tool": [["Plan"], [LOOKUP]]}
    client = FakeClient(*replies.get(case, [["Plan"], [LOOKUP], ["Draft"]]), ["Next answer"])
    failure = {"check": OperationCancelled("stop"), "error": LLMError("Ollama is down")}
    store = Store()
    recorder = SessionRecorder(store, "k7f2qa", titler=lambda *args: "T")
    session, output = chat(client, ["/think Summarize", "Next", "exit"],
                           FakeChecker(failure.get(case, Check(ok=True))),
                           error=KeyboardInterrupt() if case == "tool" else None, recorder=recorder)
    notice = {"timeout": "Délai maximal dépassé", "error": "error: Ollama is down"}
    assert output.endswith(f"\n{notice.get(case, 'Réponse interrompue')}\nNext answer\n")
    assert contents(session) == [("user", "Next"), ("assistant", "Next answer")]
    assert client.calls[-1][1:] == ["Next"]
    assert [(m.role, m.content) for m in store.sessions["k7f2qa"].messages] == contents(session)


def test_act_and_observe_text_is_sanitized():
    client = FakeClient(["Plan"], ['{"tool":"lookup","arguments":{"q":"\u202eevil"}}'], ["Done."])
    _, output = chat(client, ["/think Q", "exit"], output="ok\x1b[31m red\x07\nline 2")
    assert 'Act\nlookup({"q":"\\u202eevil"})\nObserve\nok\\x1b[31m red\\x07\nline 2\n' in output
    assert "\x1b" not in output and "\u202e" not in output


def test_tool_approval_works_inside_think():
    client = FakeClient(["Plan"], [LOOKUP], ["Done."])
    session, output = chat(client, ["/think Q", "y", "exit"], confirm=True)
    assert "Observe\n15.0\n" in output
    assert contents(session) == [("user", "Q"), ("assistant", "Done.")]


def test_normal_messages_are_unchanged_when_think_is_available():
    with_checker = chat(FakeClient([LOOKUP], ["Seven"]), ["Q", "exit"])
    without = chat(FakeClient([LOOKUP], ["Seven"]), ["Q", "exit"], None)
    assert with_checker[1] == without[1] == 'Using tool: lookup({"q": "rate"})\nSeven\n'
    assert contents(with_checker[0]) == contents(without[0])


def test_run_chat_passes_a_structured_checker_on_the_chat_host(monkeypatch, tmp_path):
    created = []

    class Structured(FakeChecker):
        def __init__(self, host, timeout, context_length=None):
            super().__init__()
            created.append((host, timeout, context_length))

    monkeypatch.setattr(cli, "OllamaStructuredClient", Structured)
    monkeypatch.setattr(saved_sessions, "new_session_id", lambda exists: "k7f2qa")
    monkeypatch.setattr(cli, "create_client", lambda settings: FakeClient(["Plan"], ["Done."]))
    monkeypatch.setattr(cli, "TerminalInput", scripted_terminal(["/think Q", "exit"]))
    monkeypatch.setenv("SENSAI_CONTEXT_LENGTH", "8192")
    cli.main(["model", "--db", str(tmp_path / "s.sqlite3"), "--host", "http://127.0.0.1:11435",
              "--operation-timeout", "42"])
    # The check's HTTP timeout is the per-step budget, with the chat's context length.
    assert created == [("http://127.0.0.1:11435", 42.0, 8192)]


def test_narration_before_a_tool_block_is_model_text_not_escaped():
    client = FakeClient(["Plan"], ["Checking\u200b now\n", LOOKUP], ["Done."])
    _, output = chat(client, ["/think Q", "exit"], output="15.0\u200b")
    # Narration is printed as is, like Plan and Draft; the tool result is escaped.
    assert "Plan\nChecking\u200b now\nAct\n" in output
    assert "Observe\n15.0\\u200b\n" in output


def test_a_long_act_line_is_cut_like_an_observation():
    block = '{"tool":"lookup","arguments":{"q":"%s"}}' % ("x" * 600)
    client = FakeClient(["Plan"], [block], ["Done."])
    _, output = chat(client, ["/think Q", "exit"])
    act = output.split("Act\n", 1)[1].split("\n", 1)[0]
    assert len(act) == 502 and act.endswith(" …") and act.startswith('lookup({"q":"xxx')


def test_an_empty_result_keeps_its_line_so_later_narration_is_not_tool_text():
    client = FakeClient(["Plan"], [LOOKUP], ["Again\u200b\n", LOOKUP], ["Done."])
    _, output = chat(client, ["/think Q", "exit"], output="")
    assert 'Observe\n\nAgain\u200b\nAct\n' in output
