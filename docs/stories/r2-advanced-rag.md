## Story 1

As a skincare creator, I want Sensai to use only the current sheet of the product I'm asking about, so that it doesn't mix up my two products or repeat an expired claim

- A question about one product cites only that product's documents and general ones
- An outdated product sheet is not used when a newer one exists
- Questions that worked with basic search still get the right answer

## Story 2

As a creator, I want weak matches dropped and their scores shown, so that I can trust that the cited sources really answer my question

- Each source shows a relevance score (terminal list, web source chips) and how many passages were kept
- Off-topic questions get no sources and a clear "not covered" answer
- evals/rag/compare.py shows advanced search doing better than basic search on the test questions
