"""Private export in the page: /api/export and the automatic campaign export after changes."""
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
    monkeypatch.setenv("SENSAI_EXPORTS_DIR", str(tmp_path / "exports"))
    return web(["Hello there."])


def test_export_writes_the_conversation_and_reports_no_campaign(page, tmp_path):
    page.stream({"text": "Hi lea@x.com"})
    body = page.call("POST", "/api/export")[1]
    assert body["campaign"] == {"none": True} and len(body["conversation"]["files"]) == 2
    md = Path(body["conversation"]["files"][1]).read_text()
    assert "Hi [redacted]" in md and "Hello there." in md
    assert page.call("GET", "/api/config")[1]["capabilities"]["export"] is True


def test_a_campaign_edit_is_exported_and_a_refusal_keeps_the_previous_export(page, tmp_path):
    page.app.checker = Checker({"op": "add", "caption": "Hydrates skin for up to 8 hours.", "claim_ids": ["C01"]})
    body = page.call("POST", "/api/campaign/edit", {"section": "posts", "request": "write one"})[1]
    md = Path(body["export"]["files"][1])
    assert "Hydrates skin for up to 8 hours." in md.read_text()
    page.app.checker = Checker({"op": "add", "caption": "A word on clinically proven results"})
    body = page.call("POST", "/api/campaign/edit", {"section": "posts", "request": "add a claim"})[1]
    assert body["export"] == {"refused": "unsupported_claim"} and "clinically" not in md.read_text()
