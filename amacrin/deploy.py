"""Amacrin deploy orchestration.

Resolves the linked archive, then delegates to `osa.cli.deploy` for OCI image
building and convention registration. Deploy never provisions an archive — run
`amacrin archive create` or `amacrin link` first.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from amacrin import credentials
from amacrin.cli.ui import UI
from amacrin.client import AmacrinClient
from amacrin.config import AmacrinError, require_archive_id


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
    api_base: str | None = None,
    cred_path: Path | None = None,
    ui: UI | None = None,
) -> dict[str, Any]:
    """Build images and register conventions with the linked archive.

    1. Resolve the linked archive's URL (errors if none is linked or ready).
    2. Delegate to osa's deploy for image build + convention registration,
       sharing our UI so both CLIs render one output stream.
    """
    from osa.cli.deploy import deploy as osa_deploy

    client = AmacrinClient(api_base, cred_path=cred_path or credentials._DEFAULT_PATH)
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
