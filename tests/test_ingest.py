"""Tests for Amacrin ingest orchestration (brokered through the cloud)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from amacrin.config import AmacrinError, write_state
from amacrin.ingest import start_ingest


def _mock_client() -> MagicMock:
    client = MagicMock()
    client.trigger_ingestion.return_value = {"id": "ingest_1", "status": "pending"}
    return client


class TestStartIngest:
    """Resolve the linked archive, then trigger through the cloud broker."""

    def test_triggers_through_the_cloud_broker(self, tmp_path: Path) -> None:
        write_state("archive-id", "arch_123", project_dir=tmp_path)
        client = _mock_client()
        with patch("amacrin.ingest.AmacrinClient", return_value=client):
            result = start_ingest(
                convention="pdb-structures",
                project_dir=tmp_path,
                batch_size=500,
                limit=10,
            )

        assert result == {"id": "ingest_1", "status": "pending"}
        # The CLI hands the convention + bounds to the cloud, keyed by the
        # linked archive id — never a tenant URL, never a tenant token.
        client.trigger_ingestion.assert_called_once_with(
            "arch_123",
            "pdb-structures",
            batch_size=500,
            limit=10,
        )

    def test_errors_when_no_archive_linked(self, tmp_path: Path) -> None:
        client = _mock_client()
        with patch("amacrin.ingest.AmacrinClient", return_value=client):
            with pytest.raises(AmacrinError, match="No archive linked"):
                start_ingest(convention="Foo", project_dir=tmp_path)
        client.trigger_ingestion.assert_not_called()

    def test_adds_triage_hint_when_the_api_gives_none(self, tmp_path: Path) -> None:
        write_state("archive-id", "arch_123", project_dir=tmp_path)
        client = _mock_client()
        client.trigger_ingestion.side_effect = AmacrinError(
            "archive instance unreachable"
        )
        with patch("amacrin.ingest.AmacrinClient", return_value=client):
            with pytest.raises(AmacrinError, match="unreachable") as exc_info:
                start_ingest(convention="Foo", project_dir=tmp_path)
        assert exc_info.value.hint == "Check `amacrin archive status`, then try again"

    def test_preserves_an_api_supplied_hint(self, tmp_path: Path) -> None:
        write_state("archive-id", "arch_123", project_dir=tmp_path)
        client = _mock_client()
        client.trigger_ingestion.side_effect = AmacrinError(
            "denied", hint="You need the Admin role in this organisation"
        )
        with patch("amacrin.ingest.AmacrinClient", return_value=client):
            with pytest.raises(AmacrinError) as exc_info:
                start_ingest(convention="Foo", project_dir=tmp_path)
        assert exc_info.value.hint == "You need the Admin role in this organisation"
