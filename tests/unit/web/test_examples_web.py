"""A7 in the page: an `examples` event names the examples, which are sent but never stored."""
from sensai.chat.examples import ExamplePicker


def embed(text):
    return tuple(float(word in text.lower()) + 0.01 for word in ("caption", "post", "reply"))


def test_the_page_is_told_which_examples_were_used(web):
    page = web(["Cap."])
    page.app.examples = ExamplePicker(embed, [{"id": "caption-a", "request": "caption post", "answer": "A caption."}])
    _, events = page.stream({"text": "write a caption for this post"})
    assert {"type": "examples", "ids": ["caption-a"]} in events
    assert "A caption." in page.client.calls[0] and page.app.active.session.extra == ()
    assert [i["text"] for i in page.call("GET", "/api/session")[1]["items"]] == ["write a caption for this post", "Cap."]
