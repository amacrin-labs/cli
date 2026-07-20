"""Amacrin CLI chrome — the osa SDK's renderer package, re-exported.

osa-py ≥ 0.6.0 ships `osa.cli.ui` (UI facade, rich + plain renderers,
TTY detection, chrome → stderr). Amacrin uses it directly so both CLIs
render identically and a shared `UI` instance can be threaded into
`osa.cli.deploy.deploy(ui=...)`. Commands must never import rich directly.

Convention: never run interactive prompts (``typer.confirm``/``prompt``)
while a phase or task is open — prompt first, then start phases.
"""

from __future__ import annotations

from osa.cli.ui import UI, Phase, Task, TaskState

__all__ = ["UI", "Phase", "Task", "TaskState"]
