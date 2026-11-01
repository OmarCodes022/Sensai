"""Load, create and save the week's document, written atomically so a crash never leaves a broken file."""
import os
import tempfile
from datetime import date, datetime, timedelta, timezone

from sensai.campaign.models import Campaign

DEFAULT_DIR = "campaigns"


class CampaignError(ValueError):
    """An edit or a command that cannot be applied; the file is left unchanged."""


def coming_week(today: date | None = None) -> tuple[str, date, date]:
    """(ISO week id, Monday, Sunday) of the week after today's."""
    today = today or date.today()
    monday = today - timedelta(days=today.weekday()) + timedelta(days=7)
    year, week, _ = monday.isocalendar()
    return f"{year}-W{week:02d}", monday, monday + timedelta(days=6)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class CampaignStore:
    def __init__(self, folder: str = DEFAULT_DIR, today=date.today):
        self.folder = folder
        self.today = today

    def path(self, week: str) -> str:
        return os.path.join(self.folder, f"{week}.json")

    def has_any(self) -> bool:
        return os.path.isdir(self.folder) and any(n.endswith(".json") for n in os.listdir(self.folder))

    def latest(self) -> Campaign:
        """The document changed last (a weekly run may prepare an earlier week), or a new one for the coming week."""
        names = [n for n in os.listdir(self.folder) if n.endswith(".json")] if os.path.isdir(self.folder) else []
        if names:
            newest = max(names, key=lambda n: (os.path.getmtime(os.path.join(self.folder, n)), n))
            return self.load(newest[:-5])
        week, start, end = coming_week(self.today())
        doc = Campaign(week=week, start=start.isoformat(), end=end.isoformat(), created_at=now(), updated_at=now())
        self.save(doc)
        return doc

    def load(self, week: str) -> Campaign:
        try:
            with open(self.path(week), encoding="utf-8") as f:
                return Campaign.model_validate_json(f.read())
        except (OSError, ValueError) as exc:
            raise CampaignError(f"cannot read {self.path(week)}: {exc}") from None

    def save(self, doc: Campaign) -> str:
        os.makedirs(self.folder, exist_ok=True)
        target = self.path(doc.week)
        fd, temporary = tempfile.mkstemp(dir=self.folder, prefix=".campaign-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(doc.model_dump_json(indent=2) + "\n")
            os.replace(temporary, target)
        except BaseException:
            try:
                os.remove(temporary)
            except OSError:
                pass
            raise
        return target
