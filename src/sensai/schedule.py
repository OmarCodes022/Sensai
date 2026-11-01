"""Scheduling (X5): recurring requests from a JSON file, each answer saved as a dated draft; nothing is sent.

    python -m sensai.schedule schedule.local.json

Each task runs when the scheduler starts, then every `every_minutes`. A run is one chat request
with the shared prompt, the brand's products and approved claims, and the task's persona, under the usual time limit; the reply goes through
the guardrails' check before it is saved in drafts/. A failed run is reported and retried at the
next interval.
"""
import json
import os
import re
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from threading import Event, Lock

from sensai.core.cancellation import CancellationToken
from sensai.core.errors import SensaiError

NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,39}\Z")
DEFAULT_DRAFTS = "drafts"
TICK_SECONDS = 30


@dataclass(frozen=True)
class Task:
    name: str
    prompt: str
    every_minutes: int
    persona: str | None = None


def load_tasks(path: str, personas) -> list[Task]:
    """The tasks, checked before anything runs; ValueError with a clear message otherwise."""
    try:
        with open(path, encoding="utf-8") as f:
            items = json.load(f)
    except OSError as exc:
        raise ValueError(f"cannot read {path}: {exc.strerror or exc}") from None
    except ValueError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from None
    if not isinstance(items, list) or not items:
        raise ValueError(f"{path} must be a non-empty JSON list of tasks")
    tasks, names = [], set()
    for n, item in enumerate(items, 1):
        if not isinstance(item, dict):
            raise ValueError(f"task {n} must be an object")
        name, prompt, every, persona = item.get("name"), item.get("prompt"), item.get("every_minutes"), item.get("persona")
        if not isinstance(name, str) or not NAME.match(name) or name in names:
            raise ValueError(f"task {n}: name must be unique, lowercase letters, digits and dashes")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError(f"task {name}: prompt must not be empty")
        if isinstance(every, bool) or not isinstance(every, int) or every < 1:
            raise ValueError(f"task {name}: every_minutes must be a whole number of minutes, at least 1")
        if persona is not None and personas.get(persona) is None:
            raise ValueError(f"task {name}: unknown persona {persona!r}")
        names.add(name)
        tasks.append(Task(name, prompt.strip(), every, persona))
    return tasks


def write_draft(folder: str, task: Task, model: str, text: str, when: datetime) -> str:
    """drafts/<date>-<time>-<task>.md with a short header; written atomically."""
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, f"{when:%Y-%m-%d-%H%M}-{task.name}.md")
    header = f"# {task.name}\n\nTask: {task.name} · persona: {task.persona or 'none'} · model: {model} · {when:%Y-%m-%d %H:%M}\n" \
             "Draft for your review. Nothing was posted or sent.\n\n"
    fd, temporary = tempfile.mkstemp(dir=folder, prefix=".draft-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(header + text.strip() + "\n")
        os.replace(temporary, target)
    except BaseException:
        try:
            os.remove(temporary)
        except OSError:
            pass
        raise
    return target


class Scheduler:
    """Runs due tasks; `run(task) -> text` does the model call. Thread-safe status for the web page."""

    def __init__(self, tasks: list[Task], run, model: str, drafts: str = DEFAULT_DRAFTS, clock=time.monotonic,
                 now=datetime.now, write=print):
        self.tasks, self._run, self.model, self.drafts = tasks, run, model, drafts
        self._clock, self._now, self._write = clock, now, write
        self._next = {t.name: clock() for t in tasks}  # Every task runs at start.
        self._lock = Lock()
        self.last: dict[str, dict] = {}

    def run_one(self, task: Task) -> dict:
        when = self._now()
        try:
            path = write_draft(self.drafts, task, self.model, self._run(task), when)
            result = {"ok": True, "draft": path, "at": when.isoformat(timespec="minutes")}
            self._write(f"[{when:%H:%M}] {task.name} -> {path}")
        except (SensaiError, OSError, ValueError) as exc:
            result = {"ok": False, "error": str(exc) or type(exc).__name__, "at": when.isoformat(timespec="minutes")}
            self._write(f"[{when:%H:%M}] {task.name} failed: {result['error']} (will retry in {task.every_minutes} min)")
        with self._lock:
            self.last[task.name] = result
        return result

    def due(self) -> list[Task]:
        now = self._clock()
        return [t for t in self.tasks if self._next[t.name] <= now]

    def tick(self) -> None:
        for task in self.due():
            self._next[task.name] = self._clock() + task.every_minutes * 60
            self.run_one(task)

    def status(self) -> list[dict]:
        now = self._clock()
        with self._lock:
            return [{"name": t.name, "prompt": t.prompt, "every_minutes": t.every_minutes, "persona": t.persona,
                     "next_in_seconds": max(0, round(self._next[t.name] - now)), "last": self.last.get(t.name)}
                    for t in self.tasks]

    def loop(self, stop: Event, tick_seconds: float = TICK_SECONDS) -> None:
        while not stop.is_set():
            self.tick()
            stop.wait(tick_seconds)


def brand_block(brand_file: str | None) -> str:
    """The products and the claims a draft may use: without them a run invents products and results."""
    if not brand_file:
        return ""
    from sensai.guardrails.rules import load_claims

    with open(brand_file, encoding="utf-8") as f:
        products = json.load(f).get("products", [])
    usable = {claim.claim_id for claim in load_claims(brand_file).approved}
    lines = ["Products (write only about these):"]
    for product in products:
        claims = [f'{c["id"]} "{c["text"]}"' for c in product.get("claims", []) if c.get("id") in usable]
        lines.append(f"- {product['name']}: " + ("; ".join(claims) if claims else "no approved claim yet"))
    lines.append("Use these claims word for word and no others. Never invent products, ingredients, results "
                 "or testimonials; if something is missing, say what is missing.")
    return "\n".join(lines)


def make_runner(client, model: str, base_prompt: str, personas, timeout: float, context=lambda: ""):
    """run(task) -> reply text: one chat request with the shared prompt, `context()` and the task's persona.

    `context` is read at every run, so profile, fact or brand file changes reach the next draft.
    """
    from sensai.chat.session import ChatSession

    def run(task: Task) -> str:
        persona = personas.get(task.persona) if task.persona else None
        prompt = "\n\n".join(part for part in (base_prompt, context(), persona.system_prompt if persona else "") if part)
        session = ChatSession(client, model, prompt)
        text = "".join(session.send(task.prompt, CancellationToken(time.monotonic() + timeout)))
        if not text.strip():
            raise SensaiError("the model returned an empty answer")
        return text
    return run


def main(argv: list[str] | None = None) -> int:
    from sensai.chat.personas import PersonaRegistry
    from sensai.chat.prompts import load_system_prompt
    from sensai.guardrails import GuardedClient, GuardrailConfigError, load_guardrail
    from sensai.llm import create_client
    from sensai.settings import Settings

    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: python -m sensai.schedule <tasks.json>")
        return 2
    settings = Settings()
    if not settings.model:
        print("error: set SENSAI_MODEL (or put it in .env) to choose the model")
        return 2
    try:
        personas = PersonaRegistry.from_file(settings.personas_file)
        tasks = load_tasks(argv[0], personas)
        guard = load_guardrail(settings.guardrails_file, settings.brand_file)
    except (ValueError, GuardrailConfigError) as exc:
        print(f"error: {exc}")
        return 2
    client = GuardedClient(create_client(settings), guard)
    run = make_runner(client, settings.model, load_system_prompt(settings.prompt_path), personas, settings.operation_timeout,
                      context=lambda: brand_block(settings.brand_file))
    scheduler = Scheduler(tasks, run, settings.model, settings.drafts_dir)
    print(f"Scheduler started: {len(tasks)} task{'s' * (len(tasks) != 1)}. Ctrl+C to stop.")
    try:
        scheduler.loop(Event())
    except KeyboardInterrupt:
        print("\nScheduler stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
