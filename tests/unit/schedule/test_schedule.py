"""Scheduling: the tasks file, due runs, dated drafts, failures retried at the next interval."""
import json
from datetime import datetime

import pytest

from fakes import FakeClient
from sensai.chat.personas import PersonaRegistry
from sensai.core.errors import LLMConnectionError
from sensai.schedule import Scheduler, Task, load_tasks, main, make_runner

PERSONAS = PersonaRegistry.from_file(None)


def tasks_file(tmp_path, items):
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps(items))
    return str(path)


def test_a_valid_file_loads_and_bad_ones_are_refused_before_anything_runs(tmp_path):
    good = [{"name": "post-ideas", "prompt": "Ideas", "every_minutes": 1, "persona": "redaction"}]
    assert load_tasks(tasks_file(tmp_path, good), PERSONAS) == [Task("post-ideas", "Ideas", 1, "redaction")]
    for items, message in (([], "non-empty"), ([{"name": "x", "prompt": "p"}], "every_minutes"),
                           ([{"name": "x", "prompt": "", "every_minutes": 1}], "prompt"),
                           ([{"name": "x", "prompt": "p", "every_minutes": 1, "persona": "ghost"}], "unknown persona"),
                           ([{"name": "x", "prompt": "p", "every_minutes": 1}] * 2, "unique")):
        with pytest.raises(ValueError, match=message):
            load_tasks(tasks_file(tmp_path, items), PERSONAS)
    (tmp_path / "broken.json").write_text("{")
    with pytest.raises(ValueError, match="not valid JSON"):
        load_tasks(str(tmp_path / "broken.json"), PERSONAS)


def test_due_tasks_run_at_start_and_then_at_their_interval(tmp_path):
    clock = [0.0]
    lines = []
    task = Task("post-ideas", "Ideas", 1, "redaction")
    runner = make_runner(FakeClient(["Idea 1"], ["Idea 2"]), "m", "Rules", PERSONAS, 30)
    scheduler = Scheduler([task], runner, "m", str(tmp_path / "drafts"), clock=lambda: clock[0],
                          now=lambda: datetime(2026, 11, 2, 9, 0 if clock[0] < 60 else 1), write=lines.append)
    scheduler.tick()
    scheduler.tick()  # Not due again yet.
    clock[0] = 61
    scheduler.tick()
    drafts = sorted((tmp_path / "drafts").glob("*.md"))
    assert [d.name for d in drafts] == ["2026-11-02-0900-post-ideas.md", "2026-11-02-0901-post-ideas.md"]
    text = drafts[0].read_text()
    assert "persona: redaction · model: m" in text and "Nothing was posted or sent." in text and text.endswith("Idea 1\n")
    assert lines[0].startswith("[09:00] post-ideas -> ")


def test_a_failed_run_saves_nothing_and_is_retried(tmp_path):
    clock = [0.0]
    lines = []
    runner = make_runner(FakeClient(LLMConnectionError("cannot reach Ollama"), ["Back"]), "m", "Rules", PERSONAS, 30)
    scheduler = Scheduler([Task("x", "p", 1)], runner, "m", str(tmp_path / "drafts"), clock=lambda: clock[0], write=lines.append)
    scheduler.tick()
    assert "failed: cannot reach Ollama (will retry in 1 min)" in lines[0] and not (tmp_path / "drafts").exists()
    assert scheduler.status()[0]["last"]["ok"] is False
    clock[0] = 61
    scheduler.tick()
    assert scheduler.status()[0]["last"]["ok"] is True and len(list((tmp_path / "drafts").glob("*.md"))) == 1


def test_main_refuses_a_bad_file_and_needs_a_model(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SENSAI_MODEL", "")  # A real variable wins over .env, so no model is chosen.
    assert main([str(tmp_path / "nope.json")]) == 2 and "SENSAI_MODEL" in capsys.readouterr().out
    monkeypatch.setenv("SENSAI_MODEL", "m")
    assert main([str(tmp_path / "nope.json")]) == 2 and "cannot read" in capsys.readouterr().out
    assert main([]) == 2
