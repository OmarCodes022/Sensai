"""The weekly run (T45) in the page: the same run as --weekly-run, one stream event per output."""
from sensai.core.messages import Message
from sensai.weekly.run import run_week
from sensai_web.campaign import _doc


class Stopped(Exception):
    """The creator pressed Stop: nothing is saved (only SensaiError fails an output on its own)."""


def run(app, stop, emit) -> None:
    """Holds the turn slot from the caller; reads the data folder, writes only the campaign document."""

    def ask(instructions: str, request: str, schema):
        if stop.is_set():
            raise Stopped()
        messages = [Message(role="system", content=instructions), Message(role="user", content=request)]
        return app.checker.complete(app.model, messages, schema)

    folder = app.cfg.data_dir or "data"
    emit({"type": "start", "folder": folder, "model": app.model})
    try:
        header, outcomes, saved = run_week(folder, app.campaign, ask, app.guardrails_file,
                                           on_step=lambda o: emit({"type": "step", "name": o.name, "ok": o.ok,
                                                                   "detail": o.detail}))
    except Stopped:
        emit({"type": "done", "status": "stopped", "saved": None})
        return
    emit({"type": "done", "status": "completed", "header": header, "saved": saved,
          "ok": all(o.ok for o in outcomes), "doc": _doc(app)})
