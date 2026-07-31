"""`amacrin init` — scaffold a new archive project.

Writes ``osa.yaml`` (server config), ``amacrin.yaml`` (deploy manifest, which
owns the slug), and ``.env.example`` (secret placeholders) into the current
directory. Interactive by default; fully driven by ``--name``/``--slug`` for
non-interactive/CI use.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Optional

import typer

from amacrin.config import AmacrinError
from amacrin.scaffold import write_project_files
from amacrin.slug import slugify, validate_archive_slug


def init(
    ctx: typer.Context,
    name: Annotated[
        Optional[str],
        typer.Option(help="Archive display name (defaults to this directory)."),
    ] = None,
    slug: Annotated[
        Optional[str],
        typer.Option(
            help="Subdomain slug — <slug>.amacr.in (defaults to a slug of the name)."
        ),
    ] = None,
    org: Annotated[
        Optional[str], typer.Option(help="Organisation ID to own the archive.")
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Overwrite existing files.")
    ] = False,
) -> None:
    """Scaffold osa.yaml (server config) and amacrin.yaml (deploy manifest) here."""
    from amacrin.cli.main import _ui

    ui = _ui(ctx)
    project_dir = Path.cwd()
    interactive = sys.stdin.isatty()
    try:
        resolved_name = _resolve_name(name, project_dir, interactive=interactive)
        resolved_slug = _resolve_slug(slug, resolved_name, interactive=interactive)
        results = write_project_files(
            project_dir, name=resolved_name, slug=resolved_slug, org=org, force=force
        )
    except AmacrinError as e:
        ui.error(str(e), cause=e.cause, hint=e.hint)
        raise typer.Exit(1) from None

    for result in results:
        if result.written:
            ui.success(f"Wrote {result.path.name}")
        else:
            ui.info(f"Skipped {result.path.name} (exists — pass --force to overwrite)")
    ui.info("Next: fill in auth in osa.yaml, then run `amacrin archive create`")


def _resolve_name(name: str | None, project_dir: Path, *, interactive: bool) -> str:
    if name:
        return name
    if interactive:
        return typer.prompt("Archive name", default=project_dir.name, err=True)
    return project_dir.name


def _resolve_slug(slug: str | None, name: str, *, interactive: bool) -> str:
    candidate = slug or slugify(name)
    if slug is None and interactive:
        candidate = typer.prompt(
            "Subdomain slug (<slug>.amacr.in)", default=candidate or None, err=True
        )
    return validate_archive_slug(candidate)
