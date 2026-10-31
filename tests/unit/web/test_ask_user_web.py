"""ask_user in the page: the form event, the answer endpoint, skips and stops."""
ASK = ('{"tool":"ask_user","arguments":{"questions":[{"type":"choice","text":"Which product?",'
       '"options":["Hydra Glow Serum","Calm Barrier Cream"]}]}}')


def answer_with(page, body):
    def on_event(event):
        if event["type"] == "question":
            page.call("POST", f"/api/questions/{event['id']}", body)
    return on_event


def test_the_page_answers_and_the_reply_continues(web):
    page = web([ASK], ["A caption for Calm Barrier Cream."])
    _, events = page.stream({"text": "Write a caption"}, answer_with(page, {"answers": ["Calm Barrier Cream"]}))
    question = next(e for e in events if e["type"] == "question")
    assert question["questions"] == [{"type": "choice", "text": "Which product?", "options": ["Hydra Glow Serum", "Calm Barrier Cream"]}]
    assert {"type": "question_result", "id": question["id"], "skipped": False} in events
    assert "Which product? -> Calm Barrier Cream" in page.client.calls[1][-1] and events[-1]["status"] == "completed"
    stored = page.call("GET", "/api/session")[1]["items"][1]["tools"][0]
    assert stored["name"] == "ask_user" and "Calm Barrier Cream" in stored["output"]


def test_skipping_returns_a_skip_to_the_model(web):
    page = web([ASK], ["Fine, tell me later."])
    _, events = page.stream({"text": "Write a caption"}, answer_with(page, {"skipped": True}))
    assert any(e["type"] == "question_result" and e["skipped"] for e in events)
    assert "The user skipped the question" in page.client.calls[1][-1]


def test_bad_answers_and_unknown_ids_are_refused(web):
    page = web()
    assert page.call("POST", "/api/questions/nope", {"answers": ["x"]})[0] == 404
    assert page.call("POST", "/api/questions/nope", {"answers": [""]})[0] == 400
    assert page.call("GET", "/api/config")[1]["capabilities"]["ask_user"] is True
