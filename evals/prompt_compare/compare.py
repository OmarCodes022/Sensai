#!/usr/bin/env python3
"""Compare two system prompt versions on the same questions with a local Ollama model."""

import argparse
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from sensai.llm import OllamaClient
from sensai.prompt_versions import (Answer, Prompt, UsageRecorder, markdown_text, read_prompt,  # noqa: F401
                                    read_questions, render_report, run_comparison, text_block)
from sensai.settings import Settings

DEFAULT_QUESTIONS = Path(__file__).resolve().parent / "questions.txt"


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
