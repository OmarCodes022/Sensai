# A4 Prompt Versioning: user stories

- Catalogue: A4 ★
- Drafting lead: Omar (taken over from Diana)
- Status: done

Code: [`prompt_versions.py`](https://github.com/OmarCodes022/Sensai/blob/main/src/sensai/prompt_versions.py),
[`evals/prompt_compare/`](https://github.com/OmarCodes022/Sensai/tree/main/evals/prompt_compare/) (versions, questions, `compare.py`) and
[`prompts.py`](https://github.com/OmarCodes022/Sensai/blob/main/web/sensai_web/prompts.py) with the Settings page section.

## Story 1: Keep the better instructions, with evidence

As Nadia, the creator of Serein Studio, I want to compare two versions of my assistant's
instructions on the same questions, so that I can keep the better one with evidence.

Acceptance criteria:
1. Both versions answer the same questions, with the same model and settings, each as a fresh
   conversation.
2. The report shows both answers side by side, with latency and token counts per answer and in a
   summary.
3. In the page, **Compare** shows the answers as they come and saves the same report.

Tests: `tests/unit/evals/test_prompt_compare.py`, `tests/unit/web/test_prompts_web.py`.

## Story 2: Undo a bad change

As Nadia, I want to go back to an older version of the instructions, so that a bad change does not
stick.

Acceptance criteria:
1. Every version is a dated file that is never edited, and the packaged prompt is one of them.
2. I can start Sensai with any version (`--prompt <file>`), or pick one in the page with **Use this
   version** until Sensai restarts, and **Back to the original** undoes it.
3. The older version's behaviour returns from the next reply.

Measured on 2026-11-01 with `qwen2.5`: with `2026-11-01-short-answers.txt` in use, "Write an Instagram
caption for the Hydra Glow Serum" gave one caption of about 45 words, citing "up to 8 hours", instead
of several drafts; **Back to the original** restored the packaged prompt.
