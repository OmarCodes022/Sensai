"""Importable run_python handlers with small limits, for spawned-worker tests only."""

from sensai import sandbox

FAST = sandbox.SandboxLimits(wall_seconds=1.5, cpu_seconds=1)


def fast_python_tool(arguments, cancellation=None, *, data_dir=None):
    """sandbox.python_tool with FAST limits; meant to run inside a ControlledTool worker."""
    defaults = sandbox.run_python.__kwdefaults__
    previous = defaults["limits"]
    defaults["limits"] = FAST
    try:
        return sandbox.python_tool(arguments, cancellation, data_dir=data_dir)
    finally:
        defaults["limits"] = previous
