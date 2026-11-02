# A2 Multi-Agent Orchestration: user stories

## Story 1: A reviewer checks every draft against my approved claims

As Nadia, the creator of Serein Studio, I want a reviewer agent to check every draft against my
approved claims, so that no post contains a claim I cannot support.

Acceptance criteria:
1. A draft with a claim to avoid is rejected with the reason, and the writer revises it.
2. The reviewer checks again, at most 2 revisions; still rejected, I see "Reviewer still disagrees:
   ..." next to the last draft instead of a falsely approved post.
3. An invalid verdict shows "Review unavailable", never approved, and the final draft still goes
   through the guardrails' output check.

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
