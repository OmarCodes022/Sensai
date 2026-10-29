"""One browser tab at a time may drive the session (HTTP 409 for the others)."""
from collections.abc import Callable
from threading import Lock
from time import monotonic

from sensai_web.errors import ApiError

IDLE_SECONDS = 90.0  # The page polls /api/health every 30 s, so a live owner never expires.


class TabLock:
    """The first tab to call owns the session until it goes quiet or another takes over.

    Requests without a tab id (curl, scripts) are never locked.
    """

    def __init__(self, idle_seconds: float = IDLE_SECONDS, clock: Callable[[], float] = monotonic):
        self._idle = idle_seconds
        self._clock = clock
        self._lock = Lock()
        self._owner: str | None = None
        self._seen = 0.0

    def check(self, tab: str | None) -> None:
        if tab is None:
            return
        with self._lock:
            now = self._clock()
            if self._owner in (None, tab) or now - self._seen > self._idle:
                self._owner = tab
                self._seen = now
                return
        raise ApiError(409, "tab_locked", "Sensai is open in another tab.")

    def takeover(self, tab: str | None) -> None:
        with self._lock:
            self._owner = tab
            self._seen = self._clock()
