# Features

The Epitech subject lists optional features in a catalogue where each one has
an ID, and B1 is the base chat every project must have. This page explains the
base features; [More features](#more-features) lists the others. Every feature
works in the terminal and in the [web page](../user-guide/web.md).

## Base chat (B1)

Nadia types a message and the reply appears as the model writes it. Sensai
sends the whole conversation with each message, so the model remembers what
she said earlier in the chat. She chooses the model when she starts Sensai, or
once in her configuration file. If Ollama is not running, the model is missing
or a reply takes too long, Sensai says so in one line and the chat goes on. She
can stop a reply at any moment with Ctrl+C or Esc.

[Chatting](../user-guide/chatting.md)

## Personas (A5)

A persona gives the assistant a name, a role, a tone and a scope. Sensai ships
with three: Rédaction drafts posts and captions, Communauté prepares reply
suggestions that Nadia sends herself, and Analyse turns the figures she gives
it into a weekly report. She can switch persona in the middle of a chat, and
the new persona sees the whole conversation. She can also replace the built-in
list with her own personas in a JSON file, without touching the code.

[Personas](../user-guide/personas.md)

## Sessions and profile (M1)

Sensai saves each chat on Nadia's computer after every completed exchange. She
can list her past sessions, each with a short title, and resume one the next
day with its history and its persona. Her creator profile, such as her tone and
her audience, is added to the instructions of every chat, so she never repeats
it. She can also reread her own messages of the current session.

[Sessions and profile](../user-guide/sessions.md)

## Tools

The model can ask Sensai to run a tool, then finish its answer with the result.
The first tool is a calculator, so a figure such as an engagement rate is
computed, not guessed. Nadia sees one line naming each tool Sensai uses; the
raw request stays hidden. She can list the available tools at any time.

[Tools and sandbox](../user-guide/tools.md)

## Python sandbox

The model can also write a short Python program, for example to average a week
of reach from Nadia's exported engagement figures. Sensai always shows her the
code first and runs it only if she agrees. The code runs in a temporary folder
with a copy of her data files and strict limits on time, memory and output, and
the folder is deleted afterwards. She can run her own Python files the same
way, without the model.

[Tools and sandbox](../user-guide/tools.md)

## Self-correcting code (T2)

When a figure must be computed, the model writes Python and Sensai runs it in
the sandbox, after Nadia agrees. If the code fails, the traceback goes back to
the model, which fixes its code; Sensai asks her again before each new try.
The model gets 3 runs per question, then must report the last error instead
of guessing, and its answer quotes the number the code printed. It knows the
names of her data files, never their contents. The code, the results and the
answer are saved with the session.

[Tools and sandbox](../user-guide/tools.md)

## Long conversations (M2)

When a conversation fills 80% of the model's window, Sensai summarizes the
oldest messages into one, keeping the system prompt, the persona and the last
4 messages as they are. Nadia can plan a week of posts in one long chat and
still get her launch date right at the end. `/context` shows how full the
window is, and `/compact` summarizes on demand, in the terminal and the page.

[Long conversations](../user-guide/context.md)

## Reasoning step by step (A1)

With `/think`, Sensai works through a request in visible steps: it writes a
plan, computes the figures with its tools, drafts an answer, checks the draft
against Nadia's request, the tool results and her brand rules, and revises it
when the check finds a problem such as a claim she may not make. She sees
every step, so she knows where each figure comes from. The loop stops after a
fixed number of steps and lists anything still wrong. Only her request and the
final answer stay in the chat.

[Reasoning step by step](../user-guide/thinking.md)

## More features

| Feature | Guide |
| --- | --- |
| Branching and interrupt (X2) | [Sessions](../user-guide/sessions.md#editing-an-earlier-message-branching) |
| MCP tools (T1) | [MCP tools](../user-guide/mcp.md) |
| Team of agents (A2) | [Team of agents](../user-guide/team.md) |
| Weekly campaign document and weekly run (M4, T5, A3) | [Campaign document](../user-guide/campaign.md) |
| Brand document search, advanced search (R1, R2) | [Document search](../user-guide/documents.md) |
| Brand facts memory (M3) | [Brand facts](../user-guide/brand-facts.md) |
| Guardrails (EV2) | [Guardrails](../user-guide/guardrails.md) |
| Answer scoring (EV1) | [Results](https://github.com/OmarCodes022/Sensai/tree/main/evals/faithfulness) |
| File access within permissions (T4) | [File access](../user-guide/files.md) |
| Questions and forms (X4) | [Questions and forms](../user-guide/questions.md) |
| Web search (T3) | [Web search](../user-guide/web-search.md) |
| Export and public links (X3) | [Export](../user-guide/export.md) |
| Scheduled drafts (X5) | [Scheduled drafts](../user-guide/scheduling.md) |
| Semantic cache (A6), picked examples (A7) | [Cache](../user-guide/cache.md), [Examples](../user-guide/examples.md) |
| Usage log and statistics (EV3) | [Usage log](../user-guide/insights.md) |
| Prompt versions (A4) | [Prompt versions](https://github.com/OmarCodes022/Sensai/tree/main/evals/prompt_compare) |

Each has at least two user stories: see the [stories index](../stories/README.md).
