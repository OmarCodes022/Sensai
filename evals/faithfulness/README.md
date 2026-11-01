# Answer scoring and hallucination detection (EV1)

`run.py` answers the 11 test questions of `tests/fixtures/docs/questions.json` the way the chat does
(`run_with_tools` with `search_docs`, no earlier history), then a judge model scores each answer:
relevance and coherence from 1 to 5, and every factual statement labelled `supported`, `unsupported`
or `contradicted` against what search returned. Faithfulness is computed from those labels
(5 when the answer makes no claim, as a correct refusal; otherwise 1 + 4 x the supported share),
because small judges give their own number inconsistently.

```bash
.venv/bin/python evals/faithfulness/run.py --model qwen2.5 --label advanced-search --search advanced
.venv/bin/python evals/faithfulness/run.py --model qwen2.5 --label basic-search --search basic
.venv/bin/python evals/faithfulness/run.py --compare basic-search advanced-search
.venv/bin/python evals/faithfulness/run.py --planted --judge qwen2.5     # how far to trust the judge
```

Each run is saved to `results/<label>.json` (answers, what search returned, scores and flagged
statements). The web **Safety** page lists the saved runs and has **Check an answer** to judge any
pasted answer against the documents. A verdict that is not valid JSON is counted as "not judged" and
the run goes on; with Ollama stopped the script prints a clear message.

## Results (2026-11-01, qwen2.5 answers and judges)

```text
                   relevance  coherence  faithfulness  flagged
basic-search            3.27       4.09          4.09        8
advanced-search         3.36       4.36          4.45        3
```

Advanced search (R2) is more faithful and flags fewer statements: it drops the wrong product's and the
outdated sheet's passages, so the model has less to mix up. Real problems the judge found:

- basic, Q11 and advanced, Q3: "formulated to reduce redness in just 4 weeks" adds "formulated" and
  "just" to the sheet's "helps to reduce redness in 4 weeks": flagged as unsupported or contradicted.
- basic, Q10 and advanced, Q9: answers that offer to check an inventory or pricing system Sensai does not
  have.

## Planted check: how far to trust the judge

`planted.json` holds 6 hand-written answers with their sources: 3 correct, and 3 with a known error
(a cure claim, "24 hours" instead of "up to 8 hours", invented ingredients and "clinically proven").

| Judge | Wrong answers flagged | False alarms on correct answers |
| --- | --- | --- |
| qwen2.5 | 3 of 3 | 0 of 3 |
| llama3.1 | 3 of 3 | 1 of 3 (flagged "it leaves the skin light", which the sheet says) |

## Limits

- The judge is a 7-8B model and is noisy on full answers: in the runs above it marked "hydrates the
  skin for up to 8 hours" as contradicted (Q1) and "Most of our products are vegan" as unsupported
  (basic, Q11), although the sources it was given say exactly that. Read the flagged
  list, do not trust a single flag blindly; a larger judge (`--judge`) should do better.
- Refusals, questions back and offers to help are removed from the statements in code (a small judge
  still lists them against the instructions); a real claim phrased as a question would be missed.
- 11 questions and 6 planted answers are a small sample: compare versions with the same questions and
  judge, and look at the per-question rows in `results/`.
