"""File access in the terminal: /read, /save, the model's file tools, and access off without settings."""
import pytest

from fakes import FakeClient, scripted_terminal
from sensai.cli import main as cli

SETTINGS = ('{"permissions": {"allow": ["Read(./notes/**)", "Create(./drafts/**)", "Write(./drafts/**)"],'
            ' "deny": ["Read(./notes/private/**)"]}}')


@pytest.fixture
def project(isolated_settings, tmp_path, monkeypatch):
    root = tmp_path.resolve()
    for d in ("notes/private", "drafts", ".sensai"):
        (root / d).mkdir(parents=True)
    (root / "notes" / "launch.md").write_text("Launch on 21 November", encoding="utf-8")
    (root / "secret.txt").write_text("secret", encoding="utf-8")
    (root / ".sensai" / "settings.json").write_text(SETTINGS)
    (root / "prompt.txt").write_text("Shared rules", encoding="utf-8")
    monkeypatch.chdir(root)
    return root


def chat(monkeypatch, root, client, inputs):
    monkeypatch.setattr(cli, "create_client", lambda settings: client)
    monkeypatch.setattr(cli, "TerminalInput", scripted_terminal(inputs))
    cli.main(["model", "--prompt", str(root / "prompt.txt"), "--db", str(root / "s.db")])


def test_read_attaches_the_file_to_the_next_message_and_save_writes_the_reply(monkeypatch, project, capsys):
    client = FakeClient(["The launch is on 21 November."])
    chat(monkeypatch, project, client, ["/read notes/launch.md", "When is the launch?", "/save drafts/answer.md",
                                        "/save drafts/answer.md", "exit"])
    out = capsys.readouterr().out
    assert "File access on: 3 allow rules, 1 deny rule (.sensai/settings.json)" in out
    assert "Read 21 characters from notes/launch.md" in out
    assert client.calls[0][-1] == "File notes/launch.md:\nLaunch on 21 November\n\nWhen is the launch?"
    assert "Created drafts/answer.md" in out and "Replaced drafts/answer.md" in out
    assert (project / "drafts" / "answer.md").read_text() == "The launch is on 21 November.\n"


def test_refused_paths_print_permission_denied_and_change_nothing(monkeypatch, project, capsys):
    chat(monkeypatch, project, FakeClient(["ok"]), ["/read secret.txt", "/read notes/../secret.txt", "/read /etc/hosts",
                                                     "Hi", "/save notes/x.md", "exit"])
    out = capsys.readouterr().out
    assert out.count("Permission denied") == 4 and "secret" not in out.replace("secret.txt", "")
    assert not (project / "notes" / "x.md").exists()


def test_the_model_reads_a_file_on_its_own(monkeypatch, project, capsys):
    call = '{"tool":"read_file","arguments":{"path":"notes/launch.md"}}'
    client = FakeClient([call], ["21 November."])
    chat(monkeypatch, project, client, ["When is the launch?", "/tools", "exit"])
    assert "Tool result from read_file:\nLaunch on 21 November" in client.calls[1][-1]
    out = capsys.readouterr().out
    assert "read_file:" in out and "create_file:" in out


def test_without_settings_file_access_is_off(monkeypatch, project, capsys):
    (project / ".sensai" / "settings.json").unlink()
    chat(monkeypatch, project, FakeClient(), ["/read notes/launch.md", "exit"])
    assert "File access is off (no .sensai/settings.json)." in capsys.readouterr().out


def test_a_broken_settings_file_stops_at_startup(monkeypatch, project):
    (project / ".sensai" / "settings.json").write_text('{"permissions": {"allow": ["Delete(./x)"]}}')
    with pytest.raises(SystemExit, match="cannot use .sensai/settings.json"):
        chat(monkeypatch, project, FakeClient(), ["exit"])
