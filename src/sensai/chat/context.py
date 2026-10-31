"""The context budget (M2): how full the model's window is, and when to summarize older messages.

The window is the number the creator set (SENSAI_CONTEXT_LENGTH / --context-budget), else the
one Ollama chose for this computer (GET /api/ps), doubled when it is 4096 or less: Sensai's own
instructions take about 2,000 tokens. Either is sent as num_ctx on every request. Without an
answer from Ollama, 4096 until it reports one.
"""
import requests

from sensai.chat import compression

DEFAULT_WINDOW = 4096
SMALL_WINDOW = 4096  # Ollama's usual choice: too small for Sensai's instructions, so it is doubled.


def loaded_window(host: str, model: str, get=None) -> int | None:
    """The context length of `model` as Ollama loaded it, or None (not loaded yet, remote, or no answer)."""
    get = get or requests.get
    try:
        models = get(f"{host.rstrip('/')}/api/ps", timeout=2).json().get("models", [])
    except (requests.RequestException, ValueError, AttributeError):
        return None
    names = {model, f"{model}:latest"}
    for entry in models:
        if isinstance(entry, dict) and (entry.get("name") in names or entry.get("model") in names):
            length = entry.get("context_length")
            return length if isinstance(length, int) and length > 0 else None
    return None


def ollama_window(host: str, model: str, get=None, post=None) -> int | None:
    """The window Ollama chose for `model` on this computer; loads the model once, without num_ctx, if needed."""
    window = loaded_window(host, model, get)
    if window is None:
        try:
            (post or requests.post)(f"{host.rstrip('/')}/api/generate",
                                    json={"model": model, "prompt": "", "stream": False}, timeout=120)
        except requests.RequestException:
            return None
        window = loaded_window(host, model, get)
    return window


def choose_window(chosen: int | None) -> tuple[int | None, str]:
    """Follow Ollama's choice, doubled when it is 4096 or less; (None, "default") without one."""
    if chosen is None:
        return None, "default"
    return (chosen * 2, "doubled") if chosen <= SMALL_WINDOW else (chosen, "ollama")


class ContextState:
    """Token budget, the last turn's count and what summaries saved."""

    def __init__(self, budget: int | None = None, source: str | None = None):
        self.budget = budget or DEFAULT_WINDOW
        # set by the creator, ollama's choice (maybe doubled), or the default until Ollama reports one
        self.source = source or ("set" if budget else "default")
        self.restart()

    def restart(self) -> None:
        """A new conversation: the counters start again, the window is kept."""
        self.reported: int | None = None
        self.last_tokens: int | None = None
        self.summaries = 0
        self.saved = 0
        self.before_summary: int | None = None
        self.after_summary = False

    def learn(self, probe) -> None:
        """Take Ollama's real window once it is known, when nothing was chosen at start."""
        if self.source == "default":
            window = probe()
            if window:
                self.budget, self.source = window, "ollama"

    def on_usage(self, usage) -> None:
        # Called once per request; the last request of a turn holds the whole history.
        if usage.prompt_tokens is not None and usage.output_tokens is not None:
            self.reported = usage.prompt_tokens + usage.output_tokens

    def start_turn(self) -> None:
        self.reported = None

    def end_turn(self, messages) -> int:
        """Real count if Ollama reported one this turn, else characters / 4."""
        tokens = self.reported if self.reported is not None else compression.estimate_tokens(messages)
        self.last_tokens = tokens
        self.after_summary = self.before_summary is not None
        if self.before_summary is not None:
            self.saved += max(self.before_summary - tokens, 0)
            self.before_summary = None
        return tokens

    def line(self, tokens: int) -> str:
        return f"Context: {tokens:,} / {self.budget:,} tokens ({tokens * 100 // self.budget}%)"

    def report(self) -> str:
        last = "n/a" if self.last_tokens is None else f"{self.last_tokens:,} ({self.last_tokens * 100 // self.budget}%)"
        source = f"ollama {self.budget // 2:,} doubled" if self.source == "doubled" else self.source
        return (f"Window {self.budget:,} ({source})   Last turn {last}   "
                f"Summaries {self.summaries}   Saved about {self.saved:,} tokens")

    def as_dict(self) -> dict:
        return {"budget": self.budget, "source": self.source, "last_tokens": self.last_tokens,
                "summaries": self.summaries, "saved": self.saved, "threshold": compression.THRESHOLD}


def summary_cap(budget: int) -> int:
    """At most a quarter of the window for the summary's own answer."""
    return max(64, budget // 4)
