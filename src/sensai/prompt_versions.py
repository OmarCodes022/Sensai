"""A4: system prompts as dated versions, and the comparison of two of them on the same questions.

A version is a file named YYYY-MM-DD-<short-name>.txt; it is never edited, a change is a new file.
Starting Sensai with an older file (`--prompt`, or "Use this version" in the page) rolls back.
"""
import hashlib
import html
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sensai.core.errors import SensaiError
from sensai.core.messages import Message
from sensai.llm import LLMClient
from sensai.llm.ollama_api import OllamaUsage

VERSION_NAME = re.compile(r"\d{4}-\d{2}-\d{2}-[a-z0-9-]+\.txt\Z")


@dataclass
class Prompt:
    path: str
    text: str
    sha256: str
    lines: int


@dataclass
class Answer:
    text: str = ""
    usage: OllamaUsage | None = None
    error: str | None = None


class UsageRecorder:
    """Usage sink keeping the report of the most recent request."""

    def __init__(self) -> None:
        self.last: OllamaUsage | None = None

    def __call__(self, usage: OllamaUsage) -> None:
        self.last = usage

    def take(self) -> OllamaUsage | None:
        usage, self.last = self.last, None
        return usage


def read_prompt(path: str) -> Prompt:
    raw = Path(path).read_bytes()
    text = raw.decode("utf-8")
    # Same text `sensai --prompt` sends: surrounding whitespace removed.
    return Prompt(path, text.strip(), hashlib.sha256(raw).hexdigest()[:12],
                  len(text.splitlines()))


def read_questions(path: Path) -> list[str]:
    lines = (line.strip() for line in path.read_text(encoding="utf-8").splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def run_comparison(client: LLMClient, model: str, prompts: Sequence[Prompt],
                   questions: Sequence[str],
                   recorder: UsageRecorder | None = None) -> list[list[Answer]]:
    results = []
    for question in questions:
        row = []
        for prompt in prompts:
            messages = [Message(role="system", content=prompt.text),
                        Message(role="user", content=question)]
            answer = Answer()
            if recorder is not None:
                recorder.take()
            try:
                for chunk in client.stream(model, messages):
                    answer.text += chunk
            except SensaiError as error:
                answer.error = str(error) or type(error).__name__
            if recorder is not None:
                answer.usage = recorder.take()
            row.append(answer)
        results.append(row)
    return results


def markdown_text(text: str) -> str:
    escaped = re.sub(r"([\\`*_{}\[\]|])", r"\\\1", html.escape(text, quote=False))
    return escaped.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")


def text_block(text: str) -> str:
    longest = max((len(match[0]) for match in re.finditer(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}text\n{text}\n{fence}"


def _number(value: int | float | None, unit: str = "") -> str:
    return "n/a" if value is None else f"{value:.0f}{unit}"


def render_report(model: str, host: str, questions_path: str, prompts: Sequence[Prompt],
                  questions: Sequence[str], results: Sequence[Sequence[Answer]],
                  date: datetime) -> str:
    labels = [chr(ord("A") + index) for index in range(len(prompts))]
    lines = [
        "# Prompt comparison report", "",
        "Model answers can vary between runs; compare several runs before concluding.", "",
        f"**Date:** {date.isoformat(timespec='seconds')}  ",
        f"**Model:** {markdown_text(model)}  ",
        f"**Host:** {markdown_text(host)}  ",
        f"**Questions:** {markdown_text(questions_path)} ({len(questions)})", "",
        "| Prompt | File | sha256 | Lines |", "| --- | --- | --- | --- |",
    ]
    for label, prompt in zip(labels, prompts):
        lines.append(f"| {label} | {markdown_text(prompt.path)} | {prompt.sha256} "
                     f"| {prompt.lines} |")
    lines.extend(["", "## Summary", "",
                  "| Prompt | Answered | Failed | Avg latency | Prompt tokens | Output tokens |",
                  "| --- | --- | --- | --- | --- | --- |"])
    for index, label in enumerate(labels):
        answers = [row[index] for row in results]
        ok = [answer for answer in answers if answer.error is None]
        latencies = [a.usage.latency_ms for a in ok if a.usage is not None]
        prompt_tokens = sum(a.usage.prompt_tokens or 0 for a in ok if a.usage is not None)
        output_tokens = sum(a.usage.output_tokens or 0 for a in ok if a.usage is not None)
        average = sum(latencies) / len(latencies) if latencies else None
        lines.append(f"| {label} | {len(ok)} | {len(answers) - len(ok)} "
                     f"| {_number(average, ' ms')} | {prompt_tokens} | {output_tokens} |")
    for number, (question, row) in enumerate(zip(questions, results), 1):
        lines.extend(["", f"## Question {number}", "", text_block(question)])
        for label, answer in zip(labels, row):
            usage = answer.usage
            lines.extend([
                "", f"### Prompt {label}", "",
                f"Latency: {_number(usage and usage.latency_ms, ' ms')}, "
                f"prompt tokens: {_number(usage and usage.prompt_tokens)}, "
                f"output tokens: {_number(usage and usage.output_tokens)}", "",
                text_block(answer.text) if answer.text else "(No answer text.)",
            ])
            if answer.error is not None:
                lines.extend(["", "**Error**", "", text_block(answer.error)])
    return "\n".join(lines) + "\n"


def versions(folder: str) -> list[Prompt]:
    """The dated versions of a folder, oldest first (the name starts with the date)."""
    path = Path(folder)
    if not path.is_dir():
        return []
    return [read_prompt(str(p)) for p in sorted(path.iterdir()) if VERSION_NAME.match(p.name)]
