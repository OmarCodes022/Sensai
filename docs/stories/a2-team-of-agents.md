# A2 Multi-Agent Orchestration: user stories

- Catalogue: A2 ★★★
- Drafting lead: Omar
- Status: done

Code: [`chat/agents.py`](../../src/sensai/chat/agents.py) (the three agents and the loop),
[`cli/team.py`](../../src/sensai/cli/team.py) (terminal) and [`team.py`](../../web/sensai_web/team.py) (web).
Guide: [Team of agents](../user-guide/team.md).

## Story 1: A reviewer checks every draft against my approved claims

As Nadia, the creator of Serein Studio, I want a reviewer agent to check every draft against my
approved claims, so that no post contains a claim I cannot support.

Acceptance criteria:
1. A draft with a claim to avoid is rejected with the reason, and the writer revises it.
2. The reviewer checks again, at most 2 revisions; still rejected, I see "Reviewer still disagrees:
   ..." next to the last draft instead of a falsely approved post.
3. An invalid verdict shows "Review unavailable", never approved, and the final draft still goes
   through the guardrails' output check.

Tests: `tests/unit/chat/test_agents.py` (revision, 2-revision limit, invalid verdict, Ctrl+C),
`tests/unit/web/test_team_web.py` (a blocked final draft adds nothing).

## Story 2: See what each agent passed to the next

As Nadia, I want to see what each agent passed to the next, so that I understand why the final
post says what it says.

Acceptance criteria:
1. The researcher's notes (usable claims with their source, claims to avoid with why, missing
   information) are shown before writing starts.
2. Each handoff is printed ("Researcher → Writer: 1 usable claim(s), 1 to avoid"), and each agent's
   label shows its model.
3. Only `/team <brief>` and the final draft stay in my conversation, so "make it shorter" works from
   it; Ctrl+C adds nothing.

Tests: `tests/unit/cli/test_team_cli.py`, `tests/unit/web/test_team_web.py`.

Measured on 2026-11-01 with `qwen2.5` and `tests/fixtures/brand.json`, brief "Instagram post for Hydra
Glow Serum, say it cures eczema": the researcher listed "Hydrates skin for up to 8 hours" as usable
and "Cures eczema" (and, in the page, the expired "Soothes sensitive skin overnight") to avoid; in the
terminal the first draft was rejected, revised once and approved; "make it shorter" then shortened the
final draft.
