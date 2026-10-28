# Sensai web UI

A framework-free, build-free single-page app in `web/sensai_web/static/`. Plain ES modules, hash routes, no network except same-origin `/api/*`. Strict CSP (`script-src 'self'; style-src 'self'`): no inline scripts or styles.

## How to run

Everything below is run from the repository root (the folder with `pyproject.toml`), after the setup in the root README.

Real mode (the default): `sensai-web` serves this folder at `/` and the endpoints below under `/api/`, same origin, on top of the existing chat, tools, sessions and sandbox code (the CLI logic is not changed).

```
.venv/bin/sensai-web gemma3:1b       # then open http://127.0.0.1:8765/
.venv/bin/sensai-web gemma3:1b --port 9000 --persona analyse --db my.sqlite3 --creator nadia
.venv/bin/sensai-web --session k7f2qa    # resume a saved session (model from SENSAI_MODEL)
```

It takes the CLI options (`--host` for Ollama, `--prompt`, `--persona`, `--personas-file`, `--session`, `--db`, `--creator`, `--profile-file`, `--operation-timeout`) and the same `.env` variables. It only listens on loopback (`127.0.0.1`, `localhost` or `::1`): the sandbox is not a security boundary, so it is never exposed to the network. Requests need a matching `Host` header (DNS rebinding), same-origin posts and `application/json`. One turn runs at a time (HTTP 429 `busy`), and a second browser tab gets 409 until it takes over.

Differences from the mock: titles are the model's own (one extra request after the first turn). Each turn's start and finish are recorded in a `web_turn_times` table of the same database (storage keeps no timestamps), so restored sessions show times; turns made in the terminal have none. `usage.prompt_tokens` is the last request's token count (the context size) and output tokens add up over tool rounds. Restored assistant messages show no token counts, since storage does not keep them.

Remote Ollama: with `SENSAI_SSH_HOST` set (and `OLLAMA_HOST=http://127.0.0.1:11435`, as for `sensai-remote`), `sensai-web` opens the same SSH tunnel for as long as it runs and `/api/health` reports `remote: true`. The tunnel code is the CLI's; it was tested here with a stand-in, not against a real SSH host.

Mock mode (no backend, no model, works offline):

```
.venv/bin/python -m http.server -d web/sensai_web/static 8765
# open http://localhost:8765/index.html?mock=1
```
or add `?mock=1` to the address of a running `sensai-web`. `?mock=1` swaps `js/api.js` to `js/mock/mock-api.js` (same interface, scripted scenarios, latency, error injection). `Ctrl/Cmd+Shift+D` opens the dev panel. Without `?mock=1`, if `/api/health` fails twice the app falls back to mock and shows a visible banner.

Self test: open `selftest.html` (XSS payloads, stream parser, formatters, view logic). Gallery: `gallery.html`.

## API contract (client side, `js/api.js` is the only module that calls the backend)

```
GET  /api/health          {ok, version, ollama:{reachable,host,latency_ms}, model:{name,available}, remote}
GET  /api/config          {capabilities, draft_personas, context_length, creator, model, limits:{turn_seconds,tool_rounds,sandbox:{wall_seconds,cpu_seconds,memory_mb,file_mb,output_chars,data_mb}}, effective?}
GET  /api/personas        {active, source, items:[{id,name,tone,role,response_scope,starters?}]}
POST /api/persona         {id} -> {active}
GET  /api/session         session shape (below)       POST /api/sessions   new empty session
GET  /api/sessions        {items:[{id,title,created_at,updated_at,persona,messages}]}
GET  /api/sessions/{id}   session shape               POST /api/sessions/{id}/resume
GET  /api/history         {items:[{n,text}]}
POST /api/chat {text}     application/x-ndjson stream     POST /api/chat/stop -> {stopped}
POST /api/approvals/{id}  {approved}
GET  /api/tools           {items:[{name,description,parameters,timeout,confirm,max_calls}]}
POST /api/run {code}      {exit_code,duration_s,timed_out,truncated,stdout,stderr,report,limits?}
GET  /api/run/data        {dir,exists,files:[{name,bytes}],limits:{file_mb,total_mb,types}}
PUT  /api/run/data/{name} {text} -> listing        DELETE /api/run/data/{name} -> listing
POST /api/run/data/example   adds engagement.csv (409 if present) -> listing
GET  /api/docs            {state,folder,embed_model,documents,pending,error,items:[{name,bytes,state,source,version,title,product,chunks}],limits}
PUT  /api/docs/{name} {text} -> listing     DELETE /api/docs/{name} -> listing     POST /api/docs/reindex -> listing
GET  /api/docs/search?q=  {items:[{source,score,text}],state}
GET/PUT /api/profile      {id,preferences}; PUT body {preferences}
POST /api/session/takeover
```

Errors: `{"error":{"code","message","hint"}}`. HTTP 409 means another tab owns the session (lock dialog).

Added by this round (assumption, not in the original contract): `GET /api/config` may carry `effective: { <key>: {value, source} }` with keys `ollama_host, model, request_timeout, turn_budget, context_length, database_path, creator, profile_file, data_dir, prompt_file, personas_file` and `source` one of `cli, env, dotenv, default`. `GET /api/health` may carry `uptime_s`. When absent, Settings shows the flat fields it has, `n/a` for the rest, and says the sources are not reported. The mock reports `effective`; nothing else does yet.

Session items: `{kind:"user",n,text,at}`, `{kind:"assistant",text,persona,usage|null,tools,at}`, `{kind:"tool",...}`, `{kind:"event",text}`.

Stream events (one JSON per line): `turn_start`, `text`, `tool_call`, `approval_request`, `approval_result`, `tool_result` (with `meta` for `run_python`), `usage` (any count may be null), `title`, `saved`, `warning`, `sources`, `done` (`completed|interrupted|timed_out`), `error`. `sources` (`items:[{n,source,version,score,outdated}]`) follows a `search_docs` result. Planned, ignored unless the capability is true: `redacted`, `blocked`, `step`. A stream that ends without `done` is a network error.

Planned endpoints (documented, never called while the capability is false): `/api/campaign/{week}`, `/api/campaign/{week}/edit`, `/api/campaign/{week}/approve`, `/api/weekly-run`, `/api/brand`, `/api/facts`, `/api/docs`, `/api/docs/search`, `/api/docs/reindex`, `/api/context`, `/api/stats`, `/api/export`, `/api/share`, `/api/schedule`, `/api/safety`, `/api/evals`.

## Capability flags

Booleans in `/api/config.capabilities`; a missing key is false: `chat personas sessions profile usage tools approval sandbox run_script history guardrails facts documents context_budget campaign weekly_run export share web_search mcp think team ask_user file_access cache examples prompt_versions branching stats schedule evaluation`.

A route in `js/router.js` with `cap` renders its real view when that flag is true, otherwise the Planned view. Mapping: `campaign` -> campaign, `facts` -> brand, `documents` -> documents, `stats` -> insights, `guardrails` -> safety, `schedule` -> schedule. There is no roadmap page.

## Views added in this round

- `#/sessions`: sortable table (`aria-sort`), persona filter, detail panel with the user's messages, Open (asks first if a reply is streaming). Cards under 768 px.
- `#/personas`: read-only catalogue, Use button, how-to for a custom catalogue file.
- `#/profile`: key-value list, JSON editor with live line-level validation, confirm modal, `PUT`. Never auto-saves; success is shown only after the backend answers.
- `#/tools`: registry, recent calls (built from the stored session items), sandbox runner reusing the `run_python` result card. Cancel only stops waiting: the real `POST /api/run` has no cancel, and the UI says so.
- `#/settings`: effective configuration with source chips, secret-looking keys shown as "hidden", UI preferences, reset, backend card with capability chips.
- `#/keynote`: launcher plus a presenter bar on `<body>` (body class `keynote`, `keynote-record` for record-friendly). Mock only: scenarios are played by the mock backend. Play, pause, step, restart, speed 0.5x to 3x, beat timeline, notes (`N`).
- Planned views with mock previews behind a "Preview with mock data" toggle, each card with a MOCK ribbon: campaign (week header, four tabs, command box with before/after card, weekly run), brand, documents (local word-overlap search, no model), insights, safety, schedule. Preview buttons that would change data are inert and say so.
- Print: `css/print.css`, `js/print.js` (expands tool cards and details before printing), `js/chat/print-head.js`. The campaign preview carries a hidden one-page document (figures table plus week grid) that replaces the page in print.

## How to add a view

1. Add a route to `ROUTES` in `js/router.js` (`live: true`, or `cap: '<flag>'` with `tasks`).
2. Create `js/views/<name>.js` exporting `mount(root, ctx)`; `ctx = {store, api, router, t, announce, actions, layout, params}`. Return an unmount function if you subscribe to anything. Use `viewShell(name, ...)` from `js/components/view.js` for the title and one `h1`.
3. Planned: add `planned.<name>.{desc,b1..b3,c1..c3}` strings and `js/views/preview/<name>.js` exporting `mountPreview(root, {store})`; put fixtures in `js/mock/`.
4. Add strings to BOTH `strings.en.json` and `strings.fr.json` with identical keys, and a nav key `nav.<name>`.
5. Keep files under 300 lines; build DOM with `h()` (never `innerHTML`).

## String keys (737 per language, identical in en and fr)

- `common` (24): `na`, `planned`, `mockData`, `cancel`, `confirm`, `close`, `copy`, `copied`, `copyFailed`, `copyCommand`, `retry`, `clear`, `loading`, `remove`, `copyDetails`, `stop`, `send`, `run`, `refuse`, `viewAll`, `saved`, `nothingSent`, `dismiss`, `loadError`
- `nav` (14): `chat`, `sessions`, `personas`, `profile`, `tools`, `settings`, `campaign`, `brand`, `documents`, `insights`, `safety`, `schedule`, `keynote`, `views`
- `theme` (3): `system`, `light`, `dark`
- `topbar` (4): `toggleSidebar`, `toggleInspector`, `search`, `themeNext`
- `chat` (33): `new`, `placeholder`, `hint`, `empty`, `thinking`, `greeting`, `greetingName`, `interrupted`, `interruptedToast`, `timeLimit`, `noMessages`, `ariaLabel`, `budget`, `composerLabel`, `interruptedDivider`, `jump`, `loadError`, `noSuchMessage`, `replyComplete`, `replying`, `resumedFrom`, `source`, `sourceNone`, `starters`, `thinkingS`, `timedOutDivider`, `title`, `transcript`, `waitReply`, `disabled.offline`, `disabled.locked`, `disabled.approval`, `disabled.resuming`
- `everything` (1): `local`
- `draft` (1): `label`
- `session` (7): `new`, `id`, `copyId`, `idCopied`, `saved`, `notSaved`, `savedAfter`
- `creator` (2): `chip`, `tip`
- `persona` (7): `switcher`, `none`, `details`, `tone`, `toast`, `changed`, `waitTip`
- `status` (14): `button`, `ollama`, `model`, `ollamaReady`, `checking`, `cannotReach`, `host`, `latency`, `modelAvailable`, `modelMissing`, `modelUnknown`, `modelFixed`, `remote`, `remoteShort`
- `sessions` (26): `title`, `search`, `untitled`, `empty`, `noMatch`, `loadError`, `switchTitle`, `switchMessage`, `stopSwitch`, `stay`, `allPersonas`, `filterPersona`, `col.title`, `col.id`, `col.persona`, `col.messages`, `col.created`, `col.updated`, `dir.asc`, `dir.desc`, `sortedBy`, `tableCaption`, `detail`, `detailNone`, `detailHint`, `open`
- `time` (7): `justNow`, `minutes`, `hours`, `days`, `today`, `yesterday`, `thisWeek`
- `usage` (10): `tokens`, `tokensNa`, `inOut`, `latency`, `server`, `turns`, `notReported`, `outputTokens`, `promptTokens`, `reported`
- `meter` (1): `text`
- `inspector` (13): `title`, `turn`, `context`, `tools`, `sources`, `noTurn`, `noTurnBody`, `persona`, `usage`, `contextMeter`, `meterUnknown`, `sourcesBody`, `meterPartial`
- `tools` (57): `confirm`, `none`, `loadError`, `roundLimit`, `group`, `registry`, `recent`, `sandboxTitle`, `col.name`, `col.description`, `col.timeout`, `col.confirm`, `col.max`, `col.time`, `col.tool`, `col.status`, `col.duration`, `col.message`, `noConfirm`, `noLimit`, `recentNone`, `openChat`, `codeLabel`, `helper`, `tooBig`, `notUtf8`, `loaded`, `loadFile`, `run`, `running`, `finished`, `elapsed`, `cancelled`, `dataTitle`, `noData`, `dataDir`, `limitsHelp`, `limitsTitle`, `limit.wall`, `limit.wall.d`, `limit.cpu`, `limit.cpu.d`, `limit.mem`, `limit.mem.d`, `limit.file`, `limit.file.d`, `limit.out`, `limit.out.d`, `notProtected`, `not.malicious`, `not.network`, `not.absolute`, `not.memory`, `not.cpu`, `not.fork`, `not.group`, `not.kill`
- `shortcuts` (14): `title`, `send`, `newline`, `stop`, `recall`, `palette`, `newChat`, `sidebar`, `inspector`, `shortcuts`, `searchSidebar`, `approval`, `views`, `theme`
- `palette` (8): `title`, `placeholder`, `none`, `sessions`, `personas`, `views`, `commands`, `planned`
- `cmd` (5): `newChat`, `theme`, `sidebar`, `shortcuts`, `copyId`
- `lock` (4): `title`, `body`, `takeover`, `closeHint`
- `banner` (4): `fallback`, `mock`, `offline`, `reconnect`
- `link` (6): `title`, `body`, `open`, `host`, `idnChip`, `idn`
- `code` (3): `wrap`, `showAll`, `plain`
- `md` (2): `imageHidden`, `source`
- `notfound` (2): `title`, `body`
- `router` (2): `notBuilt.title`, `notBuilt.body`
- `planned` (48): `youWillBeAbleTo`, `acceptance`, `owners`, `mockToggle`, `mockNote`, `noPreview`, `campaign.desc`, `campaign.b1`, `campaign.c1`, `campaign.b2`, `campaign.c2`, `campaign.b3`, `campaign.c3`, `brand.desc`, `brand.b1`, `brand.c1`, `brand.b2`, `brand.c2`, `brand.b3`, `brand.c3`, `documents.desc`, `documents.b1`, `documents.c1`, `documents.b2`, `documents.c2`, `documents.b3`, `documents.c3`, `insights.desc`, `insights.b1`, `insights.c1`, `insights.b2`, `insights.c2`, `insights.b3`, `insights.c3`, `safety.desc`, `safety.b1`, `safety.c1`, `safety.b2`, `safety.c2`, `safety.b3`, `safety.c3`, `schedule.desc`, `schedule.b1`, `schedule.c1`, `schedule.b2`, `schedule.c2`, `schedule.b3`, `schedule.c3`
- `err` (21): `connection`, `model_not_found`, `timeout`, `turn_timeout`, `llm_error`, `invalid_response`, `storage`, `profile_invalid`, `persona_unknown`, `tab_locked`, `network`, `guardrail_refused`, `code`, `details`, `editProfile`, `generic`, `hint`, `http`, `openPersonas`, `openStatus`, `time`
- `approval` (13): `title`, `paused`, `refused`, `approved`, `honesty`, `incomplete`, `more`, `moreOne`, `reason`, `refusedShort`, `running`, `ranOk`, `ranFail`
- `dev` (9): `export`, `fill`, `inject`, `none`, `reset`, `scenario`, `speed`, `title`, `turn`
- `errb` (12): `connection`, `model_not_found`, `timeout`, `llm_error`, `invalid_response`, `profile_invalid`, `persona_unknown`, `tab_locked`, `guardrail_refused`, `network`, `storage`, `turn_timeout`
- `esc` (1): `hidden`
- `export` (4): `assistant`, `date`, `session`, `you`
- `guard` (1): `redacted`
- `hint` (4): `largePaste`, `privacy`, `privacyGuarded`, `undo`
- `history` (3): `note`, `noteEdit`, `title`
- `menu` (12): `copyMd`, `download`, `go`, `hideTokens`, `hideTools`, `jump`, `jumpLabel`, `print`, `serverExport`, `showTokens`, `showTools`, `title`
- `msg` (9): `assistantLabel`, `copyMd`, `copyPlain`, `details`, `interruptedHidden`, `notSent`, `reuse`, `you`, `youN`
- `py` (16): `code`, `cpuLimit`, `errors`, `exit`, `fileLimit`, `gotoLine`, `limitCpu`, `limitMem`, `limitWall`, `noErrors`, `noOutput`, `output`, `signal`, `tabs`, `timeLimit`, `truncated`
- `reconnect` (2): `done`, `text`
- `slash` (27): `label`, `none`, `plannedMsg`, `foot.move`, `foot.complete`, `foot.pick`, `foot.close`, `persona`, `history`, `tools`, `run`, `new`, `help`, `read`, `save`, `docs`, `reindex`, `search`, `facts`, `context`, `campaign`, `export`, `share`, `unshare`, `think`, `team`, `edit`
- `starter` (9): `redaction.1`, `redaction.2`, `redaction.3`, `communaute.1`, `communaute.2`, `communaute.3`, `analyse.1`, `analyse.2`, `analyse.3`
- `tool` (14): `arguments`, `finished`, `label`, `round`, `started`, `timedOut`, `using`, `status.running`, `status.waiting`, `status.ok`, `status.error`, `status.refused`, `status.timeout`, `status.cancelled`
- `personas` (20): `builtin`, `custom`, `readOnly`, `howTitle`, `howIntro`, `shape`, `required`, `errorsTitle`, `err.missing`, `err.extra`, `err.blank`, `err.duplicate`, `err.unknown`, `none`, `active`, `use`, `inUse`, `role`, `scope`, `guard`
- `profile` (19): `plaintext`, `creatorKey`, `injected`, `empty`, `emptyBody`, `create`, `edit`, `editor`, `line`, `err.empty`, `err.syntax`, `err.notObject`, `err.notString`, `valid`, `replace`, `confirmTitle`, `confirmBody`, `saved`, `noAuto`
- `settings` (49): `effective`, `prefs`, `backend`, `k.ollama_host`, `k.model`, `k.request_timeout`, `k.turn_budget`, `k.context_length`, `k.database_path`, `k.creator`, `k.profile_file`, `k.data_dir`, `k.prompt_file`, `k.personas_file`, `packaged`, `builtin`, `none`, `hidden`, `source`, `sourceNa`, `dataNote`, `noSources`, `prefsNote`, `theme`, `density`, `comfortable`, `compact`, `fontSize`, `small`, `default`, `large`, `motion`, `reduce`, `lang`, `showTokens`, `showTools`, `showNumbers`, `draftLabel`, `reset`, `resetBody`, `resetDone`, `version`, `uptime`, `mode`, `live`, `capCount`, `caps`, `capOn`, `capOff`
- `keynote` (21): `intro`, `needsMock`, `openMock`, `scenario`, `start`, `record`, `recordHelp`, `keys`, `bar`, `play`, `pause`, `step`, `restart`, `exit`, `speed`, `timeline`, `beat`, `fallback`, `notes`, `noNotes`, `done`
- `preview` (4): `notice`, `inert`, `prev`, `next`
- `campaign` (67): `prepare`, `export`, `share`, `print`, `sections`, `tab.posts`, `tab.dm`, `tab.report`, `tab.calendar`, `status.draft`, `status.approved`, `approve`, `approveTitle`, `approveBody`, `locked`, `valid`, `invalid`, `neverPublished`, `exportBlocked`, `dmCounters`, `unsent`, `question`, `suggestion`, `leftOut`, `figure`, `value`, `period`, `tz`, `source`, `reached`, `engaged`, `rate`, `formula`, `interp`, `daily`, `chartLabel`, `tableAlt`, `day`, `zeroReach`, `flag28`, `edgeTitle`, `edge.zero`, `edge.invalid`, `edge.missing`, `view`, `grid`, `list`, `proposal`, `notScheduled`, `noDrag`, `cmd`, `cmdHelp`, `showEdit`, `invalidEdit`, `applyQ`, `postsApproved`, `autoDraft`, `action`, `where`, `replacePost`, `before`, `after`, `apply`, `noChange`, `previewApplied`, `weeklyRun`, `saved`
- `brand` (19): `claims`, `facts`, `readOnly`, `id`, `product`, `text`, `source`, `from`, `until`, `status`, `updated`, `st.valid`, `st.expiring`, `st.expired`, `st.notApproved`, `factsNote`, `memUpdated`, `memWill`, `perCreator`
- `documents` (14): `source`, `type`, `product`, `version`, `chunks`, `reindex`, `reindexNote`, `embedOk`, `pullHint`, `search`, `placeholder`, `noModel`, `score`, `notIn`
- `insights` (14): `kind`, `kindHelp`, `allKinds`, `calls`, `errors`, `failures`, `latency`, `tokens`, `perDay`, `day`, `toolUse`, `sparkCalls`, `sparkLatency`, `plain`
- `safety` (20): `rules`, `direction`, `action`, `reason`, `claimsCount`, `suite`, `defined`, `category`, `cases`, `hold`, `fail`, `notRun`, `suiteTotal`, `eval`, `metric`, `relevance`, `coherence`, `faithfulness`, `flagged`, `planted`
- `schedule` (11): `banner`, `name`, `prompt`, `every`, `minutes`, `last`, `next`, `st.ok`, `st.failed`, `retry`, `drafts`

## Accessibility checklist (honest results)

"Verified" means measured or run in the in-app browser (an emulated viewport) or by script. "By code" means read, not run. "Not done" means not done.

| Item | Result | How |
|---|---|---|
| One `h1` per view, landmarks | Verified (h1), by code (landmarks) | h1 present on all 13 routes plus not found (script). |
| Top bar fits at 1280x720 | Verified | Bar 56 px high, no horizontal overflow, session title on one line with ellipsis and the id and saved state on a second line, all inside the bar (DOM measurement after fix M3). |
| Top bar at 375 and 320 px | Verified | No page or bar overflow; all 6 visible controls are 44x44 (DOM measurement). Persona pill collapses to its avatar with an accessible name ("Persona: <name>"). Session title, id and saved state moved into the Status popover at narrow widths. |
| Touch targets elsewhere | Partly | Table links, sortable header buttons and the presenter bar are 32 px (44 px on coarse pointers or below 768 px) by CSS; not measured. |
| Contrast AA, text and control borders | Verified by script | See the table below. |
| Tables have captions, `scope`, `aria-sort` | By code, sort state verified | Sorting changed `aria-sort` (script). |
| Live regions for sort, run, keynote beat, approval outcome | By code | Polite `role=status`; no screen reader was used. |
| Dialogs, popovers, tabs, segmented controls | By code | Existing components; not keyboard-tested here. |
| Charts have text alternatives | By code | SVG `role=img` plus table in `details` (campaign), sparklines plus per-day table (insights). |
| Hidden and bidi characters visible in model text | Verified by self test | Tag characters, ALM, LS/PS, soft hyphen, CGJ, variation selectors, Hangul fillers and bidi controls become chips or are stripped; tool card name, summary and error covered. |
| Cards under 768 px, widths 768 to 2560, 200 percent zoom | Not done | |
| Keyboard-only run, screen reader spot check | Not done | |
| Forced colors, high contrast, reduced motion | Not verified | |
| Print preview | Not done | CSS written, not looked at. |
| Zero network requests besides `/api/*` | Partly | No external resource entries on the page in a route sweep (script); the pane itself still requests `/favicon.ico` (404) even with the data-URI icon link, which looks like pane behaviour. |
| No `innerHTML` in code, no em dash | PASS | grep. |

### Contrast table (script output, `--line-strong` raised in fix round 1)

Computed from `css/tokens.css` with the WCAG relative luminance formula. Text pairs need 4.5:1, control borders 3:1 (WCAG 1.4.11). `--line` is decorative and intentionally subtle. `--line-strong` is also used for chip outlines and dividers, so those got slightly heavier. It is 2.82:1 (light) and 3.09:1 (dark) against `--surface-3`, which is used for hover and track fills, not as a control background.

| Pair (foreground on background) | Need | Light | Dark | Result |
|---|---|---|---|---|
| ink on paper (text) | 4.5:1 | 16.46 | 15.70 | PASS |
| ink on surface (text) | 4.5:1 | 17.79 | 14.60 | PASS |
| ink-2 on surface (text) | 4.5:1 | 10.28 | 10.49 | PASS |
| ink-2 on surface-2 (text) | 4.5:1 | 8.85 | 9.71 | PASS |
| ink-3 on surface (text) | 4.5:1 | 5.96 | 6.86 | PASS |
| ink-3 on paper (text) | 4.5:1 | 5.52 | 7.38 | PASS |
| ink-3 on surface-2 (text) | 4.5:1 | 5.13 | 6.35 | PASS |
| ink-3 on surface-3 (text) | 4.5:1 | 4.60 | 5.66 | PASS |
| accent on surface (text) | 4.5:1 | 7.36 | 6.75 | PASS |
| accent on paper (text) | 4.5:1 | 6.81 | 7.26 | PASS |
| accent on accent-tint (text) | 4.5:1 | 6.09 | 6.02 | PASS |
| ink-inverse on accent (text) | 4.5:1 | 7.36 | 7.26 | PASS |
| sage on sage-tint (text) | 4.5:1 | 5.39 | 6.06 | PASS |
| amber on amber-tint (text) | 4.5:1 | 5.17 | 6.59 | PASS |
| rose on rose-tint (text) | 4.5:1 | 5.42 | 6.64 | PASS |
| teal on teal-tint (text) | 4.5:1 | 4.97 | 7.41 | PASS |
| plum on plum-tint (text) | 4.5:1 | 6.08 | 6.67 | PASS |
| sage on surface (text) | 4.5:1 | 6.27 | 7.05 | PASS |
| amber on surface (text) | 4.5:1 | 5.84 | 7.87 | PASS |
| rose on surface (text) | 4.5:1 | 6.54 | 7.20 | PASS |
| amber on paper (text) | 4.5:1 | 5.40 | 8.47 | PASS |
| line-strong on surface (control border) | 3:1 | 3.66 | 3.75 | PASS |
| line-strong on paper (control border) | 3:1 | 3.38 | 4.03 | PASS |
| line-strong on surface-2 (control border) | 3:1 | 3.15 | 3.47 | PASS |
| accent on surface (control border) | 3:1 | 7.36 | 6.75 | PASS |
| ink-3 on surface (control border) | 3:1 | 5.96 | 6.86 | PASS |

Every row passes (0 failures in the script output). Not covered: forced-colors mode (system colors), tints on hover states, and text over images (none).

### Spec checklist item 7 deviation

Spec 6.9 says Enter, Esc and blur default to Refuse. Implemented: Esc and Enter-less keys behave as specified (`n`, `Esc` refuse, `y` run after a 400 ms guard). Blur and window focus loss do NOT auto-decide: a stray focus change should not silently refuse a call. On `pagehide` (tab closed or navigated away) a best-effort refusal is still sent. This deviates from item 7 on purpose.

## Known limitations

- Run against the real backend (`sensai-web`) with qwen2.5: chat, calculator, approved `run_python`, persistence and Settings. The `effective` config and `uptime_s` fields are implemented as assumed.
- Sandbox Cancel cannot stop the server-side run.
- Recent calls come from the stored session, so a call appears after its turn completes, not while it streams.
- Keynote needs the mock backend; in real mode it only offers a link to mock mode. "Nadia's Monday" has 5 scripted turns while its notes list 8 beats, and the notes are shown as a list without per-beat highlighting. Its roadmap beat has no matching screen.
- The campaign preview week selector is disabled (one mock week). Approving a section in the preview is local to the page and saves nothing.
- Documents search is a word-overlap toy, not embeddings.
- French strings are my translation and have not been reviewed by a native speaker.
- `js/mock/player.js` now accepts a numeric speed multiplier (used by the keynote slider).

## Fix round 1

M1 hidden-character coverage, M2 tool-card text escaped, M3 and M4 top bar layout, M5 control-border contrast, L1 malformed hash falls back to not found, L2 labels repaint on language change (top bar and sidebar), L3 only finite numbers are known (also exit code, sandbox duration and the context meter, which now marks a partial total), L4 one shared title sanitiser, L5 approval card re-enables Run after a failed decision and updates its settled text when the call finishes, L6 link confirm shows the host and warns on non-ASCII hosts with the punycode form, L7 larger targets, L8 data-URI icon on selftest and gallery. Regression tests for M1, M2, L1 and L3 are in `js/selftest-views.js`.

## What works / current limits / what I would do differently

Works: all live views load without console errors in mock mode (14 routes including a bad route, checked by script), the sessions table sorts and opens its detail panel, the profile editor validates and enables replace only for an object of strings, the sandbox runner returns the mock result in the shared card, the keynote starts, steps a scenario and shows notes, and all planned views render their Planned state and populated mock preview. `selftest.html`: 57 passed, 0 failed.

Current limits: see the accessibility table and the list above. Responsive layouts, print output, keyboard-only and screen reader behavior were not tested.

Differently: define the `/api/config` source shape with the backend team before building Settings, give `/api/run` a cancel, and test responsive and print output in a real browser before calling the work done.
