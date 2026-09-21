"""System prompt loading."""


def load_system_prompt(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read().strip()
