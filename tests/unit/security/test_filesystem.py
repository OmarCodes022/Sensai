"""The file access policy and adapter: allow/deny rules, path tricks, symlinks and the settings file."""
import os

import pytest

from sensai.core.ports import FileAccessRule, PermissionRequest, PolicyDenied, PortError
from sensai.security.filesystem import CreatorPathPolicy, LocalFileSystem, load_settings


@pytest.fixture
def root(tmp_path):
    base = tmp_path.resolve()
    for d in ("notes", "notes/private", "drafts", "drafts-old"):
        (base / d).mkdir()
    (base / "notes" / "launch.md").write_text("Launch on 21 November", encoding="utf-8")
    (base / "notes" / "private" / "costs.md").write_text("cost 3 €", encoding="utf-8")
    (base / "drafts-old" / "a.md").write_text("old", encoding="utf-8")
    (base / "secret.txt").write_text("secret", encoding="utf-8")
    return base


def fs_for(root, allow, deny=()):
    rule = lambda path, actions, recursive=True: FileAccessRule(str(root / path), frozenset(actions), recursive)
    return LocalFileSystem(CreatorPathPolicy("nadia", [rule(*a) for a in allow], [rule(*d) for d in deny]))


def test_allowed_read_write_create_and_deny_wins(root):
    fs = fs_for(root, [("notes", {"read"}), ("drafts", {"write", "create"})], [("notes/private", {"read"})])
    assert fs.read_text(str(root / "notes/launch.md")) == "Launch on 21 November"
    fs.create_text(str(root / "drafts/c.md"), "caption")
    fs.write_text(str(root / "drafts/c.md"), "caption v2")
    assert (root / "drafts/c.md").read_text() == "caption v2"
    with pytest.raises(PolicyDenied):
        fs.read_text(str(root / "notes/private/costs.md"))
    with pytest.raises(PolicyDenied):
        fs.write_text(str(root / "notes/launch.md"), "changed")
    assert (root / "notes/launch.md").read_text() == "Launch on 21 November"


@pytest.mark.parametrize("path", ["secret.txt", "drafts-old/a.md", "notes/../secret.txt", "notes/*.md"])
def test_tricks_and_siblings_are_refused(root, path):
    fs = fs_for(root, [("notes", {"read"}), ("drafts", {"read"})])
    with pytest.raises(PolicyDenied):
        fs.read_text(str(root) + "/" + path)


def test_symlinks_are_refused_even_inside_an_allowed_folder(root):
    os.symlink(root / "secret.txt", root / "notes" / "link.md")
    os.symlink(root / "notes" / "launch.md", root / "notes" / "inner.md")
    os.symlink(root / "notes", root / "drafts" / "alias")
    fs = fs_for(root, [("notes", {"read"}), ("drafts", {"read"})])
    for target in ("notes/link.md", "notes/inner.md", "drafts/alias/launch.md"):
        with pytest.raises(PolicyDenied):
            fs.read_text(str(root / target))


def test_create_never_overwrites_and_write_never_creates(root):
    fs = fs_for(root, [("drafts", {"write", "create"})])
    (root / "drafts" / "x.md").write_text("keep")
    with pytest.raises(PortError):
        fs.create_text(str(root / "drafts/x.md"), "over")
    with pytest.raises(PortError):
        fs.write_text(str(root / "drafts/missing.md"), "new")
    with pytest.raises(PolicyDenied):  # No folder creation either.
        fs.create_text(str(root / "drafts/new/x.md"), "new")
    assert (root / "drafts/x.md").read_text() == "keep" and not (root / "drafts/missing.md").exists()


def test_an_empty_policy_allows_nothing_and_bad_rules_are_rejected(root):
    policy = CreatorPathPolicy("nadia", [])
    assert not policy.check(PermissionRequest("read", str(root / "secret.txt"))).allowed
    assert not policy.check(PermissionRequest("delete", str(root / "secret.txt"))).allowed
    for bad in (FileAccessRule("relative", frozenset({"read"})), FileAccessRule(str(root), frozenset({"delete"})),
                FileAccessRule(str(root / "missing"), frozenset({"read"}), True)):
        with pytest.raises(PolicyDenied):
            CreatorPathPolicy("nadia", [bad])


def test_settings_file_turns_access_on_with_its_rules(root):
    (root / ".sensai").mkdir()
    (root / ".sensai" / "settings.json").write_text(
        '{"permissions": {"allow": ["Read(./notes/**)", "Write(./drafts/**)", "Create(./drafts/**)", "Read(./secret.txt)"],'
        ' "deny": ["Read(./notes/private/**)"]}}')
    policy = load_settings(str(root))
    assert policy.summary == (4, 1)
    fs = LocalFileSystem(policy)
    assert fs.read_text(str(root / "secret.txt")) == "secret"
    with pytest.raises(PolicyDenied):
        fs.read_text(str(root / "notes/private/costs.md"))


def test_no_settings_file_means_access_off_and_bad_files_are_errors(root):
    assert load_settings(str(root)) is None
    (root / ".sensai").mkdir()
    for content in ('{"permissions": {"allow": ["Delete(./x)"]}}', '{"permissions": {"allow": ["Read(../x)"]}}',
                    '{"permissions": {"allow": ["Read(./notes/../x)"]}}', "{broken"):
        (root / ".sensai" / "settings.json").write_text(content)
        with pytest.raises(PolicyDenied, match="cannot use .sensai/settings.json"):
            load_settings(str(root))


def project(root):
    (root / ".sensai").mkdir()
    (root / ".sensai" / "settings.json").write_text(
        '{"permissions": {"allow": ["Read(./notes/**)", "Create(./drafts/**)", "Write(./drafts/**)"], "deny": ["Read(./notes/private/**)"]}}')
    from sensai.security.file_tools import open_project
    return open_project(str(root))


def test_the_model_tools_read_create_and_refuse_without_leaking(root):
    tools = project(root)
    assert tools.read_file({"path": "notes/launch.md"}).output == "Launch on 21 November"
    assert tools.create_file({"path": "drafts/c.md", "content": "hi"}).output == "Created drafts/c.md"
    assert tools.write_file({"path": "drafts/c.md", "content": "v2"}).output == "Replaced drafts/c.md"
    refused = tools.read_file({"path": "secret.txt"})
    assert refused.error.startswith("Permission denied") and "secret" not in refused.error.replace("secret.txt", "")
    assert tools.create_file({"path": "notes/x.md", "content": "no"}).error.startswith("Permission denied")
    assert not (root / "notes" / "x.md").exists()


def test_save_creates_then_replaces(root):
    tools = project(root)
    assert tools.save("drafts/new.md", "one") == "Created"
    assert tools.save("drafts/new.md", "two") == "Replaced"
    assert (root / "drafts" / "new.md").read_text() == "two"
    with pytest.raises(PolicyDenied):
        tools.save("notes/x.md", "no")
