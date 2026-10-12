"""Command line interface."""
import argparse
import sys
from math import isfinite
from time import monotonic
from collections.abc import Callable, Sequence

from sensai.core.errors import SensaiError
from sensai.core.cancellation import CancellationToken, OperationCancelled, OperationTimedOut
from sensai.app.terminal import TerminalInput
from sensai.llm import create_client
from sensai.app.prompts import load_system_prompt
from sensai.app.personas import PersonaRegistry
from sensai.app.session import ChatSession
from sensai.app.settings import Settings


def parse_args(settings: Settings, argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Chat with a local Ollama model.")
    p.add_argument("model", nargs="?", default=settings.model, help="model (or set SENSAI_MODEL)")
    p.add_argument("--prompt", default=settings.prompt_path, help="system prompt file")
    p.add_argument("--persona", default=settings.persona, help="persona identifier")
    p.add_argument("--personas-file", default=settings.personas_file,
                   help="JSON catalogue replacing the built-in personas")
    p.add_argument("--list-personas", action="store_true", help="list personas and exit")
    p.add_argument("--host", default=settings.host, help="Ollama base URL")
    def positive_timeout(value):
        try:
            number = float(value)
        except ValueError:
            raise argparse.ArgumentTypeError("timeout must be a positive finite number") from None
        if not isfinite(number) or number <= 0:
            raise argparse.ArgumentTypeError("timeout must be a positive finite number")
        return number
    p.add_argument("--operation-timeout", type=positive_timeout,
                   default=settings.operation_timeout, help="maximum seconds per complete turn")
    args = p.parse_args(argv)
    if not args.model and not args.list_personas:
        p.error("no model given: pass one or set SENSAI_MODEL in .env")
    return args


def repl(session: ChatSession, read: Callable[[str], str] = input, write=print,
         operation_timeout: float = 120.0, cancel_requested=None) -> None:
    while True:
        try:
            text = read("\n> ")
        except EOFError:
            write()
            return
        except KeyboardInterrupt:
            write()
            continue
        if text.strip().lower() in ("exit", "quit"):
            return
        token = CancellationToken(monotonic() + operation_timeout, cancel_requested)
        stream = session.send(text, token)
        try:
            for chunk in stream:
                write(chunk, end="", flush=True)
            write()
        except (KeyboardInterrupt, OperationCancelled):
            token.cancel()
            write("\nRéponse interrompue")
        except OperationTimedOut:
            write("\nDélai maximal dépassé")
        except ValueError:
            write("Please type something.")
        except SensaiError as e:
            write(f"error: {e}")
        finally:
            stream.close()


def main(argv: Sequence[str] | None = None) -> None:
    settings = Settings()
    args = parse_args(settings, argv)
    try:
        registry = PersonaRegistry.from_file(args.personas_file)
    except (OSError, ValueError) as e:
        sys.exit(f"error: cannot load personas: {e}")
    if args.list_personas:
        for persona_id, name in registry.options:
            print(f"{persona_id}: {name}")
        return
    persona = registry.get(args.persona) if args.persona is not None else None
    if args.persona is not None and persona is None:
        sys.exit(f"error: unknown persona: {args.persona}")
    try:
        prompt = load_system_prompt(args.prompt)
    except OSError as e:
        sys.exit(f"error: cannot read system prompt: {e}")
    if persona is not None:
        prompt = f"{prompt}\n\n{persona.system_prompt}"
    client = create_client(settings.model_copy(update={"host": args.host}))
    print(f"Chatting with {args.model}. Type 'exit' to quit.")
    with TerminalInput() as terminal:
        repl(ChatSession(client, args.model, prompt), read=terminal.read,
             operation_timeout=args.operation_timeout,
             cancel_requested=terminal.cancel_requested)
