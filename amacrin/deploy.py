"""Amacrin deploy orchestration.

By default `amacrin deploy` uses the **cloud build** path: it uploads the
convention source (a tarball) + a manifest to the platform, which builds the
component images server-side and publishes the convention to the archive's OSA
instance. Hosted customers never need Docker or a registry.

`--local` keeps the legacy path: build OCI images locally and register the
convention directly with the OSA instance (delegates to `osa.cli.deploy`).

Deploy never provisions an archive — run `amacrin archive create` or
`amacrin link` first.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from amacrin import credentials
from amacrin.cli.ui import UI
from amacrin.client import AmacrinClient
from amacrin.config import AmacrinError, require_archive_id
from amacrin.models import Build


def resolve_archive_url(client: AmacrinClient, *, project_dir: Path) -> str:
    """Return the linked archive's URL, erroring unless it is ready.

    Requires a linked archive (errors otherwise) and a succeeded deployment
    with a URL — anything else means the archive isn't serving yet.
    """
    archive_id = require_archive_id(project_dir=project_dir)
    deployment = client.archive_status(archive_id)
    if not (deployment.status == "succeeded" and deployment.url):
        raise AmacrinError(
            f"Archive is not ready (deployment {deployment.status})",
            hint="Run `amacrin archive status` to watch progress",
        )
    return deployment.url


def deploy(
    *,
    project_dir: Path,
    registry: str | None = None,
    skip_build: bool = False,
    local: bool = False,
    api_base: str | None = None,
    cred_path: Path | None = None,
    ui: UI | None = None,
) -> dict[str, Any]:
    """Deploy the project's conventions to the linked archive.

    Cloud path (default): upload source + manifest, build server-side, publish.
    `--local`: build images locally and register directly with the instance.
    """
    ui = ui or UI.create()
    client = AmacrinClient(api_base, cred_path=cred_path or credentials._DEFAULT_PATH)
    if local:
        return _local_deploy(
            client,
            project_dir=project_dir,
            registry=registry,
            skip_build=skip_build,
            ui=ui,
        )
    return _cloud_deploy(client, project_dir=project_dir, ui=ui)


def _local_deploy(
    client: AmacrinClient,
    *,
    project_dir: Path,
    registry: str | None,
    skip_build: bool,
    ui: UI,
) -> dict[str, Any]:
    """Legacy path: build images locally, register with the instance directly."""
    from osa.cli.deploy import deploy as osa_deploy

    archive_url = resolve_archive_url(client, project_dir=project_dir)
    # osa cannot refresh mid-flight, so hand it a verified-fresh access token.
    token = client.fresh_access_token()
    return osa_deploy(
        server=archive_url,
        token=token,
        project_dir=project_dir,
        registry=registry,
        skip_build=skip_build,
        ui=ui,
    )


def _verbose(ui: UI, text: str) -> None:
    """Emit a dim trace line, only under --verbose.

    Announce each silent stage *before* it runs — a deploy that stalls then
    shows exactly which stage it is stuck in.
    """
    if ui.verbose:
        ui.detail(text)


def _cloud_deploy(
    client: AmacrinClient, *, project_dir: Path, ui: UI
) -> dict[str, Any]:
    """Upload source + manifest per convention; build + publish server-side."""
    from amacrin.manifest import build_cloud_manifests, build_source_tarball

    archive_id = require_archive_id(project_dir=project_dir)
    _verbose(ui, f"checking archive {archive_id}")
    archive = client.archive(archive_id)
    _verbose(ui, f"archive status: {archive.status}")
    if archive.status != "running":
        raise AmacrinError(
            f"Archive is not running (status: {archive.status})",
            hint="Run `amacrin archive status` to watch it start, then retry",
        )

    # Manifests first — the docs gate and slug validation fail fast, before we
    # spend time tarring the source or hit the network.
    _verbose(ui, "resolving conventions via `osa manifest` (project env)")
    manifests = build_cloud_manifests(project_dir)
    _verbose(
        ui, f"{len(manifests)} convention(s): " + ", ".join(t for t, _ in manifests)
    )
    _verbose(ui, "packing source tarball")
    tarball = build_source_tarball(project_dir)
    _verbose(ui, f"source tarball: {len(tarball) / 1e6:.1f} MB")

    builds = [
        _build_and_publish(client, archive_id, title, manifest, tarball, ui)
        for title, manifest in manifests
    ]
    return {"builds": builds}


def _build_and_publish(
    client: AmacrinClient,
    archive_id: str,
    title: str,
    manifest: dict[str, Any],
    tarball: bytes,
    ui: UI,
) -> dict[str, Any]:
    """Submit one convention build and stream progress to terminal."""
    n_hooks = len(manifest.get("hooks") or [])
    suffix = " + ingester" if manifest.get("ingester") is not None else ""
    ui.info(f"Deploying '{title}' — {n_hooks} hook(s){suffix}")

    _verbose(ui, f"uploading {len(tarball) / 1e6:.1f} MB source + manifest")
    submitted = client.submit_build(archive_id, manifest, tarball)
    ui.info(f"  build {submitted.build_id} submitted")

    parent_seen: dict[str, str | None] = {"status": None}
    component_seen: dict[str, str] = {}

    def on_status(build: Build) -> None:
        if build.status != parent_seen["status"]:
            parent_seen["status"] = build.status
            ui.info(f"  {build.status}")
        for c in build.components:
            if component_seen.get(c.name) != c.status:
                component_seen[c.name] = c.status
                mark = {"succeeded": "✓", "failed": "✗", "cancelled": "✗"}.get(
                    c.status, "·"
                )
                ui.info(f"    {mark} {c.kind}:{c.name} {c.status}")

    build = client.wait_for_build(submitted.build_id, on_status=on_status)
    _raise_if_failed(build, title)
    ui.success(f"'{title}' published as {build.convention_ref}")
    return build.model_dump()


def _raise_if_failed(build: Build, title: str) -> None:
    """Turn a non-`published` terminal build into a clear, actionable error."""
    if build.status == "published":
        return
    if build.status == "publish_failed":
        # error_message carries the tenant's rejection (e.g. an OSA 422 body).
        raise AmacrinError(
            f"Publishing '{title}' to the archive failed",
            cause=build.error_message,
            hint="Fix the reported convention problem and run `amacrin deploy` again",
        )
    if build.status == "build_failed":
        failures = "; ".join(
            f"{c.kind}:{c.name}: {c.error_message}"
            for c in build.components
            if c.status == "failed"
        )
        raise AmacrinError(
            f"Building '{title}' failed",
            cause=build.error_message or failures or None,
            hint="Fix the reported build error and run `amacrin deploy` again",
        )
    if build.status == "cancelled":
        raise AmacrinError(
            f"Build for '{title}' was cancelled",
            cause=build.cancel_reason,
        )
    raise AmacrinError(
        f"Build for '{title}' ended in unexpected state {build.status!r}"
    )
