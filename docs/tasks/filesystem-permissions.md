# Task brief: creator-scoped filesystem permissions (not implemented)

This is a work brief for the File Access within Permissions feature (T4 in the
subject catalogue). **None of it is implemented yet**: only the typed
`FileSystemPort` contract exists. The files listed under "Create" do not exist.

Goal: check a creator's allowlist before reading, writing or creating a file.

## Files

Use the types in `src/sensai/core/ports.py` without changing their signatures:

- `FileAccessRule`: allowed path, actions and `recursive` flag.
- `PermissionRequest` / `PermissionDecision`: permission input and result.
- `PermissionPort`: policy interface.
- `FileSystemPort`: file access interface.
- `PolicyDenied` / `PortError`: errors.

Create:

- `src/sensai/security/__init__.py`: empty.
- `src/sensai/security/filesystem.py`: the two classes below.
- `tests/unit/security/test_filesystem.py`: tests using `tmp_path`.

## 1. Implement `CreatorPathPolicy(creator_id, rules)`

- Implement `PermissionPort.check(request) -> PermissionDecision`.
- Bind one read-only `creator_id`. Validate and copy its rules at construction; reject invalid configuration with `PolicyDenied`.
- Application code selects the creator and rules, not model arguments. The creator ID is not authentication.
- Return a denied decision for unknown actions or paths without a matching grant. An empty allowlist permits nothing.
- Treat `read`, `write` and `create` as separate permissions.
- Require absolute paths. Reject empty paths, NUL, `..` components and globs.
- Match exact paths unless `recursive=True`. Recursive rules require an existing directory and match descendants by path components: `/work/alice-other` is not inside `/work/alice`.

## 2. Implement `LocalFileSystem(policy)`

Implement `FileSystemPort` and expose the policy's read-only creator ID:

- `read_text(path)`: read an existing UTF-8 regular file.
- `write_text(path, content)`: replace an existing file's text; do not create a missing file.
- `create_text(path, content)`: exclusively create a new file in an existing parent; do not overwrite or create directories.

For every call:

1. Check `PermissionRequest(action, path)` before content access. Raise `PolicyDenied` when denied.
2. Reject symlinks at every path component, including rule roots, ancestors and the target. Parents must be directories; content targets must be regular files.
3. Use directory descriptors and no-follow opens, with checks bound to the descriptors used for I/O. Use exclusive creation for new files. Do not rely on `resolve()` followed by an unrestricted `open()`.
4. Raise `PortError` for other I/O/encoding errors or unsupported platforms. Do not use an unsafe fallback or include file contents in errors/logs.

Denied writes must preserve the original bytes; denied creates must leave no file.
An I/O failure during an authorized write does not promise rollback.

Do not add delete, listing, mkdir or binary operations. Leave CLI, SQLite,
prompt/persona loaders and model code unchanged. Build and test this component
directly; no tool dispatcher is required.

## 3. Test

Use temporary files, not real home directories, databases or external services.

- Allowed read/write/create, with a permission request on every call.
- Denied actions, empty rules, invalid configuration and separate creator policies.
- Read-only creator binding and defensive copying of rules.
- Exact/recursive matching, sibling-prefix rejection and invalid/outside paths.
- Symlinked roots, ancestors and files, including links pointing inside an allowed directory.
- Path replacement between checking and use.
- Denied writes leave bytes unchanged; denied creates leave no file.
- Create-existing does not overwrite; write-missing does not create; missing parents do not trigger mkdir.
- UTF-8, non-regular files, sanitized errors and unsupported platforms.

Run after adding the implementation and tests:

```sh
.venv/bin/python -m pytest -q tests/unit/security/test_filesystem.py
```

Existing contract examples are in `tests/unit/core/test_filesystem_ports.py`;
they do not test real filesystem security.

Full acceptance and later caller integration: [task page in Notion](https://app.notion.com/3e6d99fffe9e81bca8d3c893afda9077).
This adapter controls its own calls, not existing direct file access or arbitrary
host code; it is not an OS sandbox or hardlink/mount confinement.
