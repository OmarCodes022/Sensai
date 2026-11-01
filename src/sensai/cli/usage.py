"""EV3 in the terminal: one log line per chat turn, with the tools it used."""
import json

from sensai import usage_log


def tool_entry(call, result) -> dict:
    arguments = json.dumps(dict(call.arguments), ensure_ascii=False)
    return {"tool": call.name, "input": arguments[:200], "ms": None, "ok": result.error is None}


def log_turn(session, question: str, completed: bool, outcome: str | None, tools: list[dict], meter, persona) -> None:
    answer = session.messages[-1].content if completed and session.messages[-1].role == "assistant" else ""
    usage_log.record("chat", session.model, question, answer, persona=persona, tools=tools,
                     latency_ms=meter.latency_ms if meter is not None else None,
                     prompt_tokens=meter.prompt_tokens if meter is not None else None,
                     output_tokens=meter.output_tokens if meter is not None else None,
                     error=None if completed else outcome or "failed")
