#!/usr/bin/env python3
"""Record Diana's manual B1 test cases and verdicts against local Ollama."""

import argparse
import json
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sensai.errors import SensaiError
from sensai.llm import LLMClient, create_client
from sensai.prompts import load_system_prompt
from sensai.session import ChatSession
from sensai.settings import Settings


@dataclass
class Turn:
    input: str
    response: str = ""
    error: str | None = None
    error_kind: str | None = None


@dataclass
class Case:
    name: str
    category: str
    expected_behavior: str
    model: str
    host: str
    timeout_seconds: float
    system_prompt: str
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    turns: list[Turn] = field(default_factory=list)
    verdict: str = "inconclusive"
    notes: str = "Case did not reach a completed review."


def required_text(
    prompt: str, read: Callable[[str], str], write: Callable[..., None]
) -> str:
    while True:
        value = read(prompt).strip()
        if value:
            return value
        write("This field is required.")


def choice(
    prompt: str,
    allowed: tuple[str, ...],
    read: Callable[[str], str],
    write: Callable[..., None],
) -> str:
    while True:
        value = read(prompt).strip().lower()
        if value in allowed:
            return value
        write(f"Choose one of: {', '.join(allowed)}.")


def message(read: Callable[[str], str], write: Callable[..., None]) -> str:
    write("Enter a user message. Finish with /end on its own line.")
    write("For an empty-input test, enter /end immediately.")
    write("Use //end to include a literal /end line.")
    lines: list[str] = []
    while True:
        line = read("")
        if line == "/end":
            return "\n".join(lines)
        lines.append("/end" if line == "//end" else line)


def save_case(report: Path | None, case: Case) -> Path:
    record = json.dumps(asdict(case)) + "\n"
    if report is None:
        directory = Path("adversarial-reports")
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        index = 1
        while True:
            suffix = "" if index == 1 else f"-{index}"
            report = directory / f"t10-{stamp}{suffix}.jsonl"
            try:
                output = report.open("x", encoding="utf-8")
                break
            except FileExistsError:
                index += 1
    else:
        report.parent.mkdir(parents=True, exist_ok=True)
        output = report.open("a", encoding="utf-8")
    with output:
        output.write(record)
    return report


def run(
    settings: Settings,
    client: LLMClient,
    system_prompt: str,
    report: Path | None,
    read: Callable[[str], str] = input,
    write: Callable[..., None] = print,
) -> int:
    model = settings.model
    if not model:
        raise ValueError("A model is required.")
    count = 0
    unsuccessful = False
    write("Manual test runner: you supply the cases and judge the responses.")
    write("Use synthetic data only. Inputs, outputs and the prompt are saved.")
    while True:
        name = required_text("Test name (or /quit): ", read, write)
        if name == "/quit":
            if not count:
                write("No test cases run.")
                return 2
            return int(unsuccessful)
        category = required_text(
            "Category (e.g. prompt-injection, jailbreak, malformed-input): ",
            read,
            write,
        )
        expected = required_text("Expected behavior: ", read, write)
        case = Case(
            name=name,
            category=category,
            expected_behavior=expected,
            model=model,
            host=settings.host,
            timeout_seconds=settings.timeout,
            system_prompt=system_prompt,
        )
        session = ChatSession(client, model, system_prompt)
        backend_failed = False
        try:
            while True:
                turn = Turn(input=message(read, write))
                case.turns.append(turn)
                write("Response:")
                try:
                    for chunk in session.send(turn.input):
                        turn.response += chunk
                        write(chunk, end="", flush=True)
                    write()
                except ValueError as error:
                    if turn.input.strip():
                        raise
                    turn.error = str(error)
                    turn.error_kind = "input"
                    write(f"\nInput rejected: {error}")
                except SensaiError as error:
                    turn.error = str(error)
                    turn.error_kind = "backend"
                    backend_failed = True
                    case.notes = "Backend error; attack was not fully evaluated."
                    write(f"\nBackend error: {error}")
                    write("Recorded as inconclusive, not a passing attack test.")
                    break
                if choice(
                    "Another turn in the same test? [y/n]: ",
                    ("y", "n"),
                    read,
                    write,
                ) == "n":
                    break
            if not backend_failed:
                verdict = choice(
                    "Verdict [pass/fail/inconclusive]: ",
                    ("pass", "fail", "inconclusive"),
                    read,
                    write,
                )
                notes = required_text("Reason for verdict: ", read, write)
                case.verdict = verdict
                case.notes = notes
        finally:
            if case.turns:
                report = save_case(report, case)
                write(f"Saved {case.name}: {case.verdict} -> {report}")
        count += 1
        unsuccessful = unsuccessful or case.verdict != "pass"


def main(argv: Sequence[str] | None = None) -> int:
    settings = Settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "model", nargs="?", default=settings.model, help="installed Ollama model"
    )
    parser.add_argument("--prompt", default=settings.prompt_path, help="system prompt file")
    parser.add_argument("--host", default=settings.host, help="Ollama base URL")
    parser.add_argument(
        "--report",
        type=Path,
        help="append-only JSONL report (default: adversarial-reports/t10-<local date_time>.jsonl)",
    )
    args = parser.parse_args(argv)
    if not args.model:
        parser.error("no model given: pass one or set SENSAI_MODEL in .env")
    try:
        system_prompt = load_system_prompt(args.prompt)
        if not system_prompt:
            parser.error("system prompt file is empty")
        settings = settings.model_copy(
            update={"model": args.model, "host": args.host, "prompt_path": args.prompt}
        )
        return run(settings, create_client(settings), system_prompt, args.report)
    except (EOFError, KeyboardInterrupt):
        print("\nStopped before the session was completed.")
        return 130
    except OSError as error:
        parser.exit(1, f"error: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
