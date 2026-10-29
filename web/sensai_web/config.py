"""Command line and environment settings of the web interface, with where each came from."""
import argparse
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from math import isfinite

from sensai.settings import Settings

DEFAULT_DB = "sensai.sqlite3"
# effective-config key -> (environment variable, Settings field)
KEYS = {
    "ollama_host": ("OLLAMA_HOST", "host"), "model": ("SENSAI_MODEL", "model"),
    "request_timeout": ("SENSAI_TIMEOUT", "timeout"), "turn_budget": ("SENSAI_OPERATION_TIMEOUT", "operation_timeout"),
    "context_length": ("SENSAI_CONTEXT_LENGTH", "context_length"), "database_path": ("SENSAI_DB", "db_path"),
    "creator": ("SENSAI_CREATOR", "creator"), "profile_file": ("SENSAI_PROFILE_FILE", "profile_file"),
    "data_dir": ("SENSAI_DATA_DIR", "data_dir"), "prompt_file": ("SENSAI_PROMPT", "prompt_path"),
    "personas_file": ("SENSAI_PERSONAS_FILE", "personas_file"),
    "docs_dir": ("SENSAI_DOCS", "docs_dir"), "embed_model": ("SENSAI_EMBED_MODEL", "embed_model"),
}


@dataclass(frozen=True)
class WebConfig:
    model: str
    host: str
    timeout: float
    operation_timeout: float
    context_length: int | None
    db_path: str
    creator: str
    prompt_path: str | None
    persona: str | None
    personas_file: str | None
    profile_file: str | None
    data_dir: str | None
    session: str | None
    ssh_host: str | None = None
    docs_dir: str | None = None
    embed_model: str = "nomic-embed-text"
    bind: str = "127.0.0.1"
    port: int = 8765
    effective: dict = field(default_factory=dict)


def _dotenv_names(path: str = ".env") -> set[str]:
    try:
        with open(path, encoding="utf-8") as f:
            return {line.split("=", 1)[0].strip().removeprefix("export ").strip().upper()
                    for line in f if "=" in line and not line.lstrip().startswith("#")}
    except OSError:
        return set()


def _positive(value: str) -> float:
    try:
        number = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a positive finite number") from None
    if not isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be a positive finite number")
    return number


def _port(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a port number") from None
    if not 0 <= number <= 65535:
        raise argparse.ArgumentTypeError("must be between 0 and 65535")
    return number


def parser(settings: Settings) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sensai-web", description="Sensai in the browser (local only).")
    p.add_argument("model", nargs="?", help="model (or set SENSAI_MODEL)")
    p.add_argument("--port", type=_port, default=8765, help="port to listen on (default: 8765)")
    p.add_argument("--bind", default="127.0.0.1", help="loopback address to listen on (default: 127.0.0.1)")
    p.add_argument("--host", help="Ollama base URL")
    p.add_argument("--prompt", help="system prompt file (default: the packaged prompt)")
    p.add_argument("--persona", help="persona identifier")
    p.add_argument("--personas-file", help="JSON catalogue replacing the built-in personas")
    p.add_argument("--session", help="resume a saved session by ID")
    p.add_argument("--docs", help="folder of brand documents to search (default: data/docs; empty switches it off)")
    p.add_argument("--db", help=f"SQLite session database (default: {DEFAULT_DB})")
    p.add_argument("--creator", help="creator key scoping sessions and profile (not authentication)")
    p.add_argument("--profile-file", help="JSON object replacing the stored creator profile")
    p.add_argument("--operation-timeout", type=_positive, help="maximum seconds per complete turn")
    return p


def resolve(args: argparse.Namespace, settings: Settings, env: Mapping[str, str] | None = None,
            dotenv: set[str] | None = None) -> WebConfig:
    """Merge flags over Settings (env, .env, defaults) and record the source of each value."""
    env = os.environ if env is None else env
    dotenv = _dotenv_names() if dotenv is None else dotenv
    given = {"ollama_host": args.host, "model": args.model, "turn_budget": args.operation_timeout,
             "database_path": args.db, "creator": args.creator, "profile_file": args.profile_file,
             "prompt_file": args.prompt, "personas_file": args.personas_file, "docs_dir": args.docs}
    values, effective = {}, {}
    for key, (variable, name) in KEYS.items():
        value = given.get(key)
        source = "cli" if value is not None else ("env" if variable in env else
                                                  "dotenv" if variable in dotenv else "default")
        value = getattr(settings, name) if value is None else value
        values[name] = value
        effective[key] = {"value": value, "source": source}
    effective["database_path"]["value"] = effective["database_path"]["value"] or DEFAULT_DB
    return WebConfig(
        model=values["model"], host=values["host"], timeout=values["timeout"],
        operation_timeout=values["operation_timeout"], context_length=values["context_length"],
        db_path=values["db_path"] or DEFAULT_DB, creator=values["creator"],
        prompt_path=values["prompt_path"], persona=args.persona or settings.persona,
        personas_file=values["personas_file"], profile_file=values["profile_file"],
        data_dir=values["data_dir"] or None, session=args.session, ssh_host=settings.ssh_host or None,
        docs_dir=args.docs if args.docs is not None else (values["docs_dir"] or None), embed_model=values["embed_model"],
        bind=args.bind, port=args.port, effective=effective)
