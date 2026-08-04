"""Tests for the cloud-build manifest + source tarball builders."""

from __future__ import annotations

import io
import subprocess
import tarfile
from pathlib import Path

import pytest

from amacrin import manifest as manifest_mod
from amacrin.config import AmacrinError
from amacrin.manifest import (
    build_cloud_manifests,
    build_source_tarball,
    runtime_version,
    slugify,
)

# ---- slugify --------------------------------------------------------------


def test_slugify_normalises_title() -> None:
    assert slugify("Protein Structures") == "protein-structures"
    assert slugify("Alloy Ductility 7xxx") == "alloy-ductility-7xxx"


def test_slugify_rejects_untitleable() -> None:
    for bad in ["", "AB", "!!", "  "]:
        with pytest.raises(AmacrinError):
            slugify(bad)


# ---- runtime_version ------------------------------------------------------


def test_runtime_version_defaults_without_pyproject(tmp_path: Path) -> None:
    assert runtime_version(tmp_path) == "3.13"


def test_runtime_version_reads_requires_python(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nrequires-python = ">=3.12"\n'
    )
    assert runtime_version(tmp_path) == "3.12"


# ---- build_source_tarball -------------------------------------------------


def test_tarball_includes_source_and_excludes_junk(tmp_path: Path) -> None:
    (tmp_path / "conv.py").write_text("x = 1\n")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: x")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "conv.pyc").write_text("junk")
    (tmp_path / "stale.pyc").write_text("junk")

    data = build_source_tarball(tmp_path)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        names = set(tar.getnames())

    assert "conv.py" in names
    assert "pyproject.toml" in names
    assert not any(n.startswith(".git") for n in names)
    assert not any("__pycache__" in n for n in names)
    assert not any(n.endswith(".pyc") for n in names)


def test_tarball_excludes_local_datastore(tmp_path: Path) -> None:
    # `.data/` is the local OSA server datastore (ingest artifacts, GBs) —
    # never part of the buildable source.
    (tmp_path / "conv.py").write_text("x = 1\n")
    ingest = tmp_path / ".data" / "data" / "ingests" / "run-1"
    ingest.mkdir(parents=True)
    (ingest / "structure.cif").write_text("atoms")

    data = build_source_tarball(tmp_path)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        names = set(tar.getnames())

    assert "conv.py" in names
    assert not any(n.startswith(".data") for n in names)


# ---- build_cloud_manifests (osa manifest via subprocess, stubbed) ---------

# A release-less `osa manifest` payload — the shape `osa manifest` emits.
_OSA_MANIFEST_DOC = {
    "manifest_version": 1,
    "conventions": [
        {
            "title": "Protein Structures",
            "description": "Curated protein structures",
            "schema": {"id": "sample-schema-1", "version": "1.0.0", "fields": []},
            "file_requirements": {"accepted_types": [".cif"], "min_count": 0},
            # New symmetric shape (as `osa manifest --exclude_none` emits it):
            # config/limits authored on the component; no `release` pre-build.
            "hooks": [
                {
                    "name": "detect",
                    "feature": {"kind": "table", "cardinality": "many", "columns": []},
                    "config": {},
                    "limits": {},
                }
            ],
            "ingester": {
                "name": "rcsb",
                "config": {},
                "limits": {},
            },
            "docs": {
                "purpose": "Answer questions about protein structures.",
                "example_questions": ["q1?", "q2?", "q3?"],
                "examples": [
                    {"question": "q1?", "query": "GET /x", "interpretation": "means x"}
                ],
            },
        }
    ],
}


def test_build_cloud_manifests_layers_cloud_fields(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        manifest_mod, "_run_osa_manifest", lambda _pd: _OSA_MANIFEST_DOC
    )

    manifests = build_cloud_manifests(tmp_path)
    assert len(manifests) == 1
    title, m = manifests[0]
    assert title == "Protein Structures"

    # amacrin's cloud-only fields, layered onto the osa body.
    assert m["slug"] == "protein-structures"
    assert m["runtime_version"] == "3.13"

    # osa body carried through untouched: docs, file reqs, release-less
    # components with config/limits authored on them (no nested release yet).
    assert m["title"] == "Protein Structures"
    assert m["docs"]["purpose"].startswith("Answer questions")
    assert m["file_requirements"]["accepted_types"] == [".cif"]
    hook = m["hooks"][0]
    assert hook["config"] == {} and "limits" in hook
    assert "release" not in hook
    assert m["ingester"]["name"] == "rcsb"
    assert "release" not in m["ingester"] and "image" not in m["ingester"]


def test_build_cloud_manifests_rejects_unknown_version(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        manifest_mod,
        "_run_osa_manifest",
        lambda _pd: {"manifest_version": 2, "conventions": []},
    )
    with pytest.raises(AmacrinError, match="version"):
        build_cloud_manifests(tmp_path)


def test_run_osa_manifest_surfaces_subprocess_failure(tmp_path, monkeypatch) -> None:
    def _fail(cmd, **_kwargs):
        return subprocess.CompletedProcess(
            cmd, 1, stdout="", stderr="deploy blocked: fewer than 3 trigger questions"
        )

    monkeypatch.setattr(manifest_mod.subprocess, "run", _fail)
    with pytest.raises(AmacrinError) as exc:
        manifest_mod._run_osa_manifest(tmp_path)
    assert "manifest" in str(exc.value).lower()
    assert exc.value.cause and "trigger questions" in exc.value.cause
