"""Pickleable permission ports for run_python tests that cross into a tool worker."""

from sensai.core.ports import PermissionDecision


class Interrupting:
    """Raises KeyboardInterrupt on the first check (a Ctrl+C during the policy lookup)."""

    def check(self, request):
        raise KeyboardInterrupt


class AllowAll:
    def check(self, request):
        return PermissionDecision(True)
