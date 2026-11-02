# A7 Automated Prompt Optimization: user stories

## Story 1: Content in the right format the first time

As Nadia, the creator of Serein Studio, I want Sensai to follow good examples of the kind of content
I ask for, so that captions and replies come out in the right format the first time.

Acceptance criteria:
1. Sensai prints which examples it used for each message ("Examples used: caption-launch,
   caption-routine"); the web reply shows them in a chip.
2. A caption request picks caption examples, a DM request picks reply examples, and "hello" picks none.
3. The examples never appear in my saved conversation.

## Story 2: See whether examples actually help

As Nadia, I want to see whether examples actually help, so that I only keep the feature if it
improves the answers.

Acceptance criteria:
1. Without `SENSAI_EXAMPLES=1`, I get the usual answers.
2. The same requests with and without examples are kept side by side
   ([comparison](../user-guide/examples.md#with-and-without-gemma31b-2026-11-01)).
3. A missing embedding model shows one warning and does not stop the chat.
