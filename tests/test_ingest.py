"""Tests for Amacrin ingest orchestration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from amacrin.config import AmacrinError, write_state
from amacrin.ingest import start_ingest


def _mock_response(
    status_code: int = 200, json_data: dict | list | None = None
) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.raise_for_status = MagicMock()
    return resp


class TestStartIngest:
    """Resolve the linked archive, then delegate to osa's ingestion."""

    def test_delegates_to_osa(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AMACRIN_TOKEN", "tok")
        write_state("archive-id", "arch_123", project_dir=tmp_path)
        status_resp = _mock_response(json_data={"url": "https://arch.amacr.in"})

        with (
            patch("amacrin.api.httpx.get", return_value=status_resp),
            patch(
                "osa.cli.ingestion.start_ingestion", return_value={"run": "ing_1"}
            ) as mock_start,
        ):
            result = start_ingest(
                convention="PDB Structures",
                project_dir=tmp_path,
                batch_size=500,
                limit=10,
            )

        assert result == {"run": "ing_1"}
        mock_start.assert_called_once_with(
            server="https://arch.amacr.in",
            convention="PDB Structures",
            token="tok",
            batch_size=500,
            limit=10,
            project_dir=tmp_path,
        )

    def test_errors_when_no_archive_linked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AMACRIN_TOKEN", "tok")
        with pytest.raises(AmacrinError, match="No archive linked"):
            start_ingest(convention="Foo", project_dir=tmp_path)

    def test_translates_ingestion_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from osa.cli.ingestion import IngestionError

        monkeypatch.setenv("AMACRIN_TOKEN", "tok")
        write_state("archive-id", "arch_123", project_dir=tmp_path)
        status_resp = _mock_response(json_data={"url": "https://arch.amacr.in"})

        with (
            patch("amacrin.api.httpx.get", return_value=status_resp),
            patch(
                "osa.cli.ingestion.start_ingestion",
                side_effect=IngestionError("boom"),
            ),
        ):
            with pytest.raises(AmacrinError, match="boom"):
                start_ingest(convention="Foo", project_dir=tmp_path)
