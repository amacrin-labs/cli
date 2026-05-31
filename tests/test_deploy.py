"""Tests for Amacrin deploy orchestration (strict — no auto-provision)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from amacrin.config import AmacrinError, write_state
from amacrin.deploy import deploy


def _mock_response(
    status_code: int = 200, json_data: dict | list | None = None
) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.raise_for_status = MagicMock()
    return resp


class TestDeployStrict:
    """Deploy resolves an existing archive and never provisions one."""

    def test_errors_when_no_archive_linked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AMACRIN_TOKEN", "tok")
        with (
            patch("amacrin.api.httpx.get") as mock_get,
            patch("osa.cli.deploy.deploy") as mock_osa_deploy,
        ):
            with pytest.raises(AmacrinError, match="No archive linked"):
                deploy(project_dir=tmp_path)
        mock_get.assert_not_called()
        mock_osa_deploy.assert_not_called()

    def test_delegates_to_osa_with_resolved_url(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AMACRIN_TOKEN", "tok")
        write_state("archive-id", "arch_123", project_dir=tmp_path)
        status_resp = _mock_response(json_data={"url": "https://arch.amacr.in"})

        with (
            patch("amacrin.api.httpx.get", return_value=status_resp),
            patch("osa.cli.deploy.deploy", return_value={"ok": True}) as mock_osa,
        ):
            result = deploy(project_dir=tmp_path, registry="ghcr.io/x", skip_build=True)

        assert result == {"ok": True}
        mock_osa.assert_called_once_with(
            server="https://arch.amacr.in",
            token="tok",
            project_dir=tmp_path,
            registry="ghcr.io/x",
            skip_build=True,
        )
