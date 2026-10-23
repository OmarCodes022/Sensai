"""cli.approval.TerminalApproval with a scripted key reader."""

import json

import pytest

from sensai.cli.approval import TerminalApproval
from sensai.core.ports import ApprovalPort, ApprovalRequest


class Keys:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, prompt, choices, default):
        self.calls.append((prompt, choices, default))
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException) or isinstance(answer, type):
            raise answer
        return default if answer == "" else answer


def ask(arguments, *answers, resource=None, action="run_python", **options):
    keys, lines = Keys(*answers), []
    approval = TerminalApproval(keys, lines.append, **options)
    if resource is None:
        resource = json.dumps(arguments)
    decision = approval.request(ApprovalRequest(action, resource, "Run Python code."))
    return decision.approved, lines, keys.calls


CODE = "\n".join(f"line{i}" for i in range(1, 11))


def test_satisfies_approval_port():
    assert isinstance(TerminalApproval(Keys()), ApprovalPort)


def test_short_arguments_do_not_offer_view_all():
    approved, lines, calls = ask({"code": "print(1)\nprint(2)"}, "y")
    assert approved
    assert lines == ["", "Run run_python?", "  code:", "    print(1)", "    print(2)"]
    assert calls == [("[y] run · [n] refuse ", "yn", "n")]


def test_long_code_preview_then_view_all_then_run():
    approved, lines, calls = ask({"code": CODE}, "v", "y")
    assert approved
    preview = ["", "Run run_python?", "  code:"] + [f"    line{i}" for i in range(1, 7)]
    assert lines[:10] == preview + ["    … (+4 more lines)"]
    assert lines[10:] == ["  code:"] + [f"    line{i}" for i in range(1, 11)]
    assert calls == [("[y] run · [n] refuse · [v] view all ", "ynv", "n"),
                     ("[y] run · [n] refuse ", "yn", "n")]


@pytest.mark.parametrize("answers", [("n",), ("",), ("v", "n"), ("v", "")])
def test_refusal_and_enter_default_refuse(answers):
    assert not ask({"code": CODE}, *answers)[0]


@pytest.mark.parametrize("answers", [(EOFError,), ("v", EOFError)])
def test_eof_refuses(answers):
    assert not ask({"code": CODE}, *answers)[0]


@pytest.mark.parametrize("answers", [(KeyboardInterrupt,), ("v", KeyboardInterrupt)])
def test_ctrl_c_propagates(answers):
    with pytest.raises(KeyboardInterrupt):
        ask({"code": CODE}, *answers)


def test_preview_budget_spans_all_arguments_and_counts_hidden_lines():
    arguments = {"code": "a\nb\nc", "limit": 3, "flags": [1, "x"], "note": "n1\nn2"}
    approved, lines, calls = ask(arguments, "n", preview_lines=4)
    assert lines[2:] == ["  code:", "    a", "    b", "    c", "  limit: 3",
                         "    … (+3 more lines)"]
    assert calls[0][1] == "ynv"


def test_one_hidden_line_is_still_announced():
    lines = ask({"code": "a\nb"}, "n", preview_lines=1)[1]
    assert lines[-1] == "    … (+1 more line)"


def test_non_string_values_are_compact_json():
    lines = ask({"n": 1.5, "items": [1, {"a": None}], "ok": True}, "y")[1]
    assert lines[2:] == ["  n: 1.5", '  items: [1,{"a":null}]', "  ok: true"]


@pytest.mark.parametrize("resource", ["not json {", "[1, 2]", '"text"'])
def test_unparseable_or_non_object_resource_is_one_string(resource):
    lines = ask(None, "y", resource=resource)[1]
    assert lines[2:] == ["  " + resource]


def test_line_width_cut_offers_view_all_with_full_line():
    long = "x = 1" + " " * 200 + "; import os"
    approved, lines, calls = ask({"code": long}, "v", "n", line_width=40)
    assert lines[3] == "    " + long[:35] + "…"
    assert len(lines[3]) == 40
    assert lines[-1] == "    " + long
    assert calls[0][1] == "ynv"


DANGEROUS = {
    "\x1b[2K": "\\x1b[2K",
    "\x1b]0;t\x07": "\\x1b]0;t\\x07",
    "\x9b31m": "\\x9b31m",
    "\x85": "\\x85",
    "\x7f": "\\x7f",
    "\x00\x08\x0b\x0c": "\\x00\\x08\\x0b\\x0c",
    "‮⁦⁩‎‏؜‪": "\\u202e\\u2066\\u2069\\u200e\\u200f\\u061c\\u202a",
}


@pytest.mark.parametrize("raw, shown", DANGEROUS.items())
def test_controls_are_visible_in_preview_and_full_view(raw, shown):
    code = f"ok = 1  # {raw}done\n" + CODE
    approved, lines, _ = ask({"code": code}, "v", "n")
    expected = f"    ok = 1  # {shown}done"
    assert lines[3] == expected and lines[-11] == expected
    assert all(ch.isprintable() for ch in "".join(lines))


def test_tab_and_unicode_text_are_kept():
    lines = ask({"code": "\tprint('café ✓')"}, "y")[1]
    assert lines[3] == "    \tprint('café ✓')"


def test_carriage_return_is_escaped_and_breaks_the_line_like_python():
    code = "x = 1  # harmless\rimport shutil\r\nend"
    lines = ask({"code": code}, "y")[1]
    assert lines[2:] == ["  code:", "    x = 1  # harmless\\x0d", "    import shutil\\x0d",
                         "    end"]


def test_action_and_keys_are_sanitized():
    resource = json.dumps({"co\x1b[8mde": "x", "n‮": 1})
    lines = ask(None, "y", resource=resource, action="run\x1b[2Jpython")[1]
    assert lines[1] == "Run run\\x1b[2Jpython?"
    assert lines[2:] == ["  co\\x1b[8mde:", "    x", "  n\\u202e: 1"]


def test_non_json_resource_is_sanitized_and_cut():
    resource = "bad\x1b[31m" + "y" * 300
    approved, lines, calls = ask(None, "v", "y", resource=resource, line_width=20)
    assert lines[2] == "  bad\\x1b[31m" + "y" * 6 + "…"
    assert lines[-1] == "  bad\\x1b[31m" + "y" * 300
    assert approved


@pytest.mark.parametrize("raw, shown", [
    ("\U000e0069\U000e006d", "\\U000e0069\\U000e006d"),
    ("\u200b\u200c\u200d\u2060\ufeff", "\\u200b\\u200c\\u200d\\u2060\\ufeff"),
    ("\u2028\u2029", "\\u2028\\u2029"),
    ("\ud83d", "\\ud83d"),
    ("\xa0", "\\xa0"),
])
def test_invisible_characters_are_visible_in_values_and_keys(raw, shown):
    code = f"x = 1  # {raw}\n" + CODE
    resource = json.dumps({"code": code, f"k{raw}": [raw]})
    approved, lines, _ = ask(None, "v", "n", resource=resource, preview_lines=20)
    assert lines[3] == f"    x = 1  # {shown}"
    assert f"  k{shown}: [\"{shown}\"]" in lines
    for line in lines:
        line.encode("utf-8")
        assert line.isprintable()


def test_keys_and_action_stay_on_one_line():
    resource = json.dumps({"a\nb\rc\td": 1, "e\nf": "v"})
    lines = ask(None, "y", resource=resource, action="run\npython")[1]
    assert lines[1:] == ["Run run\\x0apython?", "  a\\x0ab\\x0dc\\x09d: 1", "  e\\x0af:", "    v"]
