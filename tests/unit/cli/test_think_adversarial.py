"""Adversarial /think checks in the REPL and through cli.main: stops, deadlines, history, saving."""

import time

import pytest

from fakes import FakeClient, FakeSessionStore, scripted_terminal
from sensai.chat import saved_sessions
from sensai.chat.personas import PersonaRegistry
from sensai.chat.reasoning import Check
from sensai.chat.saved_sessions import SessionRecorder
from sensai.chat.session import ChatSession
from sensai.cli import main as cli
from sensai.core.cancellation import OperationCancelled, OperationTimedOut
from sensai.core.errors import LLMError
from sensai.core.ports import ToolDefinition, ToolResult
from sensai.llm.structured import StructuredOutputError
from sensai.tools import ToolRegistry

pytestmark = pytest.mark.usefixtures("isolated_settings")
LOOKUP = '{"tool":"lookup","arguments":{"q":"rate"}}'


class Checker:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def complete(self, model, messages, schema):
        self.calls.append(list(messages))
        result = self.results.pop(0) if self.results else Check(ok=True)
        if isinstance(result, BaseException):
            raise result
        return result


class Store(FakeSessionStore):
    def set_title(self, session_id, title):
        self.title = title


def chat(client, inputs, checker=None, *, handler=None, confirm=False, recorder=None,
         tools=None, **repl_kwargs):
    lines = iter(inputs)
    prompts = []

    def read(prompt):
        prompts.append(prompt)
        value = next(lines)
        if isinstance(value, BaseException):
            raise value
        return value

    if tools is None:
        tools = ToolRegistry(read=read)
        tools.register(ToolDefinition("lookup", "Look up."),
                       handler or (lambda arguments, cancellation: ToolResult("15.0")),
                       timeout=None, confirm=confirm)
    elif tools == "default":
        tools = None  # repl builds the real calculate + run_python registry on ``read``.
    written = []

    def write(*args, end="\n", flush=False):
        text = "".join(map(str, args)) + end
        text.encode("utf-8")  # A real UTF-8 terminal rejects lone surrogates.
        written.append(text)

    session = ChatSession(client, "model", "sys")
    cli.repl(session, read=read, write=write, tool_registry=tools,
             checker=Checker() if checker is None else checker, recorder=recorder, **repl_kwargs)
    return session, "".join(written), prompts


def contents(session):
    return [(m.role, m.content) for m in session.messages[1:]]


# --- Command parsing ------------------------------------------------------------------------

@pytest.mark.parametrize("line", ["  /think  ", "/think\t", "\t/think \t "])
def test_think_with_only_whitespace_prints_usage(line):
    client = FakeClient()
    session, output, _ = chat(client, [line, "exit"])
    assert output == "usage: /think <request>\n" and client.requests == []


@pytest.mark.parametrize("line", ["/thinking about it", "/Think about it"])
def test_lookalike_commands_are_normal_messages(line):
    client = FakeClient(["Plain"])
    checker = Checker()
    session, output, _ = chat(client, [line, "exit"], checker)
    assert output == "Plain\n" and checker.calls == []
    assert contents(session) == [("user", line), ("assistant", "Plain")]


def test_the_request_keeps_inner_whitespace_and_drops_the_command():
    client = FakeClient(["Plan"], ["Done."])
    session, _, _ = chat(client, ["/think   a  b\tc  ", "exit"])
    assert contents(session) == [("user", "a  b\tc"), ("assistant", "Done.")]
    assert "Request: a  b\tc\n" in client.calls[0][-1]


# --- History, follow-ups and saving ---------------------------------------------------------

def test_a_second_think_and_a_normal_turn_see_only_requests_and_final_answers():
    client = FakeClient(["P1"], [LOOKUP], ["A1"], ["P2"], ["A2"], ["Plain"])
    checker = Checker()
    session, _, _ = chat(client, ["/think Q1", "/think Q2", "Q3", "exit"], checker)
    assert client.calls[3][1:3] == ["Q1", "A1"]  # The second plan request.
    assert "P1" not in client.calls[3] and not any("15.0" in c for c in client.calls[3])
    assert client.calls[-1][1:] == ["Q1", "A1", "Q2", "A2", "Q3"]
    assert len(checker.calls) == 2  # The normal turn makes no check.
    assert contents(session)[-1] == ("assistant", "Plain")


def test_a_failed_think_then_a_successful_one_saves_and_titles_only_the_success():
    store = Store()
    titled = []
    recorder = SessionRecorder(store, "k7f2qa",
                               titler=lambda *args: titled.append(args) or "T")
    client = FakeClient(["Plan"], ["half", OperationCancelled("Esc")], ["Plan"], ["Answer"])
    session, output, _ = chat(client, ["/think Q1", "/think Q2", "exit"], recorder=recorder)
    assert "Réponse interrompue" in output
    assert [(m.role, m.content) for m in store.sessions["k7f2qa"].messages] == [
        ("user", "Q2"), ("assistant", "Answer")]
    assert titled == [("Q2", "Answer")] and store.title == "T"


def test_check_unavailable_in_the_cli_keeps_the_unchecked_answer():
    store = Store()
    recorder = SessionRecorder(store, "k7f2qa", titler=lambda *args: "T")
    client = FakeClient(["Plan"], ["Draft"])
    session, output, _ = chat(client, ["/think Q", "exit"],
                              Checker(StructuredOutputError("bad JSON")), recorder=recorder)
    assert output == ("Plan\nPlan\nDraft\nDraft\nCheck unavailable\n"
                      "Final answer (1 round, 0 tool calls)\nDraft\n")
    assert contents(session) == [("user", "Q"), ("assistant", "Draft")]
    assert len(store.sessions["k7f2qa"].messages) == 2


def test_unresolved_problems_are_printed_and_the_last_draft_is_kept():
    client = FakeClient(["Plan"], ["D1"], ["D2"], ["D3"])
    checker = Checker(*[Check(ok=False, problems=["cures eczema"])] * 3)
    session, output, _ = chat(client, ["/think Q", "exit"], checker)
    assert output.endswith("Check — 1 problem\n- cures eczema\nUnresolved\n- cures eczema\n"
                           "Final answer (3 rounds, 0 tool calls)\nD3\n")
    assert contents(session) == [("user", "Q"), ("assistant", "D3")]


# --- Stops at every stage -------------------------------------------------------------------

@pytest.mark.parametrize("case, notice", [
    ("approval Ctrl+C", "Réponse interrompue"),
    ("checker Ctrl+C", "Réponse interrompue"),
    ("tool deadline", "Délai maximal dépassé"),
    ("no visible answer", "error: model returned no visible answer"),
    ("revise", "Réponse interrompue"),
    ("check error", "error: Ollama is down"),
])
def test_every_stop_adds_and_saves_nothing_and_the_next_message_works(case, notice):
    store = Store()
    recorder = SessionRecorder(store, "k7f2qa", titler=lambda *args: "T")
    replies = {
        "approval Ctrl+C": [["Plan"], [LOOKUP]],
        "tool deadline": [["Plan"], [LOOKUP]],
        "no visible answer": [["Plan"], *[[LOOKUP]] * 7],
        "revise": [["Plan"], ["D1"], ["half", OperationCancelled("Esc")]],
    }
    client = FakeClient(*replies.get(case, [["Plan"], [LOOKUP], ["D1"]]), ["Next answer"])
    checks = {"checker Ctrl+C": [KeyboardInterrupt()],
              "revise": [Check(ok=False, problems=["x"])],
              "check error": [Check(ok=False, problems=["x"]), LLMError("Ollama is down")]}
    if case == "check error":
        client = FakeClient(["Plan"], ["D1"], ["D2"], ["Next answer"])

    def handler(arguments, cancellation):
        if case == "tool deadline":
            raise OperationTimedOut("late")
        return ToolResult("15.0")

    inputs = ["/think Q", KeyboardInterrupt(), "Next", "exit"] if case == "approval Ctrl+C" \
        else ["/think Q", "Next", "exit"]
    session, output, _ = chat(client, inputs, Checker(*checks.get(case, [])), handler=handler,
                              confirm=case == "approval Ctrl+C", recorder=recorder)
    assert output.endswith(f"\n{notice}\nNext answer\n")
    assert contents(session) == [("user", "Next"), ("assistant", "Next answer")]
    assert client.calls[-1][1:] == ["Next"]
    assert [(m.role, m.content) for m in store.sessions["k7f2qa"].messages] == contents(session)


def test_one_cancel_callback_stops_the_loop_and_clears_for_the_next_message():
    requested = []

    def handler(arguments, cancellation):
        requested.append(True)  # Esc pressed while the tool runs.
        return ToolResult("15.0")

    def cancel_requested():
        return bool(requested) and requested.pop() is True

    client = FakeClient(["Plan"], [LOOKUP], ["Next answer"])
    checker = Checker()
    session, output, _ = chat(client, ["/think Q", "Next", "exit"], checker, handler=handler,
                              cancel_requested=cancel_requested)
    assert "Réponse interrompue\nNext answer\n" in output and checker.calls == []
    assert contents(session) == [("user", "Next"), ("assistant", "Next answer")]


class SlowClient(FakeClient):
    def __init__(self, delay, *replies):
        super().__init__(*replies)
        self.delay = delay

    def stream(self, model, messages, cancellation=None):
        time.sleep(self.delay)
        return super().stream(model, messages, cancellation)


def test_each_step_gets_its_own_deadline():
    class SlowChecker(Checker):
        def complete(self, *args):
            time.sleep(0.3)
            return super().complete(*args)

    # Three steps of 0.3 s each pass a 0.5 s per-step deadline (0.9 s in total).
    client = SlowClient(0.3, ["Plan"], ["Done."])
    session, output, _ = chat(client, ["/think Q", "exit"], SlowChecker(),
                              operation_timeout=0.5)
    assert output.endswith("Check — ok\nFinal answer (1 round, 0 tool calls)\nDone.\n")
    assert contents(session) == [("user", "Q"), ("assistant", "Done.")]


def test_one_step_past_its_deadline_times_out_and_adds_nothing():
    client = SlowClient(0.4, ["Plan"], ["Done."])
    client.delay = 0
    real_stream = client.stream

    def stream(model, messages, cancellation=None):
        client.delay = 0.4 if client.requests else 0  # Only the draft step is slow.
        return real_stream(model, messages, cancellation)

    client.stream = stream
    session, output, _ = chat(client, ["/think Q", "exit"], operation_timeout=0.2)
    assert output.endswith("\nDélai maximal dépassé\n") and contents(session) == []


def test_esc_after_a_tool_round_still_shows_that_round():
    client = FakeClient(["Plan"], [LOOKUP], OperationCancelled("Esc"), ["Next answer"])
    _, output, _ = chat(client, ["/think Q", "Next", "exit"])
    assert 'Act\nlookup({"q":"rate"})\nObserve\n15.0\nRéponse interrompue\n' in output


# --- Real run_python approval and escaping ---------------------------------------------------

def test_real_run_python_asks_before_running_and_a_refusal_is_the_observation():
    block = '{"tool":"run_python","arguments":{"code":"print(1)"}}'
    client = FakeClient(["Plan"], [block], ["Not run."])
    session, output, prompts = chat(client, ["/think Q", "n", "exit"], tools="default")
    assert any(p.startswith("Allow run_python(") for p in prompts)
    assert 'Act\nrun_python({"code":"print(1)"})\nObserve\ntool approval refused\n' in output
    assert contents(session) == [("user", "Q"), ("assistant", "Not run.")]


def test_control_characters_and_lone_surrogates_in_a_round_are_escaped():
    block = '{"tool":"look\\ud800","arguments":{"q":"\\u202e\\ud800"}}'
    tools_block = '{"tool":"lookup","arguments":{"q":"\\u001b[2J"}}'
    client = FakeClient(["Plan"], [block], [tools_block], ["Done."])
    _, output, _ = chat(client, ["/think Q", "exit"],
                        handler=lambda arguments, cancellation: ToolResult("a\rb\x1b[31m\ud800"))
    assert 'Act\nlook\\ud800({"q":"\\u202e\\ud800"})\nObserve\nunknown tool\n' in output
    assert 'Act\nlookup({"q":"\\u001b[2J"})\nObserve\na\nb\\x1b[31m\\ud800\n' in output
    assert not any(ch in output for ch in "\r\x1b\u202e")


# --- Personas and resumed sessions through cli.main ------------------------------------------

def run_main(monkeypatch, tmp_path, client, inputs, *argv, checker=None):
    checker = checker or Checker()
    monkeypatch.setattr(cli, "OllamaStructuredClient",
                        lambda host, timeout, context_length=None: checker)
    monkeypatch.setattr(cli, "create_client", lambda settings: client)
    monkeypatch.setattr(cli, "TerminalInput", scripted_terminal(inputs))
    cli.main(["model", "--db", str(tmp_path / "s.sqlite3"), *argv])
    return checker


def test_persona_switch_before_think_is_used_by_every_step_and_the_check(monkeypatch, tmp_path):
    monkeypatch.setattr(saved_sessions, "new_session_id", lambda exists: "k7f2qa")
    persona = PersonaRegistry.from_file().get("analyse")
    client = FakeClient(["Intro"], ["Plan"], ["Done."], ["Next answer"])
    checker = run_main(monkeypatch, tmp_path, client,
                       ["Hello", "/persona analyse", "/think Q", "Next", "exit"])
    system = client.calls[1][0]
    assert persona.system_prompt in system
    for call in client.calls[1:]:  # The active role is re-sent before every request.
        assert call[-2] == system
    rules = checker.calls[0][0].content
    assert persona.system_prompt in rules and "Available tools" not in rules
    assert client.calls[-1][1:] == ["Hello", "Intro", "Q", "Done.", system, "Next"]


def test_a_resumed_session_holds_only_the_request_and_final_answer(monkeypatch, tmp_path):
    monkeypatch.setattr(saved_sessions, "new_session_id", lambda exists: "k7f2qa")
    first = FakeClient(["1. Plan"], ["Rate is 15%."])
    run_main(monkeypatch, tmp_path, first, ["/think Summarize", "exit"])
    second = FakeClient(["Plan 2"], ["Shorter."], ["Fine."])
    run_main(monkeypatch, tmp_path, second, ["/think make it shorter", "ok?", "exit"],
             "--session", "k7f2qa")
    assert second.calls[0][1:3] == ["Summarize", "Rate is 15%."]
    assert "1. Plan" not in second.calls[0]
    assert second.calls[-1][1:] == ["Summarize", "Rate is 15%.", "make it shorter",
                                    "Shorter.", "ok?"]
