# File access

Sensai can read and save files **only where you allow it**, with a settings file in your
project folder, like Claude Code's `.claude/settings.json`. Without the file, file access is
off and every file operation is refused.

```json
// ~/serein/.sensai/settings.json
{
  "permissions": {
    "allow": ["Read(./data/notes/**)", "Read(./data/brand.json)", "Write(./outputs/drafts/**)", "Create(./outputs/drafts/**)"],
    "deny":  ["Read(./data/notes/private/**)"]
  }
}
```

Start Sensai in that folder (`cd ~/serein && sensai qwen2.5`, or `sensai-web qwen2.5`):

```text
File access on: 4 allow rules, 1 deny rule (.sensai/settings.json)
> /read data/notes/launch.md
Read 1,240 characters from data/notes/launch.md (sent with your next message)
> /save outputs/drafts/launch-caption.md
Created outputs/drafts/launch-caption.md
> /read data/notes/private/costs.md
Permission denied: read is denied for this path (data/notes/private/costs.md)
```

## In the web page

**Notes and file access** (under Inputs in the sidebar) does both without a text editor:

- **Notes**: add, open, edit and delete the notes in `data/notes/` (`.md` or `.txt`, up to three
  folders deep, for example `private/costs.md`).
- **File access rules**: one rule per line for Allow and Deny. **Review changes** checks them
  (a missing folder or `..` is refused) and shows the rules now and after; nothing is saved until
  **Apply the new rules**, and the new rules work at once. The model has no tool to change them.

## Rules

- `Read(path)`, `Write(path)` and `Create(path)` are separate: reading a folder does not allow
  saving into it. `Write` replaces an existing file; `Create` makes a new one and never
  overwrites.
- Paths start with `./` (the project folder). `./folder/**` is the folder and everything in
  it; anything else is one exact file.
- **Deny wins over allow**, and anything not allowed is refused.
- Always refused: `..`, paths outside the rules, similar-named siblings (`drafts-old` is not
  in `drafts`) and symlinks anywhere in the path. There is no delete, listing or folder creation.
- A broken settings file (unknown action, `..`, a missing folder) stops Sensai at startup.
  The web page refuses such rules before saving them.

## Who uses it

- **You**: `/read <path>` sends the file with your next message (in the web chat it fills the
  message box); `/save <path>` writes Sensai's last reply.
- **The model**, on its own: `read_file`, `write_file` and `create_file`, through the same
  check. A refusal comes back to it as an error it can read; nothing changes.

The Tools page of the web interface says whether file access is on and how many rules it has.

## Limits

Start Sensai from a folder that is not under a symlink (on macOS, `/tmp` is one): the adapter
refuses links everywhere in a path, including above the project folder.
