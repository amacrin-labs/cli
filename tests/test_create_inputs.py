"""Unit tests for `_resolve_create_inputs` — combining amacrin.yaml (deploy
identity) with osa.yaml (server config), including the interactive slug prompt.

Driven directly rather than through CliRunner: `interactive` is an explicit
parameter, so the prompt path is exercised without a real TTY.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from amacrin.cli._archive_commands import _resolve_create_inputs
from amacrin.config import AmacrinError

_CONFIG = "amacrin.cli._archive_commands.load_config"
_PROMPT = "amacrin.cli._archive_commands.typer.prompt"


def _resolve(
    tmp_path: Path, *, slug=None, org=None, interactive=False, ui=None, cfg=None
):
    ui = ui or MagicMock()
    cfg = {"name": "My Lab", "auth": {"x": 1}} if cfg is None else cfg
    with patch(_CONFIG, return_value=cfg):
        return _resolve_create_inputs(
            tmp_path, config=None, slug=slug, org=org, interactive=interactive, ui=ui
        )


class TestResolveCreateInputs:
    def test_manifest_supplies_slug_and_org(self, tmp_path: Path) -> None:
        (tmp_path / "amacrin.yaml").write_text("slug: my-lab\norg: org_9\n")
        inputs = _resolve(tmp_path)
        assert inputs.slug == "my-lab"
        assert inputs.org == "org_9"
        assert inputs.name == "My Lab"
        assert inputs.auth == {"x": 1}
        assert inputs.prompted_slug is False

    def test_flag_overrides_manifest(self, tmp_path: Path) -> None:
        (tmp_path / "amacrin.yaml").write_text("slug: manifest-slug\n")
        inputs = _resolve(tmp_path, slug="flag-slug")
        assert inputs.slug == "flag-slug"

    def test_prompts_when_interactive_and_no_slug(self, tmp_path: Path) -> None:
        with patch(_PROMPT, return_value="typed-slug") as prompt:
            inputs = _resolve(tmp_path, interactive=True)
        assert inputs.slug == "typed-slug"
        assert inputs.prompted_slug is True
        # the proposed default is a slug of the archive name
        assert prompt.call_args.kwargs["default"] == "my-lab"

    def test_non_interactive_without_slug_raises(self, tmp_path: Path) -> None:
        with pytest.raises(AmacrinError, match="slug"):
            _resolve(tmp_path, interactive=False)

    def test_missing_name_raises(self, tmp_path: Path) -> None:
        with pytest.raises(AmacrinError, match="name"):
            _resolve(tmp_path, slug="my-lab", cfg={})

    def test_invalid_slug_raises(self, tmp_path: Path) -> None:
        with pytest.raises(AmacrinError):
            _resolve(tmp_path, slug="Bad Slug")

    def test_legacy_slug_in_osa_yaml_warns(self, tmp_path: Path) -> None:
        (tmp_path / "amacrin.yaml").write_text("slug: real-slug\n")
        ui = MagicMock()
        inputs = _resolve(tmp_path, ui=ui, cfg={"name": "Lab", "slug": "legacy"})
        assert inputs.slug == "real-slug"  # amacrin.yaml wins
        ui.warn.assert_called_once()
