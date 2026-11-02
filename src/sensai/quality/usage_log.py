"""EV3: one JSON line per model call in a local log, and the statistics `sensai --stats` and the web Insights page show.

A line holds the time, the kind (chat, title or summary), the model, the persona, the question, the
answer, the latency, the token counts, the tools used (name, input, duration, success) and the error
or "cancelled". The log keeps conversations in plain text, like the session database: it is git-ignored.
"""
import json
import os
import threading
from collections import defaultdict
from datetime import datetime, timezone

DEFAULT_PATH = "sensai-log.jsonl"
_lock = threading.Lock()
_path: str | None = None  # None: logging is off (unit tests, or SENSAI_LOG set to empty).


def configure(path: str | None) -> None:
    global _path
    _path = path or None


def record(kind: str, model: str, question: str, answer: str = "", *, persona: str | None = None,
           latency_ms: float | None = None, prompt_tokens: int | None = None, output_tokens: int | None = None,
           tools: list[dict] | None = None, error: str | None = None) -> None:
    """Append one line; a log that cannot be written never stops Sensai."""
    if _path is None:
        return
    line = {"time": datetime.now(timezone.utc).isoformat(timespec="seconds"), "kind": kind, "model": model,
            "persona": persona, "question": question, "answer": answer,
            "latency_ms": round(latency_ms) if latency_ms is not None else None,
            "prompt_tokens": prompt_tokens, "output_tokens": output_tokens, "tools": tools or [], "error": error}
    try:
        with _lock, open(_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    except OSError:
        pass


class Meter:
    """Usage sink for one turn: adds up the token counts and latency of its requests."""

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self.prompt_tokens = self.output_tokens = None
        self.latency_ms = 0.0

    def add(self, usage) -> None:
        self.latency_ms += usage.latency_ms
        if usage.prompt_tokens is not None:
            self.prompt_tokens = usage.prompt_tokens  # The last request holds the whole conversation.
        if usage.output_tokens is not None:
            self.output_tokens = (self.output_tokens or 0) + usage.output_tokens


def read(path: str) -> list[dict]:
    if not os.path.isfile(path):
        return []
    lines = []
    with open(path, encoding="utf-8") as f:
        for raw in f:
            try:
                line = json.loads(raw)
            except ValueError:
                continue  # A line cut by a crash is skipped, not fatal.
            if isinstance(line, dict):
                lines.append(line)
    return lines


def _mean(values) -> float | None:
    values = [v for v in values if isinstance(v, (int, float))]
    return round(sum(values) / len(values)) if values else None


def stats(lines: list[dict]) -> dict:
    """Totals, per kind, per tool and per day (by the line's UTC date)."""
    refused = lambda line: str(line.get("error") or "").startswith("blocked")  # noqa: E731  (the guardrails' refusal)
    failed = lambda line: bool(line.get("error")) and line.get("error") != "cancelled" and not refused(line)  # noqa: E731
    tools = defaultdict(lambda: {"calls": 0, "failed": 0})
    days = defaultdict(list)
    for line in lines:
        days[str(line.get("time", ""))[:10]].append(line)
        for tool in line.get("tools") or []:
            if isinstance(tool, dict) and tool.get("tool"):
                tools[tool["tool"]]["calls"] += 1
                tools[tool["tool"]]["failed"] += tool.get("ok") is False
    errors = sum(failed(line) for line in lines)
    return {
        "calls": len(lines), "errors": errors, "cancelled": sum(line.get("error") == "cancelled" for line in lines),
        "blocked": sum(refused(line) for line in lines),
        "error_rate": round(100 * errors / len(lines)) if lines else None,
        "avg_latency_ms": _mean(line.get("latency_ms") for line in lines),
        "prompt_tokens": sum(line.get("prompt_tokens") or 0 for line in lines),
        "output_tokens": sum(line.get("output_tokens") or 0 for line in lines),
        "kinds": {kind: sum(line.get("kind") == kind for line in lines) for kind in sorted({line.get("kind") for line in lines} - {None})},
        "tools": dict(sorted(tools.items())),
        "days": [{"day": day, "calls": len(group), "avg_latency_ms": _mean(line.get("latency_ms") for line in group),
                  "errors": sum(failed(line) for line in group)} for day, group in sorted(days.items())],
    }


def report(s: dict) -> str:
    """The text of `sensai --stats`."""
    if not s["calls"]:
        return "No data yet: the log is empty. Chat with Sensai, then run --stats again."
    seconds = lambda ms: "n/a" if ms is None else f"{ms / 1000:.1f} s"  # noqa: E731
    lines = [f"Calls: {s['calls']}   Errors: {s['errors']} ({s['error_rate']}%)   Cancelled: {s['cancelled']}   "
             f"Blocked: {s['blocked']}   "
             f"Avg latency: {seconds(s['avg_latency_ms'])}   Tokens: {s['prompt_tokens']:,} in / {s['output_tokens']:,} out",
             "Kinds: " + ", ".join(f"{kind} {n}" for kind, n in s["kinds"].items())]
    lines.append("Tools: " + (", ".join(f"{name} {t['calls']} call{'s' * (t['calls'] != 1)}, {t['failed']} failed"
                                        for name, t in s["tools"].items()) or "none used"))
    lines += ["", f"{'Day':<12}{'Calls':>6}{'Avg latency':>13}{'Errors':>8}"]
    lines += [f"{d['day']:<12}{d['calls']:>6}{seconds(d['avg_latency_ms']):>13}{d['errors']:>8}" for d in s["days"]]
    return "\n".join(lines)
