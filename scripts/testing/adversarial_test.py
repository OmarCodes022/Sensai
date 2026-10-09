#!/usr/bin/env python3
"""Record Diana's manual B1 test cases and verdicts against local Ollama."""

import argparse
import html
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

from pydantic import TypeAdapter, ValidationError

from sensai.core.errors import SensaiError
from sensai.llm import LLMClient, create_client
from sensai.app.prompts import load_system_prompt
from sensai.app.session import ChatSession
from sensai.app.settings import Settings


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


class ReportError(ValueError):
    """The existing evidence cannot be rendered or safely appended to."""


_CASE_ADAPTER = TypeAdapter(Case)


def read_cases(report: Path) -> list[Case]:
    cases = []
    with report.open(encoding="utf-8") as source:
        for number, line in enumerate(source, 1):
            try:
                case = _CASE_ADAPTER.validate_json(line)
            except ValidationError as error:
                raise ReportError(f"Invalid case record in {report} at line {number}.") from error
            if case.verdict not in ("pass", "fail", "inconclusive"):
                raise ReportError(f"Invalid verdict in {report} at line {number}.")
            cases.append(case)
    return cases


def markdown_path(report: Path) -> Path:
    if report.suffix == ".jsonl":
        return report.with_suffix(".md")
    return Path(f"{report}.md")


def markdown_text(text: str) -> str:
    escaped = re.sub(r"([\\`*_{}\[\]|])", r"\\\1", html.escape(text, quote=False))
    return escaped.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")


def text_block(text: str) -> str:
    longest = max((len(match[0]) for match in re.finditer(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}text\n{text}\n{fence}"


def render_markdown(cases: Sequence[Case]) -> str:
    counts = {verdict: sum(case.verdict == verdict for case in cases)
              for verdict in ("pass", "fail", "inconclusive")}
    setups = list(dict.fromkeys(
        (case.model, case.host, case.timeout_seconds, case.system_prompt) for case in cases
    ))
    lines = [
        "# T10 adversarial test report",
        "",
        "Human-reviewed results, not an automatic security assessment or proof of coverage.",
        "Contains full test inputs, outputs and system prompts. Use synthetic data only.",
        "",
        "## Results",
        "",
        "| Total | Pass | Fail | Inconclusive |",
        "| --- | --- | --- | --- |",
        f"| {len(cases)} | {counts['pass']} | {counts['fail']} | {counts['inconclusive']} |",
        "",
        "| # | Test | Category | Verdict |",
        "| --- | --- | --- | --- |",
    ]
    for index, case in enumerate(cases, 1):
        lines.append(
            f"| {index} | {markdown_text(case.name)} | {markdown_text(case.category)} "
            f"| **{case.verdict.upper()}** |"
        )
    if not cases:
        lines.extend(["", "No test cases recorded."])
    for index, (model, host, timeout, prompt) in enumerate(setups, 1):
        lines.extend([
            "", f"## Setup {index}", "",
            f"**Model:** {markdown_text(model)}  ",
            f"**Host:** {markdown_text(host)}  ",
            f"**HTTP timeout:** {timeout:g} seconds",
            "",
            "<details>",
            "<summary>Exact system prompt</summary>",
            "",
            text_block(prompt),
            "",
            "</details>",
        ])
    for index, case in enumerate(cases, 1):
        setup = setups.index(
            (case.model, case.host, case.timeout_seconds, case.system_prompt)
        ) + 1
        lines.extend([
            "", f"## Case {index}: {markdown_text(case.name)}", "",
            f"**Verdict:** {case.verdict.upper()}  ",
            f"**Category:** {markdown_text(case.category)}  ",
            f"**Started (UTC):** {markdown_text(case.started_at)}  ",
            f"**Configuration:** [Setup {setup}](#setup-{setup})",
            "",
            "**Expected behavior**",
            "",
            markdown_text(case.expected_behavior),
            "",
            "**Reviewer's reason / notes**",
            "",
            markdown_text(case.notes),
        ])
        for turn_index, turn in enumerate(case.turns, 1):
            lines.extend([
                "", f"### Turn {turn_index}", "",
                "**Attack / user input**", "",
                text_block(turn.input) if turn.input else "(Empty input.)",
                "", "**Bot response**", "",
                text_block(turn.response) if turn.response else "(No response text.)",
            ])
            if turn.error is not None:
                label = {"input": "Input rejected", "backend": "Backend error"}.get(
                    turn.error_kind, "Recorded error"
                )
                lines.extend(["", f"**{label}**", "", text_block(turn.error)])
    return "\n".join(lines) + "\n"


def write_markdown(report: Path, cases: Sequence[Case]) -> Path:
    destination = markdown_path(report)
    content = render_markdown(cases)
    with NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=destination.parent,
        prefix=f".{destination.name}.", delete=False,
    ) as output:
        temporary = Path(output.name)
        try:
            output.write(content)
            output.close()
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
    return destination


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
    cases = read_cases(report) if report is not None and report.exists() else []
    record = json.dumps(asdict(case)) + "\n"
    if report is None:
        directory = Path("adversarial-reports")
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        index = 1
        while True:
            suffix = "" if index == 1 else f"-{index}"
            report = directory / f"t10-{stamp}{suffix}.jsonl"
            if markdown_path(report).exists():
                index += 1
                continue
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
    try:
        write_markdown(report, [*cases, case])
    except OSError as error:
        raise OSError(
            f"JSONL evidence saved to {report}, but Markdown could not be updated: {error}"
        ) from error
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
                write(
                    f"Saved {case.name}: {case.verdict} -> {markdown_path(report)} "
                    f"(raw evidence: {report})"
                )
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
    reports = parser.add_mutually_exclusive_group()
    reports.add_argument(
        "--report",
        type=Path,
        help="JSONL evidence path; also writes a Markdown companion "
        "(default: adversarial-reports/t10-<local date_time>.jsonl)",
    )
    reports.add_argument(
        "--render-report",
        type=Path,
        metavar="JSONL",
        help="render existing JSONL evidence as Markdown without calling Ollama",
    )
    args = parser.parse_args(argv)
    if args.render_report is not None:
        try:
            destination = write_markdown(args.render_report, read_cases(args.render_report))
        except (OSError, ReportError) as error:
            parser.exit(1, f"error: {error}\n")
        print(f"Markdown report saved to {destination}")
        return 0
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
    except (OSError, ReportError) as error:
        parser.exit(1, f"error: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
