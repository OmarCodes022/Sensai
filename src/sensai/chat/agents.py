"""/team (A2): a researcher, a writer and a reviewer work on one brief, each seeing only what is handed to it.

The researcher turns the brief and the brand facts into notes (usable claims, claims to avoid, what is
missing). The writer drafts from the brief and the notes only. The reviewer checks the draft against
them; a rejected draft goes back to the writer with the problems, at most twice. The run yields
Section headings and text, like /think, and returns the final draft with any remaining disagreement.
"""
import json
from dataclasses import dataclass
from datetime import date

from pydantic import BaseModel

from sensai.chat.reasoning import Section
from sensai.core.messages import Message
from sensai.llm.client import close_stream
from sensai.llm.structured import StructuredOutputError

MAX_REVISIONS = 2


@dataclass(frozen=True)
class Agent:
    id: str
    name: str
    instructions: str
    model: str | None = None  # None: the chat's model


RESEARCHER = Agent("researcher", "Researcher", (
    "You are the researcher of a skincare brand's content team. From the brief and the brand facts, list the "
    "approved claims that may be used (with their source), the claims to avoid (not approved or expired, with "
    "why) and what information is missing. Use only the brand facts; if none are given, say so in missing."))
WRITER = Agent("writer", "Writer", (
    "You are the writer of a skincare brand's content team: warm, simple, honest, no medical promises. Write "
    "the requested post from the brief and the researcher's notes only. Use usable claims word for word and "
    "never a claim to avoid, even if the brief asks for it. Reply with the draft only."))
REVIEWER = Agent("reviewer", "Reviewer", (
    "You are the reviewer of a skincare brand's content team. Check the draft against the brief and the "
    "researcher's notes. List each problem in one short sentence: a claim that is not usable, a claim changed "
    "from its approved wording, a medical promise, a missing part of the brief. Approve only with no problem."))
AGENTS = (RESEARCHER, WRITER, REVIEWER)


class Usable(BaseModel):
    claim: str
    source: str


class Avoid(BaseModel):
    claim: str
    reason: str


class Notes(BaseModel):
    usable: list[Usable]
    avoid: list[Avoid]
    missing: list[str]


class Verdict(BaseModel):
    approved: bool
    problems: list[str] = []


@dataclass(frozen=True)
class TeamResult:
    answer: str          # the final draft, plus the disagreement or "Review unavailable"
    draft: str
    revisions: int
    approved: bool
    disagreement: tuple[str, ...]


def brand_facts(brand_file: str | None, today: date | None = None) -> str:
    """Every claim of the brand file with its status, so the researcher can say what to avoid and why."""
    if not brand_file:
        return ""
    today = today or date.today()
    with open(brand_file, encoding="utf-8") as f:
        products = json.load(f).get("products", [])
    lines = []
    for product in products:
        for claim in product.get("claims", []):
            until = claim.get("valid_until")
            status = (f"expired {until}" if until and date.fromisoformat(until) < today else
                      "not approved" if claim.get("approved") is not True else "approved")
            lines.append(f'- {product.get("name")}: "{claim.get("text")}" ({status}; source: {claim.get("source") or "none"})')
    return "\n".join(lines)


def _notes_text(notes: Notes) -> str:
    usable = "\n".join(f'- "{u.claim}" ({u.source})' for u in notes.usable) or "- none"
    avoid = "\n".join(f'- "{a.claim}" ({a.reason})' for a in notes.avoid) or "- none"
    missing = "\n".join(f"- {m}" for m in notes.missing) or "- nothing"
    return f"Usable claims:\n{usable}\nClaims to avoid:\n{avoid}\nMissing information:\n{missing}"


def _ask(checker, agent: Agent, model: str, request: str, schema, token):
    """A structured call takes no cancellation token: check it before and after."""
    token.raise_if_cancelled()
    messages = [Message(role="system", content=agent.instructions), Message(role="user", content=request)]
    answer = checker.complete(agent.model or model, messages, schema)
    token.raise_if_cancelled()
    return answer


def _write(client, model: str, request: str, token):
    """Stream the writer's draft; yields its chunks and returns the whole text."""
    messages = [Message(role="system", content=WRITER.instructions), Message(role="user", content=request)]
    stream, parts = client.stream(WRITER.model or model, messages, token), []
    try:
        for chunk in stream:
            parts.append(chunk)
            yield chunk
    finally:
        close_stream(stream)
    return "".join(parts).strip()


def label(agent: Agent, model: str) -> str:
    return f"{agent.name} ({agent.model or model})"


def team(brief: str, client, checker, model: str, facts: str, new_token):
    """Yield the steps and handoffs; return a TeamResult. Cancellation and LLM errors propagate."""
    yield Section(label(RESEARCHER, model))
    notes = _ask(checker, RESEARCHER, model, f"Brief:\n{brief}\n\nBrand facts:\n{facts or '(none were given)'}",
                 Notes, new_token())
    notes_text = _notes_text(notes)
    yield notes_text + "\n"
    yield Section(f"Researcher → Writer: {len(notes.usable)} usable claim(s), {len(notes.avoid)} to avoid")
    request = f"Brief:\n{brief}\n\nResearcher's notes:\n{notes_text}"
    revisions, problems = 0, []
    while True:
        yield Section(label(WRITER, model) + (f", revision {revisions}" if revisions else ""))
        draft = yield from _write(client, model, request if not problems else (
            f"{request}\n\nYour last draft:\n{draft}\n\nThe reviewer's problems:\n" +
            "\n".join(f"- {p}" for p in problems) + "\nFix every problem."), new_token())
        yield "\n"
        yield Section("Writer → Reviewer")
        try:
            verdict = _ask(checker, REVIEWER, model, f"Brief:\n{brief}\n\nResearcher's notes:\n{notes_text}\n\n"
                                                     f"Draft:\n{draft}", Verdict, new_token())
        except StructuredOutputError:  # An invalid verdict is never shown as approved.
            yield Section("Review unavailable")
            return TeamResult(f"{draft}\n\nReview unavailable.", draft, revisions, False, ())
        problems = [p for p in verdict.problems if p.strip()]
        if verdict.approved and not problems:
            yield Section(f"{label(REVIEWER, model)}: approved")
            return TeamResult(draft, draft, revisions, True, ())
        yield Section(f"{label(REVIEWER, model)}: rejected")
        yield "\n".join(f"- {p}" for p in problems or ["(no reason given)"]) + "\n"
        if revisions == MAX_REVISIONS:
            listed = "; ".join(problems) or "no reason given"
            return TeamResult(f"{draft}\n\nReviewer still disagrees: {listed}", draft, revisions, False, tuple(problems))
        yield Section(f"Reviewer → Writer: {len(problems)} problem(s)")
        revisions += 1
