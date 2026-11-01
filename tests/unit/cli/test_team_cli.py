"""/team in the terminal: steps shown, the brief and final draft saved, Ctrl+C adds nothing, chat goes on."""
from fakes import FakeClient, scripted_terminal
from sensai.chat.agents import Notes, Verdict
from sensai.chat.session import ChatSession
from sensai.cli.main import repl


class Checker:
    def __init__(self, verdict=None):
        self.verdict = verdict or Verdict(approved=True)

    def complete(self, model, messages, schema):
        return Notes(usable=[], avoid=[], missing=["no facts"]) if schema is Notes else self.verdict


def chat(client, inputs, checker):
    session = ChatSession(client, "m", "Shared rules")
    feed, out = iter([*inputs, "exit"]), []
    repl(session, read=lambda _: next(feed), write=lambda text="", **_: out.append(text), checker=checker)
    return session, "\n".join(out)


def test_team_adds_the_brief_and_the_final_draft_then_chat_goes_on():
    client = FakeClient(["A calm post."], ["Shorter."])
    session, out = chat(client, ["/team post for the cream", "make it shorter"], Checker())
    assert "Researcher (m)" in out and "Reviewer (m): approved" in out and "Final draft\nA calm post." in out
    assert [m.content for m in session.messages[1:]] == ["/team post for the cream", "A calm post.", "make it shorter", "Shorter."]
    assert client.requests[1][1][-2].content == "A calm post."  # The chat works from the final draft.


def test_ctrl_c_during_the_team_adds_nothing():
    class Interrupted(Checker):
        def complete(self, model, messages, schema):
            raise KeyboardInterrupt  # Ctrl+C while the researcher works.
    session, out = chat(FakeClient(["Hello"]), ["/team post", "hi"], Interrupted())
    assert "Team stopped: nothing was added." in out
    assert [m.content for m in session.messages[1:]] == ["hi", "Hello"]


def test_team_needs_a_brief():
    _, out = chat(FakeClient(), ["/team"], Checker())
    assert "usage: /team <brief>" in out
