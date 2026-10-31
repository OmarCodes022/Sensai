"""File access within permissions (T4): a creator's allow and deny rules, and a file adapter that checks them.

Every operation is checked before any content is touched; deny wins over allow, anything not
allowed is refused. Paths are walked one component at a time with no-follow opens, so a symlink
anywhere (and a swap after the check) fails instead of escaping the allowed folders.
"""
import errno
import json
import os
import re
import stat
from collections.abc import Iterable
from pathlib import PurePosixPath

from sensai.core.ports import FileAccessRule, PermissionDecision, PermissionRequest, PolicyDenied, PortError

ACTIONS = frozenset({"read", "write", "create"})
GLOB = re.compile(r"[*?\[\]]")
SETTINGS = os.path.join(".sensai", "settings.json")
RULE = re.compile(r"(Read|Write|Create)\((\./[^()]*)\)\Z")


def _valid_path(path: object) -> str:
    if not isinstance(path, str) or not path or "\0" in path or not os.path.isabs(path) or GLOB.search(path):
        raise PolicyDenied("path must be an absolute path without globs")
    parts = PurePosixPath(path).parts
    if any(part in ("..", ".") for part in parts) or path != str(PurePosixPath(path)):
        raise PolicyDenied("path must not contain . or .. components")
    return path


def _rules(rules: Iterable[FileAccessRule]) -> tuple[FileAccessRule, ...]:
    out = []
    for rule in rules:
        if not isinstance(rule, FileAccessRule) or not rule.actions or not set(rule.actions) <= ACTIONS:
            raise PolicyDenied("invalid file access rule")
        _valid_path(rule.path)
        if rule.recursive and not os.path.isdir(rule.path):
            raise PolicyDenied("a folder rule needs an existing folder")
        out.append(FileAccessRule(rule.path, frozenset(rule.actions), bool(rule.recursive)))
    return tuple(out)


def _covers(rule: FileAccessRule, path: str, action: str) -> bool:
    if action not in rule.actions:
        return False
    if not rule.recursive:
        return path == rule.path
    root, target = PurePosixPath(rule.path).parts, PurePosixPath(path).parts
    return len(target) > len(root) and target[:len(root)] == root  # Component match: drafts-old is not in drafts.


class CreatorPathPolicy:
    """PermissionPort for one creator: allow rules and deny rules; deny wins."""

    def __init__(self, creator_id: str, rules: Iterable[FileAccessRule], deny: Iterable[FileAccessRule] = ()):
        if not isinstance(creator_id, str) or not creator_id.strip():
            raise PolicyDenied("creator id required")
        self._creator_id = creator_id
        self._allow, self._deny = _rules(rules), _rules(deny)

    @property
    def creator_id(self) -> str:
        return self._creator_id

    @property
    def summary(self) -> tuple[int, int]:
        """(allow, deny) counted per action, as written in the settings file."""
        return sum(len(r.actions) for r in self._allow), sum(len(r.actions) for r in self._deny)

    def check(self, request: PermissionRequest) -> PermissionDecision:
        if request.action not in ACTIONS:
            return PermissionDecision(False, "unknown action")
        try:
            path = _valid_path(request.resource)
        except PolicyDenied as exc:
            return PermissionDecision(False, str(exc))
        if any(_covers(rule, path, request.action) for rule in self._deny):
            return PermissionDecision(False, f"{request.action} is denied")
        if any(_covers(rule, path, request.action) for rule in self._allow):
            return PermissionDecision(True)
        return PermissionDecision(False, f"{request.action} is not allowed")


class LocalFileSystem:
    """FileSystemPort: UTF-8 regular files, permission-checked, never through a symlink."""

    def __init__(self, policy: CreatorPathPolicy):
        if not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd:
            raise PortError("file access needs a POSIX system")
        self._policy = policy

    @property
    def creator_id(self) -> str:
        return self._policy.creator_id

    @property
    def summary(self) -> tuple[int, int]:
        """(allow rules, deny rules)."""
        return self._policy.summary

    def _check(self, action: str, path: str) -> None:
        decision = self._policy.check(PermissionRequest(action, path))
        if not decision.allowed:
            raise PolicyDenied(f"{decision.reason or action + ' is not allowed'} for this path")

    def _parent(self, path: str) -> tuple[int, str]:
        """An fd of the parent folder, reached without following any link, and the file name."""
        *folders, name = PurePosixPath(path).parts[1:]
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        try:
            for folder in folders:
                nxt = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = nxt
        except OSError:
            os.close(fd)
            raise PolicyDenied("the path goes through a link or a missing folder") from None
        return fd, name

    def _open(self, path: str, flags: int) -> int:
        parent, name = self._parent(path)
        try:
            fd = os.open(name, flags | os.O_NOFOLLOW, 0o644, dir_fd=parent)
        except FileExistsError:
            raise PortError("the file already exists") from None
        except FileNotFoundError:
            raise PortError("the file does not exist") from None
        except OSError as exc:
            if exc.errno == errno.ELOOP:  # O_NOFOLLOW refused a link.
                raise PolicyDenied("the file is a link") from None
            raise PortError("the file cannot be opened") from None
        finally:
            os.close(parent)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            raise PortError("not a regular file")
        return fd

    def read_text(self, path: str) -> str:
        self._check("read", path)
        fd = self._open(path, os.O_RDONLY)
        try:
            with os.fdopen(fd, "rb") as f:
                return f.read().decode("utf-8")
        except UnicodeDecodeError:
            raise PortError("the file is not UTF-8 text") from None

    def write_text(self, path: str, content: str) -> None:
        self._check("write", path)
        fd = self._open(path, os.O_WRONLY)
        with os.fdopen(fd, "wb") as f:
            f.truncate(0)
            f.write(content.encode("utf-8"))

    def create_text(self, path: str, content: str) -> None:
        self._check("create", path)
        fd = self._open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        with os.fdopen(fd, "wb") as f:
            f.write(content.encode("utf-8"))


def load_settings(folder: str, creator_id: str = "default") -> CreatorPathPolicy | None:
    """The policy from <folder>/.sensai/settings.json, or None when there is no such file (access off)."""
    path = os.path.join(folder, SETTINGS)
    if not os.path.isfile(path):
        return None
    root = os.path.abspath(folder)
    try:
        with open(path, encoding="utf-8") as f:
            permissions = json.load(f).get("permissions", {})
        grouped: dict[str, dict[tuple[str, bool], set[str]]] = {"allow": {}, "deny": {}}
        for kind in grouped:
            entries = permissions.get(kind, [])
            if not isinstance(entries, list):
                raise ValueError(f"permissions.{kind} must be a list")
            for entry in entries:
                match = RULE.match(entry) if isinstance(entry, str) else None
                if match is None:
                    raise ValueError(f"{entry!r}: use Read(./path), Write(./path) or Create(./path)")
                relative = match.group(2)[2:]
                recursive = relative == "**" or relative.endswith("/**")
                relative = relative.removesuffix("**").rstrip("/")
                if ".." in PurePosixPath(relative).parts or GLOB.search(relative) or (not relative and not recursive):
                    raise ValueError(f"{entry!r}: the path must stay inside the project folder")
                target = os.path.join(root, relative) if relative else root
                grouped[kind].setdefault((target, recursive), set()).add(match.group(1).lower())
        rules = {kind: [FileAccessRule(p, frozenset(a), r) for (p, r), a in items.items()] for kind, items in grouped.items()}
        return CreatorPathPolicy(creator_id, rules["allow"], rules["deny"])
    except (OSError, ValueError, AttributeError, PolicyDenied) as exc:
        raise PolicyDenied(f"cannot use {SETTINGS}: {exc}") from None
