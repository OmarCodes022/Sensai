"""Tool-loop contract examples (T18); no working loop is tested here."""

import inspect
import subprocess
import sys
from dataclasses import FrozenInstanceError

import pytest

from sensai.chat.blocks import BlockReader, split_block
from sensai.core.isolation import ControlledTool
from sensai.core.ports import ApprovalPort, ToolCall, ToolDefinition, ToolPort, ToolResult
from sensai.tools import (
    MAX_TOOL_CALLS,
    TOOL_TIMEOUT_SECONDS,
    ToolRegistry,
    parse_tool_call,
    run_with_tools,
    tool_instructions,
)


def test_tool_definition_is_frozen_with_empty_default_parameters():
    definition = ToolDefinition("read_file", "Read a file.")
    assert definition.parameters == {}
    assert ToolDefinition("x", "y").parameters is not ToolDefinition("x", "y").parameters
    with pytest.raises(FrozenInstanceError):
        definition.name = "other"


def test_tool_result_error_defaults_to_none_and_keeps_equality():
    assert ToolResult("x").error is None
    assert ToolResult("x") == ToolResult("x", None)
    assert ToolResult("", "unknown tool") != ToolResult("")


def test_tool_call_accepts_json_values():
    arguments = {"path": "/a", "limit": 3, "flags": [True, None], "opts": {"x": 1.5}}
    assert ToolCall("run", arguments).arguments == arguments


def test_registry_has_tool_port_shape_and_limit():
    assert isinstance(ToolRegistry(), ToolPort)
    assert MAX_TOOL_CALLS == 5


def test_controlled_tool_still_satisfies_tool_port():
    assert isinstance(ControlledTool(ToolRegistry), ToolPort)


def test_register_settings_are_keyword_only_with_defaults():
    parameters = inspect.signature(ToolRegistry.register).parameters
    assert {name: (p.kind, p.default) for name, p in parameters.items()
            if name in ("timeout", "confirm", "max_calls")} == {
        "timeout": (inspect.Parameter.KEYWORD_ONLY, TOOL_TIMEOUT_SECONDS),
        "confirm": (inspect.Parameter.KEYWORD_ONLY, False),
        "max_calls": (inspect.Parameter.KEYWORD_ONLY, None),
    }
    assert TOOL_TIMEOUT_SECONDS == 30.0


def test_registry_takes_optional_approval_port():
    parameter = inspect.signature(ToolRegistry).parameters["approval"]
    assert parameter.default is None
    assert parameter.annotation == ApprovalPort | None
    ToolRegistry()


@pytest.mark.parametrize("call", [
    lambda: ToolRegistry().register(ToolDefinition("x", "y"), lambda a, c: ToolResult("")),
    lambda: ToolRegistry().register(ToolDefinition("x", "y"), lambda a, c: ToolResult(""),
                                    timeout=None, confirm=True, max_calls=1),
    lambda: ToolRegistry().definitions(),
    lambda: ToolRegistry().execute(ToolCall("x", {})),
    lambda: tool_instructions([]),
    lambda: parse_tool_call({"tool": "x"}),
    lambda: next(run_with_tools(None, ToolRegistry(), "hi")),
    lambda: BlockReader().feed("hi"),
    lambda: BlockReader().finish(),
    lambda: split_block("hi"),
])
def test_placeholders_raise_not_implemented_for_t18(call):
    with pytest.raises(NotImplementedError, match="T18"):
        call()


def test_modules_import_without_loading_cli():
    code = ("import sys, sensai.tools, sensai.chat.blocks; "
            "assert not any(m.startswith('sensai.cli') for m in sys.modules)")
    subprocess.run([sys.executable, "-c", code], check=True)
