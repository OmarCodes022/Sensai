# A7 Automated Prompt Optimization: user stories

- Catalogue: A7 ★ (stretch)
- Drafting lead: Omar
- Status: done (auto-selected few-shot examples only)

Code: [`chat/examples.py`](https://github.com/OmarCodes022/Sensai/blob/main/src/sensai/chat/examples.py), [`examples.json`](https://github.com/OmarCodes022/Sensai/blob/main/src/sensai/chat/examples.json),
`ChatSession.extra` in [`chat/session.py`](https://github.com/OmarCodes022/Sensai/blob/main/src/sensai/chat/session.py).
Guide: [Picked examples](../user-guide/examples.md).

## Story 1: Content in the right format the first time

As Nadia, the creator of Serein Studio, I want Sensai to follow good examples of the kind of content
I ask for, so that captions and replies come out in the right format the first time.

Acceptance criteria:
1. Sensai prints which examples it used for each message ("Examples used: caption-launch,
   caption-routine"); the web reply shows them in a chip.
2. A caption request picks caption examples, a DM request picks reply examples, and "hello" picks none.
3. The examples never appear in my saved conversation.

Tests: `tests/unit/chat/test_examples.py`, `tests/unit/web/test_examples_web.py`.

## Story 2: See whether examples actually help

As Nadia, I want to see whether examples actually help, so that I only keep the feature if it
improves the answers.

Acceptance criteria:
1. Without `SENSAI_EXAMPLES=1`, I get the usual answers.
2. The same requests with and without examples are kept side by side
   ([comparison](../user-guide/examples.md#with-and-without-gemma31b-2026-11-01)).
3. A missing embedding model shows one warning and does not stop the chat.

Measured on 2026-11-01 with `gemma3:1b`: with examples the caption came out as one post in the brand
format with `#SereinStudio` instead of three generic options, and the DM reply dropped the invented
"calming plant extracts".
