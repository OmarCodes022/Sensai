## Story 1

As a skincare creator, I want Sensai to fetch my weekly engagement figures from our metrics tool, so that my weekly report uses the real numbers.

- Sensai displays `sensai.weekly_engagement` and its requested week, and asks for approval.
- The answer matches the CSV: 630 engaged out of 4,200 reached for 21 September 2026, or 15%.
- Zero reach gives `n/a`; incomplete daily coverage is marked incomplete and non-unique.

## Story 2

As a creator, I want to plug in existing MCP tools by editing a config file, so that I can add abilities without changing Sensai's code.

- After adding a server and using `/mcp reload` or **Reload MCP**, its tools appear in the listing and can be used in chat.
- A broken server shows a warning while other tools and chat keep working.
- Removing a server and reloading removes its tools without losing the conversation.
