"""Registry rules from the PR #94 review: strict schemas and child control errors."""

import multiprocessing

import pytest

from tool_handlers import exercise
from sensai.core.ports import ToolCall, ToolDefinition, ToolResult
from sensai.tools import ToolRegistry

STRICT = {"type": "object", "properties": {"code": {"type": "string"}},
          "required": ["code"], "additionalProperties": False}


def strict_registry(parameters, read):
    tools = ToolRegistry(read=read)
    tools.register(ToolDefinition("strict", "Strict", parameters),
                   lambda arguments, cancellation: ToolResult("ran"), timeout=None, confirm=True)
    return tools


def test_additional_properties_false_rejects_unknown_argument_before_approval():
    prompts = []
    tools = strict_registry(STRICT, lambda prompt: prompts.append(prompt) or "yes")
    result = tools.execute(ToolCall("strict", {"code": "1", "decoy": "x" * 500}))
    assert result == ToolResult("", "invalid arguments: unexpected property decoy")
    assert prompts == []
    assert tools.execute(ToolCall("strict", {"code": "1"})) == ToolResult("ran")
    assert len(prompts) == 1


@pytest.mark.parametrize("extra", [{}, {"additionalProperties": True}, {"additionalProperties": {}}])
def test_schemas_without_additional_properties_false_accept_extra_arguments(extra):
    parameters = {k: v for k, v in STRICT.items() if k != "additionalProperties"} | extra
    tools = strict_registry(parameters, lambda prompt: "yes")
    assert tools.execute(ToolCall("strict", {"code": "1", "other": 2})) == ToolResult("ran")


def test_additional_properties_false_without_properties_accepts_only_no_arguments():
    tools = strict_registry({"additionalProperties": False}, lambda prompt: "yes")
    assert tools.execute(ToolCall("strict", {})) == ToolResult("ran")
    assert tools.execute(ToolCall("strict", {"x": 1})).error == "invalid arguments: unexpected property x"


@pytest.mark.parametrize("action, name", [
    ("keyboard", "KeyboardInterrupt"), ("exit", "SystemExit"),
    ("generator", "GeneratorExit"), ("base", "WorkerAbort"),
])
def test_child_handler_control_exceptions_become_tool_errors(action, name):
    tools = ToolRegistry()
    tools.register(ToolDefinition("test", "Test handler"), exercise)
    result = tools.execute(ToolCall("test", {"action": action}))
    assert result == ToolResult("", f"PortError: tool handler raised {name}")
    assert not multiprocessing.active_children()


def test_in_process_handler_control_exceptions_still_propagate():
    tools = ToolRegistry()
    tools.register(ToolDefinition("test", "Test handler"), exercise, timeout=None)
    with pytest.raises(KeyboardInterrupt):
        tools.execute(ToolCall("test", {"action": "keyboard"}))
