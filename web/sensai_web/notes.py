"""The notes folder (data/notes/) in the page: list, read, write and delete the notes file access reads.

Paths are relative, at most three levels deep, .md or .txt only; a symlink anywhere is refused.
"""
import os
import re
import tempfile

from sensai_web.errors import ApiError

DEFAULT_DIR = os.path.join("data", "notes")
PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}\Z")
TYPES = (".md", ".txt")
MAX_BYTES = 1 << 20


class NotesFolder:
    def __init__(self, path: str = DEFAULT_DIR):
        self.path = path

    def _target(self, path: object) -> str:
        parts = path.split("/") if isinstance(path, str) else []
        if not 0 < len(parts) <= 3 or not all(PART.match(p) for p in parts):
            raise ApiError(400, "bad_note_path", "Use a relative path like launch.md or private/costs.md.")
        if not parts[-1].lower().endswith(TYPES):
            raise ApiError(400, "bad_file_type", "Notes are .md or .txt files.")
        target = self.path
        for part in parts:
            target = os.path.join(target, part)
            if os.path.islink(target):
                raise ApiError(400, "bad_note_path", "Notes cannot go through a symlink.")
        return target

    def listing(self) -> dict:
        items = []
        for folder, dirs, names in os.walk(self.path):
            dirs[:] = sorted(d for d in dirs if PART.match(d) and not os.path.islink(os.path.join(folder, d)))
            for name in names:
                full = os.path.join(folder, name)
                if name.lower().endswith(TYPES) and PART.match(name) and not os.path.islink(full):
                    rel = os.path.relpath(full, self.path).replace(os.sep, "/")
                    if rel.count("/") < 3:
                        items.append({"path": rel, "bytes": os.path.getsize(full)})
        return {"dir": self.path.replace(os.sep, "/"), "items": sorted(items, key=lambda i: i["path"])}

    def read(self, path: object) -> dict:
        target = self._target(path)
        if not os.path.isfile(target):
            raise ApiError(404, "not_found", f"No note {path}.")
        try:
            with open(target, encoding="utf-8") as f:
                return {"path": path, "text": f.read(MAX_BYTES)}
        except (OSError, UnicodeDecodeError):
            raise ApiError(422, "not_text", "That note cannot be shown as text.") from None

    def put(self, path: object, text: object) -> dict:
        target = self._target(path)
        if not isinstance(text, str) or "\0" in text:
            raise ApiError(400, "bad_request", "text must be plain text.")
        if len(text.encode("utf-8", "surrogatepass")) > MAX_BYTES:
            raise ApiError(413, "too_large", "A note can be at most 1 MB.")
        if os.path.exists(target) and not os.path.isfile(target):
            raise ApiError(400, "bad_note_path", "That name is taken by a folder.")
        folder = os.path.dirname(target)
        try:
            os.makedirs(folder, exist_ok=True)
            fd, temporary = tempfile.mkstemp(dir=folder, prefix=".note-")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(temporary, target)
        except OSError as exc:
            raise ApiError(500, "notes_folder", f"Cannot write the note: {exc.strerror or exc}") from None
        return self.listing()

    def delete(self, path: object) -> dict:
        target = self._target(path)
        if not os.path.isfile(target):
            raise ApiError(404, "not_found", f"No note {path}.")
        os.remove(target)
        return self.listing()
