"""Web search in the terminal: the model's search, the Sources list and /search."""
import pytest

from fakes import FakeClient, scripted_terminal
from sensai import search
from sensai.cli import main as cli
from search_fakes import DUCK, Response


@pytest.fixture(autouse=True)
def isolated(isolated_settings, tmp_path):
    (tmp_path / "prompt.txt").write_text("Shared rules", encoding="utf-8")


def chat(monkeypatch, tmp_path, client, inputs):
    monkeypatch.setattr(cli, "create_client", lambda settings: client)
    monkeypatch.setattr(cli, "TerminalInput", scripted_terminal(inputs))
    cli.main(["model", "--prompt", str(tmp_path / "prompt.txt"), "--db", str(tmp_path / "s.db")])


def test_the_model_searches_and_the_answer_lists_its_sources(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(search.requests, "post", lambda *a, **k: Response(DUCK))
    client = FakeClient(['{"tool":"web_search","arguments":{"query":"skincare trends"}}'], ["Barrier care [1]."], ["Hello"])
    chat(monkeypatch, tmp_path, client, ["What is trending?", "Hi", "exit"])
    out = capsys.readouterr().out
    assert "Searching the web for: skincare trends" in out
    assert "Sources:\n[1] Skin trends https://example.com/trends" in out
    assert "[1] Skin trends\nhttps://example.com/trends" in client.calls[1][-1]


def test_slash_search_shows_results_and_errors_do_not_break_the_chat(monkeypatch, tmp_path, capsys):
    chat(monkeypatch, tmp_path, FakeClient(["ok"]), ["/search trends", "/search", "Hi", "exit"])
    out = capsys.readouterr().out
    assert "Web search unavailable: the web search failed" in out and "usage: /search <query>" in out and "ok" in out
