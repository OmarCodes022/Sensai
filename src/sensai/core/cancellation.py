"""One cancellation/deadline budget shared by all stages of an operation."""
from collections.abc import Callable
from math import isfinite
from time import monotonic

from sensai.core.errors import SensaiError


class OperationCancelled(SensaiError):
    """The caller abandoned the operation."""


class OperationTimedOut(SensaiError):
    """The complete operation exceeded its deadline."""


class CancellationToken:
    def __init__(self, deadline: float | None = None,
                 cancel_requested: Callable[[], bool] | None = None) -> None:
        if deadline is not None and not isfinite(deadline):
            raise ValueError("deadline must be finite")
        self.deadline = deadline
        self.cancelled = False
        self._cancel_requested = cancel_requested

    def cancel(self) -> None:
        self.cancelled = True

    def raise_if_cancelled(self) -> None:
        if self._cancel_requested is not None and self._cancel_requested():
            self.cancel()
        if self.cancelled:
            raise OperationCancelled("operation cancelled")
        if self.deadline is not None and monotonic() >= self.deadline:
            raise OperationTimedOut("operation timed out")
