"""ask_user in the terminal: the model asks, the form answers, the reply continues and the answer is saved."""
import pytest

from fakes import FakeClient, scripted_terminal
from sensai.cli import main as cli
from sensai.memory.sqlite_store import StorageRepository

ASK = ('{"tool":"ask_user","arguments":{"questions":[{"type":"choice","text":"Which product?",'
       '"options":["Hydra Glow Serum","Calm Barrier Cream"]}]}}')


@pytest.fixture(autouse=True)
def isolated(isolated_settings, tmp_path):
    (tmp_path / "prompt.txt").write_text("Shared rules", encoding="utf-8")


def test_the_form_answer_goes_back_to_the_model_and_stays_in_the_session(monkeypatch, tmp_path, capsys):
    client = FakeClient([ASK], ["A caption for Calm Barrier Cream."])
    monkeypatch.setattr(cli, "create_client", lambda settings: client)
    monkeypatch.setattr(cli, "TerminalInput", scripted_terminal(["Write a launch caption", "9", "2", "/tools", "exit"]))
    cli.main(["model", "--prompt", str(tmp_path / "prompt.txt"), "--db", str(tmp_path / "s.db")])
    out = capsys.readouterr().out
    assert "Sensai needs one detail:" in out and "Please enter a number from 1 to 3." in out and '"tool"' not in out
    assert "Tool result from ask_user:\nWhich product? -> Calm Barrier Cream" in client.calls[1][-1]
    assert "ask_user:" in out
    with StorageRepository(tmp_path / "s.db") as repository:
        sessions = repository.for_creator("default").sessions
        saved = " ".join(m.content for s in sessions.list() for m in sessions.load(s.id).messages)
    assert "Which product? -> Calm Barrier Cream" in saved
