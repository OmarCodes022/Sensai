"""BlockReader regressions: no raw block leaks, no stalled text, linear streaming."""

import json
import random
import time

import pytest

from fakes import FakeClient
from sensai.chat.blocks import BlockReader
from sensai.chat.session import ChatSession
from sensai.core.ports import ToolDefinition, ToolResult
from sensai.tools import ToolRegistry, run_with_tools


def _echo(arguments, cancellation=None):
    return ToolResult("ok")


def test_unterminated_quote_line_does_not_release_final_tool_block():
    block = json.dumps({"tool": "echo", "arguments": {"text": "a}b"}})
    reply = 'Draft:\n{"oops\n' + block + "\n"
    reader = BlockReader()
    shown = reader.feed(reply)
    visible, final = reader.finish()
    assert final == {"tool": "echo", "arguments": {"text": "a}b"}}
    assert visible.startswith(shown)
    assert '"tool"' not in shown


def test_run_with_tools_never_prints_raw_block_after_unterminated_quote_line():
    tools = ToolRegistry()
    tools.register(ToolDefinition("echo", "Echo"), _echo, timeout=None)
    block = json.dumps({"tool": "echo", "arguments": {"text": "a}b"}})
    session = ChatSession(FakeClient(['Draft:\n{"oops\n' + block + "\n"], ["Done."]), "m", "sys")
    chunks = list(run_with_tools(session, tools, "hi"))
    assert '"tool"' not in "".join(chunks)


def test_brace_line_followed_by_non_json_text_is_streamed_before_reply_ends():
    reader = BlockReader()
    shown = reader.feed("int main(void)\n{\n    return 0;\n")
    shown += reader.feed("    /* still streaming */\n")
    assert "return 0;" in shown


def test_quote_that_is_not_a_cut_string_is_released_before_the_line_ends():
    reader = BlockReader()
    shown = "".join(reader.feed(char) for char in '{"a" "b c d e f g')
    assert shown == '{"a" "b c d e f g'


BLOCK = {"tool": "echo", "arguments": {
    "text": 'a}b "q" \\ \n\t é 😀', "n": -1.5e+10, "e": 1E-5, "z": 0, "t": True,
    "f": False, "x": None, "l": [1, -0.25, {"k": []}]}}


@pytest.mark.parametrize("ensure_ascii", [True, False])
@pytest.mark.parametrize("indent", [None, 2])
def test_no_prefix_of_a_final_block_is_ever_shown(ensure_ascii, indent):
    # Every cut string, \uXXXX escape, surrogate pair, number and literal is held.
    block = json.dumps(BLOCK, ensure_ascii=ensure_ascii, indent=indent)
    reader = BlockReader()
    shown = "".join(reader.feed(char) for char in "Text\n" + block + "\n")
    assert shown == "Text\n"
    assert reader.finish() == ("Text\n", BLOCK)


def test_fuzzed_earlier_lines_with_braces_and_quotes_never_leak_the_final_block():
    rng = random.Random(94)
    fragments = ['{', '}', '"', '\\', 'a', ' ', ':', ',', '1', '[', ']', '\n', 'tru', '-', '.', 'u12', 'é']
    for _ in range(3000):
        lines = []
        for _ in range(rng.randint(0, 4)):
            line = "".join(rng.choice(fragments) for _ in range(rng.randint(0, 12)))
            lines.append("{" + line if rng.random() < .6 else line)
        text = "".join(rng.choice('}{"\\ab\n') for _ in range(rng.randint(0, 6)))
        block = {"tool": "echo", "arguments": {"text": text}}
        reply = "".join(line + "\n" for line in lines) + json.dumps(block) + "\n"
        reader, shown, index = BlockReader(), "", 0
        while index < len(reply):
            size = rng.randint(1, 8)
            shown += reader.feed(reply[index:index + size])
            index += size
        visible, final = reader.finish()
        assert final == block, reply
        assert visible.startswith(shown), reply
        assert '"tool"' not in shown, reply


def _feed_one_char_at_a_time(reply):
    reader = BlockReader()
    started = time.perf_counter()
    shown = "".join(reader.feed(char) for char in reply)
    return shown, reader.finish(), time.perf_counter() - started


def test_40k_reply_after_an_unclosed_brace_line_streams_in_linear_time():
    reply = "int main(void)\n{\n" + '    puts("{x}");\n' * 2_500 + "}\n"
    reader = BlockReader()
    started = time.perf_counter()
    shown = reader.feed(reply[:40])
    shown += "".join(reader.feed(char) for char in reply[40:-2])
    assert shown == reply[:-2]  # Released while streaming, not at the closing brace.
    shown += reader.feed(reply[-2:])
    assert time.perf_counter() - started < 2
    assert shown == reply
    assert reader.finish() == (reply, None)


def test_40k_string_argument_is_held_in_linear_time():
    block = {"tool": "write", "arguments": {"text": 'line\n"q"} é ' * 4_000}}
    shown, (visible, final), elapsed = _feed_one_char_at_a_time("Hi\n" + json.dumps(block))
    assert shown == visible == "Hi\n"
    assert final == block
    assert elapsed < 2
