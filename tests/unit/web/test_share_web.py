"""X3 in the page: propose, confirm, list and remove a public link."""

from sensai.campaign import apply, plan
from sensai.campaign.models import PostEdit


def test_a_share_is_published_only_after_confirm_and_can_be_removed(web, tmp_path, monkeypatch):
    monkeypatch.setenv("SENSAI_SHARES_DIR", str(tmp_path / "shares"))
    monkeypatch.setenv("SENSAI_SHARE_HOST", "192.168.1.20")
    page = web(["hi"])
    store = page.app.campaign
    apply(store, plan(store.latest(), "posts", PostEdit(op="add", caption="Your evening routine?", claim_ids=[]), page.app.guard.claims))
    p = page.call("POST", "/api/share", {"section": "posts"})[1]
    assert p["url"] == f"http://192.168.1.20:8766/s/{p['token']}" and "Your evening routine?" in p["content"]
    assert page.call("GET", "/api/shares")[1]["items"] == []
    done = page.call("POST", "/api/share/confirm", {"token": p["token"], "approved": True})[1]
    assert done["status"] == "shared" and [s["token"] for s in done["items"]] == [p["token"]]
    assert page.call("POST", "/api/share/confirm", {"token": p["token"], "approved": True})[0] == 409
    assert page.call("DELETE", f"/api/shares/{p['token']}")[1]["items"] == []
    assert page.call("GET", "/api/config")[1]["capabilities"]["share"] is True
