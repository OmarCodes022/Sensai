"""Importable run_python handlers and a permission port, for spawned-worker tests."""

import os

from sensai import sandbox
from sensai.core.ports import PermissionDecision

FAST = sandbox.SandboxLimits(wall_seconds=1.5, cpu_seconds=1)


def fast_python_tool(arguments, cancellation=None, *, data_dir=None):
    """sandbox.python_tool with FAST limits; meant to run inside a ControlledTool worker."""
    return sandbox.python_tool(arguments, cancellation, data_dir=data_dir, limits=FAST)


class RefuseNames:
    """Pickleable permission port refusing reads of the given file names."""

    def __init__(self, *names):
        self.names = names

    def check(self, request):
        allowed = request.action == "read" and os.path.basename(request.resource) not in self.names
        return PermissionDecision(allowed)
