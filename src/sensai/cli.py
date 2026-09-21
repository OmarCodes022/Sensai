"""Command line interface."""
import argparse
import sys
from collections.abc import Callable, Sequence

from sensai.errors import SensaiError
from sensai.llm import create_client
from sensai.prompts import load_system_prompt
from sensai.session import ChatSession
from sensai.settings import Settings


def parse_args(settings: Settings, argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Chat with a local Ollama model.")
    p.add_argument("model", nargs="?", default=settings.model, help="model (or set SENSAI_MODEL)")
    p.add_argument("--prompt", default=settings.prompt_path, help="system prompt file")
    p.add_argument("--host", default=settings.host, help="Ollama base URL")
    args = p.parse_args(argv)
    if not args.model:
        p.error("no model given: pass one or set SENSAI_MODEL in .env")
    return args


def repl(session: ChatSession, read: Callable[[str], str] = input, write=print) -> None:
    while True:
        try:
            text = read("\n> ")
        except (EOFError, KeyboardInterrupt):
            write()
            return
        if text.strip().lower() in ("exit", "quit"):
            return
        try:
            for chunk in session.send(text):
                write(chunk, end="", flush=True)
            write()
        except ValueError:
            write("Please type something.")
        except SensaiError as e:
            write(f"error: {e}")


def main(argv: Sequence[str] | None = None) -> None:
    settings = Settings()
    args = parse_args(settings, argv)
    try:
        prompt = load_system_prompt(args.prompt)
    except OSError as e:
        sys.exit(f"error: cannot read system prompt: {e}")
    client = create_client(settings.model_copy(update={"host": args.host}))
    print(f"Chatting with {args.model}. Type 'exit' to quit.")
    repl(ChatSession(client, args.model, prompt))
