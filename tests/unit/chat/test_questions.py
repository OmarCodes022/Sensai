"""ask_user: question checks, the terminal form, retries on invalid answers and Ctrl+C to skip."""
import pytest

from sensai.chat.questions import SKIPPED, TerminalForm, check_answers, parse

PRODUCT = {"questions": [{"type": "choice", "text": "Which product?", "options": ["Hydra Glow Serum", "Calm Barrier Cream"]}]}


def form(*answers):
    out, replies = [], iter(answers)

    def read(prompt):
        value = next(replies)
        if isinstance(value, BaseException):
            raise value
        return value
    return TerminalForm(read, out.append), out


def test_a_choice_is_shown_as_a_numbered_list_and_returned_as_text():
    ask, out = form("2")
    result = ask(PRODUCT)
    assert result.output == "Which product? -> Calm Barrier Cream" and result.error is None
    assert "Sensai needs one detail:" in out and "    1) Hydra Glow Serum   2) Calm Barrier Cream   3) Other (type it)" in out


def test_invalid_choices_are_asked_again_and_other_takes_typed_text():
    ask, out = form("9", "x", "3", "Night Cream")
    assert ask(PRODUCT).output == "Which product? -> Night Cream"
    assert out.count("  Please enter a number from 1 to 3.") == 2


def test_text_questions_and_ctrl_c_skips():
    ask, _ = form("", "warm and short")
    assert ask({"questions": [{"type": "text", "text": "Tone?"}]}).output == "Tone? -> warm and short"
    ask, out = form(KeyboardInterrupt())
    assert ask(PRODUCT).output == SKIPPED and "  Skipped." in out


@pytest.mark.parametrize("arguments", [{}, {"questions": []}, {"questions": [{"type": "x", "text": "a"}]},
                                       {"questions": [{"type": "choice", "text": "a", "options": ["one"]}]},
                                       {"questions": [{"type": "text", "text": " "}]}])
def test_bad_questions_are_errors_for_the_model(arguments):
    ask, _ = form()
    assert ask(arguments).error


def test_page_answers_are_checked():
    questions = parse(PRODUCT)
    assert check_answers(questions, [" Calm Barrier Cream "]) == ["Calm Barrier Cream"]
    for bad in ([], [""], ["a", "b"], "x"):
        with pytest.raises(ValueError):
            check_answers(questions, bad)
