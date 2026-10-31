# File access

Sensai can read and save files **only where you allow it**, with a settings file in your
project folder, like Claude Code's `.claude/settings.json`. Without the file, file access is
off and every file operation is refused.

```json
// ~/serein/.sensai/settings.json
{
  "permissions": {
    "allow": ["Read(./notes/**)", "Read(./brand.json)", "Write(./drafts/**)", "Create(./drafts/**)"],
    "deny":  ["Read(./notes/private/**)"]
  }
}
```

Start Sensai in that folder (`cd ~/serein && sensai qwen2.5`, or `sensai-web qwen2.5`):

```text
File access on: 4 allow rules, 1 deny rule (.sensai/settings.json)
> /read notes/launch.md
Read 1,240 characters from notes/launch.md (sent with your next message)
> /save drafts/launch-caption.md
Created drafts/launch-caption.md
> /read notes/private/costs.md
Permission denied: read is denied for this path (notes/private/costs.md)
```

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

## Who uses it

- **You**: `/read <path>` sends the file with your next message (in the web chat it fills the
  message box); `/save <path>` writes Sensai's last reply.
- **The model**, on its own: `read_file`, `write_file` and `create_file`, through the same
  check. A refusal comes back to it as an error it can read; nothing changes.

The Tools page of the web interface says whether file access is on and how many rules it has.

## Limits

Start Sensai from a folder that is not under a symlink (on macOS, `/tmp` is one): the adapter
refuses links everywhere in a path, including above the project folder.
