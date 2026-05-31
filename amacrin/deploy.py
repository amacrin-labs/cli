"""Amacrin deploy orchestration.

Resolves the linked archive, then delegates to `osa.cli.deploy` for
OCI image building and convention registration. Deploy never provisions
an archive — run `amacrin archive create` or `amacrin link` first.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from amacrin.api import resolve_archive_url
from amacrin.config import require_token


def deploy(
    *,
    project_dir: Path,
    registry: str | None = None,
    skip_build: bool = False,
    api_base: str | None = None,
) -> dict[str, Any]:
    """Build images and register conventions with the linked archive.

    Orchestrates the Amacrin deploy flow:
    1. Resolve the linked archive's URL (errors if no archive is linked).
    2. Delegate to osa's deploy for image build + convention registration.
    """
    from osa.cli.deploy import deploy as osa_deploy

    token = require_token(project_dir=project_dir)
    archive_url = resolve_archive_url(project_dir=project_dir, api_base=api_base)

    print(f"Deploying to {archive_url}...")
    return osa_deploy(
        server=archive_url,
        token=token,
        project_dir=project_dir,
        registry=registry,
        skip_build=skip_build,
    )
