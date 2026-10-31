"""Scheduling (X5) in the page: the tasks run in a background thread; the page shows them and their drafts."""
import os
import threading
from datetime import datetime

from sensai.chat.saved_sessions import profile_block
from sensai.schedule import Scheduler, brand_block, load_tasks, make_runner
from sensai_web.errors import ApiError


def start(app, settings, client) -> Scheduler | None:
    """The scheduler for settings.schedule_file, already running; None without a tasks file."""
    if not settings.schedule_file:
        return None
    tasks = load_tasks(settings.schedule_file, app.catalogue.registry)  # ValueError: refused before anything runs
    def context() -> str:  # As in a chat: the profile, the saved brand facts, then the products and claims.
        return "\n\n".join(part for part in (profile_block(app.preferences), app.memory.block(),
                                               brand_block(settings.brand_file)) if part)

    run = make_runner(client, app.cfg.model, app.base_prompt, app.catalogue.registry, settings.operation_timeout, context)
    scheduler = Scheduler(tasks, run, app.cfg.model, settings.drafts_dir, write=lambda line: None)
    scheduler.file = settings.schedule_file
    threading.Thread(target=scheduler.loop, args=(app.schedule_stop,), daemon=True, name="sensai-schedule").start()
    return scheduler


def _scheduler(app) -> Scheduler:
    if app.scheduler is None:
        raise ApiError(409, "schedule_off", "Scheduling is off: there is no schedule.local.json (or SENSAI_SCHEDULE_FILE).")
    return app.scheduler


def drafts(folder: str) -> list[dict]:
    if not os.path.isdir(folder):
        return []
    names = sorted((n for n in os.listdir(folder) if n.endswith(".md") and not n.startswith(".")), reverse=True)
    return [{"name": n, "bytes": os.path.getsize(os.path.join(folder, n)),
             "at": datetime.fromtimestamp(os.path.getmtime(os.path.join(folder, n))).isoformat(timespec="minutes")} for n in names]


def status(app) -> dict:
    if app.scheduler is None:
        return {"on": False}
    return {"on": True, "file": app.scheduler.file, "model": app.scheduler.model, "tasks": app.scheduler.status(),
            "drafts": drafts(app.scheduler.drafts)}


def run_now(app, name: str) -> dict:
    scheduler = _scheduler(app)
    task = next((t for t in scheduler.tasks if t.name == name), None)
    if task is None:
        raise ApiError(404, "not_found", f"No task named {name}.")
    return scheduler.run_one(task)


def read_draft(app, name: str) -> dict:
    scheduler = _scheduler(app)
    if name not in {d["name"] for d in drafts(scheduler.drafts)}:
        raise ApiError(404, "not_found", f"No draft named {name}.")
    with open(os.path.join(scheduler.drafts, name), encoding="utf-8") as f:
        return {"name": name, "text": f.read()}
