"""`amacrin archive` — provision, inspect, and tear down cloud archives."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Any, Optional

import typer

from amacrin.client import AmacrinClient
from amacrin.config import AmacrinError
from amacrin.models import ArchiveCreated, Deployment

archive_app = typer.Typer(help="Manage Amacrin archives (the cloud resource).")


@archive_app.command("create")
def archive_create(
    ctx: typer.Context,
    config: Annotated[
        Optional[Path], typer.Option(help="Path to osa.yaml (defaults to ./osa.yaml).")
    ] = None,
    org: Annotated[
        Optional[str],
        typer.Option(help="Organisation ID to own the archive (else auto-resolved)."),
    ] = None,
) -> None:
    """Provision a new archive from osa.yaml and wait for it to come up."""
    from amacrin.cli.main import _json_output, _ui
    from amacrin.config import load_config, write_state

    ui = _ui(ctx)
    json_output = _json_output(ctx)
    cwd = Path.cwd()
    client = AmacrinClient()

    created: ArchiveCreated
    deployment: Deployment
    try:
        cfg = load_config(config, project_dir=cwd)
        payload = _build_create_payload(cfg)
        # Prompt for the org (if needed) *before* opening any task/spinner.
        org_id = _resolve_org_id(client, org=org)
        created = client.create_archive(org_id, payload)
        write_state("archive-id", created.archive.id, project_dir=cwd)
        if not json_output:
            ui.info(
                f"Archive {created.archive.slug} → https://{created.archive.domain}"
            )
        deployment = _await_deployment(client, created, ui)
        if not json_output:
            ui.success("Archive is running", arrow=deployment.url)
    except AmacrinError as e:
        ui.error(str(e), cause=e.cause, hint=e.hint)
        raise typer.Exit(1) from None

    if json_output:
        print(
            json.dumps(
                {
                    "archive": created.archive.model_dump(),
                    "deployment": deployment.model_dump(),
                },
                indent=2,
                default=str,
            )
        )


def _build_create_payload(cfg: dict[str, Any]) -> dict[str, Any]:
    """Extract exactly the fields the create endpoint accepts from osa.yaml."""
    name = cfg.get("name")
    slug = cfg.get("slug")
    if not name:
        raise AmacrinError(
            "osa.yaml is missing `name`",
            hint="Add a top-level `name:` field to osa.yaml",
        )
    if not slug:
        raise AmacrinError(
            "osa.yaml is missing `slug`",
            hint="Add a top-level `slug:` field to osa.yaml",
        )
    return {"name": name, "slug": slug, "auth": cfg.get("auth")}


def _resolve_org_id(client: AmacrinClient, *, org: str | None) -> str:
    """--org flag → single org → tty picker → personal (non-tty fallback)."""
    if org:
        return org
    me = client.me()
    orgs = me.organisations
    if not orgs:
        raise AmacrinError(
            "You do not belong to any organisation",
            hint="Run `amacrin org create --name <name>` first",
        )
    if len(orgs) == 1:
        return orgs[0].id

    default = me.personal_organisation()
    if not sys.stdin.isatty():
        return default.id if default else orgs[0].id

    default_idx = next(
        (i for i, o in enumerate(orgs, 1) if default and o.id == default.id), 1
    )
    typer.echo("Select an organisation:", err=True)
    for i, o in enumerate(orgs, 1):
        typer.echo(f"  {i}. {o.name} ({o.role})", err=True)
    choice = typer.prompt("Organisation", default=default_idx, type=int, err=True)
    if choice < 1 or choice > len(orgs):
        raise AmacrinError("Invalid selection")
    return orgs[choice - 1].id


def _await_deployment(
    client: AmacrinClient, created: ArchiveCreated, ui: Any
) -> Deployment:
    """Poll the deployment with a live task row; re-raise on failure."""
    with ui.task("Deploying archive") as task:
        try:
            deployment = client.wait_for_deployment(
                created.archive.id, on_status=lambda d: task.detail(d.status)
            )
        except AmacrinError as e:
            task.fail(str(e))
            raise
        task.done(detail=deployment.url or created.archive.domain)
    return deployment


@archive_app.command("list")
def archive_list(ctx: typer.Context) -> None:
    """List the archives you can see."""
    from amacrin.cli.main import _json_output, _ui

    ui = _ui(ctx)
    try:
        archives = AmacrinClient().list_archives()
    except AmacrinError as e:
        ui.error(str(e), cause=e.cause, hint=e.hint)
        raise typer.Exit(1) from None

    if _json_output(ctx):
        print(json.dumps([a.model_dump() for a in archives], indent=2, default=str))
        return
    if not archives:
        ui.info("No archives yet — run `amacrin archive create`")
        return
    rows = [[a.slug, a.name, a.status, a.domain, a.id] for a in archives]
    ui.table(["SLUG", "NAME", "STATUS", "DOMAIN", "ID"], rows)


@archive_app.command("status")
def archive_status(ctx: typer.Context) -> None:
    """Show the latest deployment status for the linked archive."""
    from amacrin.cli.main import _json_output, _ui
    from amacrin.config import require_archive_id

    ui = _ui(ctx)
    cwd = Path.cwd()
    try:
        archive_id = require_archive_id(project_dir=cwd)
        deployment = AmacrinClient().archive_status(archive_id)
    except AmacrinError as e:
        ui.error(str(e), cause=e.cause, hint=e.hint)
        raise typer.Exit(1) from None

    if _json_output(ctx):
        print(deployment.model_dump_json(indent=2))
        return
    ui.table(
        ["FIELD", "VALUE"],
        [
            ["status", deployment.status],
            ["url", deployment.url or "-"],
            ["started", deployment.started_at],
            ["completed", deployment.completed_at or "-"],
        ],
    )


@archive_app.command("destroy")
def archive_destroy(
    ctx: typer.Context,
    force: Annotated[
        bool, typer.Option("--force", help="Skip the confirmation prompt.")
    ] = False,
) -> None:
    """Destroy the linked archive."""
    from amacrin.cli.main import _ui
    from amacrin.config import delete_state, require_archive_id

    ui = _ui(ctx)
    cwd = Path.cwd()
    try:
        archive_id = require_archive_id(project_dir=cwd)
    except AmacrinError as e:
        ui.error(str(e), cause=e.cause, hint=e.hint)
        raise typer.Exit(1) from None

    if not force:
        typer.confirm(f"Destroy archive {archive_id}?", abort=True)

    try:
        AmacrinClient().destroy_archive(archive_id, force=force)
        delete_state("archive-id", project_dir=cwd)
    except AmacrinError as e:
        ui.error(str(e), cause=e.cause, hint=e.hint)
        raise typer.Exit(1) from None
    ui.success("Archive destroy requested")
