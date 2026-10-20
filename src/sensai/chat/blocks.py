"""Final JSON block in a streamed reply — NOT IMPLEMENTED: contract only.

Implemented by T18 (tool calls) and reusable by other block-based features.
A reply may end with one JSON object on its own lines, starting on a line
whose first character is ``{``. Only a block at the very end of the reply
counts (trailing whitespace allowed). A block that is not a valid JSON
object is treated as normal text and shown.
"""


class BlockReader:
    """Incremental reader for one streamed reply."""

    def feed(self, chunk: str) -> str:
        """Add a chunk; return the text that is safe to print now.

        From the start of a line beginning with ``{``, text is held back
        until it is known whether that line starts the final block. Held text
        that turns out to be normal text (more text follows the object) is
        returned by a later feed() call; text still held at the end is only
        part of finish()'s visible text.
        """
        raise NotImplementedError("T18: BlockReader.feed is not implemented")

    def finish(self) -> tuple[str, dict | None]:
        """End the reply: return (full visible text, parsed block or None).

        The visible text is the whole reply without the final block, not just
        the remainder. The caller prints only the part not yet returned by
        feed(), i.e. ``visible[len(already_printed):]``. The block is None
        when absent or invalid; invalid block text stays in the visible text.
        """
        raise NotImplementedError("T18: BlockReader.finish is not implemented")


def split_block(reply: str) -> tuple[str, dict | None]:
    """Non-streaming version: same result as feeding ``reply`` then finish()."""
    raise NotImplementedError("T18: split_block is not implemented")
