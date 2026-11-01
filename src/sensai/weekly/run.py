"""One weekly run (T45): read the folder, prepare the four outputs, save the campaign document once.

Each output fails on its own (a missing file, a model error, too few usable items) and leaves its
section unchanged. Approved sections are never touched. Nothing is sent or published: the only
write is the campaign document, at the end, so Ctrl+C before it saves nothing.
"""
import os
from datetime import date, timedelta

from sensai.campaign import CampaignStore
from sensai.campaign.document import coming_week, now
from sensai.campaign.models import Campaign
from sensai.core.errors import SensaiError
from sensai.guardrails import GuardrailConfigError, load_guardrail
from sensai.guardrails.rules import load_claims
from sensai.schedule import brand_block
from sensai.weekly import outputs
from sensai.weekly.inputs import InputError, brand_file, dms, earlier_posts, figures
from sensai.weekly.outputs import Outcome

INSTRUCTIONS = ("You prepare the weekly Instagram outputs of Nadia, owner of the skincare brand Serein Studio: "
                "warm, simple, honest, no medical promises. Everything you write is a draft she reviews; "
                "nothing is sent or published.")


def _week(figs) -> tuple[str, date, date]:
    """The week after the report's period, else the coming week."""
    if figs is None:
        return coming_week()
    monday = date.fromisoformat(figs.end) + timedelta(days=1)
    monday -= timedelta(days=monday.weekday())
    year, number, _ = monday.isocalendar()
    return f"{year}-W{number:02d}", monday, monday + timedelta(days=6)


def _document(store: CampaignStore, week: str, start: date, end: date) -> Campaign:
    if os.path.exists(store.path(week)):
        return store.load(week)
    return Campaign(week=week, start=start.isoformat(), end=end.isoformat(), created_at=now(), updated_at=now())


def run_week(folder: str, store: CampaignStore, ask, rules_file: str | None = None, on_step=lambda outcome: None):
    """(header, outcomes, saved path or None). `on_step(outcome)` hears each output as it finishes."""
    outcomes: list[Outcome] = []

    def done(outcome: Outcome) -> None:
        outcomes.append(outcome)
        on_step(outcome)

    try:
        figs, figures_error = figures(folder), ""
    except InputError as exc:
        figs, figures_error = None, str(exc)
    week, start, end = _week(figs)
    doc = _document(store, week, start, end)
    try:
        brand = brand_file(folder)
        claims, guard, instructions = load_claims(brand), load_guardrail(rules_file, brand), f"{INSTRUCTIONS}\n\n{brand_block(brand)}"
        brand_error = ""
    except (InputError, GuardrailConfigError) as exc:
        brand, claims, brand_error = None, None, str(exc)
        guard, instructions = load_guardrail(rules_file, None), INSTRUCTIONS
    sections = doc.sections

    def attempt(name: str, approved: bool, missing: str, work) -> None:
        if approved:
            return done(Outcome(name, True, "approved, left unchanged"))
        if missing:
            return done(Outcome(name, False, missing))
        try:
            done(work())
        except InputError as exc:
            done(Outcome(name, False, str(exc)))
        except SensaiError as exc:  # The model failed or answered outside the schema: only this output fails.
            done(Outcome(name, False, f"the model failed: {exc}"))

    attempt("Report", sections.report.status == "approved", figures_error,
            lambda: outputs.report(doc, figs, ask, guard, INSTRUCTIONS, now()))
    attempt("DM replies", sections.replies.status == "approved", brand_error,
            lambda: outputs.replies(doc, dms(folder), ask, guard, instructions))

    def posts_and_keep():
        nonlocal doc
        doc, outcome = outputs.posts(doc, ask, guard, claims, instructions, earlier_posts(folder))
        return outcome

    def calendar_and_keep():
        nonlocal doc
        doc, outcome = outputs.calendar(doc, ask, guard, instructions)
        return outcome

    # Posts the approved calendar points at stay as they are.
    attempt("Posts", sections.posts.status == "approved" or sections.calendar.status == "approved",
            brand_error, posts_and_keep)
    attempt("Calendar", doc.sections.calendar.status == "approved", "", calendar_and_keep)
    doc.updated_at = now()
    saved = store.save(doc) if any(o.ok for o in outcomes) else None
    report_week = f"Report week {figs.start} to {figs.end} · " if figs else ""
    return f"{report_week}calendar for {doc.start} to {doc.end}", outcomes, saved
