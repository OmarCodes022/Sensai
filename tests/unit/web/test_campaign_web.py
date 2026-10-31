"""The campaign page API: the document, schema-forced edits, approval and the before/after confirmation (A3)."""
from pathlib import Path

import pytest

BRAND = str(Path(__file__).parents[2] / "fixtures" / "brand.json")


class Checker:
    def __init__(self, *edits):
        self.edits = list(edits)

    def complete(self, model, messages, schema):
        return schema(**self.edits.pop(0))


@pytest.fixture
def page(web, tmp_path, monkeypatch):
    monkeypatch.setenv("SENSAI_BRAND_FILE", BRAND)
    monkeypatch.setenv("SENSAI_CAMPAIGNS_DIR", str(tmp_path / "campaigns"))
    return web()


def edit(page, section, request, *edits):
    page.app.checker = Checker(*edits)
    return page.call("POST", "/api/campaign/edit", {"section": section, "request": request})


def test_the_document_and_a_direct_edit(page):
    doc = page.call("GET", "/api/campaign")[1]
    assert set(doc["sections"]) == {"posts", "replies", "report", "calendar"} and doc["file"].endswith(f"{doc['week']}.json")
    status, body = edit(page, "posts", "write a post", {"op": "add", "caption": "Hydrates skin for up to 8 hours.", "claim_ids": ["C01"]})
    assert status == 200 and body["status"] == "applied" and body["action"] == "add post P1"
    assert body["doc"]["sections"]["posts"]["items"][0]["claim_ids"] == ["C01"]
    assert page.call("GET", "/api/config")[1]["capabilities"]["campaign"] is True


def test_an_approved_section_waits_for_confirmation(page):
    edit(page, "posts", "a", {"op": "add", "caption": "First"})
    page.call("POST", "/api/campaign/approve", {"section": "posts"})
    body = edit(page, "posts", "b", {"op": "replace", "id": "P1", "caption": "Second"})[1]
    assert body["status"] == "confirm" and (body["before"], body["after"]) == ("First", "Second")
    assert page.call("POST", "/api/campaign/confirm", {"token": body["token"], "approved": False})[1]["status"] == "discarded"
    assert page.call("GET", "/api/campaign")[1]["sections"]["posts"]["items"][0]["caption"] == "First"
    body = edit(page, "posts", "c", {"op": "replace", "id": "P1", "caption": "Third"})[1]
    assert page.call("POST", "/api/campaign/confirm", {"token": "wrong", "approved": True})[0] == 409
    body = edit(page, "posts", "c", {"op": "replace", "id": "P1", "caption": "Third"})[1]
    done = page.call("POST", "/api/campaign/confirm", {"token": body["token"], "approved": True})[1]
    assert done["status"] == "applied" and done["doc"]["sections"]["posts"]["items"][0]["caption"] == "Third"
    assert done["doc"]["sections"]["posts"]["status"] == "approved"


def test_invalid_edits_are_400_and_change_nothing(page):
    status, body = edit(page, "posts", "x", {"op": "add", "caption": "Cures eczema", "claim_ids": ["C02"]})
    assert status == 400 and "C02" in body["error"]["message"]
    assert edit(page, "report", "x")[1]["error"]["code"] == "invalid_edit"
    assert page.call("GET", "/api/campaign")[1]["sections"]["posts"]["items"] == []
    assert page.call("POST", "/api/campaign/approve", {"section": "nope"})[0] == 400
