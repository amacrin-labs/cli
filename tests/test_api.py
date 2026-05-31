"""Tests for Amacrin API client."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from amacrin.api import (
    create,
    destroy,
    list_archives,
    load_config,
    login,
    redeploy,
    set_account,
    status,
)
from amacrin.config import AmacrinError, read_state, write_state


def _mock_response(
    status_code: int = 200, json_data: dict | list | None = None
) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.raise_for_status = MagicMock()
    return resp


class TestLoadConfig:
    """Parse YAML config with ${VAR} interpolation."""

    def test_parses_yaml(self, tmp_path: Path) -> None:
        config_path = tmp_path / "osa.yaml"
        config_path.write_text(
            "name: My Archive\n"
            "domain: data.mylab.org\n"
            "auth:\n"
            "  providers:\n"
            "    orcid:\n"
            "      client_id: APP-XXX\n"
            "      client_secret: secret\n"
            "  admins:\n"
            "    orcid:\n"
            "      - '0000-0002-1234-5678'\n"
        )
        cfg = load_config(config_path, project_dir=tmp_path)
        assert cfg["name"] == "My Archive"
        assert cfg["auth"]["providers"]["orcid"]["client_id"] == "APP-XXX"

    def test_interpolates_env_vars(self, tmp_path: Path) -> None:
        config_path = tmp_path / "osa.yaml"
        config_path.write_text("name: ${ARCHIVE_NAME}\n")
        dotenv = tmp_path / ".env"
        dotenv.write_text("ARCHIVE_NAME=Test Archive\n")
        cfg = load_config(config_path, project_dir=tmp_path)
        assert cfg["name"] == "Test Archive"

    def test_os_env_overrides_dotenv(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_path = tmp_path / "osa.yaml"
        config_path.write_text("name: ${ARCHIVE_NAME}\n")
        dotenv = tmp_path / ".env"
        dotenv.write_text("ARCHIVE_NAME=from_dotenv\n")
        monkeypatch.setenv("ARCHIVE_NAME", "from_env")
        cfg = load_config(config_path, project_dir=tmp_path)
        assert cfg["name"] == "from_env"

    def test_fails_on_unresolved_vars(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("MISSING_VAR", raising=False)
        config_path = tmp_path / "osa.yaml"
        config_path.write_text("name: ${MISSING_VAR}\n")
        with pytest.raises(Exception, match="MISSING_VAR"):
            load_config(config_path, project_dir=tmp_path)

    def test_missing_config_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "nonexistent.yaml", project_dir=tmp_path)


class TestLogin:
    def test_stores_token(self, tmp_path: Path) -> None:
        login("tok_abc", project_dir=tmp_path)
        assert read_state("token", project_dir=tmp_path) == "tok_abc"


class TestSetAccount:
    def test_stores_account_id(self, tmp_path: Path) -> None:
        set_account("acct_xxx", project_dir=tmp_path)
        assert read_state("account-id", project_dir=tmp_path) == "acct_xxx"


class TestCreate:
    def test_creates_archive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AMACRIN_TOKEN", "tok")
        write_state("account-id", "acct_xxx", project_dir=tmp_path)

        config_path = tmp_path / "osa.yaml"
        config_path.write_text(
            "name: Test\n"
            "auth:\n"
            "  providers:\n"
            "    orcid:\n"
            "      client_id: APP-X\n"
            "      client_secret: s\n"
            "  admins:\n"
            "    orcid:\n"
            "      - '0000-0002-1234-5678'\n"
        )

        response_data = {
            "archive": {"id": "arch_123", "status": "deploying"},
            "deployment": {"id": "deploy_456", "status": "pending"},
        }
        mock_resp = _mock_response(202, response_data)

        with patch("amacrin.api.httpx.post", return_value=mock_resp) as mock_post:
            result = create(
                config_path=config_path,
                project_dir=tmp_path,
                api_base="https://api.test.com/api/v1",
            )

        assert result == response_data
        assert read_state("archive-id", project_dir=tmp_path) == "arch_123"

        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["json"]["account_id"] == "acct_xxx"
        assert call_kwargs[1]["json"]["config"]["name"] == "Test"

    def test_defaults_config_to_osa_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AMACRIN_TOKEN", "tok")
        write_state("account-id", "acct_xxx", project_dir=tmp_path)

        config_path = tmp_path / "osa.yaml"
        config_path.write_text(
            "name: Default\n"
            "auth:\n"
            "  providers:\n"
            "    orcid:\n"
            "      client_id: X\n"
            "      client_secret: s\n"
        )

        mock_resp = _mock_response(202, {"archive": {"id": "arch_1"}, "deployment": {}})

        with patch("amacrin.api.httpx.post", return_value=mock_resp):
            result = create(
                config_path=None,
                project_dir=tmp_path,
                api_base="https://api.test.com/api/v1",
            )

        assert result["archive"]["id"] == "arch_1"

    def test_requires_account_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AMACRIN_TOKEN", "tok")
        config_path = tmp_path / "osa.yaml"
        config_path.write_text("name: Test\nauth:\n  providers: {}\n")

        with pytest.raises(AmacrinError, match="account"):
            create(
                config_path=config_path,
                project_dir=tmp_path,
                api_base="https://api.test.com/api/v1",
            )


class TestListArchives:
    def test_lists_archives(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AMACRIN_TOKEN", "tok")
        write_state("account-id", "acct_xxx", project_dir=tmp_path)

        archives = [{"id": "arch_1", "name": "A1"}, {"id": "arch_2", "name": "A2"}]
        mock_resp = _mock_response(200, archives)

        with patch("amacrin.api.httpx.get", return_value=mock_resp) as mock_get:
            result = list_archives(
                project_dir=tmp_path,
                api_base="https://api.test.com/api/v1",
            )

        assert result == archives
        url = mock_get.call_args[0][0]
        assert "account_id=acct_xxx" in url


class TestStatus:
    def test_gets_status(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AMACRIN_TOKEN", "tok")
        write_state("archive-id", "arch_123", project_dir=tmp_path)

        status_data = {"status": "running", "url": "https://test.amacr.in"}
        mock_resp = _mock_response(200, status_data)

        with patch("amacrin.api.httpx.get", return_value=mock_resp) as mock_get:
            result = status(
                project_dir=tmp_path,
                api_base="https://api.test.com/api/v1",
            )

        assert result == status_data
        url = mock_get.call_args[0][0]
        assert "/archives/arch_123/status" in url

    def test_errors_when_no_archive_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AMACRIN_TOKEN", "tok")

        with pytest.raises(AmacrinError, match="archive"):
            status(
                project_dir=tmp_path,
                api_base="https://api.test.com/api/v1",
            )


class TestRedeploy:
    def test_deploys_with_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AMACRIN_TOKEN", "tok")
        write_state("archive-id", "arch_123", project_dir=tmp_path)

        config_path = tmp_path / "osa.yaml"
        config_path.write_text(
            "name: Test\n"
            "auth:\n"
            "  providers:\n"
            "    orcid:\n"
            "      client_id: X\n"
            "      client_secret: s\n"
        )

        deploy_resp = {"id": "deploy_789", "status": "pending"}
        mock_resp = _mock_response(202, deploy_resp)

        with patch("amacrin.api.httpx.post", return_value=mock_resp) as mock_post:
            result = redeploy(
                config_path=config_path,
                project_dir=tmp_path,
                api_base="https://api.test.com/api/v1",
            )

        assert result == deploy_resp
        url = mock_post.call_args[0][0]
        assert "/archives/arch_123/deploy" in url
        payload = mock_post.call_args[1]["json"]
        assert "config" in payload

    def test_deploys_without_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AMACRIN_TOKEN", "tok")
        write_state("archive-id", "arch_123", project_dir=tmp_path)

        deploy_resp = {"id": "deploy_789", "status": "pending"}
        mock_resp = _mock_response(202, deploy_resp)

        with patch("amacrin.api.httpx.post", return_value=mock_resp) as mock_post:
            result = redeploy(
                config_path=None,
                project_dir=tmp_path,
                api_base="https://api.test.com/api/v1",
            )

        assert result == deploy_resp
        payload = mock_post.call_args[1]["json"]
        assert payload == {}


class TestDestroy:
    def test_destroys_archive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AMACRIN_TOKEN", "tok")
        write_state("archive-id", "arch_123", project_dir=tmp_path)

        destroy_resp = {"id": "arch_123", "status": "destroying"}
        mock_resp = _mock_response(202, destroy_resp)

        with patch("amacrin.api.httpx.post", return_value=mock_resp):
            destroy(
                force=False,
                project_dir=tmp_path,
                api_base="https://api.test.com/api/v1",
            )

        assert read_state("archive-id", project_dir=tmp_path) is None

    def test_passes_force_flag(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AMACRIN_TOKEN", "tok")
        write_state("archive-id", "arch_123", project_dir=tmp_path)

        mock_resp = _mock_response(202, {"status": "destroying"})

        with patch("amacrin.api.httpx.post", return_value=mock_resp) as mock_post:
            destroy(
                force=True,
                project_dir=tmp_path,
                api_base="https://api.test.com/api/v1",
            )

        url = mock_post.call_args[0][0]
        assert "force=true" in url
