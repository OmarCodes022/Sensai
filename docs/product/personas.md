# Personas (A5)

This guide covers the Persona feature (A5 in the subject catalogue): its user
stories, manual checks and automated test coverage. Command usage is in the
root [README](https://github.com/OmarCodes022/Sensai/blob/main/README.md#personas).

The fictional skincare creator Nadia can start the same chat in three distinct
working roles. **Rédaction** prepares posts and captions in the supplied brand
voice; **Communauté** prepares unsent suggestions for fictional or already
sanitized non-sensitive questions; **Analyse** interprets supplied aggregate
metrics and proposes next-week recommendations. Each profile instructs the
model to honor an explicitly requested response language, otherwise the language
of the latest user message, including headings and variants. Prior replies or
the instruction language should not determine that choice. Shared claim,
privacy and action instructions still apply. Rédaction and Communauté request two variants
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
   the model to explain the appropriate role and suggest `/persona <id>`;
   the user runs that command to change profiles.

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

## Story 3: change roles within the conversation

As Nadia, I want to change personas between turns while retaining the prior
exchanges so I can continue the same work in another role.

Acceptance criteria:

1. `/persona` lists the startup-loaded profiles, including a custom catalogue;
   `/persona <id>` confirms a valid selection without contacting the model or
   recording the command in chat history.
2. The next request contains the original shared prompt followed by only the
   newly selected persona, plus every completed user and assistant turn.
   Repeated switches do not accumulate earlier persona instructions.
3. An unknown ID reports an error and leaves the prompt and history intact.
   Switching does not reload the catalogue or prompt files.
4. Replies still stream; cancellation and model errors discard the incomplete
   turn. Subsequent switches and requests remain usable.

Switches happen at the input prompt between turns. They preserve text already
exchanged with previous personas; they do not rewrite those replies.
The active system instructions identify the profile selected by the application;
earlier assistant introductions describe previous roles and do not undo a switch.
After a switch, every request repeats the current system instructions immediately
before the newest user message. This request-only reminder is never added to
stored history, which retains one current system message and the original turns.
Requests before any runtime switch keep their original message structure.
Chat requests keep the model/server's default thinking mode and wait for visible
answer content, without displaying or storing separate thinking text. A completed
stream without a nonblank answer reports an error and removes the incomplete
turn, preserving earlier exchanges and the selected profile.

## Manual checks and feature boundary

Use a locally installed model and the commands in the root README. For each
persona, start with `hello`, then ask in French about the assistant's role or
request a post/reply/report, and explicitly ask for French if needed. Finally
request English to check that language selection follows the current request
rather than the first exchange. Check language, tone and scope. Use only
fictional inputs and the policy's fictional approval scenario
when checking post/reply variants. For Analyse, supply matching-period,
sourced aggregate counts, then repeat with missing figures or zero reach;
check that the model distinguishes unavailable data from zero and avoids
fabricated metrics. Try an out-of-scope request and check the suggested role.
Interrupt a reply and verify that the next turn still works.
Then run `/persona`, select a different listed ID with `/persona <id>` and
ask a follow-up referring to an earlier completed exchange. Check that the
new reply follows the selected role and can use that earlier context. Try an
unknown ID, then continue; the last valid role and history should remain.

Observed local CLI checks on fictional data (2026-10-08): `gemma3:1b`
completed all three persona streams and exited normally, but answered in
English to French requests and invented benefits or metrics despite the
instructions. `mistral:latest` also invented skincare claims in drafting and
community replies, and answered the drafting request in English. These are
observed model-quality failures, not passing persona-behavior acceptance
checks.

The built-in profiles now use French instructions and a bilingual reminder
with short examples to follow the latest message or explicitly requested
language at each turn. This prompt adjustment is not a language detector or
an enforcement gate; the checks above still require observing a real model's
responses.

After that adjustment (2026-10-09), actual CLI checks with `gemma3:1b` covered
English greetings followed by French and explicit English requests for all
three profiles. Rédaction identified itself in French, and an explicit
`En français` request produced French throughout, including the introduction
and headings. However, its spontaneous French post request still received
English, as did French requests to Communauté and Analyse; unsupported claims
and invented metrics remained. Explicit English requests received English.
This is a partial language improvement, not passing behavior acceptance.
The same five-turn Rédaction comparison with `mistral:latest` reached the
test harness's overall 210-second limit before producing complete output;
that attempt establishes no conclusion about language compliance.

On 2026-10-13, seven scripted CLI turns through the SSH launcher with
`qwen3.5:9b-q4_K_M` produced visible answers after the empty-reply and active-role
fixes, with thinking explicitly disabled for that check. This does not establish
the result with the model's default thinking mode. Role queries matched Analyse,
then Communauté, then Analyse after the
corresponding switches. Before the request-only role reminder, the same scenario
still answered Analyse after selecting Communauté. This checks that scenario,
not general persona obedience or claim, privacy and metric acceptance.

A subsequent check with default thinking reproduced a completed empty answer:
the 4096-token context was exhausted by 2987 prompt tokens plus 1109 generated
tokens, with `done_reason: length`. With `SENSAI_CONTEXT_LENGTH=8192`, the same
seven-turn launcher scenario produced seven nonempty answers, all ending with
`stop`; raw stream counters confirmed thinking was active, and Ollama reported
an 8192-token context. After the switches the model correctly identified
Analyse, then Communauté, then Analyse again. The client now reports token-limit termination explicitly
and never records an incomplete answer as a completed turn.

Final verification of runtime switching ran the full test suite as it stood
then, including the four live Ollama integration checks, without skips. Two
consecutive isolated CLI scenarios each completed five turns across Analyse,
Communauté and Rédaction switches, retained the literal fictional campaign code `AZUR729`, rejected an invalid selection
without changing state, and checked every outgoing request and streamed reply.
An earlier live attempt at 8192 still returned no visible answer and was reported
as an error with history preserved. These successful scenarios establish the
tested switching behavior; they do not guarantee that Ollama always produces an answer.

Unit tests establish catalogue validation, selection and prompt assembly, not
the quality or safety of every model response. These persona instructions
are not privacy sanitization, evidence verification or an output-validation
gate. They do not fetch analytics, send replies, save artifacts or deliver the
four-output workflow in [the product scope](scope.md).

## Automated regression coverage

All tests below run offline with scripted clients under `tests/unit/cli/` and `tests/unit/chat/`.

| Criterion | Tests |
|---|---|
| Persona creation | `chat/test_personas.py` (catalogue validation, stripped fields, built-in routing IDs), `cli/test_personas.py` (startup selection, real shared prompt first) |
| Runtime switching with preserved history | `cli/test_personas.py` (three switches through `cli.main`, unchanged turn objects, interrupted and empty replies), `chat/test_session.py`, `cli/test_remote.py` (switching through `sensai-remote`) |
| Invalid-profile errors | `chat/test_personas.py` (blank ID, invalid fields), `cli/test_personas.py` (bad catalogue files, unknown `SENSAI_PERSONA`, JSON object catalogue) |
| Unchanged base-chat streaming | `cli/test_personas.py` (each chunk written and flushed before the next is pulled; no reminder without a switch; cancellation keeps the persona) |

`tests/integration/test_persona_live.py` optionally repeats one switch against a
local Ollama model (skipped when unavailable) and checks only streaming, retained
context and history shape. Model-quality behavior (response language, unsupported
claims, invented metrics) remains a manual check and is not established by these
automated tests.

The stories above were written by the feature's implementers and have not yet
been independently reviewed by another team member; model-quality failures
recorded above remain open.
