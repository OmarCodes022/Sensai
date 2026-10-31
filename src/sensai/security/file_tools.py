"""read_file, write_file and create_file for the model, and the shared helpers /read and /save use.

Paths are relative to the project folder; every operation goes through LocalFileSystem's check.
"""
import os
from pathlib import PurePosixPath

from sensai.core.ports import PolicyDenied, PortError, ToolDefinition, ToolResult
from sensai.security.filesystem import LocalFileSystem

MAX_READ = 20_000
PATH = {"type": "string", "description": "path relative to the project folder, e.g. notes/launch.md"}
READ_FILE = ToolDefinition("read_file", "Read a text file the creator allowed (path relative to the project folder).",
                           {"type": "object", "properties": {"path": PATH}, "required": ["path"]})
WRITE_FILE = ToolDefinition("write_file", "Replace the text of an existing file the creator allowed you to change.",
                            {"type": "object", "properties": {"path": PATH, "content": {"type": "string"}},
                             "required": ["path", "content"]})
CREATE_FILE = ToolDefinition("create_file", "Create a new text file where the creator allowed it (never overwrites).",
                             {"type": "object", "properties": {"path": PATH, "content": {"type": "string"}},
                              "required": ["path", "content"]})
FILE_TOOLS = (READ_FILE, WRITE_FILE, CREATE_FILE)


class FileTools:
    def __init__(self, fs: LocalFileSystem, root: str):
        self.fs = fs
        self.root = os.path.abspath(root)

    def absolute(self, path: object) -> str:
        if not isinstance(path, str) or not path.strip():
            raise PolicyDenied("give a path")
        path = path.strip()
        # Kept as typed (no resolving): the policy refuses .. and the adapter refuses links.
        return path if path.startswith("/") else str(PurePosixPath(self.root) / path.removeprefix("./"))

    def read(self, path: object) -> str:
        return self.fs.read_text(self.absolute(path))

    def save(self, path: object, content: str) -> str:
        """Create the file, or replace it when it exists: 'Created' or 'Replaced'."""
        target = self.absolute(path)
        try:
            self.fs.create_text(target, content)
            return "Created"
        except PortError as exc:
            if isinstance(exc, PolicyDenied) or not os.path.lexists(target):
                raise
        self.fs.write_text(target, content)
        return "Replaced"

    # Tool handlers (timeout=None: they run in this process, with the loaded policy).

    def _run(self, action, arguments) -> ToolResult:
        path = arguments.get("path")
        try:
            return ToolResult(action(path))
        except PolicyDenied as exc:
            return ToolResult("", f"Permission denied: {exc} ({path})")
        except PortError as exc:
            return ToolResult("", f"File error: {exc} ({path})")

    def read_file(self, arguments, cancellation=None) -> ToolResult:
        def read(path):
            text = self.read(path)
            return text if len(text) <= MAX_READ else text[:MAX_READ] + f"\n[cut at {MAX_READ} characters]"
        return self._run(read, arguments)

    def write_file(self, arguments, cancellation=None) -> ToolResult:
        content = arguments.get("content")
        if not isinstance(content, str):
            return ToolResult("", "content must be text")
        return self._run(lambda p: (self.fs.write_text(self.absolute(p), content), f"Replaced {p}")[1], arguments)

    def create_file(self, arguments, cancellation=None) -> ToolResult:
        content = arguments.get("content")
        if not isinstance(content, str):
            return ToolResult("", "content must be text")
        return self._run(lambda p: (self.fs.create_text(self.absolute(p), content), f"Created {p}")[1], arguments)


def open_project(folder: str, creator: str = "default") -> FileTools | None:
    """File tools for <folder>/.sensai/settings.json, or None when file access is off. Raises PolicyDenied."""
    from sensai.security.filesystem import load_settings
    policy = load_settings(folder, creator)
    return None if policy is None else FileTools(LocalFileSystem(policy), folder)
