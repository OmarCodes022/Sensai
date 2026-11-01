# Web interface

Every feature of the terminal chat also works in a page served from your machine:

```bash
.venv/bin/sensai-web qwen2.5      # http://127.0.0.1:8765/ (--port to change)
```

It uses the same options, database, creator and `.env` as the terminal, and listens on `127.0.0.1`
only. Add `?mock=1` to the address for a demo without a model.

| Page | What it does |
| --- | --- |
| Chat | streaming replies, Stop, edit an earlier message, `/think`, `/team`, `/search`, `/context`, `/compact`; tool, approval and form cards; document and web sources |
| Sessions, Profile, Personas | resume or delete a session, edit the profile, pick or write a persona |
| Campaign | the week's four sections, **Run the week**, approve, edit with the confirm card, **Share** |
| Documents, Brand facts | the indexed brand files; the facts the model saved |
| Tools | every tool with its timeout, approval and call limit, MCP tools included |
| Safety | the guardrail rules and **Check an answer** (answer scoring) |
| Insights | calls, errors, latency, tokens, tools and days from the usage log |
| Schedule | the recurring drafts, **Run now** |
| Settings | the effective configuration and where each value comes from, theme and language, prompt versions side by side |
| Keynote | a scripted offline demo on the recorded mock backend |

Only one tab talks to Sensai at a time; another tab offers to take over. Tool calls work best with a
larger model such as `qwen2.5`.
