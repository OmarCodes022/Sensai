"""The fact sheet (M3) in the page: the store, the creator's own edits, and settling a turn's changes."""
import json
import os
from datetime import date

from sensai.chat.facts import FACT_ID, MAX_TEXT, PROFILE, FactMemory
from sensai.core.messages import Message
from sensai.core.ports import Fact, PortError
from sensai_web.datafiles import DEFAULT_DIR
from sensai_web.errors import ApiError


class AppFactStore:
    """FactStorePort over the app's database: SQLite connections are per thread, so each call opens its own."""

    def __init__(self, app):
        self._app = app

    def list_for(self, profile_id: str):
        with self._app.creator_storage() as creator:
            return creator.facts.list_for(profile_id)

    def upsert(self, profile_id: str, fact: Fact) -> None:
        with self._app.creator_storage() as creator:
            creator.facts.upsert(profile_id, fact)

    def delete(self, profile_id: str, fact_id: str) -> None:
        with self._app.creator_storage() as creator:
            creator.facts.delete(profile_id, fact_id)


def make_memory(app) -> FactMemory:
    return FactMemory(AppFactStore(app))


def listing(app) -> dict:
    return {"items": [{"id": f.id, "text": f.text, "source": f.source} for f in app.memory.facts()]}


def put(app, fact_id: str, text: object) -> dict:
    """The creator writes a fact by hand (source: edited <date>)."""
    if not FACT_ID.match(fact_id):
        raise ApiError(400, "bad_fact", "Use entity.topic in lowercase with dashes, e.g. hydra-glow-serum.price.")
    if not isinstance(text, str) or not text.strip() or "\n" in text.strip() or len(text) > MAX_TEXT:
        raise ApiError(400, "bad_fact", f"Write the fact on one line, at most {MAX_TEXT} characters.")
    with app.mutex:
        app.require_idle()
        app.memory.store.upsert(PROFILE, Fact(fact_id, " ".join(text.split()), f"edited {date.today().isoformat()}"))
        app.active.session.messages[0] = Message(role="system", content=app.system_prompt(app.active.persona_id))
    return listing(app)


def delete(app, fact_id: str) -> dict:
    with app.mutex:
        app.require_idle()
        if all(f.id != fact_id for f in app.memory.facts()):
            raise ApiError(404, "not_found", f"No fact named {fact_id}.")
        app.memory.store.delete(PROFILE, fact_id)
        app.active.session.messages[0] = Message(role="system", content=app.system_prompt(app.active.persona_id))
    return listing(app)


def settle(app, active, completed: bool, emit) -> None:
    """After a turn: write the queued changes if it completed (and say what changed), drop them otherwise."""
    if not completed:
        app.memory.drop()
        return
    try:
        lines = app.memory.commit()
    except PortError as exc:
        app.memory.drop()
        emit({"type": "warning", "code": "storage", "message": f"Facts not saved: {exc}"})
        return
    if lines:
        emit({"type": "memory", "changes": [line.removeprefix("Memory: ") for line in lines]})
        active.session.messages[0] = Message(role="system", content=app.system_prompt(active.persona_id))


def claims(app) -> dict:
    """The approved-claims register from brand.json in the data folder (read-only), or none."""
    path = os.path.join(app.data.path or DEFAULT_DIR, "brand.json")
    try:
        with open(path, encoding="utf-8") as f:
            brand = json.load(f)
        items = [{"id": c["id"], "product": p.get("name", p.get("id", "")), "text": c["text"], "source": c.get("source"),
                  "from": c.get("valid_from"), "until": c.get("valid_until"), "approved": bool(c.get("approved"))}
                 for p in brand.get("products", []) for c in p.get("claims", [])]
    except FileNotFoundError:
        return {"file": None, "items": []}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ApiError(422, "bad_brand_file", f"brand.json could not be read: {exc}") from None
    return {"file": "brand.json", "items": items}
