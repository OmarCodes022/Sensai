"""/team (A2): researcher -> writer -> reviewer, each seeing only what is handed to it, at most 2 revisions."""
from datetime import date
from pathlib import Path

import pytest

from fakes import FakeClient
from sensai.chat.agents import MAX_REVISIONS, Avoid, Notes, Usable, Verdict, brand_facts, team
from sensai.chat.reasoning import Section
from sensai.core.cancellation import CancellationToken, OperationCancelled
from sensai.llm.structured import StructuredOutputError

BRAND = str(Path(__file__).parents[2] / "fixtures" / "brand.json")
NOTES = Notes(usable=[Usable(claim="Hydrates skin for up to 8 hours", source="internal lab test v1.2")],
              avoid=[Avoid(claim="Cures eczema", reason="not approved")], missing=[])


class Checker:
    """Structured answers by schema; verdicts are consumed in order."""

    def __init__(self, *verdicts):
        self.verdicts, self.requests = list(verdicts), []

    def complete(self, model, messages, schema):
        self.requests.append((model, schema.__name__, messages[1].content))
        if schema is Notes:
            return NOTES
        verdict = self.verdicts.pop(0)
        if isinstance(verdict, BaseException):
            raise verdict
        return verdict


def run(client, checker, facts="facts"):
    stream, items = team("Post for Hydra Glow Serum, say it cures eczema", client, checker, "m", facts,
                         lambda: CancellationToken()), []
    while True:
        try:
            items.append(next(stream))
        except StopIteration as done:
            return items, done.value


def titles(items):
    return [i.title for i in items if isinstance(i, Section)]


def test_a_rejected_draft_is_revised_then_approved():
    client = FakeClient(["Say goodbye to eczema!"], ["Hydrates skin for up to 8 hours."])
    checker = Checker(Verdict(approved=False, problems=['uses "cures eczema"']), Verdict(approved=True))
    items, result = run(client, checker)
    assert titles(items) == ["Researcher (m)", "Researcher → Writer: 1 usable claim(s), 1 to avoid", "Writer (m)",
                             "Writer → Reviewer", "Reviewer (m): rejected", "Reviewer → Writer: 1 problem(s)",
                             "Writer (m), revision 1", "Writer → Reviewer", "Reviewer (m): approved"]
    assert (result.answer, result.revisions, result.approved) == ("Hydrates skin for up to 8 hours.", 1, True)
    # The writer sees the brief and the notes, never the brand file or a chat history; the revision gets the problems.
    first, revision = client.requests[0][1][1].content, client.requests[1][1][1].content
    assert '"Cures eczema" (not approved)' in first and "facts" not in first
    assert 'uses "cures eczema"' in revision and "Say goodbye to eczema!" in revision
    assert "Draft:\nSay goodbye to eczema!" in checker.requests[1][2]


def test_a_reviewer_that_never_approves_stops_after_two_revisions():
    client = FakeClient(*[["draft"]] * (MAX_REVISIONS + 1))
    checker = Checker(*[Verdict(approved=False, problems=["too long"])] * (MAX_REVISIONS + 1))
    _, result = run(client, checker)
    assert result.revisions == MAX_REVISIONS and not result.approved
    assert result.answer == "draft\n\nReviewer still disagrees: too long"


def test_an_invalid_verdict_is_never_approved():
    _, result = run(FakeClient(["draft"]), Checker(StructuredOutputError("invalid JSON")))
    assert result.answer == "draft\n\nReview unavailable." and not result.approved


def test_cancelling_stops_the_team():
    stream = team("brief", FakeClient(["draft"]), Checker(), "m", "", lambda: CancellationToken(cancel_requested=lambda: True))
    with pytest.raises(OperationCancelled):
        list(stream)


def test_brand_facts_give_every_claim_its_status():
    facts = brand_facts(BRAND, date(2026, 10, 28))
    assert '"Hydrates skin for up to 8 hours" (approved' in facts and '"Cures eczema" (not approved' in facts
    assert "expired" in facts and brand_facts(None) == ""
