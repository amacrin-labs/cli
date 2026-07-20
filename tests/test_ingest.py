"""Tests for Amacrin ingest orchestration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from amacrin.config import AmacrinError, write_state
from amacrin.ingest import start_ingest
from amacrin.models import Deployment


def _deployment(
    status: str = "succeeded", url: str | None = "https://slug.amacr.in"
) -> Deployment:
    return Deployment(
        id="deploy_1",
        archive_id="arch_123",
        provider="fly",
        status=status,
        url=url,
        started_at="2026-07-20T00:00:00Z",
    )


def _mock_client(deployment: Deployment) -> MagicMock:
    client = MagicMock()
    client.archive_status.return_value = deployment
    client.fresh_access_token.return_value = "fresh-at"
    return client


class TestStartIngest:
    """Resolve the linked archive, then delegate to osa's ingestion."""

    def test_delegates_to_osa_with_fresh_token(self, tmp_path: Path) -> None:
        write_state("archive-id", "arch_123", project_dir=tmp_path)
        client = _mock_client(_deployment())
        with (
            patch("amacrin.ingest.AmacrinClient", return_value=client),
            patch(
                "osa.cli.ingestion.start_ingestion", return_value={"run": "ing_1"}
            ) as mock_start,
        ):
            result = start_ingest(
                convention="pdb-structures",
                project_dir=tmp_path,
                batch_size=500,
                limit=10,
            )

        assert result == {"run": "ing_1"}
        mock_start.assert_called_once_with(
            server="https://slug.amacr.in",
            convention_id="pdb-structures",
            token="fresh-at",
            batch_size=500,
            limit=10,
        )

    def test_errors_when_no_archive_linked(self, tmp_path: Path) -> None:
        client = _mock_client(_deployment())
        with (
            patch("amacrin.ingest.AmacrinClient", return_value=client),
            patch("osa.cli.ingestion.start_ingestion") as mock_start,
        ):
            with pytest.raises(AmacrinError, match="No archive linked"):
                start_ingest(convention="Foo", project_dir=tmp_path)
        mock_start.assert_not_called()

    def test_translates_ingestion_error(self, tmp_path: Path) -> None:
        from osa.cli.ingestion import IngestionError

        write_state("archive-id", "arch_123", project_dir=tmp_path)
        client = _mock_client(_deployment())
        with (
            patch("amacrin.ingest.AmacrinClient", return_value=client),
            patch(
                "osa.cli.ingestion.start_ingestion",
                side_effect=IngestionError("boom"),
            ),
        ):
            with pytest.raises(AmacrinError, match="boom") as exc_info:
                start_ingest(convention="Foo", project_dir=tmp_path)
        assert exc_info.value.hint == "Check `amacrin archive status` and try again"
