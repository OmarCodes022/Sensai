"""Rename, delete and export a saved session."""
import pytest


def two_sessions(page):
    page.stream({"text": "about serum"})
    first = page.call("GET", "/api/session")[1]["id"]
    page.call("POST", "/api/sessions")
    page.stream({"text": "about cream"})
    return first, page.call("GET", "/api/session")[1]["id"]


def test_a_session_can_be_renamed_including_the_open_one(web):
    page = web(["a1"], ["a2"])
    first, second = two_sessions(page)
    assert page.call("PATCH", f"/api/sessions/{first}", {"title": "  Launch   plan "}) == (200, {"title": "Launch plan"})
    page.call("PATCH", f"/api/sessions/{second}", {"title": "Now"})
    titles = {s["id"]: s["title"] for s in page.call("GET", "/api/sessions")[1]["items"]}
    assert titles == {first: "Launch plan", second: "Now"}
    assert page.call("GET", "/api/session")[1]["title"] == "Now"


@pytest.mark.parametrize("title", ["", "  ", 3, "x" * 101, "two\nlines"])
def test_a_bad_title_is_refused(web, title):
    page = web(["a1"])
    page.stream({"text": "hello"})
    sid = page.call("GET", "/api/session")[1]["id"]
    status, body = page.call("PATCH", f"/api/sessions/{sid}", {"title": title})
    assert status == 400 and body["error"]["code"] == "bad_title"
    assert page.call("PATCH", "/api/sessions/nope", {"title": "ok"})[0] == 404


def test_a_session_can_be_deleted_unless_it_is_open(web):
    page = web(["a1"], ["a2"])
    first, second = two_sessions(page)
    assert page.call("DELETE", f"/api/sessions/{second}")[1]["error"]["code"] == "session_open"
    status, body = page.call("DELETE", f"/api/sessions/{first}")
    assert status == 200 and [s["id"] for s in body["items"]] == [second]
    assert page.call("GET", f"/api/sessions/{first}")[0] == 404
    assert page.call("DELETE", f"/api/sessions/{first}")[0] == 404


def test_a_session_exports_as_markdown(web):
    page = web(["Answer one"])
    page.stream({"text": "about serum"})
    sid = page.call("GET", "/api/session")[1]["id"]
    status, body = page.call("GET", f"/api/sessions/{sid}/export")
    assert status == 200 and body["filename"] == f"sensai-{sid}.md"
    assert "**You**\n\nabout serum" in body["markdown"] and "**Sensai**\n\nAnswer one" in body["markdown"]
    assert page.call("GET", "/api/sessions/nope/export")[0] == 404
