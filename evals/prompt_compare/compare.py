#!/usr/bin/env python3
"""Compare two system prompt versions on the same questions with a local Ollama model."""

import argparse
import hashlib
import html
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sensai.core.errors import SensaiError
from sensai.core.messages import Message
from sensai.llm import LLMClient, OllamaClient
from sensai.llm.ollama_api import OllamaUsage
from sensai.settings import Settings

DEFAULT_QUESTIONS = Path(__file__).resolve().parent / "questions.txt"


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


def main(argv: Sequence[str] | None = None) -> int:
    settings = Settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt_a", help="first system prompt file")
    parser.add_argument("prompt_b", help="second system prompt file")
    parser.add_argument("--model", default=settings.model, help="installed Ollama model")
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS,
                        help="one question per line, # for comments")
    parser.add_argument("--host", default=settings.host, help="Ollama base URL")
    parser.add_argument("--output", type=Path,
                        help="report path (default: prompt-reports/compare-<date-time>.md)")
    args = parser.parse_args(argv)
    if not args.model:
        parser.error("no model given: pass --model or set SENSAI_MODEL in .env")
    try:
        prompts = [read_prompt(args.prompt_a), read_prompt(args.prompt_b)]
        questions = read_questions(args.questions)
    except (OSError, UnicodeDecodeError) as error:
        parser.error(str(error))
    for prompt in prompts:
        if not prompt.text:
            parser.error(f"prompt file is empty: {prompt.path}")
    if not questions:
        parser.error(f"no questions in {args.questions}")
    recorder = UsageRecorder()
    client = OllamaClient(args.host, settings.timeout, usage_sink=recorder,
                          context_length=settings.context_length)
    date = datetime.now()
    results = run_comparison(client, args.model, prompts, questions, recorder)
    output = args.output or Path("prompt-reports") / f"compare-{date:%Y%m%d-%H%M%S}.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    questions_path = args.questions.resolve()
    if questions_path.is_relative_to(Path.cwd()):
        questions_path = questions_path.relative_to(Path.cwd())
    output.write_text(render_report(args.model, args.host, str(questions_path), prompts,
                                    questions, results, date), encoding="utf-8")
    print(f"Report saved to {output}")
    return int(all(answer.error is not None for row in results for answer in row))


if __name__ == "__main__":
    raise SystemExit(main())
