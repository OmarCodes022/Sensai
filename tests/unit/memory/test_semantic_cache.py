"""A6: the semantic cache matches close questions in the same scope, and an embedding error only turns it off."""
import pytest

from sensai.core.errors import LLMConnectionError
from sensai.memory.semantic_cache import SemanticCache, scope

WORDS = ("serum", "cream", "hydrate", "redness", "price")


def embed(text):
    """A bag of known words: questions sharing them point the same way."""
    low = text.lower()
    return tuple(float(word in low) + 0.01 for word in WORDS)


@pytest.fixture
def cache(tmp_path):
    return SemanticCache(str(tmp_path / "cache.sqlite3"), embed, threshold=0.9)


def test_a_reworded_question_in_the_same_scope_is_a_hit(cache):
    here = scope("default", "qwen2.5", "system prompt")
    cache.store(here, "What does the serum do to hydrate?", "It hydrates for up to 8 hours.")
    hit = cache.lookup(here, "How does the serum hydrate my skin?")
    assert hit.answer == "It hydrates for up to 8 hours." and hit.similarity > 0.99
    assert hit.label().startswith('from cache · 100% similar to "What does the serum do to hydrate?"')
    assert cache.lookup(here, "What is the price of the cream?") is None


def test_another_model_persona_or_creator_is_a_miss(cache):
    cache.store(scope("default", "qwen2.5", "rules + redaction"), "serum hydrate?", "Yes.")
    for other in (scope("default", "gemma3:1b", "rules + redaction"), scope("default", "qwen2.5", "rules + analyse"),
                  scope("amy", "qwen2.5", "rules + redaction")):
        assert cache.lookup(other, "serum hydrate?") is None


def test_an_embedding_error_turns_the_cache_off(tmp_path):
    def down(text):
        raise LLMConnectionError("cannot reach Ollama")
    broken = SemanticCache(str(tmp_path / "c.sqlite3"), down)
    assert broken.lookup("s", "q") is None and "cache is off" in broken.off
    broken.store("s", "q", "a")  # Silently skipped.


def test_clear_removes_every_answer(cache):
    cache.store("s", "serum", "a")
    cache.store("s", "cream", "b")
    assert cache.clear() == 2 and cache.lookup("s", "serum") is None


def test_an_empty_answer_is_never_stored(cache):
    cache.store("s", "serum", "  ")
    assert cache.lookup("s", "serum") is None
