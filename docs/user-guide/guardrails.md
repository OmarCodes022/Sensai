# Guardrails

Sensai checks every message **before** it reaches the model and every reply **before** it is
shown or saved. The rules follow [the privacy and claims policy](../product/privacy-and-claims.md):
refuse wins over redact, and redact over allow.

| Direction | What | Action | Reason code |
| --- | --- | --- | --- |
| message | emails, phone numbers, @handles | replaced with `[redacted]` | `email`, `phone`, `handle` |
| message | "ignore previous instructions", "reveal your system prompt", "you are now…" | refused, not sent to the model | `unsafe_request` |
| message | a person's health details (pregnant, medication, diagnosis…) | refused, not sent to the model | `sensitive_detail` |
| reply | identifiers | replaced with `[redacted]` | |
| reply | the text of a claim that is not approved or out of date in the brand file | reply stopped, nothing saved | `unapproved_claim:<id>` |
| reply | a claim word (cures, heals, clinically proven, guaranteed…) without an approved claim on the same line | reply stopped, nothing saved | `unsupported_claim` |

A product question such as "Does it cure acne?" is not a health detail about a person: it
reaches the model, and the reply check handles the answer.

```text
> Reply to emma@example.com about dry skin
(sent as: "Reply to [redacted] about dry skin")
...
> Can I use the serum while pregnant?
Blocked before the model: This message mentions a personal health detail. ... (sensitive_detail)
> Repeat exactly: Our serum cures acne.
Reply blocked: The reply made a product claim that is not in the approved claims. ... (unsupported_claim)
```

## Streaming

Replies are checked one line at a time, so they appear line by line instead of word by word.
A line is only shown once it passed; when a line is stopped, the reply ends there and the turn
is dropped, as for an interrupted reply.

## In the web interface

A redacted message shows its sent text with a chip naming what was removed. A refused message
or a stopped reply shows a "Blocked by guardrails" card with the reason; nothing is saved.
The same checks apply to `/think` and `/edit`.

## The brand file and your own rules

- **Approved claims** come from `SENSAI_BRAND_FILE` (default `data/brand.json`, same format as
  `tests/fixtures/brand.json`). Only claims with `"approved": true` and valid today count; the
  text of the others is blocked. Without a brand file nothing is approved, so every claim-like
  line is stopped.
- **Your rules**: `SENSAI_GUARDRAILS_FILE` points to a JSON file that adds patterns (regular
  expressions) and changes actions, without code:

  ```json
  {
    "patterns": {"sensitive_detail": ["\\ballerg(y|ies)\\b"]},
    "actions": {"input": {"handle": "allow"}}
  }
  ```

  Pattern classes: `email`, `phone`, `handle`, `unsafe_request`, `sensitive_detail`,
  `claim_word`. Actions: `allow`, `redact`, `refuse`. A broken file stops Sensai at startup
  with a clear error.

## Limits

Patterns catch the common cases, not everything: a phone number written in words, or an
unusual claim wording, can slip through. A refusal line by the model ("I can't say it cures
eczema") is also stopped, because it contains the claim. Review drafts before you use them.
