"""Amacrin ingest orchestration.

Triggers an ingestion run through the cloud control plane. The cloud brokers to
the archive's tenant instance with a scoped, short-lived token — the CLI never
holds a tenant credential (a platform token is not, and must not be, a tenant
credential). Status is polled through the read-proxy (`amacrin ingest status`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from amacrin import credentials
from amacrin.client import AmacrinClient
from amacrin.config import AmacrinError, require_archive_id


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

    Resolves the linked archive id, then triggers the run through the cloud
    broker (``POST /archives/{id}/ingestions``). Errors — a missing archive, an
    unreachable tenant (502), a bad convention (400), or a denial (403) —
    surface as ``AmacrinError`` from the client with the API's message.
    """
    client = AmacrinClient(api_base, cred_path=cred_path or credentials._DEFAULT_PATH)
    archive_id = require_archive_id(project_dir=project_dir)
    try:
        return client.trigger_ingestion(
            archive_id, convention, batch_size=batch_size, limit=limit
        )
    except AmacrinError as e:
        # Preserve the API's message/cause; add a triage hint if none was set.
        if e.hint is None:
            e.hint = "Check `amacrin archive status`, then try again"
        raise
