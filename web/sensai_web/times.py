"""When each turn started and finished.

Session storage keeps messages without timestamps, so the web layer records its
own in an extra table of the same database. Turns made in the terminal have no
entry, and the page then simply shows no time for them.
"""
import sqlite3

SCHEMA = ("CREATE TABLE IF NOT EXISTS web_turn_times ("
          "creator_id TEXT NOT NULL, session_id TEXT NOT NULL, turn INTEGER NOT NULL, "
          "started_at TEXT NOT NULL, finished_at TEXT NOT NULL, "
          "PRIMARY KEY (creator_id, session_id, turn))")


class TurnTimes:
    """Per-call connections: each request thread opens its own, as with the session store."""

    def __init__(self, path: str, creator: str):
        self._path = path
        self._creator = creator

    def record(self, session_id: str, turn: int, started: str, finished: str) -> None:
        """Remember one finished turn; a failure only costs a timestamp, so it is ignored."""
        try:
            connection = sqlite3.connect(self._path, timeout=5)
            try:
                with connection:
                    connection.execute(SCHEMA)
                    connection.execute("INSERT OR REPLACE INTO web_turn_times VALUES (?, ?, ?, ?, ?)",
                                       (self._creator, session_id, turn, started, finished))
            finally:
                connection.close()
        except sqlite3.Error:
            pass

    def load(self, session_id: str) -> dict[int, tuple[str, str]]:
        """{turn number: (started, finished)} of a session; empty if nothing was recorded."""
        try:
            connection = sqlite3.connect(self._path, timeout=5)
            try:
                rows = connection.execute(
                    "SELECT turn, started_at, finished_at FROM web_turn_times "
                    "WHERE creator_id = ? AND session_id = ?", (self._creator, session_id)).fetchall()
            finally:
                connection.close()
        except sqlite3.Error:
            return {}
        return {turn: (started, finished) for turn, started, finished in rows}
