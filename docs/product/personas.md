# Startup personas (T23)

The fictional skincare creator Nadia can start the same chat in three distinct
working roles. **Rédaction** prepares posts and captions in the supplied brand
voice; **Communauté** prepares unsent suggestions for fictional or already
sanitized non-sensitive questions; **Analyse** interprets supplied aggregate
metrics and proposes next-week recommendations. Each profile instructs the
model to follow the language of the user's message and the shared claim,
privacy and action instructions. Rédaction and Communauté request two variants
by default when the required safe inputs are available; Analyse requests a
detailed response separating figures, interpretations, limitations and
recommendations.

## Story 1: choose a role for the activity

As Nadia, I want to choose a drafting, community or analysis assistant at
startup so its tone and response structure fit my current activity.

Acceptance criteria:

1. `sensai --list-personas` shows `redaction`, `communaute` and `analyse` with
   their display names without requiring a model or Ollama.
2. Starting with each ID preserves the shared instructions and adds the chosen
   role, tone and scope. With suitable fictional inputs, a human checks two
   draft/reply variants or an analysis separating facts from interpretation.
3. An unknown ID fails before any model call. An out-of-scope request instructs
   the model to explain the appropriate role and suggest a new launch; no
   runtime switch or external action is performed.

## Story 2: customize a role without changing code

As Nadia, I want to supply a persona catalogue with my chosen names, tone,
roles and scope so I can adapt the assistant without editing Python.

Acceptance criteria:

1. A valid catalogue passed through `--personas-file` or
   `SENSAI_PERSONAS_FILE` replaces the built-in catalogue and its profiles can
   be listed and selected. CLI values take precedence over environment values.
2. Unreadable files, invalid JSON, missing/extra fields, non-string or blank
   values, duplicate IDs and unknown selections produce explicit startup
   errors before contacting the model.
3. The selected custom instructions follow the shared `--prompt` in the actual
   model request. Without a selected persona the original assistant prompt,
   streaming and conversation history remain unchanged.

## Manual checks and feature boundary

Use a locally installed model and the commands in the root README. For each
persona, ask a question in French, then in English; check language, tone and
scope. Use only fictional inputs and the policy's fictional approval scenario
when checking post/reply variants. For Analyse, supply matching-period,
sourced aggregate counts, then repeat with missing figures or zero reach;
check that the model distinguishes unavailable data from zero and avoids
fabricated metrics. Try an out-of-scope request and check the suggested role.
Interrupt a reply and verify that the next turn still works.

Observed local CLI checks on fictional data (2026-10-08): `gemma3:1b`
completed all three persona streams and exited normally, but answered in
English to French requests and invented benefits or metrics despite the
instructions. `mistral:latest` also invented skincare claims in drafting and
community replies, and answered the drafting request in English. These are
observed model-quality failures, not passing persona-behavior acceptance
checks.

Unit tests establish catalogue validation, selection and prompt assembly, not
the quality or safety of every model response. These persona instructions
are not privacy sanitization, evidence verification or an output-validation
gate. They do not fetch analytics, send replies, save artifacts or deliver the
four-output workflow in [the product scope](creator-product.md).

T23 implements definitions and startup selection. T24 owns switching without
losing history; T25 owns broader persona behavior regressions. These stories
still need the independent review coordinated by T08 before claiming the
complete A5 feature.
