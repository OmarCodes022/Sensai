"""The weekly campaign document (M4): four sections, each a status and its items (pydantic models)."""
from typing import Literal

from pydantic import BaseModel, Field

Status = Literal["draft", "approved"]
SECTIONS = ("posts", "replies", "report", "calendar")
EDITABLE = ("posts", "calendar")  # The report and DM replies are filled only by the weekly run.


class Post(BaseModel):
    id: str
    caption: str
    channel: str = "Instagram"
    claim_ids: list[str] = []


class Reply(BaseModel):
    case_key: str
    question: str
    suggestion: str


class Report(BaseModel):
    period_start: str
    period_end: str
    timezone: str
    source: str
    extracted_at: str
    accounts_reached: int | None
    accounts_engaged: int | None
    engagement_rate: str  # "15.0%" or "n/a (zero reach)": set by code, never by the model
    interpretation: str = ""


class Entry(BaseModel):
    id: str
    date: str
    time: str
    channel: str = "Instagram"
    post_id: str
    theme: str


class Section(BaseModel):
    status: Status = "draft"
    approved_at: str | None = None


class Posts(Section):
    items: list[Post] = []


class Replies(Section):
    items: list[Reply] = []
    eligible: int | None = None  # None: the inbox was not read yet; 0 is a verified empty queue
    left_out: list[str] = []


class ReportSection(Section):
    item: Report | None = None


class Calendar(Section):
    items: list[Entry] = []


class Sections(BaseModel):
    posts: Posts = Field(default_factory=Posts)
    replies: Replies = Field(default_factory=Replies)
    report: ReportSection = Field(default_factory=ReportSection)
    calendar: Calendar = Field(default_factory=Calendar)


class Campaign(BaseModel):
    week: str
    start: str
    end: str
    timezone: str = "Europe/Paris"
    created_at: str
    updated_at: str
    sections: Sections = Field(default_factory=Sections)


# The edits the model must answer with (T5: Ollama is forced into these schemas).

class PostEdit(BaseModel):
    op: Literal["add", "replace", "remove"]
    id: str | None = Field(None, description="the post to replace or remove; null to add")
    caption: str = Field(description="the full caption, in the brand voice (empty to remove)")
    claim_ids: list[str] = Field([], description="ids of the approved claims the caption uses")


class EntryEdit(BaseModel):
    op: Literal["add", "replace", "remove"]
    id: str | None = Field(None, description="the entry to replace or remove; null to add")
    date: str = Field(description="YYYY-MM-DD inside the campaign week (use the dates table for day names)")
    time: str = Field(description="HH:MM, 24-hour")
    post_id: str = Field(description="an existing post id, e.g. P1")
    theme: str = Field(description="a short theme for the post")


EDIT_SCHEMAS = {"posts": PostEdit, "calendar": EntryEdit}
