"""System prompt loading."""
from importlib.resources import files


def load_system_prompt(path: str | None = None) -> str:
    """Read a prompt file, or the packaged default prompt when `path` is None or empty."""
    if not path:
        return files("sensai.chat").joinpath("system_prompt.txt").read_text(encoding="utf-8").strip()
    with open(path, encoding="utf-8") as f:
        return f.read().strip()
