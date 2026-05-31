"""Amacrin CLI — Typer app for the `amacrin` command."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer

from amacrin.config import AmacrinError

app = typer.Typer(help="Amacrin — deploy and manage OSA archives in the cloud.")
archive_app = typer.Typer(help="Manage Amacrin archives (the cloud resource).")
ingest_app = typer.Typer(help="Manage ingestion runs.")
app.add_typer(archive_app, name="archive")
app.add_typer(ingest_app, name="ingest")


@app.command()
def login(
    token: Annotated[str, typer.Option(help="Amacrin admin token.")],
) -> None:
    """Authenticate with the Amacrin platform."""
    from amacrin.api import login as do_login

    try:
        do_login(token, project_dir=Path.cwd())
        print("Token stored.")
    except AmacrinError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise typer.Exit(1) from None


@app.command()
def set_account(
    id: Annotated[str, typer.Option(help="Amacrin account ID.")],
) -> None:
    """Store the Amacrin account ID for this project."""
    from amacrin.api import set_account as do_set_account

    try:
        do_set_account(id, project_dir=Path.cwd())
        print(f"Account set to {id}")
    except AmacrinError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise typer.Exit(1) from None


@app.command()
def link(
    archive: Annotated[str, typer.Option(help="Existing Amacrin archive ID.")],
) -> None:
    """Link this project to an existing archive."""
    from amacrin.config import write_state

    try:
        write_state("archive-id", archive, project_dir=Path.cwd())
        print(f"Linked to archive {archive}")
    except AmacrinError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise typer.Exit(1) from None


@archive_app.command(name="create")
def archive_create(
    config: Annotated[
        Optional[Path], typer.Option(help="Path to osa.yaml config file.")
    ] = None,
) -> None:
    """Provision a new Amacrin archive."""
    from amacrin.api import create as do_create

    try:
        result = do_create(config_path=config, project_dir=Path.cwd())
        print(json.dumps(result, indent=2, default=str))
    except AmacrinError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise typer.Exit(1) from None


@archive_app.command(name="list")
def archive_list() -> None:
    """List archives for the current account."""
    from amacrin.api import list_archives as do_list

    try:
        result = do_list(project_dir=Path.cwd())
        print(json.dumps(result, indent=2))
    except AmacrinError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise typer.Exit(1) from None


@archive_app.command(name="status")
def archive_status() -> None:
    """Get deployment status for the linked archive."""
    from amacrin.api import status as do_status

    try:
        result = do_status(project_dir=Path.cwd())
        print(json.dumps(result, indent=2))
    except AmacrinError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise typer.Exit(1) from None


@archive_app.command(name="destroy")
def archive_destroy(
    force: Annotated[
        bool, typer.Option(help="Force destroy without confirmation.")
    ] = False,
) -> None:
    """Destroy the linked archive."""
    from amacrin.api import destroy as do_destroy

    try:
        do_destroy(force=force, project_dir=Path.cwd())
        print("Archive destroyed.")
    except AmacrinError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise typer.Exit(1) from None


@app.command()
def deploy(
    registry: Annotated[
        Optional[str],
        typer.Option(
            help="Container registry to push images to (e.g. ghcr.io/your-org).",
            envvar="OSA_REGISTRY",
        ),
    ] = None,
    skip_build: Annotated[
        bool,
        typer.Option(
            "--skip-build", help="Skip image build/push, reuse last-pushed images."
        ),
    ] = False,
) -> None:
    """Deploy conventions to the linked Amacrin archive.

    Requires a linked archive — run `amacrin archive create` or
    `amacrin link --archive <id>` first.
    """
    import importlib
    import importlib.metadata

    from amacrin.deploy import deploy as do_deploy

    for ep in importlib.metadata.entry_points(group="osa.conventions"):
        importlib.import_module(ep.value)

    try:
        result = do_deploy(
            project_dir=Path.cwd(),
            registry=registry,
            skip_build=skip_build,
        )
        print(json.dumps(result, indent=2, default=str))
    except AmacrinError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise typer.Exit(1) from None


@ingest_app.command(name="start")
def ingest_start(
    convention: Annotated[
        Optional[str],
        typer.Option(
            "--convention", help="Convention title. Auto-detected if omitted."
        ),
    ] = None,
    batch_size: Annotated[int, typer.Option(help="Records per batch.")] = 1000,
    limit: Annotated[Optional[int], typer.Option(help="Max total records.")] = None,
) -> None:
    """Start an ingestion run on the linked archive."""
    from amacrin.ingest import start_ingest

    try:
        name = convention or _select_convention()
        result = start_ingest(
            convention=name,
            project_dir=Path.cwd(),
            batch_size=batch_size,
            limit=limit,
        )
        print(json.dumps(result, indent=2))
    except AmacrinError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise typer.Exit(1) from None


def _select_convention() -> str:
    """Discover ingestable conventions and pick one interactively.

    Mirrors osa's `osa ingestion start` UX: 0 -> error, 1 -> confirm,
    many -> numbered prompt.
    """
    from osa.cli.ingestion import (
        IngestionError,
        discover_ingestable_conventions,
    )

    try:
        candidates = discover_ingestable_conventions()
    except IngestionError as e:
        raise AmacrinError(str(e)) from e

    if not candidates:
        raise AmacrinError("No conventions with an ingester found. Did you deploy?")

    if len(candidates) == 1:
        pick = candidates[0]
        typer.confirm(
            f"Start ingestion for {pick.title}@{pick.version} "
            f"(ingester: {pick.ingester_name})?",
            abort=True,
        )
        return pick.title

    print("Multiple ingestable conventions found:\n")
    for i, c in enumerate(candidates, 1):
        print(f"  {i}. {c.title}@{c.version} (ingester: {c.ingester_name})")
    print()
    choice = typer.prompt("Select a convention", type=int)
    if choice < 1 or choice > len(candidates):
        raise AmacrinError("Invalid selection.")
    return candidates[choice - 1].title
