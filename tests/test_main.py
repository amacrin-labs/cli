"""CLI-level tests for the `amacrin` command grammar and behaviour.

The command tree is exercised through Typer's ``CliRunner``; the network is
never touched — ``AmacrinClient`` (and the auth entry points) are patched at
their import site in each command module. Machine data goes to stdout, chrome
to stderr, so JSON assertions read ``result.stdout`` and parse it directly.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from typer.testing import CliRunner

from amacrin.cli.main import app
from amacrin.config import AmacrinError, read_state, write_state
from amacrin.models import Archive, ArchiveCreated, Deployment, Me

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _plain(output: str) -> str:
    """Strip ANSI colour codes from CLI output.

    Typer renders error panels through Rich, which colourises option names when
    colour is enabled (as CI does) — splitting a literal like ``--convention``
    across escape sequences. Assert against the de-styled text so substring
    checks are stable regardless of the terminal/CI colour setting.
    """
    return _ANSI_RE.sub("", output)


# -- fixtures / builders ----------------------------------------------------


def _me(*orgs: dict[str, str]) -> Me:
    organisations = list(orgs) or [
        {"id": "org_1", "name": "Personal", "role": "owner", "created_at": "2026-01-01"}
    ]
    return Me.model_validate(
        {
            "user": {
                "id": "usr_1",
                "email": "rory@rory.bio",
                "created_at": "2026-01-01",
            },
            "organisations": organisations,
        }
    )


def _archive(**overrides: object) -> Archive:
    data: dict[str, object] = {
        "id": "arch_1",
        "organisation_id": "org_1",
        "name": "My Archive",
        "slug": "my-archive",
        "domain": "my-archive.amacrin.com",
        "config": {},
        "status": "running",
        "created_at": "2026-01-01",
        "updated_at": "2026-01-01",
    }
    data.update(overrides)
    return Archive.model_validate(data)


def _deployment(status: str = "succeeded", **overrides: object) -> Deployment:
    data: dict[str, object] = {
        "id": "dep_1",
        "archive_id": "arch_1",
        "provider": "fly",
        "status": status,
        "url": "https://my-archive.amacrin.com",
        "started_at": "2026-01-01T00:00:00Z",
        "completed_at": "2026-01-01T00:01:00Z",
    }
    data.update(overrides)
    return Deployment.model_validate(data)


# -- grammar ----------------------------------------------------------------


class TestGrammar:
    def test_top_level_help_lists_commands(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for cmd in (
            "login",
            "logout",
            "whoami",
            "org",
            "link",
            "archive",
            "deploy",
            "ingest",
        ):
            assert cmd in result.output

    def test_set_account_is_gone(self) -> None:
        result = runner.invoke(app, ["set-account", "--id", "x"])
        assert result.exit_code != 0

    def test_version_prints_version(self) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "amacrin" in result.output

    @pytest.mark.parametrize(
        "argv",
        [
            ["login", "--help"],
            ["logout", "--help"],
            ["whoami", "--help"],
            ["link", "--help"],
            ["deploy", "--help"],
            ["org", "--help"],
            ["org", "list", "--help"],
            ["org", "create", "--help"],
            ["archive", "--help"],
            ["archive", "create", "--help"],
            ["archive", "list", "--help"],
            ["archive", "status", "--help"],
            ["archive", "destroy", "--help"],
            ["ingest", "--help"],
            ["ingest", "start", "--help"],
        ],
    )
    def test_every_command_has_help(self, argv: list[str]) -> None:
        result = runner.invoke(app, argv)
        assert result.exit_code == 0


# -- whoami -----------------------------------------------------------------


class TestWhoami:
    def test_table_output(self) -> None:
        client = MagicMock()
        client.me.return_value = _me()
        with patch("amacrin.cli.main.AmacrinClient", return_value=client):
            result = runner.invoke(app, ["whoami"])
        assert result.exit_code == 0
        assert "rory@rory.bio" in result.output
        assert "Personal" in result.output

    def test_json_output_parses(self) -> None:
        client = MagicMock()
        client.me.return_value = _me()
        with patch("amacrin.cli.main.AmacrinClient", return_value=client):
            result = runner.invoke(app, ["--json", "whoami"])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["user"]["email"] == "rory@rory.bio"

    def test_unauthenticated_shows_hint_no_traceback(self) -> None:
        client = MagicMock()
        client.me.side_effect = AmacrinError(
            "Not authenticated", hint="Run `amacrin login`"
        )
        with patch("amacrin.cli.main.AmacrinClient", return_value=client):
            result = runner.invoke(app, ["whoami"])
        assert result.exit_code == 1
        assert "Not authenticated" in result.output
        assert "amacrin login" in result.output
        assert "Traceback" not in result.output


# -- login / logout ---------------------------------------------------------


class TestLogin:
    def test_token_path_stores_and_verifies(self) -> None:
        client = MagicMock()
        client.me.return_value = _me()
        with (
            patch("amacrin.cli.main.login_with_token") as mock_token,
            patch("amacrin.cli.main.run_login_flow") as mock_flow,
            patch("amacrin.cli.main.AmacrinClient", return_value=client),
        ):
            result = runner.invoke(app, ["login", "--token", "adm_123"])
        assert result.exit_code == 0
        assert mock_token.call_args.args[0] == "adm_123"
        mock_flow.assert_not_called()
        assert "rory@rory.bio" in result.output

    def test_browser_flow_when_no_token(self) -> None:
        client = MagicMock()
        client.me.return_value = _me()
        with (
            patch("amacrin.cli.main.run_login_flow") as mock_flow,
            patch("amacrin.cli.main.login_with_token") as mock_token,
            patch("amacrin.cli.main.AmacrinClient", return_value=client),
        ):
            result = runner.invoke(app, ["login"])
        assert result.exit_code == 0
        mock_flow.assert_called_once()
        mock_token.assert_not_called()


class TestLogout:
    def test_removes_credentials(self) -> None:
        client = MagicMock()
        with (
            patch("amacrin.cli.main.AmacrinClient", return_value=client),
            patch("amacrin.cli.main.remove_credentials", return_value=True),
        ):
            result = runner.invoke(app, ["logout"])
        assert result.exit_code == 0
        client.logout.assert_called_once()
        assert "Logged out" in result.output

    def test_nothing_stored(self) -> None:
        client = MagicMock()
        with (
            patch("amacrin.cli.main.AmacrinClient", return_value=client),
            patch("amacrin.cli.main.remove_credentials", return_value=False),
        ):
            result = runner.invoke(app, ["logout"])
        assert result.exit_code == 0
        assert "No credentials stored" in result.output


# -- link -------------------------------------------------------------------


class TestLink:
    def test_writes_archive_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["link", "--archive", "arch_x"])
        assert result.exit_code == 0
        assert read_state("archive-id", project_dir=tmp_path) == "arch_x"


# -- org --------------------------------------------------------------------


class TestOrg:
    def test_list_table(self) -> None:
        client = MagicMock()
        me = _me()
        client.list_organisations.return_value = me.organisations
        with patch("amacrin.cli._org_commands.AmacrinClient", return_value=client):
            result = runner.invoke(app, ["org", "list"])
        assert result.exit_code == 0
        assert "Personal" in result.output

    def test_create_prints_id(self) -> None:
        from amacrin.models import Organisation

        client = MagicMock()
        client.create_organisation.return_value = Organisation(
            id="org_new", name="Acme", role="owner", created_at="2026-01-01"
        )
        with patch("amacrin.cli._org_commands.AmacrinClient", return_value=client):
            result = runner.invoke(app, ["org", "create", "--name", "Acme"])
        assert result.exit_code == 0
        assert "org_new" in result.output


# -- archive ----------------------------------------------------------------


class TestArchiveCreate:
    def _patch_config(self, cfg: Mapping[str, object]):
        # load_config is imported into the command module — patch it there.
        return patch("amacrin.cli._archive_commands.load_config", return_value=cfg)

    @staticmethod
    def _write_manifest(tmp_path: Path, body: str = "slug: my-archive\n") -> None:
        (tmp_path / "amacrin.yaml").write_text(body)

    def test_declarative_manifest_create(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        self._write_manifest(tmp_path)  # slug lives in amacrin.yaml
        client = MagicMock()
        client.me.return_value = _me()
        created = ArchiveCreated(
            archive=_archive(), deployment=_deployment(status="pending")
        )
        client.create_archive.return_value = created
        client.wait_for_deployment.return_value = _deployment(status="succeeded")

        cfg = {"name": "My Archive", "auth": {"mode": "open"}}  # osa.yaml: no slug
        with (
            self._patch_config(cfg),
            patch("amacrin.cli._archive_commands.AmacrinClient", return_value=client),
        ):
            result = runner.invoke(app, ["archive", "create"])

        assert result.exit_code == 0, result.output
        # org auto-resolved to the single org
        org_id, payload = client.create_archive.call_args.args
        assert org_id == "org_1"
        # name/auth from osa.yaml, slug from amacrin.yaml
        assert payload == {
            "name": "My Archive",
            "slug": "my-archive",
            "auth": {"mode": "open"},
        }
        # archive-id persisted
        assert read_state("archive-id", project_dir=tmp_path) == "arch_1"

    def test_json_output(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        self._write_manifest(tmp_path)
        client = MagicMock()
        client.me.return_value = _me()
        client.create_archive.return_value = ArchiveCreated(
            archive=_archive(), deployment=_deployment(status="pending")
        )
        client.wait_for_deployment.return_value = _deployment(status="succeeded")

        cfg = {"name": "My Archive", "auth": None}
        with (
            self._patch_config(cfg),
            patch("amacrin.cli._archive_commands.AmacrinClient", return_value=client),
        ):
            result = runner.invoke(app, ["--json", "archive", "create"])

        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["archive"]["slug"] == "my-archive"
        assert payload["deployment"]["status"] == "succeeded"

    def test_slug_flag_overrides_manifest(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        self._write_manifest(tmp_path, "slug: from-manifest\n")
        client = MagicMock()
        client.me.return_value = _me()
        client.create_archive.return_value = ArchiveCreated(
            archive=_archive(), deployment=_deployment(status="pending")
        )
        client.wait_for_deployment.return_value = _deployment(status="succeeded")

        cfg = {"name": "My Archive", "auth": None}
        with (
            self._patch_config(cfg),
            patch("amacrin.cli._archive_commands.AmacrinClient", return_value=client),
        ):
            result = runner.invoke(app, ["archive", "create", "--slug", "from-flag"])

        assert result.exit_code == 0, result.output
        _, payload = client.create_archive.call_args.args
        assert payload["slug"] == "from-flag"

    def test_no_slug_non_interactive_errors(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # No amacrin.yaml, no --slug, and CliRunner stdin is not a TTY.
        monkeypatch.chdir(tmp_path)
        client = MagicMock()
        cfg = {"name": "My Archive"}
        with (
            self._patch_config(cfg),
            patch("amacrin.cli._archive_commands.AmacrinClient", return_value=client),
        ):
            result = runner.invoke(app, ["archive", "create"])
        assert result.exit_code == 1
        assert "slug" in result.output.lower()
        client.create_archive.assert_not_called()

    def test_slug_taken_shows_clean_message(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        self._write_manifest(tmp_path)
        client = MagicMock()
        client.me.return_value = _me()
        client.create_archive.side_effect = AmacrinError(
            "'my-archive' is taken — pick another slug",
            hint="Change `slug` in amacrin.yaml and re-run",
            status=409,
        )
        cfg = {"name": "My Archive", "auth": None}
        with (
            self._patch_config(cfg),
            patch("amacrin.cli._archive_commands.AmacrinClient", return_value=client),
        ):
            result = runner.invoke(app, ["archive", "create"])
        assert result.exit_code == 1
        assert "is taken" in result.output
        assert "Traceback" not in result.output


class TestInit:
    def test_scaffolds_files_with_flags(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["init", "--name", "My Lab", "--slug", "my-lab"])
        assert result.exit_code == 0, result.output
        osa = yaml.safe_load((tmp_path / "osa.yaml").read_text())
        manifest = yaml.safe_load((tmp_path / "amacrin.yaml").read_text())
        assert osa["name"] == "My Lab"
        assert "slug" not in osa  # server config stays slug-free
        assert manifest["slug"] == "my-lab"
        assert (tmp_path / ".env.example").exists()

    def test_derives_slug_from_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["init", "--name", "My Lab Archive"])
        assert result.exit_code == 0, result.output
        manifest = yaml.safe_load((tmp_path / "amacrin.yaml").read_text())
        assert manifest["slug"] == "my-lab-archive"

    def test_no_clobber(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "osa.yaml").write_text("keep me")
        result = runner.invoke(app, ["init", "--name", "X", "--slug", "x"])
        assert result.exit_code == 0
        assert (tmp_path / "osa.yaml").read_text() == "keep me"
        assert (tmp_path / "amacrin.yaml").exists()  # the other file is still written

    def test_invalid_slug_errors(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["init", "--name", "X", "--slug", "Bad Slug"])
        assert result.exit_code == 1
        assert "slug" in result.output.lower()


class TestArchiveList:
    def test_table(self) -> None:
        client = MagicMock()
        client.list_archives.return_value = [_archive()]
        with patch("amacrin.cli._archive_commands.AmacrinClient", return_value=client):
            result = runner.invoke(app, ["archive", "list"])
        assert result.exit_code == 0
        assert "my-archive" in result.output


class TestArchiveStatus:
    def test_requires_linked_archive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        client = MagicMock()
        with patch("amacrin.cli._archive_commands.AmacrinClient", return_value=client):
            result = runner.invoke(app, ["archive", "status"])
        assert result.exit_code == 1
        assert "archive" in result.output.lower()

    def test_shows_status(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        write_state("archive-id", "arch_1", project_dir=tmp_path)
        client = MagicMock()
        client.archive_status.return_value = _deployment(status="succeeded")
        with patch("amacrin.cli._archive_commands.AmacrinClient", return_value=client):
            result = runner.invoke(app, ["archive", "status"])
        assert result.exit_code == 0
        assert "succeeded" in result.output


class TestArchiveDestroy:
    def test_confirm_aborts_without_force(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        write_state("archive-id", "arch_1", project_dir=tmp_path)
        client = MagicMock()
        with patch("amacrin.cli._archive_commands.AmacrinClient", return_value=client):
            result = runner.invoke(app, ["archive", "destroy"], input="n\n")
        assert result.exit_code == 1
        client.destroy_archive.assert_not_called()

    def test_force_skips_prompt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        write_state("archive-id", "arch_1", project_dir=tmp_path)
        client = MagicMock()
        client.destroy_archive.return_value = _archive(status="destroying")
        with patch("amacrin.cli._archive_commands.AmacrinClient", return_value=client):
            result = runner.invoke(app, ["archive", "destroy", "--force"])
        assert result.exit_code == 0
        client.destroy_archive.assert_called_once_with("arch_1", force=True)
        assert read_state("archive-id", project_dir=tmp_path) is None


# -- ingest -----------------------------------------------------------------


class TestIngestStart:
    def test_convention_slug_passed_through(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        with patch(
            "amacrin.ingest.start_ingest", return_value={"run": "ing_1"}
        ) as mock_start:
            result = runner.invoke(app, ["ingest", "start", "--convention", "foo"])
        assert result.exit_code == 0
        assert mock_start.call_args.kwargs["convention"] == "foo"

    def test_convention_is_required(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["ingest", "start"])
        assert result.exit_code != 0
        assert "--convention" in _plain(result.output)
