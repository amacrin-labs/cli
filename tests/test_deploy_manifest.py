"""Unit tests for the amacrin.yaml deploy manifest loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from amacrin.config import AmacrinError
from amacrin.deploy_manifest import (
    MANIFEST_FILENAME,
    DeployManifest,
    load_deploy_manifest,
)


def _write(tmp_path: Path, body: str) -> None:
    (tmp_path / MANIFEST_FILENAME).write_text(body)


class TestLoad:
    def test_absent_returns_none(self, tmp_path: Path) -> None:
        assert load_deploy_manifest(tmp_path) is None

    def test_minimal(self, tmp_path: Path) -> None:
        _write(tmp_path, "slug: my-lab\n")
        manifest = load_deploy_manifest(tmp_path)
        assert isinstance(manifest, DeployManifest)
        assert manifest.slug == "my-lab"
        assert manifest.org is None
        assert manifest.config == Path("osa.yaml")  # default

    def test_full(self, tmp_path: Path) -> None:
        _write(tmp_path, "slug: my-lab\norg: org_1\nconfig: custom.yaml\n")
        manifest = load_deploy_manifest(tmp_path)
        assert manifest is not None
        assert manifest.org == "org_1"
        assert manifest.config == Path("custom.yaml")

    def test_interpolation_from_dotenv(self, tmp_path: Path) -> None:
        (tmp_path / ".env").write_text("SLUG=env-lab\n")
        _write(tmp_path, "slug: ${SLUG}\n")
        manifest = load_deploy_manifest(tmp_path)
        assert manifest is not None and manifest.slug == "env-lab"

    def test_environment_wins_over_dotenv(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / ".env").write_text("SLUG=from-dotenv\n")
        monkeypatch.setenv("SLUG", "from-env")
        _write(tmp_path, "slug: ${SLUG}\n")
        manifest = load_deploy_manifest(tmp_path)
        assert manifest is not None and manifest.slug == "from-env"

    def test_explicit_path(self, tmp_path: Path) -> None:
        path = tmp_path / "custom-manifest.yaml"
        path.write_text("slug: my-lab\n")
        manifest = load_deploy_manifest(tmp_path, path)
        assert manifest is not None and manifest.slug == "my-lab"

    def test_unknown_key_rejected(self, tmp_path: Path) -> None:
        # extra='forbid' — a mistyped/cloud-only key fails loudly.
        _write(tmp_path, "slug: my-lab\nregion: sea\n")
        with pytest.raises(AmacrinError):
            load_deploy_manifest(tmp_path)

    def test_missing_slug_rejected(self, tmp_path: Path) -> None:
        _write(tmp_path, "org: org_1\n")
        with pytest.raises(AmacrinError):
            load_deploy_manifest(tmp_path)

    def test_non_mapping_rejected(self, tmp_path: Path) -> None:
        _write(tmp_path, "- a\n- b\n")
        with pytest.raises(AmacrinError):
            load_deploy_manifest(tmp_path)

    def test_unresolved_interpolation_raises(self, tmp_path: Path) -> None:
        _write(tmp_path, "slug: ${MISSING}\n")
        with pytest.raises(AmacrinError):
            load_deploy_manifest(tmp_path)
