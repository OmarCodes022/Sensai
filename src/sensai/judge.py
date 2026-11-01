"""EV1: an LLM judge scores an answer against the documents it was given, and flags what they do not back.

Scores are 1 to 5 for relevance, coherence and faithfulness. The answer is split into statements,
each `supported`, `unsupported` (the sources say nothing) or `contradicted` (the sources say otherwise).
"""
import re
from typing import Literal

from pydantic import BaseModel, Field

from sensai.core.messages import Message

PROMPT = """You check one answer of a skincare brand's assistant against the sources it was given.
Split the answer into its factual statements (product effects, timings, ingredients, prices, policies).
Label each one:
- supported: a source says the same thing;
- unsupported: no source says it (an invented or unverifiable claim);
- contradicted: a source says something different (for example "up to 8 hours" against "24 hours").
These are NOT statements, leave them out: greetings, questions, offers to help, advice to see a dermatologist,
and saying the documents do not cover something (that is the right answer when they do not). Then score from 1 to 5: relevance (does it answer the question), coherence (is it clear and
consistent), faithfulness (5 = every statement supported, 1 = mostly unsupported or contradicted)."""


# What a small judge still lists against the instructions: a refusal, a question back or an offer is never a claim.
NOT_A_CLAIM = re.compile(r"\?\s*$|\b(?:do(?:es)? not|don't|doesn't) (?:cover|mention|include|say|specify)|"
                         r"\bnot (?:specified|listed|mentioned|documented|available|covered|included)\b|"
                         r"\bno (?:information|documentation|details?|data)\b|\b(?:unable to|cannot|can't) (?:provide|find|say)\b|"
                         r"\b(?:would you like|let me know|i can|we can|we may need|we could|please provide)\b", re.I)


class Statement(BaseModel):
    text: str = Field(description="the statement, as short as possible")
    label: Literal["supported", "unsupported", "contradicted"]
    source: str = Field("", description="the source it relies on or conflicts with, if any")


class Judgement(BaseModel):
    relevance: int = Field(ge=1, le=5)
    coherence: int = Field(ge=1, le=5)
    faithfulness: int = Field(ge=1, le=5)
    statements: list[Statement]

    def flagged(self) -> list[Statement]:
        return [s for s in self.statements if s.label != "supported"]


def judge(client, model: str, question: str, sources: str, answer: str) -> Judgement:
    """One structured call; raises the client's errors (unreachable, invalid JSON) for the caller to report."""
    request = f"Question:\n{question}\n\nSources:\n{sources or '(none: no document was retrieved)'}\n\nAnswer:\n{answer}"
    verdict = client.complete(model, [Message(role="system", content=PROMPT), Message(role="user", content=request)],
                              Judgement)
    verdict.statements = [s for s in verdict.statements if not NOT_A_CLAIM.search(s.text)]
    return verdict
