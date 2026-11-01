"""A7: the two closest examples are sent for one request only, never stored; an embedding error turns them off."""
from fakes import FakeClient
from sensai.chat.examples import ExamplePicker, turns
from sensai.chat.session import ChatSession
from sensai.cli.main import repl
from sensai.core.errors import LLMError

EXAMPLES = [{"id": "caption-a", "request": "caption post", "answer": "A caption."},
            {"id": "caption-b", "request": "caption launch post", "answer": "B caption."},
            {"id": "dm-a", "request": "reply dm", "answer": "A reply."}]


def embed(text):
    """Known words, plus one dimension for a message with none of them ("hello")."""
    low = text.lower()
    found = tuple(float(word in low) for word in ("caption", "post", "launch", "reply", "dm"))
    return (*found, float(not any(found)))


def test_the_closest_examples_are_picked_and_weak_matches_left_out():
    picker = ExamplePicker(embed, EXAMPLES)
    assert [e["id"] for e in picker.pick("write a caption for this post")] == ["caption-a", "caption-b"]
    assert [e["id"] for e in picker.pick("draft a reply to this dm")] == ["dm-a"]
    assert picker.pick("hello there") == []


def test_the_packaged_examples_cover_captions_dms_and_analysis():
    kinds = {e["kind"] for e in ExamplePicker(embed).examples}
    assert kinds == {"caption", "dm", "analysis"}


def test_an_embedding_error_turns_examples_off():
    def down(text):
        raise LLMError("model not found")
    picker = ExamplePicker(down, EXAMPLES)
    assert picker.pick("caption") == [] and "examples are off" in picker.off


def test_examples_are_sent_after_the_system_prompt_and_never_stored():
    client = FakeClient(["Done."])
    session = ChatSession(client, "m", "Rules")
    session.extra = turns(EXAMPLES[:1])
    list(session.send("write a caption"))
    assert [m.content for m in client.requests[0][1]] == ["Rules", "caption post", "A caption.", "write a caption"]
    assert [m.content for m in session.messages] == ["Rules", "write a caption", "Done."]


def test_the_terminal_says_which_examples_were_used_for_each_message():
    client = FakeClient(["Cap."], ["Hi."])
    session = ChatSession(client, "m", "Rules")
    feed, out = iter(["write a caption for this post", "hello there", "exit"]), []
    repl(session, read=lambda _: next(feed), write=lambda text="", **_: out.append(text),
         examples=ExamplePicker(embed, EXAMPLES))
    assert "Examples used: caption-a, caption-b" in out and out.count("Examples used: caption-a, caption-b") == 1
    assert len(client.requests[0][1]) == 6 and len(client.requests[1][1]) == 4  # system, 2 turns of examples, question
    assert all(m.content not in ("A caption.", "B caption.") for m in session.messages)
