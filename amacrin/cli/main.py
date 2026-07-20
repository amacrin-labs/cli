"""Amacrin CLI — Typer app for the `amacrin` command.

Command bodies are thin: parse args, call a service/client method, render the
result through :class:`UI` (chrome → stderr) with machine data on stdout under
``--json``. Every body wraps its work in an ``AmacrinError`` boundary so the
user never sees a traceback.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Optional

import typer
from pydantic import BaseModel, ConfigDict

from amacrin.auth import login_with_token, run_login_flow
from amacrin.cli._archive_commands import archive_app
from amacrin.cli._ingest_commands import ingest_app
from amacrin.cli._org_commands import org_app
from amacrin.cli.ui import UI
from amacrin.client import AmacrinClient, resolve_api_base
from amacrin.config import AmacrinError
from amacrin.credentials import remove_credentials

app = typer.Typer(help="Amacrin — deploy and manage OSA archives in the cloud.")
app.add_typer(org_app, name="org")
app.add_typer(archive_app, name="archive")
app.add_typer(ingest_app, name="ingest")


class CLIState(BaseModel):
    """Per-invocation state stashed on ``ctx.obj`` by the root callback."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    ui: UI
    json_output: bool = False
    verbose: bool = False


def _ui(ctx: typer.Context) -> UI:
    state = ctx.obj
    return state.ui if isinstance(state, CLIState) else UI.create()


def _json_output(ctx: typer.Context) -> bool:
    state = ctx.obj
    return state.json_output if isinstance(state, CLIState) else False


def _version_callback(value: bool) -> None:
    if value:
        from importlib.metadata import version

        print(f"amacrin {version('amacrin')}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Show version and exit.",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Stream extra detail and full output."),
    ] = False,
    json_: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON on stdout."),
    ] = False,
) -> None:
    """Amacrin — deploy and manage OSA archives in the cloud."""
    ctx.obj = CLIState(
        ui=UI.create(verbose=verbose), json_output=json_, verbose=verbose
    )


@app.command()
def login(
    ctx: typer.Context,
    token: Annotated[
        Optional[str],
        typer.Option(help="Static admin token (break-glass; skips the browser flow)."),
    ] = None,
) -> None:
    """Sign in to Amacrin (browser flow, or `--token` for admin break-glass)."""
    ui = _ui(ctx)
    api_base = resolve_api_base()
    try:
        if token:
            login_with_token(token, api_base=api_base)
        else:
            run_login_flow(api_base=api_base, ui=ui)
        me = AmacrinClient(api_base).me()
    except AmacrinError as e:
        ui.error(str(e), cause=e.cause, hint=e.hint)
        raise typer.Exit(1) from None

    if _json_output(ctx):
        print(me.model_dump_json(indent=2))
        return
    ui.success(f"Logged in as {me.user.email}")
    ui.info("Next: run `amacrin archive create` to provision an archive")


@app.command()
def logout(ctx: typer.Context) -> None:
    """Sign out: revoke the session server-side and drop stored credentials."""
    ui = _ui(ctx)
    api_base = resolve_api_base()
    try:
        AmacrinClient(api_base).logout()
    except AmacrinError as e:
        ui.error(str(e), cause=e.cause, hint=e.hint)
        raise typer.Exit(1) from None

    if remove_credentials(api_base):
        ui.success("Logged out")
    else:
        ui.info("No credentials stored")


@app.command()
def whoami(ctx: typer.Context) -> None:
    """Show the signed-in user and their organisations."""
    ui = _ui(ctx)
    try:
        me = AmacrinClient().me()
    except AmacrinError as e:
        ui.error(str(e), cause=e.cause, hint=e.hint)
        raise typer.Exit(1) from None

    if _json_output(ctx):
        print(me.model_dump_json(indent=2))
        return
    ui.info(me.user.email)
    rows = [[o.name, o.id, o.role] for o in me.organisations]
    ui.table(["ORGANISATION", "ID", "ROLE"], rows)


@app.command()
def link(
    ctx: typer.Context,
    archive: Annotated[str, typer.Option(help="Existing Amacrin archive ID to bind.")],
) -> None:
    """Bind this project to an existing archive (writes `.amacrin/archive-id`)."""
    from amacrin.config import write_state

    ui = _ui(ctx)
    try:
        write_state("archive-id", archive, project_dir=Path.cwd())
    except AmacrinError as e:
        ui.error(str(e), cause=e.cause, hint=e.hint)
        raise typer.Exit(1) from None
    ui.success(f"Linked to archive {archive}")


@app.command()
def deploy(
    ctx: typer.Context,
    local: Annotated[
        bool,
        typer.Option(
            "--local",
            help="Build images locally and register directly with the instance "
            "(requires Docker + a registry). Default is server-side cloud build.",
        ),
    ] = False,
    registry: Annotated[
        Optional[str],
        typer.Option(
            help="[--local only] Container registry to push images to "
            "(e.g. ghcr.io/your-org).",
            envvar="OSA_REGISTRY",
        ),
    ] = None,
    skip_build: Annotated[
        bool,
        typer.Option(
            "--skip-build",
            help="[--local only] Skip image build/push, reuse last-pushed images.",
        ),
    ] = False,
) -> None:
    """Deploy the project's conventions to the linked archive.

    By default the source is uploaded and built in the cloud (no local Docker
    needed); `--local` builds images locally and registers them directly.

    Requires a linked archive — run `amacrin archive create` or
    `amacrin link --archive <id>` first.
    """
    import importlib
    import importlib.metadata

    from amacrin.deploy import deploy as do_deploy

    ui = _ui(ctx)

    for ep in importlib.metadata.entry_points(group="osa.conventions"):
        importlib.import_module(ep.value)

    try:
        result = do_deploy(
            project_dir=Path.cwd(),
            registry=registry,
            skip_build=skip_build,
            local=local,
            ui=ui,
        )
    except AmacrinError as e:
        ui.error(str(e), cause=e.cause, hint=e.hint)
        raise typer.Exit(1) from None

    if _json_output(ctx):
        print(json.dumps(result, indent=2, default=str))
    ui.success("Deploy complete")
