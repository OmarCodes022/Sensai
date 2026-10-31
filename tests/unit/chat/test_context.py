"""chat.context: the window Ollama loaded, the creator's number, and the summary cap."""

import requests

from sensai.chat.context import DEFAULT_WINDOW, ContextState, loaded_window, summary_cap


class Reply:
    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


def ps(*models):
    return lambda url, timeout: Reply({"models": list(models)})


def test_loaded_window_matches_name_or_latest_tag():
    get = ps({"name": "other", "context_length": 1}, {"name": "qwen2.5:latest", "context_length": 32768})
    assert loaded_window("http://h/", "qwen2.5", get) == 32768
    assert loaded_window("http://h", "qwen2.5:latest", ps({"model": "qwen2.5:latest", "context_length": 8})) == 8


def test_loaded_window_is_none_when_unknown():
    def down(url, timeout):
        raise requests.ConnectionError("refused")
    assert loaded_window("http://h", "m", down) is None
    assert loaded_window("http://h", "m", ps()) is None
    assert loaded_window("http://h", "m", ps({"name": "m", "context_length": "big"})) is None


def test_learn_takes_ollama_window_but_never_overrides_the_creator():
    state = ContextState()
    assert (state.budget, state.source) == (DEFAULT_WINDOW, "default")
    state.learn(lambda: None)
    assert state.source == "default"
    state.learn(lambda: 32768)
    assert (state.budget, state.source) == (32768, "ollama")
    fixed = ContextState(1500)
    fixed.learn(lambda: 32768)
    assert (fixed.budget, fixed.source) == (1500, "set")


def test_summary_cap_is_a_quarter_with_a_floor():
    assert summary_cap(4096) == 1024
    assert summary_cap(100) == 64
