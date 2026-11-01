"""A4 in the page: list the dated prompt versions, use one (rollback), and compare two on the same questions."""
import os
from datetime import datetime
from pathlib import Path
from time import monotonic

from sensai.chat.prompts import load_system_prompt
from sensai.core.cancellation import CancellationToken
from sensai.core.errors import SensaiError
from sensai.core.messages import Message
from sensai.llm.client import close_stream
from sensai.llm.ollama_api import OllamaUsage
from sensai.prompt_versions import Answer, read_questions, render_report, versions
from sensai_web.errors import ApiError

FOLDER = os.environ.get("SENSAI_PROMPT_VERSIONS", os.path.join("evals", "prompt_compare", "versions"))
REPORTS = "prompt-reports"


def named(name: object):
    found = {Path(v.path).name: v for v in versions(FOLDER)}
    if not isinstance(name, str) or name not in found:
        raise ApiError(404, "not_found", f"No prompt version named {name}.")
    return found[name]


def listing(app) -> dict:
    return {"folder": FOLDER, "active": app.prompt_version,
            "items": [{"name": Path(v.path).name, "lines": v.lines, "sha256": v.sha256} for v in versions(FOLDER)]}


def use(app, name: object) -> dict:
    """The version for the next turns of this run (None: back to the prompt Sensai started with)."""
    text = load_system_prompt(app.cfg.prompt_path) if name is None else named(name).text
    with app.mutex:
        app.require_idle()
        app.base_prompt, app.prompt_version = text, name
        active = app.active
        # Not set_system_prompt: that marks a persona switch and re-sends the prompt on every turn.
        active.session.messages[0] = Message(role="system", content=app.system_prompt(active.persona_id))
    return listing(app)


def compare(app, stop, emit, a: object, b: object) -> None:
    """Each question, to version A then B, as a fresh conversation; one event per answer, then the report."""
    prompts = [named(a), named(b)]
    questions = read_questions(Path(FOLDER).parent / "questions.txt")
    client = getattr(app.chat_client, "client", app.chat_client)  # The raw answer, as the script compares it.
    emit({"type": "start", "questions": len(questions), "a": Path(prompts[0].path).name, "b": Path(prompts[1].path).name})
    results = []
    for n, question in enumerate(questions, 1):
        row = []
        for label, prompt in zip("AB", prompts):
            if stop.is_set():
                return emit({"type": "done", "status": "stopped", "report": None})
            app.usage.reset()
            answer, started = Answer(), monotonic()
            stream = client.stream(app.model, [Message(role="system", content=prompt.text), Message(role="user", content=question)],
                                   CancellationToken(monotonic() + app.cfg.operation_timeout, stop.is_set))
            try:
                answer.text = "".join(stream)
            except SensaiError as exc:
                answer.error = str(exc) or type(exc).__name__
            finally:
                close_stream(stream)
            usage = app.usage.summary()
            answer.usage = OllamaUsage(usage["prompt_tokens"], usage["output_tokens"], usage["latency_ms"] or (monotonic() - started) * 1000)
            row.append(answer)
            emit({"type": "answer", "n": n, "label": label, "question": question, "text": answer.text, "error": answer.error,
                  "latency_ms": round(answer.usage.latency_ms), "prompt_tokens": usage["prompt_tokens"], "output_tokens": usage["output_tokens"]})
        results.append(row)
    date = datetime.now()
    os.makedirs(REPORTS, exist_ok=True)
    report = os.path.join(REPORTS, f"compare-{date:%Y%m%d-%H%M%S}.md")
    with open(report, "w", encoding="utf-8") as f:
        f.write(render_report(app.model, app.cfg.host, "questions.txt", prompts, questions, results, date))
    emit({"type": "done", "status": "completed", "report": report})
