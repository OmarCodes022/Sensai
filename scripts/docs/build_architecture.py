"""Build editable Sensai architecture diagrams for Draw.io/Lucidchart."""

from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET


DIAGRAMS = Path(__file__).resolve().parents[2] / "docs" / "diagrams"
OUTPUT = DIAGRAMS / "sensai-architecture.drawio"
SIMPLE_OUTPUT = DIAGRAMS / "sensai-simple.drawio"
STRATEGY_OUTPUT = DIAGRAMS / "sensai-strategy-flow.drawio"
INK = "#172033"
NAVY = "#151D2D"
BLUE = "#315FCE"
TEAL = "#277D75"
PURPLE = "#7554BC"
ORANGE = "#AF671E"
MUTED = "#536078"


class Page:
    def __init__(self, parent: ET.Element, page_id: str, title: str, width: int, height: int):
        diagram = ET.SubElement(parent, "diagram", {"id": page_id, "name": title})
        graph = ET.SubElement(diagram, "mxGraphModel", {
            "dx": "1600", "dy": "1000", "grid": "1", "gridSize": "10",
            "guides": "1", "tooltips": "1", "connect": "1", "arrows": "1",
            "fold": "1", "page": "1", "pageScale": "1",
            "pageWidth": str(width), "pageHeight": str(height), "math": "0", "shadow": "0",
        })
        self.root = ET.SubElement(graph, "root")
        ET.SubElement(self.root, "mxCell", {"id": "0"})
        ET.SubElement(self.root, "mxCell", {"id": "1", "parent": "0"})
        self.prefix = page_id
        self.next_id = 0
        self.keys: dict[str, str] = {}
        self.width = width

    def cell(self, label: str, x: int, y: int, w: int, h: int, style: str, key: str | None = None):
        self.next_id += 1
        cell_id = f"{self.prefix}-{self.next_id}"
        if key is not None:
            if key in self.keys:
                raise ValueError(f"duplicate diagram key: {key}")
            self.keys[key] = cell_id
        cell = ET.SubElement(self.root, "mxCell", {
            "id": cell_id, "value": label, "style": style, "vertex": "1", "parent": "1",
        })
        ET.SubElement(cell, "mxGeometry", {
            "x": str(x), "y": str(y), "width": str(w), "height": str(h), "as": "geometry",
        })
        return cell_id

    def background(self, x: int, y: int, w: int, h: int, color: str):
        self.cell("", x, y, w, h,
                  f"rounded=1;arcSize=3;fillColor={color};strokeColor=#DCE2EE;strokeWidth=1;")

    def text(self, label: str, x: int, y: int, w: int, h: int,
             size: int = 18, color: str = INK, bold: bool = False):
        self.cell(label, x, y, w, h,
                  f"text;html=1;whiteSpace=wrap;overflow=fill;align=left;verticalAlign=middle;"
                  f"strokeColor=none;fillColor=none;fontFamily=Arial;fontSize={size};"
                  f"fontColor={color};fontStyle={1 if bold else 0};")

    def card(self, key: str, title: str, detail: str, x: int, y: int,
             w: int, h: int = 116, color: str = BLUE):
        label = f"<b>{title}</b><br><font color='{MUTED}'>{detail}</font>"
        self.cell(label, x, y, w, h,
                  f"rounded=1;arcSize=11;whiteSpace=wrap;html=1;align=left;"
                  f"verticalAlign=middle;spacingLeft=20;spacingRight=12;spacingTop=8;"
                  f"fillColor=#FFFFFF;strokeColor={color};strokeWidth=2;"
                  f"fontFamily=Arial;fontSize=16;fontColor={INK};",
                  key)

    def edge(self, source: str, target: str, label: str = "", color: str = BLUE,
             dashed: bool = False, reverse: bool = False, down: bool = False):
        self.next_id += 1
        exit_x, entry_x = (0, 1) if reverse else (1, 0)
        exit_y, entry_y = 0.5, 0.5
        if down:
            exit_x = entry_x = 0.5
            exit_y, entry_y = 1, 0
        style = (
            f"edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;"
            f"html=1;strokeColor={color};strokeWidth=2;endArrow=block;endFill=1;"
            f"fontFamily=Arial;fontSize=13;fontColor={color};labelBackgroundColor=#FFFFFF;"
            f"exitX={exit_x};exitY={exit_y};entryX={entry_x};entryY={entry_y};"
        )
        if dashed:
            style += "dashed=1;dashPattern=6 5;"
        cell = ET.SubElement(self.root, "mxCell", {
            "id": f"{self.prefix}-{self.next_id}", "value": label, "style": style,
            "edge": "1", "parent": "1", "source": self.keys[source], "target": self.keys[target],
        })
        ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})

    def routed_edge(self, source: str, target: str, points: list[tuple[int, int]],
                    label: str, color: str):
        self.next_id += 1
        cell = ET.SubElement(self.root, "mxCell", {
            "id": f"{self.prefix}-{self.next_id}", "value": label,
            "style": f"edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;"
                     f"strokeColor={color};strokeWidth=3;endArrow=block;endFill=1;"
                     f"dashed=1;dashPattern=8 5;fontFamily=Arial;fontSize=16;"
                     f"fontColor={color};labelBackgroundColor=#FFFFFF;"
                     f"exitX=0.5;exitY=1;entryX=0;entryY=0.5;",
            "edge": "1", "parent": "1", "source": self.keys[source], "target": self.keys[target],
        })
        geometry = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
        waypoints = ET.SubElement(geometry, "Array", {"as": "points"})
        for x, y in points:
            ET.SubElement(waypoints, "mxPoint", {"x": str(x), "y": str(y)})

    def heading(self, title: str, subtitle: str):
        self.cell("", 0, 0, self.width, 140, f"fillColor={NAVY};strokeColor=none;")
        self.text(title, 55, 23, self.width - 110, 66, 36, "#FFFFFF", True)
        self.text(subtitle, 57, 87, self.width - 114, 34, 16, "#A8E0D6")


def architecture(root: ET.Element):
    p = Page(root, "system", "01 - System architecture", 2910, 1850)
    p.heading("SENSAI  |  SYSTEM ARCHITECTURE",
              "Skincare creator's own brand: existing Ollama CLI + proposed future capabilities")
    p.text("TEAL = implemented B1    |    BLUE / PURPLE = proposed    |    Solid arrow = runtime path    |    Dashed = background or alternate path",
           57, 158, 2750, 45, 16, MUTED)

    lanes = [
        (50, 420, "#F0FBF9", "01  CHANNELS", TEAL),
        (495, 545, "#F1F6FF", "02  CONVERSATION", BLUE),
        (1065, 585, "#F5F2FF", "03  ORCHESTRATION", PURPLE),
        (1675, 635, "#F1F6FF", "04  CAPABILITIES", BLUE),
        (2335, 525, "#FAF7FF", "05  STATE & OPERATIONS", PURPLE),
    ]
    for x, w, fill, label, color in lanes:
        p.background(x, 240, w, 1435, fill)
        p.text(label, x + 21, 250, w - 42, 53, 22, color, True)

    def column(x, w, entries):
        for i, (key, title, detail, color) in enumerate(entries):
            p.card(key, title, detail, x + 15, 320 + i * 169, w - 30, 130, color)

    column(50, 420, [
        ("cli", "B1  CLI  ·  existing", "sensai [model] / python -m sensai; streams text", TEAL),
        ("web", "X1  Web UI", "Decoupled frontend + usage and agent controls", BLUE),
        ("schedule", "X5  Scheduler", "Interval triggers for unattended tasks", BLUE),
        ("forms", "X4  Questions & forms", "Collect and return structured user answers", BLUE),
        ("interrupt", "X2  Branch / interrupt", "Fork old turns; cancel in-flight generations", BLUE),
        ("share", "X3  Export / publication", "Automatic private files; public links need approval", BLUE),
        ("user", "USER / AUTOMATION", "Requests, reviews, approvals, and results", TEAL),
    ])
    column(495, 545, [
        ("settings", "B1  Settings + prompt  ·  existing", "pydantic-settings; prompt file; selectable model", TEAL),
        ("input", "EV2  Input guardrails", "Check unsafe / out-of-scope content before Ollama", BLUE),
        ("session", "B1  ChatSession  ·  existing", "In-session turns, streaming, rollback on LLM error", TEAL),
        ("context", "M1 + M2  Context assembly", "Profiles, saved sessions, token budget + compression", BLUE),
        ("prompt", "A4 + A5 + A7  Prompt layer", "Versions, switchable personas, adaptive prompts", BLUE),
        ("retrieve", "R1 + R2 + A6  Grounding", "Retrieve/rerank documents; semantic cache", BLUE),
        ("output", "EV2 + T5  Output gate", "Privacy/content check + schema-conformant JSON", BLUE),
        ("delivery", "B1 + X1 + X4  Delivery", "Progressive stream to CLI / web / forms", TEAL),
    ])
    column(1065, 585, [
        ("reason", "A1  Reasoning loop", "Plan, act, observe, verify; bounded iterations", PURPLE),
        ("agents", "A2  Multi-agent routing", "Specialized agents coordinate on shared tasks", PURPLE),
        ("dispatch", "T1  Tool dispatch", "Structured MCP tool calls and result messages", PURPLE),
        ("approval", "A3 + T4  Permission gate", "Approve public actions; scope every file operation", PURPLE),
        ("structured", "T5  Structured responses", "Schema generation and validation", PURPLE),
        ("artifact", "M4  Artifact coordinator", "Four private outputs: posts, replies, report, calendar", PURPLE),
        ("metrics", "EV3  Telemetry", "Prompts, tools, latency, token usage, errors", PURPLE),
        ("evaluation", "EV1 + EV4  Evaluation", "LLM-as-judge, faithfulness, adversarial tests", PURPLE),
    ])
    column(1675, 635, [
        ("ollama", "B1  Ollama HTTP API  ·  existing", "requests POST /api/chat; local model; streamed chunks", TEAL),
        ("mcp", "T1  MCP servers", "Own tools and pre-existing MCP server", BLUE),
        ("sandbox", "T2  Isolated code runtime", "Run generated code; capture output / traceback", BLUE),
        ("search", "T3  Live web search", "Search, extract and cite retrieved results", BLUE),
        ("files", "T4  Scoped file access", "Read/write/create only inside granted paths", BLUE),
        ("memory", "M3  Structured memory CRUD", "Agent-managed facts, entities and relationships", BLUE),
        ("rag", "R1 + R2  Document pipeline", "Chunk, embed, index, search, filter and rerank", BLUE),
        ("publisher", "X3  Export / link service", "Private downloads; approved public shared views", BLUE),
    ])
    column(2335, 525, [
        ("models", "LOCAL MODEL SERVICE", "Ollama model weights + embeddings via HTTP", PURPLE),
        ("history", "M1 + X2  Session store", "Persistent turns, profiles and branches", PURPLE),
        ("facts", "M3  Facts database", "SQLite or another structured local store", PURPLE),
        ("vectors", "R1 + R2  Vector index", "Embeddings, document metadata and scores", PURPLE),
        ("documents", "M4 + T4  Local files", "Artifacts and permission-scoped documents", PURPLE),
        ("versions", "A4 + A6  Version / cache store", "Prompt history and scoped semantic cache", PURPLE),
        ("observability", "EV3  Metrics / dashboard", "Interaction logs, costs, latency and errors", PURPLE),
        ("links", "X3  Public views", "Approval, share-link storage and revocation", PURPLE),
    ])

    for source, target, label in [
        ("cli", "settings", "input"),
        ("web", "input", ""),
        ("settings", "session", ""),
        ("session", "reason", "turn"),
        ("reason", "ollama", "stream"),
        ("dispatch", "mcp", "tool"),
        ("approval", "files", "allowed"),
        ("ollama", "models", ""),
        ("context", "history", ""),
        ("memory", "facts", ""),
        ("rag", "vectors", ""),
        ("metrics", "observability", ""),
        ("publisher", "links", ""),
    ]:
        p.edge(source, target, label)
    p.edge("schedule", "session", "trigger", dashed=True)
    p.edge("evaluation", "observability", "offline", dashed=True)
    p.text("Boundaries: no LLM framework; every model / embedding request goes directly to the local Ollama HTTP API. "
           "The catalog is a blueprint, not a claim that these extensions are already implemented.",
           65, 1695, 2780, 100, 18, INK)


FEATURES = [
    ("Memory & Context", [
        ("M1", "Session Persistence & Profiles", "Reload sessions; auto-inject a persistent user profile."),
        ("M2", "Token Budgeting & Compression", "Count tokens; summarize older turns near the cap. Needs metrics."),
        ("M3", "External Structured Memory", "Agent-managed facts / entities via structured CRUD."),
        ("M4", "Artifact & State Document", "Parseable incremental edits to a living document."),
    ]),
    ("Tools", [
        ("T1", "MCP", "Tool calls through own and pre-existing MCP servers."),
        ("T2", "Sandboxed Code Execution", "Isolated runtime; feed stdout / errors back into the loop."),
        ("T3", "Web Search", "Live search results injected into model context."),
        ("T4", "File Access within Permissions", "Policy check before every read / write / create."),
        ("T5", "Structured Output", "Validated JSON conforming to a defined schema."),
    ]),
    ("RAG", [
        ("R1", "Basic RAG", "Ingest, chunk, embed, index, retrieve and inject."),
        ("R2", "Advanced RAG", "After R1: rerank, filter metadata and score relevance."),
    ]),
    ("Orchestration & Reasoning", [
        ("A1", "Reasoning Loops (ReAct)", "Iterative plan / tool / observation / verification."),
        ("A2", "Multi-Agent Orchestration", "Specialist agents coordinate and hand off work."),
        ("A3", "Human-in-the-Loop", "Pause critical actions until explicit user approval."),
        ("A4", "Prompt Versioning", "Timestamp, compare, measure and roll back prompts."),
        ("A5", "Persona", "Switch profiles at runtime without clearing history."),
        ("A6", "Semantic Cache", "Embedding similarity returns scoped cached replies."),
        ("A7", "Automated Prompt Optimization", "Select examples or adapt prompts using quality signals."),
    ]),
    ("Evaluation", [
        ("EV1", "Automated Eval / Hallucinations", "Judge relevance and faithfulness; flag unsupported claims."),
        ("EV2", "Content & Privacy Guardrails", "Input block; output PII filtering / anonymization."),
        ("EV3", "Logging & Monitoring", "Structured interaction logs, counts, latency and trends."),
        ("EV4", "Adversarial Testing", "Document jailbreak / injection / malformed-input failures."),
    ]),
    ("UX & Lifecycle", [
        ("X1", "Web UI", "Decoupled streaming frontend with configuration controls."),
        ("X2", "Branching / Resume / Interrupt", "Fork old turns; cancel and redirect a live stream."),
        ("X3", "Export & Publication", "Private JSON/Markdown/PDF; approve public no-auth links."),
        ("X4", "Questions & Forms", "User answers to model-generated questions."),
        ("X5", "Scheduling", "Periodic autonomous runs and task triggers."),
    ]),
]


def catalog(root: ET.Element):
    p = Page(root, "catalog", "02 - Complete feature catalog", 2310, 2220)
    p.heading("SENSAI  |  FULL FEATURE MAP",
              "All 28 catalog features: B1 is implemented; every M / T / R / A / EV / X item is a proposed extension")
    p.card("base", "B1  Functional CLI chatbot  ·  IMPLEMENTED",
           "Local Ollama via HTTP; streaming, in-session history, clean errors, model selected by argument or config.",
           55, 175, 2200, 104, TEAL)

    def group(x: int, y: int, name: str, entries: list[tuple[str, str, str]]):
        w = 716
        h = 88 + len(entries) * 112
        p.background(x, y, w, h, "#F4F2FC")
        p.text(f"{name.upper()}  /  {len(entries)}", x + 20, y + 12, w - 40, 52, 23, PURPLE, True)
        for i, (code, title, description) in enumerate(entries):
            p.card(f"feature-{code}", f"{code}  {title}", description,
                   x + 16, y + 76 + i * 112, w - 32, 94, PURPLE)

    (memory, tools, rag, orchestration, evaluation, ux) = FEATURES
    group(55, 310, *memory)
    group(795, 310, *tools)
    group(1535, 310, *rag)
    group(55, 935, *orchestration)
    group(795, 1035, *evaluation)
    group(1535, 700, *ux)
    p.text("Key dependencies  →  M2 needs usage metrics (EV3); R2 extends R1; T1 requires external MCP interoperability; "
           "X1 reuses the conversation backend; T4 scopes files; A3 gates public actions, not private export.",
           810, 1630, 1420, 86, 17, INK)
    p.background(795, 1770, 1456, 270, "#F0FBF9")
    p.text("IMPLEMENTATION CONTRACT", 825, 1785, 1390, 43, 22, TEAL, True)
    p.text("Each implemented additional feature needs at least two user stories with observable acceptance criteria. "
           "The deliverables also require a README with setup, features and usage. "
           "Use direct Ollama HTTP calls, Python 3.10+, and no LLM frameworks.",
           825, 1830, 1365, 173, 19, INK)


def flow(root: ET.Element):
    p = Page(root, "flow", "03 - Runtime flow and codebase", 2730, 1770)
    p.heading("SENSAI  |  REQUEST & TOOL FLOW",
              "How the skincare brand owner gets four private outputs; existing modules are called out below")
    for x, y, w, h, color, title in [
        (50, 215, 2630, 370, "#F0FBF9", "01  INGEST & ASSEMBLE"),
        (50, 620, 2630, 490, "#F1F6FF", "02  PLAN, USE TOOLS & GENERATE"),
        (50, 1145, 2630, 315, "#F5F2FF", "03  VALIDATE, DELIVER & RECORD"),
    ]:
        p.background(x, y, w, h, color)
        p.text(title, x + 20, y + 8, w - 40, 47, 20, TEAL if y == 215 else PURPLE, True)

    def card(key, title, detail, x, y, w=375, h=142, color=BLUE):
        p.card(key, title, detail, x, y, w, h, color)

    card("source", "1  Request", "CLI B1, Web X1, schedule X5, forms X4; cancel/branch X2",
         70, 304, 380, color=TEAL)
    card("guard-in", "2  Input gate  EV2", "Refuse unsafe input or strip sensitive values before model calls",
         495, 304, 385)
    card("load", "3  Load context  M1 / M2", "Session, profile, history; measure tokens and compress",
         925, 304, 385)
    card("enrich", "4  Enrich prompt", "A4/A5/A7 versions and persona; R1/R2 retrieval and ranking",
         1355, 304, 385)
    card("cache", "5  Semantic cache  A6", "After input policy + context scope; hit skips model",
         1785, 304, 385)
    card("route", "6  Route / plan  A1/A2", "Miss: iterative reasoning and specialist coordination",
         2215, 304, 385, color=PURPLE)
    for a, b, name in [
        ("source", "guard-in", ""), ("guard-in", "load", ""), ("load", "enrich", ""),
        ("enrich", "cache", ""), ("cache", "route", "miss"),
    ]:
        p.edge(a, b, name)

    card("model", "Ollama HTTP  ·  B1", "POST /api/chat, stream=True; no LLM framework",
         2215, 727, 385, color=TEAL)
    card("tools", "Tool dispatcher  T1", "MCP client: own + external servers; structured result",
         1785, 727, 385, color=PURPLE)
    card("approve", "Action gate  A3 / T4", "Approval for public send/share; path policy for file IO",
         1355, 727, 385, color=PURPLE)
    card("services", "Capability adapters", "T2 isolated code; T3 live search; T4 files; M3 memory CRUD",
         925, 727, 385)
    card("ground", "Knowledge & artifacts", "R1/R2 vector index; M4 parseable document edits",
         495, 727, 385)
    card("budget", "Loop budget  A1", "Return observations to planner; limit tool iterations",
         70, 727, 380, color=PURPLE)
    p.edge("route", "model", "answer", PURPLE, down=True)
    p.edge("route", "approve", "tool needed", PURPLE, reverse=True)
    p.edge("approve", "tools", "permitted", PURPLE)
    p.edge("tools", "model", "tool result", PURPLE)
    p.edge("services", "approve", "side effect", PURPLE)
    p.edge("ground", "services", "context", BLUE)
    p.edge("budget", "ground", "iteration", PURPLE, dashed=True)

    card("output-gate", "Output gate  EV2 / T5", "Buffer for PII checks; hold strict JSON until schema-valid",
         2044, 1225, 590, 142)
    card("reply", "Deliver reply  B1 / X1", "Posts, DM replies, report, calendar; auto-private export",
         1386, 1225, 590, 142, color=TEAL)
    card("commit", "Save state  M1 / M4 / X2", "Only committed turns; persist profile, branch and artifact",
         728, 1225, 590, 142, color=PURPLE)
    card("observe", "Observe & evaluate  EV1/3/4", "Record tokens, latency, errors; run evals and attack tests",
         70, 1225, 590, 142, color=PURPLE)
    p.edge("model", "output-gate", "chunks", down=True)
    p.edge("cache", "output-gate", "hit (skip model)", ORANGE, dashed=True, down=True)
    p.edge("output-gate", "reply", "approved", reverse=True)
    p.edge("reply", "commit", "", reverse=True)
    p.edge("commit", "observe", "", PURPLE, dashed=True, reverse=True)
    p.text("Response direction: Ollama / cache → output gate → streaming delivery. "
           "Approval refusal, invalid JSON, tool failure, or a cancelled stream are surfaced explicitly; "
           "do not commit partial turns as successful replies.",
           75, 1475, 2550, 74, 18, INK)
    p.text("CURRENT CODE:  src/sensai/app/cli.py  →  session.py  →  llm/base.py  →  llm/ollama.py  →  Ollama HTTP API",
           75, 1550, 2530, 40, 18, TEAL, True)
    p.text("SUPPORTING CODE:  settings.py  ·  prompts.py  ·  messages.py  ·  llm/schemas.py  ·  errors.py  ·  tests/unit/  ·  tests/integration/",
           75, 1605, 2530, 45, 18, INK)
    p.text("Future modules shown above are architectural responsibilities, not files already present in the repository.",
           75, 1660, 2530, 48, 17, MUTED)


def simple(root: ET.Element):
    p = Page(root, "simple", "Features and flow", 2110, 1320)
    p.heading("SENSAI  |  FEATURES & FLOW",
              "Skincare creator's own brand: from approved inputs to four private drafts")
    p.text("TEAL = implemented base loop (B1)    |    PURPLE = optional future features (M / T / R / A / EV / X)",
           65, 159, 1990, 45, 18, MUTED)
    p.background(50, 230, 2010, 350, "#F0FBF9")
    p.text("MAIN FLOW", 76, 247, 1940, 42, 22, TEAL, True)

    steps = [
        ("request", "1  Request", "B1 CLI today; X1 web, X4 forms and X5 scheduling later", 75, TEAL),
        ("context", "2  Build context", "B1 history; M1/M2 memory, R1/R2 documents, A4/A5/A7 prompts", 475, PURPLE),
        ("agent", "3  Decide & act", "A1/A2 reasoning; T1-T4 tools; A3 approval for public actions", 875, PURPLE),
        ("model", "4  Local Ollama", "B1 direct HTTP streaming; tool results feed the next model turn", 1275, TEAL),
        ("answer", "5  Four private outputs", "Posts, DM replies, weekly report, calendar; export locally", 1675, TEAL),
    ]
    for key, title, detail, x, color in steps:
        p.card(key, title, detail, x, 325, 360, 178, color)
    for source, target in zip(steps, steps[1:]):
        p.edge(source[0], target[0])

    p.text("OPTIONAL FEATURE GROUPS", 76, 615, 1940, 48, 23, PURPLE, True)
    groups = [
        ("memory-group", "MEMORY & KNOWLEDGE",
         "M1 saved sessions/profiles · M2 token budget<br>M3 structured facts · M4 living artifact<br>"
         "R1 document retrieval · R2 reranking", 75, 690, 620),
        ("tools-group", "TOOLS",
         "T1 MCP · T2 code sandbox · T3 web search<br>T4 permission-scoped files · T5 structured JSON", 745, 690, 620),
        ("reason-group", "REASONING & PROMPTS",
         "A1 reasoning loop · A2 multi-agent · A3 approval<br>A4 prompt versions · A5 persona · A6 cache · A7 optimization",
         1415, 690, 620),
        ("quality-group", "QUALITY & SAFETY",
         "EV1 automatic evaluation · EV2 input/output guardrails<br>"
         "EV3 monitoring & metrics · EV4 adversarial tests", 75, 955, 950),
        ("experience-group", "EXPERIENCE",
         "X1 web UI · X2 branch/interrupt · X3 private export / approved share<br>"
         "X4 questions/forms · X5 scheduling", 1085, 955, 950),
    ]
    for key, title, detail, x, y, width in groups:
        p.card(key, title, detail, x, y, width, 190, PURPLE)
    p.text("Present implementation = B1 only. The remaining features are catalog options, not working components yet.",
           75, 1190, 1950, 55, 19, INK)


def strategy_flow(root: ET.Element):
    p = Page(root, "strategy", "Skincare creator and her brand - people, product and flow", 4220, 1780)
    p.heading("SENSAI  |  THE SKINCARE CREATOR'S BRAND",
              "One creator, her own brand, her audience and four private deliverables")
    p.text("TEAL = B1 exists today   |   BLUE = proposed   |   PURPLE = conditional   |   ORANGE = approval boundary",
           65, 159, 2700, 48, 18, MUTED)
    p.text("FEATURE REFERENCE", 2855, 32, 1280, 62, 32, "#FFFFFF", True)
    p.text("Catalog ID + what each feature does", 2857, 89, 1250, 38, 17, "#A8E0D6")
    for x, width, fill, title, color in [
        (50, 750, "#F0FBF9", "01  CREATOR + AUDIENCE", TEAL),
        (830, 1200, "#F1F6FF", "02  SENSAI WORKBENCH", BLUE),
        (2060, 740, "#F5F2FF", "03  FOUR CREATOR DELIVERABLES", PURPLE),
    ]:
        p.background(x, 250, width, 1320, fill)
        p.text(title, x + 25, 267, width - 50, 54, 23, color, True)

    def person(x: int, y: int, color: str):
        p.cell("", x + 7, y + 69, 90, 77,
               f"rounded=1;arcSize=42;fillColor={color};strokeColor=none;")
        p.cell("", x + 24, y + 2, 57, 57,
               f"ellipse;fillColor={color};strokeColor=none;")

    outline = "rounded=1;arcSize=10;fillColor=#FFFFFF;strokeColor=#C9D4E5;strokeWidth=2;"
    p.cell("", 80, 340, 690, 200, outline, "owner")
    person(110, 360, TEAL)
    p.text("SKINCARE CREATOR + BRAND OWNER", 250, 356, 495, 58, 22, TEAL, True)
    p.text("Sets her brand goals and voice; approves public sharing and sends.<br>X1 web UI / B1 CLI / A5 personas",
           250, 410, 465, 105, 18)
    p.cell("", 80, 575, 690, 170, outline, "audience")
    person(110, 586, BLUE)
    p.text("AUDIENCE + FOLLOWERS", 250, 586, 480, 55, 21, BLUE, True)
    p.text("Ask questions, read posts and react.<br>Their messages and engagement inform the next brief.",
           250, 637, 480, 91, 18)

    p.cell("", 115, 790, 620, 350,
           f"rounded=1;arcSize=15;fillColor=#FFFFFF;strokeColor={BLUE};strokeWidth=3;",
           "social")
    p.text("CREATOR'S BRAND ACCOUNTS", 144, 802, 560, 56, 23, BLUE, True)
    p.text("Instagram / TikTok / LinkedIn  |  future connector", 145, 850, 550, 36, 16, MUTED)
    for x, title, subtitle in [
        (145, "POSTS", "Published<br>content"),
        (329, "DMs", "Audience<br>messages"),
        (513, "METRICS", "Reach +<br>engagement"),
    ]:
        p.card(f"social-{title.lower()}", title, subtitle, x, 916, 172, 130, BLUE)
    p.text("First demo: import anonymized local data instead of a live account.",
           148, 1075, 550, 46, 16, MUTED)

    p.cell("", 80, 1200, 690, 345, outline, "inputs")
    p.text("CREATOR-APPROVED INPUTS", 108, 1214, 615, 52, 22, TEAL, True)
    for x, title, subtitle in [
        (108, "BRAND DOCS", "R1 knowledge"),
        (322, "DATA CSV", "T2 analysis"),
        (536, "PUBLIC WEB", "T3 trends"),
    ]:
        p.card(f"input-{x}", title, subtitle, x, 1306, 202, 128, TEAL)
    p.text("T4 restricts which brand files the agent may read or edit.",
           111, 1465, 615, 55, 17, MUTED)

    p.cell("", 850, 340, 1160, 174, outline, "assistant")
    p.cell("AI", 886, 378, 96, 96,
           f"ellipse;fillColor={TEAL};strokeColor=none;fontFamily=Arial;fontSize=31;"
           "fontStyle=1;fontColor=#FFFFFF;align=center;verticalAlign=middle;")
    p.text("SENSAI  |  your strategy assistant", 1010, 358, 955, 66, 31, INK, True)
    p.text("B1 local Ollama HTTP chatbot exists today. Everything else below is a proposed extension.",
           1012, 422, 950, 72, 18, MUTED)
    p.card("persona", "Conversation + personas  [A5]",
           "B1 chat; M1 saved creator sessions; M2 context budget. X1 UI, X2 branch/interrupt, "
           "X4 clarification form. Change personas without losing history.",
           850, 565, 540, 208)
    p.card("knowledge", "Creator's brand knowledge  [R1]",
           "M3 structured facts; R1 vector retrieval; R2 filtering/rerank if needed. "
           "T4 permission-scoped files keep brand data private.",
           1450, 565, 540, 208)
    p.card("research", "Research + analytics  [A1]",
           "T2 sandboxed CSV code; T3 live trends; bounded A1 reasoning. "
           "T1 MCP and A2 specialist agents only when justified.",
           850, 830, 540, 208)
    p.card("writing", "Four drafts + living report  [M4]",
           "Post drafts, DM replies, weekly performance report and content calendar. "
           "T5 structured edits; A4 prompt versions and A6 scoped cache if useful. "
           "A7 automatic optimization is a stretch goal.",
           1450, 830, 540, 208)
    p.card("quality", "Check evidence, privacy and reliability",
           "EV1 scores source faithfulness; EV2 checks input/output privacy; "
           "EV3 monitors latency and tokens; EV4 attacks the system with test fixtures.",
           850, 1095, 1140, 188)
    p.card("workspace", "Creator-private brand workspace",
           "Session/profile + brand facts + source index + four saved drafts. Research, drafting "
           "and private export may run automatically; the creator controls public sharing.",
           850, 1330, 1140, 195, PURPLE)

    p.card("posts", "1  POST DRAFTS",
           "Skincare posts in the creator's chosen brand voice, grounded in approved facts.",
           2090, 340, 675, 172)
    p.card("replies", "2  DM REPLY SUGGESTIONS",
           "Draft answers to anonymized audience questions; never sent automatically.",
           2090, 528, 675, 172)
    p.card("report", "3  WEEKLY PERFORMANCE REPORT",
           "Engagement analysis, cited brand/trend insights and next actions.",
           2090, 716, 675, 172)
    p.card("calendar", "4  PROPOSED CONTENT CALENDAR",
           "Post ideas, intended dates and channels; X5 schedules drafts, not publication.",
           2090, 904, 675, 172)
    p.card("private-export", "AUTOMATIC PRIVATE EXPORT  [X3]",
           "After EV2 checks, save/download all four outputs locally. No public link or send.",
           2090, 1100, 675, 134)
    p.card("approval", "PUBLIC SHARE / SEND APPROVAL  [A3]",
           "Only for external sends, publication or a public link: show exact content and "
           "destination; reject keeps the private draft. No live connector in the first demo.",
           2090, 1260, 675, 277, ORANGE)

    p.edge("owner", "assistant", "brief + voice", TEAL)
    p.edge("audience", "social", "messages", BLUE, down=True)
    p.edge("social", "research", "posts / DMs / metrics", BLUE, dashed=True)
    p.edge("inputs", "research", "local demo data", TEAL)
    p.edge("assistant", "persona", down=True)
    p.edge("persona", "knowledge")
    p.edge("knowledge", "writing", down=True)
    p.edge("research", "writing")
    p.edge("writing", "posts", "drafts", dashed=True)
    p.edge("writing", "replies", "drafts", dashed=True)
    p.edge("writing", "report", "analysis + sources")
    p.edge("writing", "calendar", "ideas + dates", dashed=True)
    p.edge("calendar", "private-export", "all four outputs", down=True)
    p.edge("quality", "private-export", "checked", ORANGE)
    p.edge("private-export", "approval", "only if public", ORANGE, dashed=True, down=True)
    p.routed_edge("approval", "social", [(2430, 1640), (65, 1640), (65, 965)],
                  "APPROVED PUBLIC ACTION  (future connector)", ORANGE)

    p.text("Only B1 is implemented. Catalog IDs are feature goals, not completed claims. "
           "Conditional: T1, R2, A2, A4, A6, X3; A7 is stretch. The first demo needs no live social account.",
           68, 1690, 2720, 60, 18, MUTED)

    p.background(2835, 250, 1335, 1375, "#FAFAFE")
    reference = [
        ("BASE", 2855, 280, [
            ("B1", "Functional CLI chatbot", "Stream Ollama replies with in-session history."),
        ]),
        ("MEMORY & CONTEXT", 2855, 420, [
            ("M1", "Session Persistence & Profiles", "Reload chats; auto-inject user preferences."),
            ("M2", "Token Budgeting & Compression", "Track tokens; summarize old context near the cap."),
            ("M3", "External Structured Memory", "Agent-managed records of facts and entities."),
            ("M4", "Artifact & State Document", "Incrementally update a separate living document."),
        ]),
        ("TOOLS", 2855, 760, [
            ("T1", "MCP", "Call external tools; return results to the model."),
            ("T2", "Sandboxed Code Execution", "Run generated code safely and feed back errors."),
            ("T3", "Web Search", "Inject live search results into context."),
            ("T4", "File Access within Permissions", "Check allowed paths before read or write."),
            ("T5", "Structured Output", "Produce JSON validated against a schema."),
        ]),
        ("RAG", 2855, 1170, [
            ("R1", "Basic RAG", "Embed and retrieve local document chunks."),
            ("R2", "Advanced RAG", "Filter, rerank and score retrieved chunks."),
        ]),
        ("ORCHESTRATION & REASONING", 3510, 280, [
            ("A1", "Reasoning Loops (ReAct)", "Iterate through plan, action and observation."),
            ("A2", "Multi-Agent Orchestration", "Coordinate specialized agents on one task."),
            ("A3", "Human-in-the-Loop", "Pause critical actions for explicit approval."),
            ("A4", "Prompt Versioning", "Compare prompt revisions and roll back."),
            ("A5", "Persona", "Switch configurable roles without losing history."),
            ("A6", "Semantic Cache", "Skip model calls for similar past queries."),
            ("A7", "Automated Prompt Optimization", "Adapt prompts using measured quality."),
        ]),
        ("EVALUATION", 3510, 830, [
            ("EV1", "Automated Eval & Hallucinations", "Score answers and flag unsupported claims."),
            ("EV2", "Content & Privacy Guardrails", "Check input/output for sensitive content."),
            ("EV3", "Logging & Monitoring Dashboard", "Track calls, tokens, latency and errors."),
            ("EV4", "Adversarial Testing", "Test injections, jailbreaks and malformed input."),
        ]),
        ("UX & LIFECYCLE", 3510, 1170, [
            ("X1", "Web UI", "Use a decoupled streaming browser interface."),
            ("X2", "Branching / Resume / Interrupt", "Fork old turns or stop a live generation."),
            ("X3", "Export & Publication", "Private JSON/MD/PDF; approved public link."),
            ("X4", "Questions & Forms", "Collect answers to the model's questions."),
            ("X5", "Scheduling", "Run tasks automatically at set intervals."),
        ]),
    ]
    conditional = {"T1", "R2", "A2", "A4", "A6", "X3"}
    for group, x, y, entries in reference:
        p.text(group, x + 8, y, 600, 42, 20, PURPLE, True)
        for i, (code, name, hint) in enumerate(entries):
            top = y + 50 + i * 69
            color = TEAL if code == "B1" else "#778094" if code == "A7" else PURPLE if code in conditional else BLUE
            p.cell("", x, top, 620, 64,
                   "rounded=1;arcSize=9;fillColor=#FFFFFF;strokeColor=#DEE3EF;strokeWidth=1;")
            p.cell(code, x + 10, top + 10, 67, 44,
                   f"rounded=1;arcSize=10;fillColor={color};strokeColor=none;"
                   "fontFamily=Arial;fontSize=16;fontStyle=1;fontColor=#FFFFFF;"
                   "align=center;verticalAlign=middle;", f"ref-{code}")
            p.text(name, x + 88, top + 5, 520, 27, 16, INK, True)
            p.text(hint, x + 88, top + 33, 520, 25, 14, MUTED)
    p.text("B1 exists today. All other entries describe catalog targets, not delivered features.",
           2862, 1650, 1270, 82, 17, MUTED)


def document(builders: tuple) -> ET.Element:
    root = ET.Element("mxfile", {
        "host": "app.diagrams.net", "modified": datetime.now(timezone.utc).isoformat(),
        "agent": "Sensai architecture", "version": "24.0.0", "type": "device",
    })
    for build in builders:
        build(root)
    return root


def main():
    DIAGRAMS.mkdir(parents=True, exist_ok=True)
    for path, builders in [
        (OUTPUT, (architecture, catalog, flow)),
        (SIMPLE_OUTPUT, (simple,)),
        (STRATEGY_OUTPUT, (strategy_flow,)),
    ]:
        root = document(builders)
        ET.indent(root, space="  ")
        path.write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))
        print(f"Wrote {path}")


if __name__ == "__main__":
    main()
