"""Arbitrary command execution.

Disabled by default in config.yaml, and confirm-gated when enabled. Turn this on
only once you trust the whole loop — a misheard sentence becomes a real command.
"""

from __future__ import annotations

import subprocess

from .registry import tool


@tool(
    group="shell",
    description=(
        "Run a shell command on the PC and return its output. Only use when the user "
        "clearly asks to run a specific command."
    ),
    parameters={
        "command": {"type": "string", "description": "The command line to execute."},
        "timeout": {"type": "integer", "description": "Seconds to wait (default 20)."},
    },
    required=["command"],
    confirm=True,
)
def shell_run(command: str, timeout: int = 20) -> str:
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return f"The command timed out after {timeout} seconds."

    output = (result.stdout or "").strip() or (result.stderr or "").strip()
    if len(output) > 2000:
        output = output[:2000] + " ... (truncated)"
    return output or f"Command finished with exit code {result.returncode}."
