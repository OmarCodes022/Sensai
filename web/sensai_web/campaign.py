"""The campaign document (M4, T5) in the page, with A3: an approved section changes only after a confirmation."""
import secrets

from sensai.campaign import CampaignError, apply, approve, ask, plan
from sensai.campaign.edits import editable
from sensai.core.errors import LLMError
from sensai.llm.structured import StructuredOutputError
from sensai_web.errors import ApiError
from sensai_web.exports import campaign_export


def _doc(app) -> dict:
    doc = app.campaign.latest()
    return {**doc.model_dump(), "file": app.campaign.path(doc.week)}


def show(app) -> dict:
    try:
        return _doc(app)
    except CampaignError as exc:
        raise ApiError(422, "campaign_unreadable", str(exc)) from None


def edit(app, section: object, request: object) -> dict:
    """Ask the model for one edit; apply it, or hold it for confirmation when the section is approved."""
    if not isinstance(section, str) or not isinstance(request, str) or not request.strip():
        raise ApiError(400, "bad_request", "Choose posts or calendar and write what to change.")
    try:
        doc = app.campaign.latest()
        editable(doc, section)
        change = plan(doc, section, ask(app.checker, app.model, doc, section, request.strip(), app.guard.claims),
                      app.guard.claims)
    except CampaignError as exc:
        raise ApiError(400, "invalid_edit", str(exc)) from None
    except (StructuredOutputError, LLMError) as exc:
        raise ApiError(502, "no_valid_edit", f"No valid edit from the model ({exc}). Nothing changed.") from None
    described = {"section": section, "action": change.action, "where": app.campaign.path(doc.week),
                 "before": change.before, "after": change.after}
    if getattr(doc.sections, section).status == "approved":
        token = secrets.token_urlsafe(12)
        with app.mutex:
            app.pending_change = (token, change)
        return {"status": "confirm", "token": token, **described}
    apply(app.campaign, change)
    return {"status": "applied", **described, "doc": _doc(app), "export": campaign_export(app, change.doc)}


def confirm(app, token: object, approved: object) -> dict:
    with app.mutex:
        pending, app.pending_change = app.pending_change, None
    if pending is None or pending[0] != token:
        raise ApiError(409, "no_pending_change", "There is no change waiting for confirmation.")
    if approved is True:
        apply(app.campaign, pending[1])
        return {"status": "applied", "action": pending[1].action, "doc": _doc(app), "export": campaign_export(app, pending[1].doc)}
    return {"status": "discarded", "doc": _doc(app)}


def approve_section(app, section: object) -> dict:
    try:
        campaign_export(app, approve(app.campaign, app.campaign.latest(), section if isinstance(section, str) else ""))
    except CampaignError as exc:
        raise ApiError(400, "invalid_section", str(exc)) from None
    return _doc(app)
