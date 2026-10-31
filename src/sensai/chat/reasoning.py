"""/think: a bounded plan, act/observe, draft, check, revise loop on a scratch session."""

from collections.abc import Callable, Generator
from dataclasses import dataclass
import json

from pydantic import BaseModel

from sensai.chat.blocks import BlockReader
from sensai.chat.session import ChatSession
from sensai.core.cancellation import CancellationToken
from sensai.core.errors import LLMError
from sensai.core.messages import Message
from sensai.core.ports import ToolCall, ToolResult
from sensai.llm.client import close_stream
from sensai.llm.structured import StructuredOutputError
from sensai.tools import ToolObserver, ToolRegistry, run_with_tools, tool_instructions

SHOWN_LINES = 6
SHOWN_CHARS = 500

PLAN_PROMPT = (
    "Request: {request}\n\n"
    "Before answering, write a short numbered plan (at most 5 steps) for this request. "
    "Say which tools may help ({tools}), or that none is needed. "
    "Write only the plan: do not answer yet and do not call a tool."
)
ACT_PROMPT = (
    "Now follow your plan and answer the request. Use a tool for every figure you compute "
    "or look up, and use only figures from tool results or from the conversation."
)
REVISE_PROMPT = (
    "A check found these problems in your answer:\n{problems}\n"
    "Fix every problem and keep what was right. You may use tools again. "
    "Reply with the corrected answer only."
)
NO_TOOLS = "\nAnswer without tools."
CHECK_PROMPT = (
    "You check a draft answer before the creator sees it. Compare it with the request, the plan, "
    "the tool results and the rules below. List each problem in one short sentence, such as a "
    "claim the rules do not approve, an invented number, a number that differs from the tool "
    "results, or a part of the request that is not answered. Set ok to true and leave problems "
    "empty only if there is no problem.\n\nRules:\n{rules}"
)
CHECK_INPUT = "Request:\n{request}\n\nPlan:\n{plan}\n\nTool results:\n{results}\n\nDraft:\n{draft}"


class Check(BaseModel):
    ok: bool
    problems: list[str] = []


@dataclass(frozen=True)
class Budget:
    steps: int = 8
    checks: int = 3

    def __post_init__(self):
        if type(self.steps) is not int or self.steps < 2:
            raise ValueError("steps must be an integer >= 2")
        if type(self.checks) is not int or self.checks < 1:
            raise ValueError("checks must be an integer >= 1")


@dataclass(frozen=True)
class Section:
    title: str


@dataclass(frozen=True)
class ThinkResult:
    answer: str
    rounds: int
    tool_calls: int
    unresolved: tuple[str, ...]
    checked: bool


def _plural(count, word):
    return f"{count} {word}{'' if count == 1 else 's'}"


def _line(text):
    """Text ending a section always ends its line."""
    return text if text.endswith("\n") else text + "\n"


def _arguments(call):
    return json.dumps(dict(call.arguments), ensure_ascii=False, separators=(",", ":"))


def _result_text(result):
    return result.error if result.error is not None else result.output


def _shown(text):
    """A tool call or result cut to 6 lines and 500 characters, with a ` …` marker."""
    lines = text.splitlines()
    shown = "\n".join(lines[:SHOWN_LINES])
    cut = len(lines) > SHOWN_LINES or len(shown) > SHOWN_CHARS
    return shown[:SHOWN_CHARS] + (" …" if cut else "")


def _scratch(session):
    scratch = ChatSession(session.client, session.model, session.messages[0].content)
    if session.system_prompt_changed:
        # A persona switch re-sends the active system prompt before each request; keep that.
        scratch.set_system_prompt(session.messages[0].content)
    scratch.messages = list(session.messages)
    return scratch


def _reply_without_tools(scratch, text, token):
    """One model step with no tool round; a final tool block is hidden, not executed."""
    reader = BlockReader()
    stream = scratch.send(text + NO_TOOLS, token)
    try:
        for chunk in stream:
            reader.feed(chunk)
    finally:
        close_stream(stream)
    visible, block = reader.finish()
    return visible, block if block is not None and "tool" not in block else None


def _act(scratch, registry, text, steps_left, token, observed, on_tool, emit):
    """Show the step's tool rounds; return (visible text, non-tool block, replies).

    With ``emit``, each round goes out as it happens, before the next model
    request; without it, the rounds are yielded with the next reply's text.
    """
    if steps_left < 2:
        return (*_reply_without_tools(scratch, text, token), 1)
    queue, pending = [], []

    def observe(call: ToolCall, result: ToolResult):
        # Text buffered so far came before this tool block: show it before Act.
        narration = "".join(pending)
        # The call and result always get a line, even when empty: it is the tool text.
        items = ([_line(narration)] if narration else []) + [
            Section("Act"), _line(_shown(f"{call.name}({_arguments(call)})")),
            Section("Observe"), _line(_shown(_result_text(result)))]
        pending.clear()
        observed.append((call, result))
        if emit is None:
            queue.extend(items)
        else:
            for item in items:
                emit(item)
        if on_tool is not None:
            on_tool(call, result)

    def flush():
        yield from queue
        queue.clear()

    calls = len(observed)
    stream = run_with_tools(scratch, registry, text, token, max_rounds=steps_left - 1,
                            on_tool=observe, new_question=False)
    try:
        while True:
            try:
                chunk = next(stream)
            except StopIteration as stop:
                visible, block = stop.value
                break
            yield from flush()
            pending.append(chunk)
        yield from flush()
    finally:
        stream.close()
    return visible, block, len(observed) - calls + 1


def _rules(session, registry):
    prompt = session.messages[0].content
    return prompt.removesuffix(tool_instructions(registry.definitions())).rstrip()


def _check(checker, model, rules, request, plan, observed, draft, token):
    results = "\n".join(f"- {call.name}({_arguments(call)}): {_result_text(result)}"
                        for call, result in observed) or "(none)"
    messages = [Message(role="system", content=CHECK_PROMPT.format(rules=rules)),
                Message(role="user", content=CHECK_INPUT.format(
                    request=request, plan=plan, results=results, draft=draft))]
    # complete() takes no token: Ctrl+C takes effect as soon as the call returns.
    token.raise_if_cancelled()
    check = checker.complete(model, messages, Check)
    token.raise_if_cancelled()
    problems = [problem.strip() for problem in check.problems if problem.strip()]
    if not check.ok and not problems:
        problems = ["the check did not pass but named no problem"]
    return problems


def think(session: ChatSession, registry: ToolRegistry, request: str, checker, *,
          new_token: Callable[[], CancellationToken], budget: Budget = Budget(),
          on_tool: ToolObserver | None = None,
          emit: Callable[[Section | str], None] | None = None,
          ) -> Generator[object, None, ThinkResult]:
    """Answer ``request`` step by step; yield ``Section`` labels and text chunks.

    The plan streams under ``Plan``. Each act/draft (or revise) step runs
    ``run_with_tools`` on a scratch copy of the conversation and shows every
    tool round as ``Act``/``Observe``, then its answer under ``Draft`` (or
    ``Revise``). ``checker.complete(model, messages, Check)`` reviews each
    answer and passes only with ``ok`` and no problems; problems lead to a
    revision while the budget allows, else to ``Unresolved``. Every model
    reply is one of ``budget.steps``; each check is one of ``budget.checks``.
    A ``StructuredOutputError`` from the check ends the loop under
    ``Check unavailable`` with ``checked=False``.

    ``emit(item)``, if given, receives each finished tool round (the text
    before its block, ``Act``, the call, ``Observe``, the result) as soon as
    it ends, instead of the stream. Each step gets a fresh token from
    ``new_token()``. ``session`` is never
    modified; any other error (cancellation, timeout, ``LLMError``,
    ``KeyboardInterrupt``) propagates.
    """
    scratch = _scratch(session)
    registry.start_question()  # One count for the whole /think, not one per step.
    rules = _rules(session, registry)
    tools = ", ".join(definition.name for definition in registry.definitions()) or "no tools"
    yield Section("Plan")
    reader, printed = BlockReader(), 0
    stream = scratch.send(PLAN_PROMPT.format(request=request, tools=tools), new_token())
    try:
        for chunk in stream:
            visible = reader.feed(chunk)
            printed += len(visible)
            if visible:
                yield visible
    finally:
        close_stream(stream)
    plan, _ = reader.finish()
    if plan[printed:]:
        yield plan[printed:]
    if plan and not plan.endswith("\n"):
        yield "\n"
    steps_left, checks_left = budget.steps - 1, budget.checks
    observed, rounds, prompt, title = [], 0, ACT_PROMPT, "Draft"
    while True:
        visible, block, used = yield from _act(scratch, registry, prompt, steps_left,
                                               new_token(), observed, on_tool, emit)
        draft = visible.strip()
        if not draft and block is None:  # Only a hidden tool block: nothing to show or keep.
            raise LLMError("model returned no visible answer")
        # A reply holding only a non-tool block has no visible text: keep the raw reply.
        draft = draft or scratch.messages[-1].content.strip()
        steps_left -= used
        rounds += 1
        yield Section(title)
        yield _line(draft)
        try:
            problems = _check(checker, session.model, rules, request, plan, observed, draft,
                              new_token())
        except StructuredOutputError:
            yield Section("Check unavailable")
            unresolved, checked = (), False
            break
        checks_left -= 1
        if not problems:
            yield Section("Check — ok")
            unresolved, checked = (), True
            break
        yield Section(f"Check — {_plural(len(problems), 'problem')}")
        for problem in problems:
            yield _line(f"- {problem}")
        if steps_left < 1 or checks_left < 1:
            yield Section("Unresolved")
            for problem in problems:
                yield _line(f"- {problem}")
            unresolved, checked = tuple(problems), True
            break
        prompt = REVISE_PROMPT.format(problems="\n".join(f"- {problem}" for problem in problems))
        title = "Revise"
    tool_calls = len(observed)
    yield Section(f"Final answer ({_plural(rounds, 'round')}, {_plural(tool_calls, 'tool call')})")
    yield _line(draft)
    return ThinkResult(draft, rounds, tool_calls, unresolved, checked)
