"""Private export (X3, the export half): the conversation and the week's campaign as JSON and Markdown in exports/.

Every text goes through the guardrails' output check first: identifiers are redacted in the
exported copy, and a file with a refused claim is not written (the reason is given). Files are
written atomically and stay on this computer; nothing is uploaded or shared.
"""
import json
import os
import tempfile

from sensai.campaign.models import Campaign
from sensai.chat.blocks import split_block
from sensai.chat.saved_sessions import TOOL_PROTOCOL_PREFIXES
from sensai.core.errors import SensaiError

DEFAULT_DIR = "exports"


class ExportRefused(SensaiError):
    """The guardrails refused something in this file; it was not written."""


class Exporter:
    def __init__(self, guard, folder: str = DEFAULT_DIR):
        self.guard = guard
        self.folder = folder

    # The check before writing

    def clean(self, text: str) -> str:
        """The text with identifiers redacted, line by line; ExportRefused if a line is refused."""
        out = []
        for line in text.split("\n"):
            decision = self.guard.inspect(line, "output") if self.guard is not None else None
            if decision is not None and not decision.allowed:
                raise ExportRefused(decision.reason)
            out.append(decision.text if decision is not None else line)
        return "\n".join(out)

    def _clean_all(self, value):
        if isinstance(value, str):
            return self.clean(value)
        if isinstance(value, list):
            return [self._clean_all(v) for v in value]
        if isinstance(value, dict):
            return {k: self._clean_all(v) for k, v in value.items()}
        return value

    def _write(self, relative: str, text: str) -> str:
        target = os.path.join(self.folder, relative)
        folder = os.path.dirname(target)
        os.makedirs(folder, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=folder, prefix=".export-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(temporary, target)
        except BaseException:
            try:
                os.remove(temporary)
            except OSError:
                pass
            raise
        return target

    # Conversations

    def session(self, session_id: str, title: str, messages) -> list[str]:
        """exports/sessions/<id>.json and .md: the creator's messages and the replies (no system prompt)."""
        turns = []
        for m in messages:
            if m.role == "system" or (m.role == "user" and m.content.startswith(TOOL_PROTOCOL_PREFIXES)):
                continue
            text = split_block(m.content)[0].strip() if m.role == "assistant" else m.content
            if text:
                turns.append({"role": m.role, "content": self.clean(text)})
        title = self.clean(title)
        markdown = "\n\n".join([f"# {title}", f"Session {session_id}"]
                               + [f"## {'You' if t['role'] == 'user' else 'Sensai'}\n\n{t['content']}" for t in turns]) + "\n"
        payload = json.dumps({"id": session_id, "title": title, "messages": turns}, ensure_ascii=False, indent=2) + "\n"
        return [self._write(f"sessions/{session_id}.json", payload), self._write(f"sessions/{session_id}.md", markdown)]

    # The campaign

    def campaign(self, doc: Campaign) -> list[str]:
        """exports/campaigns/<week>.json and .md with the four sections (refused as a whole if any text is)."""
        data = self._clean_all(doc.model_dump())
        payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        return [self._write(f"campaigns/{doc.week}.json", payload), self._write(f"campaigns/{doc.week}.md", markdown(data))]


def markdown(doc: dict) -> str:
    s = doc["sections"]
    lines = [f"# Week {doc['week']} ({doc['start']} to {doc['end']}, {doc['timezone']})", "",
             f"## Post drafts ({s['posts']['status']})", ""]
    lines += [f"- **{p['id']}** · {p['channel']}" + (f" · claims {', '.join(p['claim_ids'])}" if p["claim_ids"] else "")
              + f": {p['caption']}" for p in s["posts"]["items"]] or ["No posts yet."]
    lines += ["", f"## DM reply suggestions, unsent ({s['replies']['status']})", ""]
    lines += [f"- **{r['case_key']}**: {r['question']}\n  - Suggestion: {r['suggestion']}" for r in s["replies"]["items"]] \
        or ["Filled by the weekly run."]
    lines += ["", f"## Weekly report ({s['report']['status']})", ""]
    report = s["report"]["item"]
    if report:
        lines += ["| Figure | Value |", "| --- | --- |",
                  f"| Period | {report['period_start']} to {report['period_end']} ({report['timezone']}) |",
                  f"| Source | {report['source']} |", f"| Accounts reached | {report['accounts_reached']} |",
                  f"| Accounts engaged | {report['accounts_engaged']} |", f"| Engagement rate | {report['engagement_rate']} |"]
        if report["interpretation"]:
            lines += ["", f"Interpretation (not a figure): {report['interpretation']}"]
    else:
        lines.append("No data yet: filled by the weekly run.")
    lines += ["", f"## Content calendar, proposed, not scheduled ({s['calendar']['status']})", ""]
    entries = sorted(s["calendar"]["items"], key=lambda e: (e["date"], e["time"]))
    lines += (["| Date | Time | Channel | Post | Theme |", "| --- | --- | --- | --- | --- |"]
              + [f"| {e['date']} | {e['time']} | {e['channel']} | {e['post_id']} | {e['theme']} |" for e in entries]) \
        if entries else ["No entries yet."]
    return "\n".join(lines) + "\n"
