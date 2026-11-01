"""A6 in the terminal: the first question of a session may be served from the cache, follow-ups never."""
from fakes import FakeClient
from sensai.chat.session import ChatSession
from sensai.cli import main as cli
from sensai.cli.main import repl
from sensai.core.errors import LLMError
from sensai.memory.semantic_cache import SemanticCache


def embed(text):
    low = text.lower()
    return tuple(float(word in low) + 0.01 for word in ("serum", "cream", "hydrate", "price"))


def chat(cache, client, inputs, prompt="Shared rules"):
    session = ChatSession(client, "m", prompt)
    feed, out = iter([*inputs, "exit"]), []
    repl(session, read=lambda _: next(feed), write=lambda text="", **_: out.append(text),
         cache=cache, cache_scope=lambda: f"m|{session.messages[0].content}")
    return session, "\n".join(out)


def test_a_new_session_with_a_similar_first_question_skips_the_model(tmp_path):
    cache = SemanticCache(str(tmp_path / "c.db"), embed)
    chat(cache, FakeClient(["It hydrates for up to 8 hours."]), ["Does the serum hydrate?"])
    client = FakeClient()
    session, out = chat(cache, client, ["How does the serum hydrate skin?"])
    assert client.requests == [] and "It hydrates for up to 8 hours." in out and "from cache" in out
    assert [m.content for m in session.messages[1:]] == ["How does the serum hydrate skin?", "It hydrates for up to 8 hours."]


def test_follow_ups_and_other_scopes_go_to_the_model(tmp_path):
    cache = SemanticCache(str(tmp_path / "c.db"), embed)
    chat(cache, FakeClient(["Cached."]), ["Does the serum hydrate?"])
    client = FakeClient(["About the cream."], ["Fresh."])
    _, out = chat(cache, client, ["The cream price?", "Does the serum hydrate?"])  # Second message: never cached.
    assert "from cache" not in out and len(client.requests) == 2
    other = FakeClient(["Other persona."])
    chat(cache, other, ["Does the serum hydrate?"], prompt="Shared rules + analyse")
    assert len(other.requests) == 1


def test_a_failed_reply_is_not_cached(tmp_path):
    cache = SemanticCache(str(tmp_path / "c.db"), embed)
    chat(cache, FakeClient(LLMError("connection refused")), ["Does the serum hydrate?"])
    client = FakeClient(["Now it works."])
    chat(cache, client, ["Does the serum hydrate?"])
    assert len(client.requests) == 1


def test_an_embedding_error_warns_once_and_the_chat_works(tmp_path):
    def down(text):
        raise LLMError("model not found")
    _, out = chat(SemanticCache(str(tmp_path / "c.db"), down), FakeClient(["Hi."], ["Again."]), ["hello", "again"])
    assert out.count("warning: the cache is off for this session (model not found)") == 1 and "Hi." in out


def test_clear_cache_empties_it_without_a_model(tmp_path, monkeypatch, capsys):
    path = tmp_path / "c.db"
    SemanticCache(str(path), embed).store("s", "serum", "a")
    monkeypatch.setenv("SENSAI_CACHE_FILE", str(path))
    cli.main(["--clear-cache"])
    assert "Cache cleared: 1 answer removed" in capsys.readouterr().out
