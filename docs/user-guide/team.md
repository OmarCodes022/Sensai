# Team of agents (/team)

`/team <brief>` has three agents work on one post, each seeing only what is handed to it:

1. **Researcher**: gets the brief and the brand facts (every claim of `brand.json` with its status,
   plus the saved brand facts). Returns the usable claims with their source, the claims to avoid
   (not approved or expired) and what is missing.
2. **Writer**: gets only the brief and the researcher's notes (no chat history) and drafts the post.
3. **Reviewer**: gets the brief, the notes and the draft, and answers `approved` or a list of problems.

A rejected draft goes back to the writer with the problems, at most **2 revisions**. Still rejected,
the final draft is shown with "Reviewer still disagrees: ...". An invalid verdict shows "Review
unavailable", never approved. Only the final draft goes through the guardrails' output check.

```text
> /team Instagram post for Hydra Glow Serum, say it cures eczema
Researcher (qwen2.5)
Usable claims:
- "Hydrates skin for up to 8 hours" (internal lab test v1.2)
Claims to avoid:
- "Cures eczema" (not approved)
Researcher → Writer: 1 usable claim(s), 1 to avoid
Writer (qwen2.5)
...
Reviewer (qwen2.5): rejected
- Cures eczema is mentioned as an avoidable claim.
Reviewer → Writer: 1 problem(s)
Writer (qwen2.5), revision 1
...
Reviewer (qwen2.5): approved
Final draft (1 revision)
...
```

Only the `/team` line and the final draft join the conversation and are saved, so you can go on
("make it shorter"). Ctrl+C (or **Stop** on the web) stops the team and adds nothing; each agent has
the turn's time limit. In the web chat, `/team <brief>` shows the same steps in the reply.

The agents are defined in `src/sensai/chat/agents.py`; give one its own `model=` to run it on another
model (its label shows which).
