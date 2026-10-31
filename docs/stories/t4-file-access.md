## Story 1

As a skincare creator, I want one settings file to say which folders Sensai may read and save to, so that I can work with my notes and drafts without exposing the rest of my computer

- With `.sensai/settings.json` present, file access turns on and Sensai says so at startup (and on the Tools page)
- Allowed files can be read into the chat with `/read`, or by the model on its own with `read_file`; allowed folders can be saved to with `/save` or `create_file`
- A read-only folder can't be written to

## Story 2

As a creator, I want everything not explicitly allowed refused, even when the model asks or the path is a trick, so that a mistake or a prompt injection can't read or change private files

- Deny rules win over allow rules
- `..` paths, absolute paths outside the rules, sibling folders and symlinks are refused with "Permission denied"
- A refused operation changes nothing, never shows file contents, and the chat continues
