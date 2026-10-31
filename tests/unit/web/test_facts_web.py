"""The fact sheet in the page: the model's changes after a completed reply, and the creator's own edits."""
from sensai.core.cancellation import OperationCancelled

SAVE = '{"tool":"save_fact","arguments":{"id":"hydra-glow-serum.price","text":"Costs 29 €"}}'


def test_a_completed_reply_saves_the_fact_and_says_so(web):
    page = web([SAVE], ["Noted."], ["29 €"])
    _, events = page.stream({"text": "The serum costs 29 €."})
    assert {"type": "memory", "changes": ["added hydra-glow-serum.price"]} in events
    items = page.call("GET", "/api/facts")[1]["items"]
    assert [(f["id"], f["text"]) for f in items] == [("hydra-glow-serum.price", "Costs 29 €")]
    assert items[0]["source"].startswith("chat ")
    page.stream({"text": "Price?"})
    assert "- hydra-glow-serum.price: Costs 29 €" in page.client.calls[-1][0]


def test_an_interrupted_reply_saves_nothing(web):
    page = web([SAVE], ["partial", OperationCancelled("operation cancelled")])
    _, events = page.stream({"text": "29 €"})
    assert events[-1]["status"] == "interrupted" and not any(e["type"] == "memory" for e in events)
    assert page.call("GET", "/api/facts")[1]["items"] == []


def test_the_creator_can_write_and_delete_facts_and_the_prompt_follows(web):
    page = web()
    status, body = page.call("PUT", "/api/facts/brand.name", {"text": "Serein  Studio"})
    assert status == 200 and body["items"][0]["text"] == "Serein Studio" and body["items"][0]["source"].startswith("edited ")
    assert "- brand.name: Serein Studio" in page.app.active.session.messages[0].content
    assert page.call("DELETE", "/api/facts/brand.name")[1]["items"] == []
    assert "brand.name" not in page.app.active.session.messages[0].content
    assert page.call("DELETE", "/api/facts/brand.name")[0] == 404


def test_bad_facts_are_refused(web):
    page = web()
    for path, body in (("/api/facts/Bad", {"text": "x"}), ("/api/facts/brand.name", {"text": " "}),
                       ("/api/facts/brand.name", {"text": "a\nb"}), ("/api/facts/brand.name", {})):
        status, data = page.call("PUT", path, body)
        assert status == 400 and data["error"]["code"] == "bad_fact"


def test_facts_is_a_capability_and_the_tools_are_listed(web):
    page = web()
    assert page.call("GET", "/api/config")[1]["capabilities"]["facts"] is True
    assert {"save_fact", "delete_fact"} <= {t["name"] for t in page.call("GET", "/api/tools")[1]["items"]}


def test_the_claims_register_is_read_from_brand_json(web, tmp_path):
    folder = tmp_path / "files"
    folder.mkdir()
    (folder / "brand.json").write_text('{"products": [{"id": "P01", "name": "Hydra Glow Serum", "claims": [{"id": "C01", '
                                       '"text": "Hydrates for 8 hours", "source": "lab", "valid_from": "2026-01-01", '
                                       '"valid_until": "2027-06-01", "approved": true}]}]}', encoding="utf-8")
    body = web(data_dir=str(folder)).call("GET", "/api/brand/claims")[1]
    assert body["file"] == "brand.json" and body["items"][0]["product"] == "Hydra Glow Serum" and body["items"][0]["approved"]
    (folder / "brand.json").write_text("{broken", encoding="utf-8")
    assert web(data_dir=str(folder)).call("GET", "/api/brand/claims")[0] == 422
    assert web().call("GET", "/api/brand/claims")[1] == {"file": None, "items": []}


def test_the_shorthand_tool_block_saves_the_fact_too(web):
    page = web(['{"save_fact": {"id": "hydra-glow-serum.price", "text": "Costs 32 €"}}'], ["Noted."])
    _, events = page.stream({"text": "It costs 32 €."})
    assert {"type": "memory", "changes": ["added hydra-glow-serum.price"]} in events
    stored = page.call("GET", "/api/session")[1]["items"][1]["tools"]
    assert stored[0]["name"] == "save_fact" and stored[0]["ok"] is True
