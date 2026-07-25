"""Unit tests for project scaffolding (amacrin init file rendering + writing)."""

from __future__ import annotations

from pathlib import Path

import yaml

from amacrin.scaffold import (
    render_amacrin_yaml,
    render_osa_yaml,
    save_manifest,
    write_project_files,
)


class TestRender:
    def test_osa_yaml_has_name_and_no_slug(self) -> None:
        data = yaml.safe_load(render_osa_yaml("My Lab"))
        assert data["name"] == "My Lab"
        assert "slug" not in data  # server config is slug-free

    def test_amacrin_yaml_carries_slug_and_config(self) -> None:
        data = yaml.safe_load(render_amacrin_yaml("my-lab"))
        assert data["slug"] == "my-lab"
        assert data["config"] == "osa.yaml"

    def test_amacrin_yaml_with_org(self) -> None:
        data = yaml.safe_load(render_amacrin_yaml("my-lab", "org_1"))
        assert data["org"] == "org_1"

    def test_amacrin_yaml_omits_org_when_absent(self) -> None:
        data = yaml.safe_load(render_amacrin_yaml("my-lab"))
        assert "org" not in data  # only a comment, not a real key


class TestWriteProjectFiles:
    def test_writes_three_files(self, tmp_path: Path) -> None:
        results = write_project_files(tmp_path, name="My Lab", slug="my-lab")
        written = {r.path.name for r in results if r.written}
        assert written == {"osa.yaml", "amacrin.yaml", ".env.example"}
        for name in written:
            assert (tmp_path / name).exists()

    def test_does_not_clobber_existing(self, tmp_path: Path) -> None:
        (tmp_path / "osa.yaml").write_text("keep me")
        results = write_project_files(tmp_path, name="X", slug="x")
        osa = next(r for r in results if r.path.name == "osa.yaml")
        assert osa.written is False
        assert (tmp_path / "osa.yaml").read_text() == "keep me"
        # the other files are still scaffolded
        assert (tmp_path / "amacrin.yaml").exists()

    def test_force_overwrites(self, tmp_path: Path) -> None:
        (tmp_path / "osa.yaml").write_text("old")
        write_project_files(tmp_path, name="New Name", slug="x", force=True)
        assert "New Name" in (tmp_path / "osa.yaml").read_text()


class TestSaveManifest:
    def test_writes_manifest(self, tmp_path: Path) -> None:
        result = save_manifest(tmp_path, slug="my-lab", org="org_1")
        assert result.written
        data = yaml.safe_load((tmp_path / "amacrin.yaml").read_text())
        assert data["slug"] == "my-lab"
        assert data["org"] == "org_1"

    def test_does_not_clobber(self, tmp_path: Path) -> None:
        (tmp_path / "amacrin.yaml").write_text("existing")
        result = save_manifest(tmp_path, slug="my-lab")
        assert result.written is False
        assert (tmp_path / "amacrin.yaml").read_text() == "existing"
