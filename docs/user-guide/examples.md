# Picked examples

With `SENSAI_EXAMPLES=1`, Sensai picks, for each message, the two closest examples from a small set
of good requests and answers (captions, DM replies, weekly analysis) and shows them to the model as
example turns. A small model then follows the right format and tone.

```text
$ SENSAI_EXAMPLES=1 sensai gemma3:1b
> Write a caption for our new vitamin C serum
Examples used: caption-launch, caption-routine
...
```

- Examples are compared by the cosine similarity of their embeddings (`SENSAI_EMBED_MODEL`, default
  `nomic-embed-text`); a match needs 0.6, so "hello" gets none.
- They are sent right after the system prompt **for that request only**: never saved, never in
  `--session`, `/history` or exports.
- If embedding fails, Sensai warns once and chats without examples. Without `SENSAI_EXAMPLES=1`
  nothing changes, which is also how to compare.
- In the web page, a reply shows an "Examples used" chip.
- The examples are in `src/sensai/chat/examples.json` (8: 3 captions, 3 DM replies, 2 analyses).

## With and without (gemma3:1b, 2026-11-01)

| Request | Without examples | With examples |
| --- | --- | --- |
| Write a caption for our new vitamin C serum | Three generic options ("Option 1 (Focus on results)…"), no brand hashtag | One caption in the brand's format: short lines, a call to action, `#SereinStudio` (examples `caption-launch`, `caption-routine`) |
| A follower asks if the cream is safe for sensitive skin, draft a reply | Invents "calming plant extracts" and offers "a detailed safety profile" | Short and careful, ends with a question to the follower, like the DM examples (`dm-medical`, `dm-dry-skin`) |
| hello | A greeting | A greeting; no example used |

Examples change the shape and tone more than the facts: the caption still made up ingredients,
which is why document search, the guardrails and `/team` remain the safeguards for claims.
