"""Amacrin ingest orchestration.

Resolves the linked archive, then delegates to `osa.cli.ingestion` to start
an ingestion run for a convention. Convention discovery and selection live in
the CLI layer (they're interactive); this module takes a resolved convention
name.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from amacrin.api import resolve_archive_url
from amacrin.config import AmacrinError, require_token


def start_ingest(
    *,
    convention: str,
    project_dir: Path,
    batch_size: int = 1000,
    limit: int | None = None,
    api_base: str | None = None,
) -> dict[str, Any]:
    """Start an ingestion run for a convention on the linked archive.

    Resolves the archive URL (errors if no archive is linked), then delegates
    to osa's ingestion. The convention title is passed through — osa builds the
    SRN from osa.yaml.
    """
    from osa.cli.ingestion import IngestionError, start_ingestion

    token = require_token(project_dir=project_dir)
    archive_url = resolve_archive_url(project_dir=project_dir, api_base=api_base)

    try:
        return start_ingestion(
            server=archive_url,
            convention=convention,
            token=token,
            batch_size=batch_size,
            limit=limit,
            project_dir=project_dir,
        )
    except IngestionError as e:
        raise AmacrinError(str(e)) from e
