"""/team in the page: the steps as text, only the brief and the final draft in the conversation."""
from types import SimpleNamespace

from sensai.chat.agents import Notes, Verdict


def test_the_team_streams_its_steps_and_keeps_the_final_draft(web):
    page = web(["Hydrates skin for up to 8 hours."])
    page.app.checker = SimpleNamespace(complete=lambda model, messages, schema:
                                       Notes(usable=[], avoid=[], missing=[]) if schema is Notes else Verdict(approved=True))
    status, events = page.stream({"text": "post for the serum"}, path="/api/team")
    text = "".join(e["delta"] for e in events if e["type"] == "text")
    assert status == 200 and "**Researcher (fake)**" in text and "**Final draft**" in text
    assert events[-1]["status"] == "completed"
    items = page.call("GET", "/api/session")[1]["items"]
    assert [(i["kind"], i["text"]) for i in items] == [("user", "/team post for the serum"),
                                                       ("assistant", "Hydrates skin for up to 8 hours.")]
    assert page.call("GET", "/api/config")[1]["capabilities"]["team"] is True


def test_a_final_draft_with_an_unapproved_claim_is_blocked(web):
    page = web(["It cures eczema."])
    page.app.checker = SimpleNamespace(complete=lambda model, messages, schema:
                                       Notes(usable=[], avoid=[], missing=[]) if schema is Notes else Verdict(approved=True))
    _, events = page.stream({"text": "post"}, path="/api/team")
    assert any(e["type"] == "blocked" for e in events)
    assert page.call("GET", "/api/session")[1]["items"] == []
