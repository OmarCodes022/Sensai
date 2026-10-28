"""Serve the packaged page from web/static, nothing outside it."""
from pathlib import Path
from urllib.parse import unquote

from sensai_web.errors import ApiError

ROOT = (Path(__file__).parent / "static").resolve()
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
         ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon",
         ".woff2": "font/woff2", ".txt": "text/plain; charset=utf-8"}


def read(path: str, root: Path = ROOT) -> tuple[str, bytes]:
    """(content type, bytes) of a static file; "/" is the page. Raise ApiError 404 otherwise."""
    relative = unquote(path).lstrip("/") or "index.html"
    if "\x00" in relative or "\\" in relative or any(part in ("", "..") for part in relative.split("/")):
        raise ApiError(404, "not_found", "Not found.")
    target = (root / relative).resolve()
    kind = TYPES.get(target.suffix.lower())
    if kind is None or root not in target.parents or not target.is_file():
        raise ApiError(404, "not_found", "Not found.")
    return kind, target.read_bytes()
