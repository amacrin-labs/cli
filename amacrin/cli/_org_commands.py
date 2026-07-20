"""`amacrin org` — list and create organisations."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from amacrin.client import AmacrinClient
from amacrin.config import AmacrinError

org_app = typer.Typer(help="Manage organisations.")


@org_app.command("list")
def org_list(ctx: typer.Context) -> None:
    """List the organisations you belong to."""
    from amacrin.cli.main import _json_output, _ui

    ui = _ui(ctx)
    try:
        orgs = AmacrinClient().list_organisations()
    except AmacrinError as e:
        ui.error(str(e), cause=e.cause, hint=e.hint)
        raise typer.Exit(1) from None

    if _json_output(ctx):
        print(json.dumps([o.model_dump() for o in orgs], indent=2, default=str))
        return
    if not orgs:
        ui.info("No organisations found")
        return
    rows = [[o.name, o.id, o.role or "-"] for o in orgs]
    ui.table(["NAME", "ID", "ROLE"], rows)


@org_app.command("create")
def org_create(
    ctx: typer.Context,
    name: Annotated[str, typer.Option(help="Name for the new organisation.")],
) -> None:
    """Create a new organisation."""
    from amacrin.cli.main import _json_output, _ui

    ui = _ui(ctx)
    try:
        org = AmacrinClient().create_organisation(name)
    except AmacrinError as e:
        ui.error(str(e), cause=e.cause, hint=e.hint)
        raise typer.Exit(1) from None

    if _json_output(ctx):
        print(org.model_dump_json(indent=2))
        return
    ui.success(f"Created organisation {org.name}", arrow=org.id)
