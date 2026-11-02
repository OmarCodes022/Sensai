# EV1 Automated Eval & Hallucination Detection: user stories

## Story 1: Know whether a change made Sensai better or worse

As a developer working on Sensai, I want one command that scores answers for relevance,
coherence and faithfulness, so that I can tell whether a change made Sensai better or worse
before showing it.

Acceptance criteria:
1. `evals/faithfulness/run.py --model qwen2.5 --label v1` answers every test question the way the
   chat does (`run_with_tools` with `search_docs`), has a judge score each answer from 1 to 5, prints
   the averages and saves the results under the label.
2. A question whose verdict is not valid JSON is counted as "not judged" and the run goes on; with
   Ollama stopped the script prints a clear message, no traceback.
3. `--compare v1 v2` prints both versions side by side; the web Safety page lists the saved runs.

## Story 2: No invented or outdated claim ends up in a post

As Nadia, the creator of Serein Studio, I want answers checked for claims my documents do not
support, so that no invented or outdated claim ends up in my posts.

Acceptance criteria:
1. Every statement the documents do not back is listed with its question, as `unsupported` or
   `contradicted`, with the source it conflicts with.
2. Planted wrong answers (a cure claim, a wrong duration, invented ingredients) are flagged, and the
   README records the misses and false alarms on correct answers.
3. On the web Safety page, **Check an answer** judges any pasted answer against what document search
   finds for its question.
