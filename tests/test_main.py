"""CLI-level smoke tests for the command grammar."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from amacrin.cli.main import app
from amacrin.config import read_state

runner = CliRunner()


class TestGrammar:
    """The command tree: archive + ingest sub-apps, no flat lifecycle commands."""

    def test_top_level_help_lists_new_commands(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for cmd in ("archive", "deploy", "ingest", "link", "login"):
            assert cmd in result.output

    def test_old_flat_commands_are_gone(self) -> None:
        # `list`/`status`/`destroy` now live under `archive`.
        result = runner.invoke(app, ["status"])
        assert result.exit_code != 0

    def test_archive_help_lists_subcommands(self) -> None:
        result = runner.invoke(app, ["archive", "--help"])
        assert result.exit_code == 0
        for cmd in ("create", "list", "status", "destroy"):
            assert cmd in result.output

    def test_ingest_help_lists_subcommands(self) -> None:
        result = runner.invoke(app, ["ingest", "--help"])
        assert result.exit_code == 0
        assert "start" in result.output


class TestLink:
    """`amacrin link` writes archive-id state."""

    def test_link_writes_archive_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["link", "--archive", "arch_x"])
        assert result.exit_code == 0
        assert read_state("archive-id", project_dir=tmp_path) == "arch_x"


class TestIngestStartCommand:
    """`amacrin ingest start` wiring and convention selection."""

    def test_explicit_convention_skips_discovery(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        with patch(
            "amacrin.ingest.start_ingest", return_value={"run": "ing_1"}
        ) as mock_start:
            result = runner.invoke(app, ["ingest", "start", "--convention", "Foo"])
        assert result.exit_code == 0
        assert mock_start.call_args.kwargs["convention"] == "Foo"

    def test_single_candidate_confirm(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from osa.cli.ingestion import IngestableConvention

        monkeypatch.chdir(tmp_path)
        candidates = [IngestableConvention("Foo", "1.0.0", "foo-ingester")]
        with (
            patch(
                "osa.cli.ingestion.discover_ingestable_conventions",
                return_value=candidates,
            ),
            patch(
                "amacrin.ingest.start_ingest", return_value={"run": "ing_1"}
            ) as mock_start,
        ):
            result = runner.invoke(app, ["ingest", "start"], input="y\n")
        assert result.exit_code == 0
        assert mock_start.call_args.kwargs["convention"] == "Foo"

    def test_no_candidates_errors(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        with patch(
            "osa.cli.ingestion.discover_ingestable_conventions", return_value=[]
        ):
            result = runner.invoke(app, ["ingest", "start"])
        assert result.exit_code != 0
        assert "ingester" in result.output
