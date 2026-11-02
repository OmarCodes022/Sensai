"""Customer DMs in document search: only the privacy-safe ones, redacted, without names or message ids.

The same rule as the weekly run: a DM flagged as not eligible or not privacy-safe is never read further,
and the others pass the guardrails' input check before they are indexed.
"""
import json

NAME = "dms.json"
HEADER = "---\nsource: customer-dms\ntitle: Customer questions (DMs, privacy-filtered)\n---\n\n"
GROUP = 10  # Questions per search result: a short inbox comes back whole for "what DMs did I get?"


def inbox_document(path: str, guard) -> str:
    """The indexable text of the inbox: blocks of up to GROUP usable questions (one result lists them, for "what
    DMs did I get?"), then each question on its own (a topic search such as "shipping" finds the one it is about)."""
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
            questions.append(" ".join(decision.text.split()))
    blocks = ["Customer questions received by DM (privacy-filtered):\n" + "\n".join(f"- {q}" for q in questions[i:i + GROUP])
              for i in range(0, len(questions), GROUP)]
    return HEADER + "\n\n".join([*blocks, *(f"Customer question received by DM: {q}" for q in questions)])
