# MCP tools

Sensai supports MCP stdio tools using protocol **2025-11-25** and its `initialize` handshake, and accepts servers answering with an older version of that handshake (2024-11-05 onwards). HTTP servers, resources, prompts, and the newer stateless protocol are outside this feature.

Inside Sensai, **`/mcp`** shows the config file in use, each server's status and these setup steps: in the terminal it prints them, in web chat it opens the **MCP servers** section of the Tools view. Sensai never edits the file for you, because each entry runs a local command.

Copy `mcp.example.json` to `mcp.json`. Run Sensai with the Python environment containing Sensai activated, so the example's `python -m sensai.mcp_server` resolves correctly. Install [uv](https://docs.astral.sh/uv/getting-started/installation/) for the reference `uvx mcp-server-time==2026.10.28` server, or install that release separately and configure its executable. The time server can download dependencies on first startup.

`SENSAI_MCP_CONFIG` selects another configuration file. No file means no MCP tools. Entries under `mcpServers` accept `command`, an `args` array, and optional `env` string overrides. Commands execute locally during discovery, so Sensai first shows them and asks **Trust this file?**: in the terminal at startup or on `/mcp reload`, in the web Tools view otherwise. Until you accept, nothing from the file runs, which protects you when you start Sensai in a downloaded folder that ships its own `mcp.json`. The answer covers that path and that exact content, and editing the file asks again. Trust does not cover what a command does later or the scripts it loads, so only accept servers you know. Your answers are kept in `~/.config/sensai/trusted-mcp.json`; delete an entry to be asked again. Keep credentials in the environment; local `mcp.json` is ignored by Git.

Startup discovers tools such as `sensai.weekly_engagement` and `time.get_current_time`. `/tools` and the web Tools view list them. Each call requires approval through the existing terminal prompt or web approval card. Denial prevents execution. The model receives tool results and errors through the same loop as the calculator.

After editing the configuration, use **`/mcp reload`** in terminal chat or **Reload MCP** in the web Tools view (`/mcp reload` also works in web chat). Reload refreshes only MCP tools, preserves your conversation, and is allowed between turns. Removing a server removes its tools. Invalid configuration keeps the previous tools and reports the error; a broken individual server is omitted while other servers remain available. Fix the configuration and reload again.

## Weekly engagement demo

Our server reads packaged fictional figures by default. Ask “What was the engagement rate for the week starting 21 September 2026?” The weekly unique row gives **630 / 4,200 = 15%**. For another week's available daily rows, totals are marked non-unique and missing days are listed. Zero reach gives `n/a`.

To read another CSV, set the server environment:

```json
{"mcpServers":{"sensai":{"command":"python","args":["-m","sensai.mcp_server"],"env":{"SENSAI_ENGAGEMENT_CSV":"/absolute/path/engagement.csv"}}}}
```

Columns: `date`, `channel`, `accounts_reached`, `accounts_engaged`. Dates are ISO daily dates or `YYYY-MM-DD/YYYY-MM-DD` weekly ranges from Monday through Sunday. Channels are reported separately. Negative counts, engaged counts above reach, and duplicate date/channel rows are rejected. A matching weekly row takes precedence over daily rows. The tool requires an ISO Monday `week_start`.

## Lifecycle and failures

Discovery and calls each have a 30-second budget. Servers start afresh for every call and are stopped afterwards, including on timeout or cancellation. This makes cleanup simple but adds startup latency to every call. Results are cut at 10,000 characters. Startup and `/mcp reload` check servers one at a time and cannot be interrupted, so a hung server delays them by up to 30 seconds. Server stderr is discarded; protocol errors are surfaced without dumping commands or environment values.

For a demonstration, try the question above and “What time is it in Tokyo?” Approve each call. Then try an invalid server command, deny a call, or interrupt a slow call: chat remains usable. The two user stories are in [MCP stories](https://github.com/OmarCodes022/Sensai/blob/main/docs/stories/t1-mcp-tools.md).
