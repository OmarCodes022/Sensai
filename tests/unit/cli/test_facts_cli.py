"""The fact sheet in the terminal: model tool calls, Memory lines, /facts, restarts and interruptions."""
import pytest

from fakes import FakeClient, scripted_terminal
from sensai.cli import main as cli
from sensai.core.cancellation import OperationCancelled

SAVE = '{"tool":"save_fact","arguments":{"id":"hydra-glow-serum.price","text":"Costs 29 €"}}'
UPDATE = '{"tool":"save_fact","arguments":{"id":"hydra-glow-serum.price","text":"Costs 32 €"}}'


@pytest.fixture(autouse=True)
def isolated(isolated_settings, tmp_path):
    (tmp_path / "prompt.txt").write_text("Shared rules", encoding="utf-8")


def chat(monkeypatch, tmp_path, client, inputs, *argv):
    monkeypatch.setattr(cli, "create_client", lambda settings: client)
    monkeypatch.setattr(cli, "TerminalInput", scripted_terminal(inputs))
    cli.main(["model", "--prompt", str(tmp_path / "prompt.txt"), "--db", str(tmp_path / "s.db"), *argv])


def test_a_fact_is_saved_when_the_turn_completes_and_shown_by_facts(monkeypatch, tmp_path, capsys):
    chat(monkeypatch, tmp_path, FakeClient([SAVE], ["Noted."]), ["The serum costs 29 €.", "/facts", "exit"])
    out = capsys.readouterr().out
    assert "Memory: added hydra-glow-serum.price" in out
    assert "hydra-glow-serum.price  Costs 29 €  (chat " in out


def test_saved_facts_reach_the_next_session_and_corrections_update(monkeypatch, tmp_path, capsys):
    chat(monkeypatch, tmp_path, FakeClient([SAVE], ["Noted."]), ["29 €", "exit"])
    client = FakeClient([UPDATE], ["Updated."], ["32 €"])
    chat(monkeypatch, tmp_path, client, ["Now 32 €", "Price?", "exit"])
    assert "- hydra-glow-serum.price: Costs 29 €" in client.calls[0][0]
    assert "Memory: updated hydra-glow-serum.price" in capsys.readouterr().out
    assert "- hydra-glow-serum.price: Costs 32 €" in client.calls[2][0]  # The system message follows the change.


def test_an_interrupted_turn_changes_nothing(monkeypatch, tmp_path, capsys):
    client = FakeClient([SAVE], ["partial", OperationCancelled("operation cancelled")])
    chat(monkeypatch, tmp_path, client, ["29 €", "/facts", "exit"])
    out = capsys.readouterr().out
    assert "Memory:" not in out and "No saved facts yet" in out


def test_another_creator_sees_no_facts_and_tools_lists_them(monkeypatch, tmp_path, capsys):
    chat(monkeypatch, tmp_path, FakeClient([SAVE], ["Noted."]), ["29 €", "exit"])
    capsys.readouterr()
    chat(monkeypatch, tmp_path, FakeClient(), ["/facts", "/tools", "exit"], "--creator", "other")
    out = capsys.readouterr().out
    assert "No saved facts yet" in out and "save_fact:" in out and "delete_fact:" in out
