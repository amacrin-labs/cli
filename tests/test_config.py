"""Tests for Amacrin project-local state management."""

from __future__ import annotations

from pathlib import Path

import pytest

from amacrin.config import (
    AmacrinError,
    read_state,
    require_archive_id,
    require_token,
    write_state,
)


class TestStateFiles:
    """Read/write .amacrin/ state files."""

    def test_write_creates_amacrin_dir(self, tmp_path: Path) -> None:
        write_state("token", "tok_abc", project_dir=tmp_path)
        assert (tmp_path / ".amacrin" / "token").read_text() == "tok_abc"

    def test_read_returns_value(self, tmp_path: Path) -> None:
        (tmp_path / ".amacrin").mkdir()
        (tmp_path / ".amacrin" / "token").write_text("tok_abc")
        assert read_state("token", project_dir=tmp_path) == "tok_abc"

    def test_read_returns_none_when_missing(self, tmp_path: Path) -> None:
        assert read_state("token", project_dir=tmp_path) is None

    def test_read_strips_whitespace(self, tmp_path: Path) -> None:
        (tmp_path / ".amacrin").mkdir()
        (tmp_path / ".amacrin" / "token").write_text("  tok_abc \n")
        assert read_state("token", project_dir=tmp_path) == "tok_abc"

    def test_write_overwrites_existing(self, tmp_path: Path) -> None:
        write_state("token", "old", project_dir=tmp_path)
        write_state("token", "new", project_dir=tmp_path)
        assert read_state("token", project_dir=tmp_path) == "new"


class TestRequireToken:
    """Token resolution: env var -> state file -> error."""

    def test_env_var_takes_priority(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AMACRIN_TOKEN", "env_tok")
        write_state("token", "file_tok", project_dir=tmp_path)
        assert require_token(project_dir=tmp_path) == "env_tok"

    def test_falls_back_to_state_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("AMACRIN_TOKEN", raising=False)
        write_state("token", "file_tok", project_dir=tmp_path)
        assert require_token(project_dir=tmp_path) == "file_tok"

    def test_raises_when_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("AMACRIN_TOKEN", raising=False)
        with pytest.raises(AmacrinError, match="No Amacrin token found"):
            require_token(project_dir=tmp_path)


class TestRequireArchiveId:
    """Archive ID resolution from .amacrin/archive-id."""

    def test_returns_value(self, tmp_path: Path) -> None:
        write_state("archive-id", "arch_123", project_dir=tmp_path)
        assert require_archive_id(project_dir=tmp_path) == "arch_123"

    def test_raises_when_missing(self, tmp_path: Path) -> None:
        with pytest.raises(AmacrinError, match="No archive linked"):
            require_archive_id(project_dir=tmp_path)
