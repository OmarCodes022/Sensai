"""Importable run_python handlers with small limits, for spawned-worker tests only."""

from sensai import sandbox

FAST = sandbox.SandboxLimits(wall_seconds=1.5, cpu_seconds=1)


def fast_python_tool(arguments, cancellation=None, *, data_dir=None):
    """sandbox.python_tool with FAST limits; meant to run inside a ControlledTool worker."""
    return sandbox.python_tool(arguments, cancellation, data_dir=data_dir, limits=FAST)
