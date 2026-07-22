"""Amacrin ingest orchestration.

Resolves the linked archive, then delegates to `osa.cli.ingestion` to start an
ingestion run for a convention, identified by its slug (shown by
`amacrin deploy` when conventions are registered).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from amacrin import credentials
from amacrin.client import AmacrinClient
from amacrin.config import AmacrinError
from amacrin.deploy import resolve_archive_url


def start_ingest(
    *,
    convention: str,
    project_dir: Path,
    batch_size: int = 1000,
    limit: int | None = None,
    api_base: str | None = None,
    cred_path: Path | None = None,
) -> dict[str, Any]:
    """Start an ingestion run for a convention on the linked archive.

    Resolves the archive URL (errors if no archive is linked or ready), then
    delegates to osa's ingestion with the convention slug.
    """
    from osa.cli.ingestion import IngestionError, start_ingestion

    client = AmacrinClient(api_base, cred_path=cred_path or credentials._DEFAULT_PATH)
    archive_url = resolve_archive_url(client, project_dir=project_dir)
    # osa cannot refresh mid-flight, so hand it a verified-fresh access token.
    token = client.fresh_access_token()

    try:
        return start_ingestion(
            server=archive_url,
            convention_id=convention,
            token=token,
            batch_size=batch_size,
            limit=limit,
        )
    except IngestionError as e:
        raise AmacrinError(
            str(e),
            hint="Check `amacrin archive status` and try again",
        ) from e
