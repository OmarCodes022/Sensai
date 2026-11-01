"""The four outputs of the weekly run (T45): model drafts, then the same checks as a chat or a campaign edit.

`ask(instructions, request, schema)` returns one schema-validated answer. Every generated text goes
through the guardrails' output check; a refused one gets one rewrite, told why, then is dropped.
"""
import re
from dataclasses import dataclass
from datetime import date, timedelta

from pydantic import BaseModel, Field

from sensai.campaign import CampaignError, plan
from sensai.campaign.models import EntryEdit, PostEdit, Reply, Report
from sensai.core.errors import SensaiError
from sensai.guardrails.rules import message_for
from sensai.weekly.inputs import Figures

MIN_ITEMS = 3  # posts and calendar entries
MEDICAL = ("If they ask whether a product fixes a skin condition, say kindly that our products are cosmetics, "
           "not medicines, and that a dermatologist is the right person to ask; do not repeat their words.")
AVOID = "Never use the words cure, heal, treat, clinically, guaranteed or eliminate, even to deny them."


@dataclass(frozen=True)
class Outcome:
    name: str
    ok: bool
    detail: str


class Suggestion(BaseModel):
    text: str = Field(description="a short, kind reply suggestion; it is never sent")


class PostDraft(BaseModel):
    caption: str = Field(description="the full Instagram caption, in the brand voice")
    claim_ids: list[str] = Field(description="ids of the approved claims the caption uses, word for word")


class PostDrafts(BaseModel):
    posts: list[PostDraft]


class EntryDraft(BaseModel):
    date: str = Field(description="YYYY-MM-DD, a date from the table")
    time: str = Field(description="HH:MM, 24-hour, for example 18:30")
    post_id: str = Field(description="one of the post ids given")
    theme: str = Field(description="a short theme")


class EntryDrafts(BaseModel):
    entries: list[EntryDraft]


class Reading(BaseModel):
    interpretation: str = Field(description="two short sentences on what the figures say; no new numbers")


def _checked(guard, ask, instructions: str, request: str, schema, text_of):
    """(answer, "") once the guardrails allow its text, or (None, why) after one rewrite."""
    answer = ask(instructions, request, schema)
    decision = guard.inspect(text_of(answer), "output")
    if not decision.allowed:
        why = message_for(decision.reason)
        answer = ask(instructions, f"{request}\n\nYour last answer was refused: {why} Rewrite it. {AVOID}", schema)
        decision = guard.inspect(text_of(answer), "output")
        if not decision.allowed:
            return None, message_for(decision.reason)
    return answer, ""


def _time(text: str) -> str:
    """"10:00 AM", "6:30 pm" or "18h00" as HH:MM; anything else is left for the campaign check to refuse."""
    found = re.fullmatch(r"\s*(\d{1,2})\s*[:h.]\s*(\d{2})\s*([ap]\.?m\.?)?\s*", text or "", re.I)
    if not found:
        return text
    hour, minute, half = int(found[1]), found[2], (found[3] or "").lower()[:1]
    hour = hour % 12 + (12 if half == "p" else 0) if half else hour
    return f"{hour:02d}:{minute}"


def _claim_ids(given: list[str], claims) -> list[str]:
    """Models often write a claim's wording where its id belongs: map that wording back to the id."""
    by_text = {c.exact_text.lower(): c.claim_id for c in claims.approved}
    return [next((i for text, i in by_text.items() if text in c.lower()), c) for c in given]


def report(doc, figs: Figures, ask, guard, instructions: str, extracted_at: str) -> Outcome:
    request = (f"Week {figs.start} to {figs.end}: {figs.reached:,} accounts reached, {figs.engaged:,} engaged, "
               f"engagement rate {figs.rate}. Interpret these figures for the creator.")
    try:  # The figures stand on their own: a failed interpretation only leaves it out.
        answer, why = _checked(guard, ask, instructions, request, Reading, lambda a: a.interpretation)
    except SensaiError as exc:
        answer, why = None, f"the model failed: {exc}"
    doc.sections.report.item = Report(
        period_start=figs.start, period_end=figs.end, timezone=doc.timezone, source=figs.source,
        extracted_at=extracted_at, accounts_reached=figs.reached, accounts_engaged=figs.engaged,
        engagement_rate=figs.rate, interpretation=answer.interpretation if answer else "")
    note = f" · interpretation left out: {why}" if why else ""
    return Outcome("Report", True, f"reached {figs.reached:,} · engaged {figs.engaged:,} · rate {figs.rate} "
                                   f"({figs.source}){note}")


def replies(doc, dms: list[dict], ask, guard, instructions: str) -> Outcome:
    kept, left_out = [], []
    for dm in dms:
        question = dm.get("question")
        if not dm.get("eligible") or not dm.get("privacy_safe"):
            left_out.append(dm.get("rejection_reason") or "not eligible")  # Its text is never read further.
            continue
        if not isinstance(question, str) or not question.strip():
            left_out.append("empty question")
            continue
        decision = guard.inspect(question, "input")
        if not decision.allowed:
            left_out.append(message_for(decision.reason))
            continue
        answer, why = _checked(guard, ask, f"{instructions}\n{AVOID}",
                               f"A follower asks: {decision.text}\nSuggest a reply. {MEDICAL}", Suggestion, lambda a: a.text)
        if answer is None:
            left_out.append(f"reply refused: {why}")
            continue
        kept.append(Reply(case_key=f"Q{len(kept) + 1}", question=decision.text, suggestion=answer.text))
    section = doc.sections.replies
    eligible = sum(1 for dm in dms if dm.get("eligible") and dm.get("privacy_safe"))
    section.items, section.eligible, section.left_out = kept, eligible, left_out
    reasons = f" · {len(left_out)} DMs left out ({', '.join(left_out)})" if left_out else ""
    ok = bool(kept) or not section.eligible
    return Outcome("DM replies", ok, f"{len(kept)} suggestion{'s' * (len(kept) != 1)}{reasons}")


def posts(doc, ask, guard, claims, instructions: str, examples: list[str]):
    """(doc with the new posts, outcome); fewer than 3 usable posts fails and changes nothing."""
    shown = "\n".join(f"- {caption}" for caption in examples) or "- (none)"
    request = (f"Write {MIN_ITEMS + 1} different Instagram post captions for the week of {doc.start}. Each caption "
               "either quotes one approved claim exactly, as its own sentence copied character for character (for "
               "example: Hydrates skin for up to 8 hours.), or makes no product promise at all (a routine tip, a "
               "question to followers). Never write claim ids in the caption: list them in claim_ids.\n"
               f"Last week's approved captions, for the voice:\n{shown}")
    draft, dropped = doc.model_copy(deep=True), []
    draft.sections.posts.items = []
    for _ in range(2):  # One more try when too few captions pass the checks, told why.
        for item in ask(f"{instructions}\n{AVOID}", request, PostDrafts).posts:
            decision = guard.inspect(item.caption, "output")
            if not decision.allowed:
                dropped.append(message_for(decision.reason))
                continue
            if any(p.caption == decision.text for p in draft.sections.posts.items):
                continue  # The same caption twice is one post.
            try:
                edit = PostEdit(op="add", caption=decision.text, claim_ids=_claim_ids(item.claim_ids, claims))
                draft = plan(draft, "posts", edit, claims).doc
            except CampaignError as exc:
                dropped.append(str(exc))
        if len(draft.sections.posts.items) >= MIN_ITEMS:
            break
        request += "\n\nSome captions were refused: " + "; ".join(dropped) + ". Write new ones that pass."
    items = draft.sections.posts.items
    used = sorted({c for p in items for c in p.claim_ids})
    detail = f"{len(items)} drafts" + (f" (claims {', '.join(used)})" if used else "")
    detail += f" · {len(dropped)} left out ({'; '.join(dropped)})" if dropped else ""
    if len(items) < MIN_ITEMS:
        return doc, Outcome("Posts", False, f"only {detail}; at least {MIN_ITEMS} are needed")
    return draft, Outcome("Posts", True, detail)


def calendar(doc, ask, guard, instructions: str):
    """(doc with the entries, outcome); entries must point at real posts and fall inside the week."""
    posts_ = doc.sections.posts.items
    if not posts_:
        return doc, Outcome("Calendar", False, "no posts to schedule")
    start = date.fromisoformat(doc.start)
    days = "\n".join(f"- {(start + timedelta(days=i)):%A}: {(start + timedelta(days=i)).isoformat()}" for i in range(7))
    shown = "\n".join(f"- {p.id}: {p.caption}" for p in posts_)
    request = (f"Plan {max(MIN_ITEMS, len(posts_))} calendar entries for the week, one per post where you can.\n"
               f"Dates:\n{days}\nPosts:\n{shown}")
    drafts = ask(instructions, request, EntryDrafts).entries
    draft, dropped = doc.model_copy(deep=True), []
    draft.sections.calendar.items = []
    for item in drafts:
        decision = guard.inspect(item.theme, "output")
        if not decision.allowed:
            dropped.append(message_for(decision.reason))
            continue
        edit = EntryEdit(op="add", date=item.date, time=_time(item.time), post_id=item.post_id, theme=decision.text)
        try:
            draft = plan(draft, "calendar", edit, None).doc
        except CampaignError as exc:
            dropped.append(str(exc))
    entries = sorted(draft.sections.calendar.items, key=lambda e: (e.date, e.time))
    detail = f"{len(entries)} entries" + (f", {entries[0].date} to {entries[-1].date}" if entries else "")
    detail += f" · {len(dropped)} left out ({'; '.join(dropped)})" if dropped else ""
    if len(entries) < MIN_ITEMS:
        return doc, Outcome("Calendar", False, f"only {detail}; at least {MIN_ITEMS} are needed")
    return draft, Outcome("Calendar", True, detail)
