"""Tests for Amacrin project-local state and config loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from amacrin.config import (
    AmacrinError,
    load_config,
    read_state,
    require_archive_id,
    write_state,
)


class TestStateFiles:
    """Read/write .amacrin/ state files."""

    def test_write_creates_amacrin_dir(self, tmp_path: Path) -> None:
        write_state("archive-id", "arch_abc", project_dir=tmp_path)
        assert (tmp_path / ".amacrin" / "archive-id").read_text() == "arch_abc"

    def test_read_returns_value(self, tmp_path: Path) -> None:
        (tmp_path / ".amacrin").mkdir()
        (tmp_path / ".amacrin" / "archive-id").write_text("arch_abc")
        assert read_state("archive-id", project_dir=tmp_path) == "arch_abc"

    def test_read_returns_none_when_missing(self, tmp_path: Path) -> None:
        assert read_state("archive-id", project_dir=tmp_path) is None

    def test_read_strips_whitespace(self, tmp_path: Path) -> None:
        (tmp_path / ".amacrin").mkdir()
        (tmp_path / ".amacrin" / "archive-id").write_text("  arch_abc \n")
        assert read_state("archive-id", project_dir=tmp_path) == "arch_abc"

    def test_write_overwrites_existing(self, tmp_path: Path) -> None:
        write_state("archive-id", "old", project_dir=tmp_path)
        write_state("archive-id", "new", project_dir=tmp_path)
        assert read_state("archive-id", project_dir=tmp_path) == "new"


class TestRequireArchiveId:
    """Archive ID resolution from .amacrin/archive-id."""

    def test_returns_value(self, tmp_path: Path) -> None:
        write_state("archive-id", "arch_123", project_dir=tmp_path)
        assert require_archive_id(project_dir=tmp_path) == "arch_123"

    def test_raises_when_missing(self, tmp_path: Path) -> None:
        with pytest.raises(AmacrinError, match="No archive linked"):
            require_archive_id(project_dir=tmp_path)


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

    def test_defaults_to_osa_yaml(self, tmp_path: Path) -> None:
        (tmp_path / "osa.yaml").write_text("name: Default\n")
        cfg = load_config(project_dir=tmp_path)
        assert cfg["name"] == "Default"

    def test_interpolates_env_vars_from_dotenv(self, tmp_path: Path) -> None:
        config_path = tmp_path / "osa.yaml"
        config_path.write_text("name: ${ARCHIVE_NAME}\n")
        (tmp_path / ".env").write_text("ARCHIVE_NAME=Test Archive\n")
        cfg = load_config(config_path, project_dir=tmp_path)
        assert cfg["name"] == "Test Archive"

    def test_os_env_overrides_dotenv(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_path = tmp_path / "osa.yaml"
        config_path.write_text("name: ${ARCHIVE_NAME}\n")
        (tmp_path / ".env").write_text("ARCHIVE_NAME=from_dotenv\n")
        monkeypatch.setenv("ARCHIVE_NAME", "from_env")
        cfg = load_config(config_path, project_dir=tmp_path)
        assert cfg["name"] == "from_env"

    def test_fails_on_unresolved_vars(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("MISSING_VAR", raising=False)
        config_path = tmp_path / "osa.yaml"
        config_path.write_text("name: ${MISSING_VAR}\n")
        with pytest.raises(AmacrinError, match="MISSING_VAR"):
            load_config(config_path, project_dir=tmp_path)

    def test_missing_config_file_raises_amacrin_error(self, tmp_path: Path) -> None:
        with pytest.raises(AmacrinError, match="No config file found") as exc_info:
            load_config(tmp_path / "nonexistent.yaml", project_dir=tmp_path)
        assert exc_info.value.hint == "Create an osa.yaml or pass --config"
