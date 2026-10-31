"""The brand fact sheet (M3): facts the model saves, corrects and deletes itself through two tools.

Tool calls only queue a change; the queue is written to SQLite when the turn completes, and
dropped when it is interrupted or fails, so a bad reply never changes the stored facts.
"""
import re
from collections.abc import Callable
from datetime import date

from sensai.core.ports import Fact, ToolDefinition, ToolResult

PROFILE = "default"
FACTS_HEADER = "Brand facts (saved memory, newest wording wins; keep them current with save_fact and delete_fact):"
FACT_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,39}(?:\.[a-z0-9][a-z0-9-]{0,39}){1,3}\Z")
MAX_TEXT = 300
BLOCK = re.compile(r"\n\n" + re.escape(FACTS_HEADER) + r"(?:\n- [^\n]*)*")

SAVE_FACT = ToolDefinition(
    "save_fact",
    "Save or correct one brand fact the creator told you (a price, a date, a product detail). "
    "Reuse the id from the fact list to correct a fact.",
    {"type": "object", "properties": {
        "id": {"type": "string", "description": "entity.topic, lowercase with dashes, e.g. hydra-glow-serum.price"},
        "text": {"type": "string", "description": "the fact in one short sentence"}},
     "required": ["id", "text"]},
)
DELETE_FACT = ToolDefinition(
    "delete_fact",
    "Delete a brand fact that is no longer true, by its id from the fact list.",
    {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
)


class FactMemory:
    """One creator's facts; `store` is a FactStorePort (creator.facts)."""

    def __init__(self, store, today: Callable[[], date] = date.today):
        self.store = store
        self.today = today
        self.pending: dict[str, str | None] = {}  # id -> new text, or None to delete

    def facts(self) -> tuple[Fact, ...]:
        return self.store.list_for(PROFILE)

    def _known(self) -> set[str]:
        ids = {fact.id for fact in self.facts()}
        for fact_id, text in self.pending.items():
            (ids.add if text is not None else ids.discard)(fact_id)
        return ids

    # Tool handlers (timeout=None: they run in this process, next to the queue).

    def save(self, arguments, cancellation=None) -> ToolResult:
        fact_id, text = arguments.get("id"), arguments.get("text")
        if not isinstance(fact_id, str) or not FACT_ID.match(fact_id):
            return ToolResult("", "invalid id: use entity.topic in lowercase with dashes, e.g. hydra-glow-serum.price")
        if not isinstance(text, str) or not text.strip() or "\n" in text.strip() or len(text) > MAX_TEXT:
            return ToolResult("", f"invalid text: one non-empty line of at most {MAX_TEXT} characters")
        verb = "update" if fact_id in self._known() else "add"
        self.pending[fact_id] = " ".join(text.split())
        return ToolResult(f"Will {verb} {fact_id} when this reply completes.")

    def delete(self, arguments, cancellation=None) -> ToolResult:
        fact_id = arguments.get("id")
        if not isinstance(fact_id, str) or fact_id not in self._known():
            return ToolResult("", f"no fact with id {fact_id!r}; nothing to delete")
        self.pending[fact_id] = None
        return ToolResult(f"Will delete {fact_id} when this reply completes.")

    # Turn boundaries

    def drop(self) -> None:
        self.pending.clear()

    def commit(self) -> list[str]:
        """Write the queued changes; one 'Memory: …' line per change."""
        stored = {fact.id for fact in self.facts()}
        lines = []
        for fact_id, text in self.pending.items():
            if text is None:
                if fact_id in stored:
                    self.store.delete(PROFILE, fact_id)
                    lines.append(f"Memory: deleted {fact_id}")
            else:
                self.store.upsert(PROFILE, Fact(fact_id, text, f"chat {self.today().isoformat()}"))
                lines.append(f"Memory: {'updated' if fact_id in stored else 'added'} {fact_id}")
        self.pending.clear()
        return lines

    # Display

    def block(self) -> str:
        facts = self.facts()
        return "\n".join([FACTS_HEADER, *(f"- {f.id}: {f.text}" for f in facts)]) if facts else ""

    def listing(self) -> list[str]:
        facts = self.facts()
        if not facts:
            return ["No saved facts yet. Tell Sensai a product fact and it will remember it."]
        width = max(len(f.id) for f in facts)
        return [f"{f.id.ljust(width)}  {f.text}  ({f.source})" for f in facts]


def with_facts(prompt: str, block: str, tools_text: str = "", docs_text: str = "") -> str:
    """The system prompt with the fact block placed before the documents and tool instructions."""
    core = prompt.removesuffix(tools_text).rstrip() if tools_text else prompt
    docs = docs_text and f"\n\n{docs_text}" in core
    if docs:
        core = core.replace(f"\n\n{docs_text}", "")
    core = BLOCK.sub("", core)
    parts = [core, block, docs_text if docs else "", tools_text]
    return "\n\n".join(part for part in parts if part)
