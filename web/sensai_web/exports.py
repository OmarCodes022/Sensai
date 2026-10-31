"""Private export (X3) in the page: the open conversation and the week's campaign as files on this computer."""
from sensai.chat.saved_sessions import display_title
from sensai.export import ExportRefused


def campaign_export(app, doc) -> dict:
    """Export the campaign after a saved change; never raises (the page shows the outcome)."""
    try:
        return {"files": app.exporter.campaign(doc)}
    except ExportRefused as exc:
        return {"refused": str(exc)}
    except OSError as exc:
        return {"error": f"Campaign not exported: {exc.strerror or exc}"}


def export_all(app) -> dict:
    with app.mutex:
        active = app.active
        messages = list(active.session.messages)
        session_id, title = active.recorder.session_id, active.recorder.title
    title = title or display_title(None, messages[1:])
    try:
        conversation = {"files": app.exporter.session(session_id, title, messages)}
    except ExportRefused as exc:
        conversation = {"refused": str(exc)}
    except OSError as exc:
        conversation = {"error": f"Conversation not exported: {exc.strerror or exc}"}
    campaign = campaign_export(app, app.campaign.latest()) if app.campaign.has_any() else {"none": True}
    return {"conversation": conversation, "campaign": campaign}
