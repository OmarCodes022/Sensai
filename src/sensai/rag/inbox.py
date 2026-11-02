"""Customer DMs in document search: only the privacy-safe ones, redacted, without names or message ids.

The same rule as the weekly run: a DM flagged as not eligible or not privacy-safe is never read further,
and the others pass the guardrails' input check before they are indexed.
"""
import json

NAME = "dms.json"
HEADER = "---\nsource: customer-dms\ntitle: Customer questions (DMs, privacy-filtered)\n---\n\n"


def inbox_document(path: str, guard) -> str:
    """The indexable text of the inbox: one paragraph per usable question."""
    try:
        with open(path, encoding="utf-8") as f:
            dms = json.load(f).get("dms", [])
    except (OSError, ValueError, AttributeError):
        dms = []
    questions = []
    for dm in dms if isinstance(dms, list) else []:
        if not isinstance(dm, dict) or not dm.get("eligible") or not dm.get("privacy_safe"):
            continue
        question = dm.get("question")
        if not isinstance(question, str) or not question.strip():
            continue
        decision = guard.inspect(question, "input")
        if decision.allowed:
            questions.append(f"A customer asked: {decision.text.strip()}")
    return HEADER + "\n\n".join(questions)
