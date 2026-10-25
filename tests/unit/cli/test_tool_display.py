"""`Using tool:` shows compact JSON arguments on its own line, without blank lines."""

import pytest

from fakes import FakeClient
from sensai.chat.session import ChatSession
from sensai.cli import main as cli
from sensai.core.ports import ToolDefinition, ToolResult
from sensai.tools import ToolRegistry

pytestmark = pytest.mark.usefixtures("isolated_settings")
TOOL_CALL = r'{"tool":"lookup","arguments":{"text":"é \"q\"","n":[1,2],"bad":"\ud800"}}'
SHOWN = 'Using tool: lookup({"text": "é \\"q\\"", "n": [1, 2], "bad": "\\ud800"})\n'


def run(*replies):
    tools = ToolRegistry()
    tools.register(ToolDefinition("lookup", "Look up."),
                   lambda arguments, cancellation: ToolResult("7"), timeout=None)
    output = []

    def write(*args, end="\n", flush=False):
        text = "".join(map(str, args)) + end
        text.encode("utf-8")  # A real UTF-8 terminal would reject lone surrogates.
        output.append(text)

    inputs = iter(["Question", "exit"])
    session = ChatSession(FakeClient(*replies), "model", "sys")
    cli.repl(session, read=lambda prompt: next(inputs), write=write, tool_registry=tools)
    return "".join(output)


def test_block_as_its_own_chunk_prints_json_line_without_blank_lines():
    assert run([TOOL_CALL], ["Seven"]) == SHOWN + "Seven\n"


def test_visible_text_then_block_prints_json_line_without_blank_lines():
    assert run(["Checking", "\n", TOOL_CALL], ["Seven"]) == "Checking\n" + SHOWN + "Seven\n"
