"""Ask the model for one schema-forced edit, check it against the document and the brand file, then apply it.

A change is planned first (before/after), so an approved section can be confirmed before it is written.
"""
import json
import re
from dataclasses import dataclass
from datetime import date, timedelta

from sensai.campaign.document import CampaignError, CampaignStore, now
from sensai.campaign.models import EDIT_SCHEMAS, EDITABLE, SECTIONS, Campaign, Entry, EntryEdit, Post, PostEdit
from sensai.core.messages import Message

TIME = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d\Z")
EDIT_PROMPT = (
    "You edit ONE section of the weekly Instagram campaign of Nadia, owner of the skincare brand Serein Studio. "
    "Answer with exactly one edit as JSON in the given schema: op add, replace or remove; id of the item to replace "
    "or remove (null to add). Post captions are drafts in a warm, simple, honest voice and may only state product "
    "facts from the approved claims, word for word, listing their ids in claim_ids. Calendar entries use dates inside the week, "
    "time HH:MM and the id of an existing post; turn day names into dates with the dates table."
)


@dataclass(frozen=True)
class Change:
    section: str
    action: str          # e.g. "replace post P1"
    before: str | None
    after: str | None
    doc: Campaign        # the document with the change applied (not saved yet)


def editable(doc: Campaign, section: str) -> None:
    if section not in SECTIONS:
        raise CampaignError(f"unknown section {section!r}: use posts, replies, report or calendar")
    if section not in EDITABLE:
        raise CampaignError(f"the {section} section is filled only by the weekly run, not by chat edits")


def ask(checker, model: str, doc: Campaign, section: str, request: str, claims) -> object:
    """The model's edit, forced into the section's schema (StructuredOutputError or LLMError on failure)."""
    editable(doc, section)
    monday = date.fromisoformat(doc.start)
    days = {(monday + timedelta(days=i)).strftime("%A"): (monday + timedelta(days=i)).isoformat() for i in range(7)}
    context = {"week": doc.week, "start": doc.start, "end": doc.end, "dates": days,
               "items": [i.model_dump() for i in getattr(doc.sections, section).items],
               "posts": [p.id for p in doc.sections.posts.items],
               "approved_claims": [{"id": c.claim_id, "text": c.exact_text} for c in claims.approved]}
    messages = [Message(role="system", content=EDIT_PROMPT),
                Message(role="user", content=f"Section: {section}\nDocument: {json.dumps(context, ensure_ascii=False)}\n"
                                             f"Request: {request}")]
    return checker.complete(model, messages, EDIT_SCHEMAS[section])


def _next_id(prefix: str, ids: list[str]) -> str:
    numbers = [int(i[1:]) for i in ids if i[:1] == prefix and i[1:].isdigit()]
    return f"{prefix}{max(numbers, default=0) + 1}"


def _post(edit: PostEdit, doc: Campaign, claims, item_id: str) -> Post:
    if not edit.caption or not edit.caption.strip():
        raise CampaignError("the post has no caption")
    approved = {c.claim_id: c.exact_text for c in claims.approved}
    bad = [c for c in edit.claim_ids if c not in approved]
    if bad:
        raise CampaignError(f"claim {', '.join(bad)} is not approved and in date in the brand file")
    caption = edit.caption.strip()
    # A claim the caption cites, by id or by its wording, is listed even if the model forgot it.
    cited = [i for i, text in approved.items() if re.search(rf"\b{i}\b", caption) or text.lower() in caption.lower()]
    claim_ids = list(dict.fromkeys([*edit.claim_ids, *cited]))
    reworded = [i for i in claim_ids if approved[i].lower() not in caption.lower()]
    if reworded:  # "for 8 hours" is not "for up to 8 hours".
        raise CampaignError(f"claim {', '.join(reworded)} must keep its approved wording: "
                            + "; ".join(f'"{approved[i]}"' for i in reworded))
    return Post(id=item_id, caption=caption, claim_ids=claim_ids)


def _entry(edit: EntryEdit, doc: Campaign, item_id: str) -> Entry:
    try:
        day = date.fromisoformat(edit.date or "")
    except ValueError:
        raise CampaignError("the entry needs a date as YYYY-MM-DD") from None
    if not doc.start <= day.isoformat() <= doc.end:
        raise CampaignError(f"{day.isoformat()} is outside the week {doc.start} to {doc.end}")
    if not edit.time or not TIME.match(edit.time):
        raise CampaignError("the entry needs a time as HH:MM")
    if edit.post_id not in {p.id for p in doc.sections.posts.items}:
        raise CampaignError(f"post {edit.post_id} does not exist")
    return Entry(id=item_id, date=day.isoformat(), time=edit.time, post_id=edit.post_id, theme=(edit.theme or "").strip() or "Post")


def _show(item) -> str:
    return item.caption if isinstance(item, Post) else f"{item.date} {item.time} {item.channel} {item.post_id}: {item.theme}"


def plan(doc: Campaign, section: str, edit, claims) -> Change:
    """Check one edit and return the document with it applied; CampaignError if anything is wrong."""
    editable(doc, section)
    if not isinstance(edit, EDIT_SCHEMAS[section]):
        raise CampaignError("the edit does not match the section's schema")
    new = doc.model_copy(deep=True)
    part = getattr(new.sections, section)
    ids = [i.id for i in part.items]
    noun, prefix = ("post", "P") if section == "posts" else ("entry", "E")
    if edit.op in ("replace", "remove") and edit.id not in ids:
        raise CampaignError(f"{noun} {edit.id} does not exist")
    item_id = _next_id(prefix, ids) if edit.op == "add" else edit.id
    before = _show(part.items[ids.index(item_id)]) if edit.op != "add" else None
    if section == "posts" and edit.op == "remove" and any(e.post_id == item_id for e in new.sections.calendar.items):
        raise CampaignError(f"post {item_id} is used in the calendar: remove those entries first")
    if edit.op == "remove":
        part.items = [i for i in part.items if i.id != item_id]
        after = None
    else:
        item = _post(edit, doc, claims, item_id) if section == "posts" else _entry(edit, doc, item_id)
        part.items = [item if i.id == item_id else i for i in part.items] if edit.op == "replace" else [*part.items, item]
        after = _show(item)
    new.updated_at = now()
    return Change(section, f"{'add' if edit.op == 'add' else edit.op} {noun} {item_id}", before, after, new)


def apply(store: CampaignStore, change: Change) -> str:
    return store.save(change.doc)


def approve(store: CampaignStore, doc: Campaign, section: str) -> Campaign:
    if section not in SECTIONS:
        raise CampaignError(f"unknown section {section!r}: use posts, replies, report or calendar")
    new = doc.model_copy(deep=True)
    part = getattr(new.sections, section)
    if part.status != "approved":
        part.status, part.approved_at, new.updated_at = "approved", now(), now()
        store.save(new)
    return new


def overview(doc: Campaign) -> list[str]:
    s = doc.sections
    report = s.report.item
    figures = (f"reached {report.accounts_reached:,} · engaged {report.accounts_engaged:,} · rate {report.engagement_rate}"
               if report and report.accounts_reached is not None else "no data yet")
    rows = [("Posts", f"({len(s.posts.items)})", s.posts.status), ("DM replies", f"({len(s.replies.items)})", s.replies.status),
            ("Report", "", f"{s.report.status}: {figures}"), ("Calendar", f"({len(s.calendar.items)})", s.calendar.status)]
    lines = [f"Week {doc.week} ({doc.start} to {doc.end}, {doc.timezone})"]
    lines += [f"{name} {count}".strip().ljust(18, ".") + f" {status}" for name, count, status in rows]
    lines += [f"  {p.id}: {p.caption}" + (f" [{', '.join(p.claim_ids)}]" if p.claim_ids else "") for p in s.posts.items]
    lines += [f"  {e.id}: {e.date} {e.time} {e.channel} {e.post_id} · {e.theme}" for e in s.calendar.items]
    return lines
