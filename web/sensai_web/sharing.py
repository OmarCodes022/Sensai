"""X3 public links in the page: propose (checked, nothing written), then publish only on the creator's yes."""
from sensai.share import Shares, ShareError
from sensai_web.errors import ApiError


def make_shares(settings) -> Shares:
    return Shares(settings.shares_dir, settings.share_host, settings.share_port)


def listing(app) -> dict:
    return {"items": [{"token": t, "url": app.shares.url(t)} for t in app.shares.list()], "port": app.shares.port}


def propose(app, section: object) -> dict:
    try:
        token, url, text = app.shares.propose(app.guard, app.campaign.latest(), section if isinstance(section, str) else "")
    except ShareError as exc:
        raise ApiError(400, "not_shared", str(exc)) from None
    with app.mutex:
        app.pending_share = (token, text)
    return {"token": token, "url": url, "content": text, "section": section}


def confirm(app, token: object, approved: object) -> dict:
    with app.mutex:
        pending, app.pending_share = app.pending_share, None
    if pending is None or pending[0] != token:
        raise ApiError(409, "no_pending_share", "There is no share waiting for confirmation.")
    if approved is True:
        app.shares.publish(*pending)
        return {"status": "shared", "url": app.shares.url(pending[0]), **listing(app)}
    return {"status": "discarded", **listing(app)}


def remove(app, token: str) -> dict:
    if not app.shares.remove(token):
        raise ApiError(404, "not_found", f"No share {token}.")
    return listing(app)
