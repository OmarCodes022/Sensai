"""Notes and file access rules in the page: the creator sets both; rules are saved only after a yes."""
import json
import os

import pytest

RULES = {"allow": ["Read(./data/notes/**)", "Write(./outputs/drafts/**)", "Create(./outputs/drafts/**)"],
         "deny": ["Read(./data/notes/private/**)"]}


@pytest.fixture
def project(tmp_path):
    root = tmp_path.resolve()
    for d in ("data/notes/private", "outputs/drafts"):
        (root / d).mkdir(parents=True)
    return root


def test_notes_can_be_written_listed_read_and_deleted(web, project):
    page = web()
    assert page.call("GET", "/api/notes")[1]["items"] == []
    page.call("PUT", "/api/notes/launch.md", {"text": "Launch on 21 November"})
    listing = page.call("PUT", "/api/notes/private/costs.md", {"text": "Margin 62%"})[1]
    assert [i["path"] for i in listing["items"]] == ["launch.md", "private/costs.md"]
    assert page.call("GET", "/api/notes/private/costs.md")[1]["text"] == "Margin 62%"
    assert (project / "data" / "notes" / "launch.md").read_text() == "Launch on 21 November"
    page.call("DELETE", "/api/notes/launch.md")
    assert [i["path"] for i in page.call("GET", "/api/notes")[1]["items"]] == ["private/costs.md"]


@pytest.mark.parametrize("path", ["../secret.md", "%2Fetc%2Fhosts.md", "a/b/c/d.md", "launch.py", ".hidden.md", "a%2F..%2Fb.md"])
def test_bad_note_paths_are_refused(web, project, path):
    status, body = web().call("PUT", f"/api/notes/{path}", {"text": "x"})
    assert status == 400 and body["error"]["code"] in {"bad_note_path", "bad_file_type"}
    assert not [p for p in (project / "data").rglob("*") if p.is_file()]


def test_a_symlinked_note_folder_is_refused(web, project, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    os.symlink(outside, project / "data" / "notes" / "link")
    status, body = web().call("PUT", "/api/notes/link/x.md", {"text": "x"})
    assert status == 400 and not (outside / "x.md").exists()


def test_rules_are_proposed_then_saved_on_yes_and_used_at_once(web, project):
    page = web()
    assert page.call("GET", "/api/files/rules")[1] == {"on": False, "file": ".sensai/settings.json", "allow": [], "deny": []}
    (project / "data" / "notes" / "private" / "costs.md").write_text("Margin 62%")
    (project / "data" / "notes" / "launch.md").write_text("Launch on 21 November")
    proposal = page.call("POST", "/api/files/rules", RULES)[1]
    assert proposal["before"] == {"allow": [], "deny": []} and proposal["after"] == RULES
    assert not (project / ".sensai" / "settings.json").exists()  # Nothing written before the yes.
    saved = page.call("POST", "/api/files/rules/confirm", {"token": proposal["token"], "approved": True})[1]
    assert saved["status"] == "saved" and saved["on"] is True and saved["allow"] == RULES["allow"]
    assert json.loads((project / ".sensai" / "settings.json").read_text()) == {"permissions": RULES}
    assert page.call("POST", "/api/files/read", {"path": "data/notes/launch.md"})[1]["text"] == "Launch on 21 November"
    assert page.call("POST", "/api/files/read", {"path": "data/notes/private/costs.md"})[0] == 403


def test_a_no_or_a_stale_token_changes_nothing(web, project):
    page = web()
    proposal = page.call("POST", "/api/files/rules", RULES)[1]
    assert page.call("POST", "/api/files/rules/confirm", {"token": proposal["token"], "approved": False})[1]["status"] == "discarded"
    assert page.call("POST", "/api/files/rules/confirm", {"token": proposal["token"], "approved": True})[0] == 409
    assert not (project / ".sensai").exists()


@pytest.mark.parametrize("allow", [["Read(../outside/**)"], ["Read(./missing/**)"], ["Delete(./data/notes/**)"], "Read(./data/**)"])
def test_invalid_rules_are_refused_before_any_confirm_card(web, project, allow):
    status, body = web().call("POST", "/api/files/rules", {"allow": allow, "deny": []})
    assert status == 400 and body["error"]["code"] == "bad_rules"
