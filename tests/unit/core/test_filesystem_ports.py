"""No-disk contract examples; not evidence of real filesystem confinement."""

from dataclasses import FrozenInstanceError
from typing import get_args

import pytest

from sensai.core.ports import (
    FileAccessRule,
    FileAction,
    FileSystemPort,
    PermissionDecision,
    PermissionPort,
    PermissionRequest,
    PolicyDenied,
    PortError,
)


class FakePermission:
    """Exact, scripted grants only; deliberately not a real path policy."""

    def __init__(self, grants: frozenset[PermissionRequest]):
        self.grants = grants
        self.requests: list[PermissionRequest] = []

    def check(self, request: PermissionRequest) -> PermissionDecision:
        self.requests.append(request)
        return PermissionDecision(request in self.grants)


class FakeFileSystem:
    """Dictionary-backed example: no path validation, symlinks or OS access."""

    def __init__(self, creator_id: str, permission: PermissionPort,
                 files: dict[str, str]):
        self._creator_id = creator_id
        self.permission = permission
        self.files = dict(files)

    @property
    def creator_id(self) -> str:
        return self._creator_id

    def _authorize(self, action: FileAction, path: str) -> None:
        if not self.permission.check(PermissionRequest(action, path)).allowed:
            raise PolicyDenied("file access denied")

    def read_text(self, path: str) -> str:
        self._authorize("read", path)
        if path not in self.files:
            raise PortError("file missing")
        return self.files[path]

    def write_text(self, path: str, content: str) -> None:
        self._authorize("write", path)
        if path not in self.files:
            raise PortError("file missing")
        self.files[path] = content

    def create_text(self, path: str, content: str) -> None:
        self._authorize("create", path)
        if path in self.files:
            raise PortError("file exists")
        self.files[path] = content


def assert_text_file_contract(filesystem: FileSystemPort, existing: str,
                              new: str) -> None:
    """Reusable text semantics; caller supplies isolated, authorized paths."""
    assert filesystem.read_text(existing) == "before"
    assert filesystem.write_text(existing, "après") is None
    assert filesystem.read_text(existing) == "après"
    assert filesystem.create_text(new, "新") is None
    assert filesystem.read_text(new) == "新"
    with pytest.raises(PortError):
        filesystem.create_text(new, "replacement")
    assert filesystem.read_text(new) == "新"


def test_file_actions_and_rule_are_frozen_values():
    assert get_args(FileAction) == ("read", "write", "create")
    rule = FileAccessRule("/workspace/note.txt", frozenset({"read"}))
    assert rule.recursive is False
    assert rule == FileAccessRule("/workspace/note.txt", frozenset({"read"}))
    with pytest.raises(FrozenInstanceError):
        rule.path = "/elsewhere"
    assert not hasattr(rule.actions, "add")


def test_rule_is_typed_input_not_runtime_validation():
    # The future policy constructor, not the value dataclass, must reject this.
    rule = FileAccessRule("relative", frozenset({"unknown"}))
    assert rule.path == "relative"
    assert rule.actions == frozenset({"unknown"})


def test_fake_has_protocol_shape_and_read_only_creator():
    permission = FakePermission(frozenset())
    filesystem = FakeFileSystem("alice", permission, {})
    assert isinstance(permission, PermissionPort)
    assert isinstance(filesystem, FileSystemPort)
    assert filesystem.creator_id == "alice"
    with pytest.raises(AttributeError):
        filesystem.creator_id = "bob"
    # isinstance is structural, not a security or signature conformance test.


def test_reusable_text_semantics_and_per_operation_requests():
    existing, new = "/workspace/existing", "/workspace/new"
    permission = FakePermission(frozenset(
        PermissionRequest(action, path)
        for action, path in (("read", existing), ("write", existing),
                             ("create", new), ("read", new))
    ))
    filesystem = FakeFileSystem("alice", permission, {existing: "before"})
    assert_text_file_contract(filesystem, existing, new)
    assert permission.requests == [
        PermissionRequest("read", existing),
        PermissionRequest("write", existing),
        PermissionRequest("read", existing),
        PermissionRequest("create", new),
        PermissionRequest("read", new),
        PermissionRequest("create", new),
        PermissionRequest("read", new),
    ]


def test_denied_operations_do_not_mutate_fake_state():
    permission = FakePermission(frozenset())
    filesystem = FakeFileSystem("alice", permission, {"/note": "private"})
    with pytest.raises(PolicyDenied):
        filesystem.read_text("/note")
    with pytest.raises(PolicyDenied):
        filesystem.write_text("/note", "replacement")
    with pytest.raises(PolicyDenied):
        filesystem.create_text("/new", "new")
    assert filesystem.files == {"/note": "private"}
    assert permission.requests == [
        PermissionRequest("read", "/note"),
        PermissionRequest("write", "/note"),
        PermissionRequest("create", "/new"),
    ]


def test_write_missing_does_not_create_even_when_authorized():
    permission = FakePermission(frozenset({PermissionRequest("write", "/missing")}))
    filesystem = FakeFileSystem("alice", permission, {})
    with pytest.raises(PortError):
        filesystem.write_text("/missing", "new")
    assert filesystem.files == {}


def test_creator_views_do_not_share_fake_state_or_grants():
    files = {"/note": "before"}
    alice = FakeFileSystem("alice", FakePermission(frozenset({
        PermissionRequest("write", "/note"),
    })), files)
    bob = FakeFileSystem("bob", FakePermission(frozenset()), files)
    alice.write_text("/note", "alice")
    with pytest.raises(PolicyDenied):
        bob.read_text("/note")
    assert bob.files == files == {"/note": "before"}
    assert alice.files == {"/note": "alice"}
