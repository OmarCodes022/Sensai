# A6 Semantic Cache: user stories

## Story 1: Common questions answered instantly

As Nadia, the creator of Serein Studio, I want common questions about my products answered
instantly, so that I do not wait for the model to repeat an answer it already gave.

Acceptance criteria:

1. With `SENSAI_CACHE=1`, a reworded first question that matches an earlier one is answered in
   under a second, without calling the chat model.
2. The answer is labelled as cached, with the original question and the similarity.
3. Unrelated questions still get a fresh answer.

## Story 2: A fast answer is never a wrong one

As Nadia, I want the cache never to serve an answer that does not fit my current setup, so that a
fast answer is never a wrong one.

Acceptance criteria:

1. Another model, persona, profile or creator never reuses an old answer.
2. Interrupted or failed replies are never cached, and follow-up messages always go to the model.
3. An embedding error only turns the cache off, with one warning; `--clear-cache` empties it.
