"""`amacrin ingest` — start ingestion runs on the linked archive."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Optional

import typer

from amacrin.config import AmacrinError

ingest_app = typer.Typer(help="Manage ingestion runs.")


@ingest_app.command("start")
def ingest_start(
    ctx: typer.Context,
    convention: Annotated[
        str,
        typer.Option(
            "--convention", help="Convention slug (shown by `amacrin deploy`)."
        ),
    ],
    batch_size: Annotated[int, typer.Option(help="Records per batch.")] = 1000,
    limit: Annotated[Optional[int], typer.Option(help="Max total records.")] = None,
) -> None:
    """Start an ingestion run for a convention, identified by its slug."""
    from amacrin.cli.main import _json_output, _ui
    from amacrin.ingest import start_ingest

    ui = _ui(ctx)
    try:
        result = start_ingest(
            convention=convention,
            project_dir=Path.cwd(),
            batch_size=batch_size,
            limit=limit,
        )
    except AmacrinError as e:
        ui.error(str(e), cause=e.cause, hint=e.hint)
        raise typer.Exit(1) from None

    if _json_output(ctx):
        print(json.dumps(result, indent=2, default=str))
        return
    ui.success(f"Ingestion started for {convention}")
