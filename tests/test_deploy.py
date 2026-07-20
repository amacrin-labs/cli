"""Tests for Amacrin deploy orchestration (strict — no auto-provision)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from amacrin.config import AmacrinError, write_state
from amacrin.deploy import deploy
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


class TestDeployStrict:
    """Deploy resolves an existing archive and never provisions one."""

    def test_errors_when_no_archive_linked(self, tmp_path: Path) -> None:
        client = _mock_client(_deployment())
        with (
            patch("amacrin.deploy.AmacrinClient", return_value=client),
            patch("osa.cli.deploy.deploy") as mock_osa_deploy,
        ):
            with pytest.raises(AmacrinError, match="No archive linked"):
                deploy(project_dir=tmp_path)
        client.archive_status.assert_not_called()
        mock_osa_deploy.assert_not_called()

    def test_errors_when_deployment_not_succeeded(self, tmp_path: Path) -> None:
        write_state("archive-id", "arch_123", project_dir=tmp_path)
        client = _mock_client(_deployment(status="in_progress", url=None))
        with (
            patch("amacrin.deploy.AmacrinClient", return_value=client),
            patch("osa.cli.deploy.deploy") as mock_osa_deploy,
        ):
            with pytest.raises(AmacrinError) as exc_info:
                deploy(project_dir=tmp_path)
        assert "not ready" in str(exc_info.value)
        assert exc_info.value.hint == "Run `amacrin archive status` to watch progress"
        mock_osa_deploy.assert_not_called()

    def test_delegates_to_osa_with_resolved_url_and_fresh_token(
        self, tmp_path: Path
    ) -> None:
        write_state("archive-id", "arch_123", project_dir=tmp_path)
        client = _mock_client(_deployment())
        with (
            patch("amacrin.deploy.AmacrinClient", return_value=client),
            patch("osa.cli.deploy.deploy", return_value={"ok": True}) as mock_osa,
        ):
            result = deploy(project_dir=tmp_path, registry="ghcr.io/x", skip_build=True)

        assert result == {"ok": True}
        mock_osa.assert_called_once_with(
            server="https://slug.amacr.in",
            token="fresh-at",
            project_dir=tmp_path,
            registry="ghcr.io/x",
            skip_build=True,
            ui=None,
        )
