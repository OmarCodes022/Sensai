"""/api/edit: continue from message N as a new saved session; the original stays unchanged."""
from sensai.core.cancellation import OperationCancelled


def three(page):
    for text in ("First", "Second", "Third"):
        page.stream({"text": text})
    return page.call("GET", "/api/session")[1]["id"]


def texts(session):
    return [i["text"] for i in session["items"]]


def test_edit_forks_a_new_session_from_message_n(web):
    page = web(["R1"], ["R2"], ["R3"], ["Playful"])
    original = three(page)
    status, events = page.stream({"n": 2, "text": "More playful"}, path="/api/edit")
    branch = next(e for e in events if e["type"] == "branch")
    assert status == 200 and branch["from"] == original and branch["session_id"] != original
    assert events[-1]["status"] == "completed"
    assert page.client.calls[-1][1:] == ["First", "R1", "More playful"]
    now = page.call("GET", "/api/session")[1]
    assert now["id"] == branch["session_id"] and texts(now) == ["First", "R1", "More playful", "Playful"]
    assert texts(page.call("GET", f"/api/sessions/{original}")[1]) == ["First", "R1", "Second", "R2", "Third", "R3"]
    titles = {s["id"]: s["title"] for s in page.call("GET", "/api/sessions")[1]["items"]}
    assert titles[branch["session_id"]] == f"{titles[original]} (branch)"


def test_an_interrupted_edit_keeps_the_original_open_and_saves_nothing(web):
    page = web(["R1"], ["R2"], ["R3"], ["partial", OperationCancelled("operation cancelled")])
    original = three(page)
    _, events = page.stream({"n": 1, "text": "Other"}, path="/api/edit")
    assert events[-1]["status"] == "interrupted"
    assert page.call("GET", "/api/session")[1]["id"] == original
    assert [s["id"] for s in page.call("GET", "/api/sessions")[1]["items"]] == [original]


def test_a_bad_edit_is_refused_before_anything_runs(web):
    page = web(["R1"])
    page.stream({"text": "First"})
    for body in ({"n": 2, "text": "x"}, {"n": 0, "text": "x"}, {"n": "1", "text": "x"}, {"n": True, "text": "x"},
                 {"n": 1, "text": " "}, {"n": 1}):
        status, data = page.stream(body, path="/api/edit")
        assert status == 400 and data["error"]["code"] in ("bad_message", "empty_input")
    assert len(page.client.calls) == 1


def test_branching_is_a_capability(web):
    assert web().call("GET", "/api/config")[1]["capabilities"]["branching"] is True


def test_a_branch_keeps_the_times_of_the_turns_it_kept(web):
    page = web(["R1"], ["R2"], ["R3"], ["New"])
    original = three(page)
    before = page.call("GET", f"/api/sessions/{original}")[1]["items"]
    page.stream({"n": 3, "text": "Changed"}, path="/api/edit")
    after = page.call("GET", "/api/session")[1]["items"]
    assert [i.get("at") for i in after[:4]] == [i.get("at") for i in before[:4]] and all(i.get("at") for i in after)
