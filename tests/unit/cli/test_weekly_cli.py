"""`sensai <model> --weekly-run <folder>`: one line per output, then where it was saved; Ctrl+C saves nothing."""
import pytest

from sensai.cli import main as cli
from sensai.cli import weekly
from sensai.weekly.outputs import Outcome


def run(monkeypatch, result):
    def fake(folder, store, ask, rules_file=None, on_step=lambda o: None):
        if isinstance(result, BaseException):
            raise result
        for outcome in result[1]:
            on_step(outcome)
        return result
    monkeypatch.setattr(weekly, "run_week", fake)
    with pytest.raises(SystemExit) as stopped:
        cli.main(["model", "--weekly-run", "inputs"])
    return stopped.value.code


def test_summary_lines_and_saved_file(monkeypatch, capsys):
    outcomes = [Outcome("Report", True, "rate 15.0%"), Outcome("Posts", False, "only 1 drafts")]
    code = run(monkeypatch, ("Report week a to b · calendar for c to d", outcomes, "campaigns/2026-W40.json"))
    out = capsys.readouterr().out.splitlines()
    assert out[1:] == ["Report ....... OK     rate 15.0%", "Posts ........ failed only 1 drafts",
                       "Report week a to b · calendar for c to d",
                       "Saved campaigns/2026-W40.json: nothing was sent or published."]
    assert code == 1


def test_all_ok_exits_zero(monkeypatch):
    assert run(monkeypatch, ("h", [Outcome("Report", True, "ok")], "x.json")) == 0


def test_ctrl_c_says_nothing_was_saved(monkeypatch, capsys):
    assert run(monkeypatch, KeyboardInterrupt()) == 130
    assert "Stopped: nothing was saved." in capsys.readouterr().out
