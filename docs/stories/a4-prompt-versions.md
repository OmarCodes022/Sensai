# A4 Prompt Versioning: user stories

## Story 1: Keep the better instructions, with evidence

As Nadia, the creator of Serein Studio, I want to compare two versions of my assistant's
instructions on the same questions, so that I can keep the better one with evidence.

Acceptance criteria:
1. Both versions answer the same questions, with the same model and settings, each as a fresh
   conversation.
2. The report shows both answers side by side, with latency and token counts per answer and in a
   summary.
3. In the page, **Compare** shows the answers as they come and saves the same report.

## Story 2: Undo a bad change

As Nadia, I want to go back to an older version of the instructions, so that a bad change does not
stick.

Acceptance criteria:
1. Every version is a dated file that is never edited, and the packaged prompt is one of them.
2. I can start Sensai with any version (`--prompt <file>`), or pick one in the page with **Use this
   version** until Sensai restarts, and **Back to the original** undoes it.
3. The older version's behaviour returns from the next reply.
