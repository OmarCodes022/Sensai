"""The sandbox data folder: list, add, delete and example data, under the sandbox's own limits."""
import os
import re
import tempfile

from sensai.sandbox import SandboxLimits, _wanted
from sensai_web.errors import ApiError

DEFAULT_DIR = "data"
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}\Z")
TYPES = (".csv", ".tsv", ".json", ".txt", ".md")  # Text only; never anything Python could import.
EXAMPLE_NAME = "engagement.csv"
EXAMPLE = """date,channel,accounts_reached,accounts_engaged,engagement_rate,source
2026-09-21,Instagram,1200,180,15.0,instagram_insights_daily
2026-09-22,Instagram,950,95,10.0,instagram_insights_daily
2026-09-23,Instagram,1100,143,13.0,instagram_insights_daily
2026-09-24,Instagram,800,72,9.0,instagram_insights_daily
2026-09-25,Instagram,1300,195,15.0,instagram_insights_daily
2026-09-26,Instagram,750,60,8.0,instagram_insights_daily
2026-09-27,Instagram,1050,126,12.0,instagram_insights_daily
2026-09-28,Instagram,0,0,n/a,instagram_insights_daily
2026-09-21/2026-09-27,Instagram,4200,630,15.0,instagram_insights_weekly_unique
"""


class DataFolder:
    """Files copied into every run_python folder. `path` is None until the folder exists."""

    def __init__(self, path: str | None):
        self.path = path
        self._limits = SandboxLimits()

    @property
    def location(self) -> str:
        return os.path.abspath(self.path or DEFAULT_DIR)

    def _files(self) -> list[tuple[str, int]]:
        if self.path is None or not os.path.isdir(self.path):
            return []
        with os.scandir(self.path) as entries:
            return sorted((e.name, e.stat(follow_symlinks=False).st_size) for e in entries if _wanted(e))

    def listing(self) -> dict:
        return {"dir": self.location, "exists": self.path is not None and os.path.isdir(self.path),
                "files": [{"name": name, "bytes": size} for name, size in self._files()],
                "limits": {"file_mb": self._limits.file_bytes // 2**20, "total_mb": self._limits.data_bytes // 2**20,
                           "types": list(TYPES)}}

    @staticmethod
    def _name(name: object) -> str:
        if not isinstance(name, str) or not NAME.match(name):
            raise ApiError(400, "bad_file_name", "Use letters, digits, dots, dashes and underscores (no folders).")
        if not name.lower().endswith(TYPES):
            raise ApiError(400, "bad_file_type", f"Only {', '.join(TYPES)} files can be added.")
        return name

    def put(self, name: object, text: object) -> dict:
        name = self._name(name)
        if not isinstance(text, str):
            raise ApiError(400, "bad_request", "text must be a string.")
        data = text.encode("utf-8", "surrogatepass")
        if b"\x00" in data:
            raise ApiError(400, "not_text", "That does not look like a text file.")
        if len(data) > self._limits.file_bytes:
            raise ApiError(413, "too_large", f"A file can be at most {self._limits.file_bytes // 2**20} MB.")
        folder = self.path or DEFAULT_DIR
        target = os.path.join(folder, name)
        others = sum(size for other, size in self._files() if other != name)
        if others + len(data) > self._limits.data_bytes:
            raise ApiError(413, "too_large", f"The folder can hold {self._limits.data_bytes // 2**20} MB in total.")
        try:
            os.makedirs(folder, exist_ok=True)
            if os.path.islink(target) or (os.path.exists(target) and not os.path.isfile(target)):
                raise ApiError(400, "bad_file_name", "That name is taken by something that is not a plain file.")
            fd, temporary = tempfile.mkstemp(dir=folder, prefix=".upload-")
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                os.replace(temporary, target)
            except BaseException:
                try:
                    os.remove(temporary)
                except OSError:
                    pass
                raise
        except OSError as exc:
            raise ApiError(500, "data_folder", f"Cannot write to the data folder: {exc.strerror or exc}") from None
        self.path = folder
        return self.listing()

    def delete(self, name: object) -> dict:
        name = self._name(name)
        target = os.path.join(self.path or DEFAULT_DIR, name)
        if self.path is None or os.path.islink(target) or not os.path.isfile(target):
            raise ApiError(404, "not_found", f"No data file named {name}.")
        try:
            os.remove(target)
        except OSError as exc:
            raise ApiError(500, "data_folder", f"Cannot remove the file: {exc.strerror or exc}") from None
        return self.listing()

    def add_example(self) -> dict:
        if any(name == EXAMPLE_NAME for name, _ in self._files()):
            raise ApiError(409, "exists", f"{EXAMPLE_NAME} is already in the data folder.")
        return self.put(EXAMPLE_NAME, EXAMPLE)
