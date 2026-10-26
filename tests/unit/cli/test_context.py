"""M2 token budget through cli.main: status lines, /context, failures and resumed summaries."""

import pytest

from fakes import FakeClient, scripted_terminal
from sensai.chat import compression, saved_sessions
from sensai.cli import main as cli
from sensai.core.errors import LLMError
from sensai.llm.ollama_api import OllamaUsage
from sensai.memory.sqlite_store import StorageRepository

SUMMARY = f"{compression.SUMMARY_PREFIX}\nLaunch 14 November, hero Calm Barrier Cream."


class UsageClient(FakeClient):
    """FakeClient that reports one scripted token count per request, like Ollama's usage_sink."""

    def __init__(self, counts, *replies):
        super().__init__(*replies)
        self.counts = list(counts)
        self.sink = None

    def stream(self, model, messages, cancellation=None):
        yield from super().stream(model, messages, cancellation)
        count = self.counts.pop(0)
        if self.sink is not None:
            self.sink(OllamaUsage(prompt_tokens=None if count is None else count - 5,
                                  output_tokens=None if count is None else 5, latency_ms=1.0))


@pytest.fixture(autouse=True)
def isolated(isolated_settings, monkeypatch, tmp_path):
    (tmp_path / "prompt.txt").write_text("Shared rules", encoding="utf-8")
    monkeypatch.setattr(saved_sessions, "new_session_id", lambda exists: "abcdef")


def chat(monkeypatch, tmp_path, client, inputs, *argv):
    def create_client(settings, usage_sink=None):
        client.sink = usage_sink
        return client

    monkeypatch.setattr(cli, "create_client", create_client)
    monkeypatch.setattr(cli, "TerminalInput", scripted_terminal(inputs))
    cli.main(["model", "--prompt", str(tmp_path / "prompt.txt"),
              "--db", str(tmp_path / "s.db"), *argv])


def saved_messages(tmp_path):
    with StorageRepository(tmp_path / "s.db") as repository:
        return repository.for_creator("default").sessions.load("abcdef").messages


def test_summary_near_budget_lowers_count_and_is_reported(monkeypatch, tmp_path, capsys):
    client = UsageClient([30, 50, 85, 20, 40],
                         ["A1"], ["A2"], ["A3"], ["Launch 14 November, hero Calm Barrier Cream."],
                         ["A4"])
    chat(monkeypatch, tmp_path, client,
         ["Launch is 14 November, product Calm Barrier Cream", "Q2", "Q3", "Q4", "/context", "exit"],
         "--context-budget", "100")
    out = capsys.readouterr().out.splitlines()
    assert "Context: 85 / 100 tokens (85%), summarizing 2 older messages…" in out
    assert "Context: 40 / 100 tokens (40%)" in out
    assert out[-1] == "Budget 100   Last turn 40 (40%)   Summaries 1   Saved about 45 tokens"
    # The turn after the summary sends: system, summary, the last 4 messages, the new question.
    sent = [m.content for m in client.requests[4][1]]
    assert sent == ["Shared rules", SUMMARY, "Q2", "A2", "Q3", "A3", "Q4"]
    assert [m.content for m in saved_messages(tmp_path)] == [SUMMARY, "Q2", "A2", "Q3", "A3", "Q4", "A4"]


def test_default_budget_short_chat_never_summarizes(monkeypatch, tmp_path, capsys):
    client = UsageClient([300, 600], ["A1"], ["A2"])
    chat(monkeypatch, tmp_path, client, ["Q1", "Q2", "/context", "exit"])
    out = capsys.readouterr().out
    assert "summarizing" not in out and "Context:" not in out
    assert "Budget 4,096   Last turn 600 (14%)   Summaries 0   Saved about 0 tokens" in out
    assert len(client.requests) == 2


def test_budget_falls_back_to_context_length_and_env(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SENSAI_CONTEXT_LENGTH", "2048")
    chat(monkeypatch, tmp_path, UsageClient([]), ["/context", "exit"])
    monkeypatch.setenv("SENSAI_CONTEXT_BUDGET", "1500")
    chat(monkeypatch, tmp_path, UsageClient([]), ["/context", "exit"])
    out = capsys.readouterr().out.splitlines()
    assert "Budget 2,048   Last turn —   Summaries 0   Saved about 0 tokens" in out
    assert "Budget 1,500   Last turn —   Summaries 0   Saved about 0 tokens" in out


@pytest.mark.parametrize("value", ["0", "-5", "abc"])
def test_invalid_context_budget_is_rejected(monkeypatch, tmp_path, value):
    with pytest.raises(SystemExit):
        chat(monkeypatch, tmp_path, UsageClient([]), [], "--context-budget", value)


def test_missing_counts_use_character_estimate(monkeypatch, tmp_path, capsys):
    client = UsageClient([None], ["y" * 400])
    chat(monkeypatch, tmp_path, client, ["x" * 400, "/context", "exit"], "--context-budget", "10000")
    # (12 + 400 + 400) characters / 4
    assert "Budget 10,000   Last turn 203 (2%)   Summaries 0   Saved about 0 tokens" \
        in capsys.readouterr().out


@pytest.mark.parametrize("failure", [LLMError("connection refused"), KeyboardInterrupt()])
def test_failed_summary_keeps_full_history_and_chat_continues(monkeypatch, tmp_path, capsys, failure):
    class Failing(UsageClient):
        def stream(self, model, messages, cancellation=None):
            if messages[-1].content.endswith(compression.SUMMARY_REQUEST):
                raise failure
            yield from super().stream(model, messages, cancellation)

    client = Failing([30, 50, 85, 90], ["A1"], ["A2"], ["A3"], ["A4"])
    chat(monkeypatch, tmp_path, client, ["Q1", "Q2", "Q3", "Q4", "/context", "exit"],
         "--context-budget", "100")
    out = capsys.readouterr().out.splitlines()
    assert out.count("warning: summary failed, full history kept") == 2
    assert out[-1] == "Budget 100   Last turn 90 (90%)   Summaries 0   Saved about 0 tokens"
    assert [m.content for m in saved_messages(tmp_path)] == \
        ["Q1", "A1", "Q2", "A2", "Q3", "A3", "Q4", "A4"]


def test_too_few_old_messages_does_nothing(monkeypatch, tmp_path, capsys):
    client = UsageClient([95, 99], ["A1"], ["A2"])
    chat(monkeypatch, tmp_path, client, ["Q1", "Q2", "exit"], "--context-budget", "100")
    assert "summarizing" not in capsys.readouterr().out
    assert len(client.requests) == 2


def test_persona_kept_and_switchable_after_summary(monkeypatch, tmp_path, capsys):
    client = UsageClient([30, 50, 85, 20, 40], ["A1"], ["A2"], ["A3"], ["facts"], ["A4"])
    chat(monkeypatch, tmp_path, client, ["Q1", "Q2", "Q3", "/persona analyse", "Q4", "exit"],
         "--context-budget", "100", "--persona", "communaute")
    system_before = client.requests[0][1][0].content
    last = client.requests[4][1]
    assert last[0].content != system_before  # /persona still switched the role
    assert [m.content for m in last[1:6]] == [f"{compression.SUMMARY_PREFIX}\nfacts",
                                              "Q2", "A2", "Q3", "A3"]


def test_resumed_session_contains_summary(monkeypatch, tmp_path, capsys):
    client = UsageClient([30, 50, 85, 20], ["A1"], ["A2"], ["A3"], ["facts"])
    chat(monkeypatch, tmp_path, client, ["Q1", "Q2", "Q3", "exit"], "--context-budget", "100")
    resumed = UsageClient([10], ["A4"])
    chat(monkeypatch, tmp_path, resumed, ["When is the launch?", "exit"], "--session", "abcdef")
    sent = [m.content for m in resumed.requests[0][1]]
    assert sent[1:] == [f"{compression.SUMMARY_PREFIX}\nfacts", "Q2", "A2", "Q3", "A3",
                        "When is the launch?"]
