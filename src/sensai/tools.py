"""Tool loop (T18) — NOT IMPLEMENTED: contracts only.

The model has no native tool calling. It asks for a tool by ending its reply
with one JSON block ``{"tool": "<name>", "arguments": {...}}`` on its own
lines. The loop reads that block (see ``sensai.chat.blocks``), runs the tool
with a time limit, sends the result back to the model and repeats, at most
``MAX_TOOL_CALLS`` rounds per question. Tool failures become ``ToolResult``
errors the model can read; they never crash the chat.

Full brief: docs/tasks/tool-loop.md. Every body below raises
``NotImplementedError`` until T18 lands.
"""

from collections.abc import Callable, Generator, Mapping, Sequence
from typing import TYPE_CHECKING

from sensai.core.cancellation import CancellationToken
from sensai.core.ports import ApprovalPort, ToolCall, ToolDefinition, ToolResult

if TYPE_CHECKING:
    from sensai.chat.session import ChatSession

MAX_TOOL_CALLS = 5
TOOL_TIMEOUT_SECONDS = 30.0

ToolHandler = Callable[[Mapping[str, object], CancellationToken | None], ToolResult]


class ToolRegistry:
    """Named tools the model may call; satisfies ``ToolPort``."""

    def __init__(self, approval: ApprovalPort | None = None) -> None:
        """``approval`` answers ``confirm=True`` tools (T46 will provide a
        terminal-backed one). Without it, confirm uses a plain y/N prompt on
        the chat's terminal reader. ``ToolRegistry()`` must keep working."""
        self._approval = approval

    def register(
        self,
        definition: ToolDefinition,
        handler: ToolHandler,
        *,
        timeout: float | None = TOOL_TIMEOUT_SECONDS,
        confirm: bool = False,
        max_calls: int | None = None,
    ) -> None:
        """Add a tool. Must raise ValueError if the name is already registered.

        - ``timeout``: seconds per call. A number runs the handler with that
          limit (isolation such as ``ControlledTool`` is the implementer's
          choice). ``None`` means no limit and the handler runs in the main
          process: use it for interactive tools that read the terminal
          (child processes cannot). Such a handler receives a token with the
          same cancel check but no deadline. It handles Ctrl+C itself and
          returns a "user skipped" result instead of cancelling the turn, and
          must not poll the chat's ``cancel_requested`` callback (directly or
          via ``raise_if_cancelled()``) while the user types (it discards
          unrecognised pending keys).
        - ``confirm``: before each call, ask through the registry's
          ``ApprovalPort`` (``ApprovalRequest(action, resource, reason)``,
          run only if ``ApprovalDecision.approved``), else a plain y/N prompt
          on the chat's terminal reader. A refusal gives an error result and
          the handler does not run.
        - ``max_calls``: limit for this tool per question (``None``: no own
          limit). Calls beyond it give an error result. Every call also
          counts toward ``MAX_TOOL_CALLS``. ``run_with_tools`` resets the
          counts at the start of each question; how (e.g. a
          ``start_question()`` method) is the implementer's choice.
        """
        raise NotImplementedError("T18: ToolRegistry.register is not implemented")

    def definitions(self) -> tuple[ToolDefinition, ...]:
        """Registered definitions in registration order."""
        raise NotImplementedError("T18: ToolRegistry.definitions is not implemented")

    def execute(
        self, call: ToolCall, cancellation: CancellationToken | None = None
    ) -> ToolResult:
        """Run one call and return a ``ToolResult``.

        - Unknown tool: ``ToolResult`` with ``error`` set, not an exception.
        - Arguments are checked against the definition's ``parameters``
          (``required`` names present, ``properties`` basic JSON types);
          invalid ones give an error result.
        - Exceeding the tool's ``timeout`` gives an error result. For a
          ``timeout=None`` tool, the handler gets a token that keeps the
          cancel check of ``cancellation`` but has no deadline.
        - ``confirm`` and ``max_calls`` are applied before the handler runs.
        - Handler ``Exception`` subclasses become error results with a short
          message, so tool errors never crash the chat. ``BaseException``
          that is not an ``Exception`` (``KeyboardInterrupt``, ...) is not
          swallowed.
        - ``OperationCancelled`` and ``OperationTimedOut`` (the token's own
          cancellation or overall deadline) propagate; they are not results.
        """
        raise NotImplementedError("T18: ToolRegistry.execute is not implemented")


def tool_instructions(definitions: Sequence[ToolDefinition]) -> str:
    """Text appended to the system prompt: each tool (name, description,
    parameters) and the block format."""
    raise NotImplementedError("T18: tool_instructions is not implemented")


def parse_tool_call(block: Mapping[str, object]) -> ToolCall:
    """Turn a parsed block into a ``ToolCall``.

    Requires a non-empty string ``tool`` and an optional object ``arguments``
    (missing means ``{}``). Raises ValueError on any other shape.
    """
    raise NotImplementedError("T18: parse_tool_call is not implemented")


def run_with_tools(
    session: "ChatSession",
    registry: ToolRegistry,
    text: str,
    cancellation: CancellationToken | None = None,
) -> Generator[str, None, tuple[str, dict | None]]:
    """Answer ``text``, calling tools as the model asks; yield visible text.

    Send the message and stream the reply through a ``BlockReader``. A final
    block with a ``"tool"`` key starts a round: parse and execute it (a
    malformed call or unknown tool gives an error result), send the result
    back to the model and read the next reply. Every round counts toward
    ``MAX_TOOL_CALLS``, whatever its outcome. After the limit, ask for a final
    answer without tools.

    After a ``timeout=None`` (interactive) tool returns, the rest of the turn
    uses the deadline extended by the time the tool took, keeping the same
    cancel check (e.g. a new ``CancellationToken``).

    The loop ends on a reply without a tool block, or on that final reply.
    Returns (via ``StopIteration.value`` / ``yield from``) the last reply's
    visible text and a block: a non-tool block unchanged, otherwise None.
    A tool block in the final reply after the limit is hidden, not executed,
    and gives None.

    Whenever the turn does not complete (any exception, including
    ``OperationCancelled``, ``OperationTimedOut``, ``LLMError`` and
    ``KeyboardInterrupt``, or ``close()`` / ``GeneratorExit``), trim
    ``session.messages`` back to its length before the turn, then re-raise.
    ``ChatSession.send`` saves each finished round, so this leaves no partial
    rounds (same idea as the ``completed`` flag in ``ChatSession.send``).
    """
    raise NotImplementedError("T18: run_with_tools is not implemented")
