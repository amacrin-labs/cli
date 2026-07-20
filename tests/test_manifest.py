"""Tests for the cloud-build manifest + source tarball builders."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest
from pydantic import BaseModel

# Imported at module level so hook annotations resolve via the function's
# __globals__ (osa introspects hooks with typing.get_type_hints).
from osa.types.record import Record
from osa.types.schema import MetadataSchema

from amacrin.config import AmacrinError
from amacrin.manifest import (
    _release_less,
    build_cloud_manifests,
    build_source_tarball,
    runtime_version,
    slugify,
)


class SampleSchema(MetadataSchema):
    __schema_id__ = "sample-schema-1"

    organism: str


class _Pocket(BaseModel):
    pocket_id: str
    score: float


@pytest.fixture(autouse=True)
def _clean_registry() -> None:
    """The osa convention registry is global — reset it around each test."""
    from osa._registry import clear

    clear()
    yield
    clear()


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


# ---- _release_less --------------------------------------------------------


def test_release_less_strips_cloud_filled_fields() -> None:
    payload = {
        "hooks": [
            {
                "name": "h",
                "feature": {"kind": "table"},
                "release": {
                    "image": "img",
                    "digest": "sha256:x",
                    "source_ref": "s",
                    "config": {"k": "v"},
                    "limits": {"cpu": "0.5"},
                },
            }
        ],
        "ingester": {
            "image": "img",
            "digest": "sha256:x",
            "runner": "oci",
            "config": {},
            "schedule": {"cron": "0 0 * * *"},
        },
    }
    _release_less(payload)
    rel = payload["hooks"][0]["release"]
    assert set(rel) == {"config", "limits"}, "cloud fills image/digest/source_ref"
    ing = payload["ingester"]
    assert "image" not in ing and "digest" not in ing and "runner" not in ing
    assert ing["schedule"] == {"cron": "0 0 * * *"}  # client scheduling preserved


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


# ---- build_cloud_manifests (real convention via the osa SDK) --------------


def _register_convention(*, with_ingester: bool = False) -> None:
    from osa import Example
    from osa.authoring.convention import convention
    from osa.authoring.hook import hook

    @hook
    def detect(record: Record[SampleSchema]) -> list[_Pocket]:
        return []

    kwargs: dict = {}
    if with_ingester:

        class MyIngester:
            name = "rcsb"

            class RuntimeConfig(BaseModel):
                api_key: str = ""

            async def pull(self, **_: object):  # pragma: no cover - not run
                yield

        kwargs["ingester"] = MyIngester

    convention(
        title="Protein Structures",
        description="Curated protein structures",
        version="1.0.0",
        schema=SampleSchema,
        files={"accepted_types": [".cif"]},
        hooks=[detect],
        purpose="Answer questions about protein structures.",
        example_questions=["q1?", "q2?", "q3?"],
        examples=[Example(question="q1?", query="GET /x", interpretation="means x")],
        **kwargs,
    )


def test_build_cloud_manifests_has_osa_body_plus_build_fields(tmp_path: Path) -> None:
    _register_convention()
    manifests = build_cloud_manifests(tmp_path)
    assert len(manifests) == 1
    title, m = manifests[0]
    assert title == "Protein Structures"

    # Build-only fields the cloud consumes then strips.
    assert m["slug"] == "protein-structures"
    assert m["runtime_version"] == "3.13"

    # OSA body carried through (docs = SKILL.md source, mandatory).
    assert m["title"] == "Protein Structures"
    assert m["description"] == "Curated protein structures"
    assert m["docs"]["purpose"].startswith("Answer questions")
    assert len(m["docs"]["examples"]) == 1
    assert m["file_requirements"]["accepted_types"] == [".cif"]

    # Hook: feature present; release is release-LESS (cloud fills image/digest).
    hook = m["hooks"][0]
    assert hook["name"] == "detect"
    assert hook["feature"]["kind"] == "table"
    assert "image" not in hook["release"] and "digest" not in hook["release"]
    assert "config" in hook["release"]


def test_build_cloud_manifests_ingester_has_name_no_image(tmp_path: Path) -> None:
    _register_convention(with_ingester=True)
    _title, m = build_cloud_manifests(tmp_path)[0]
    ing = m["ingester"]
    # Build-only fan-out key present; cloud-filled fields absent.
    assert ing["name"] == "rcsb"
    assert "image" not in ing and "digest" not in ing and "runner" not in ing


def test_build_cloud_manifests_runs_docs_gate(tmp_path: Path) -> None:
    from osa import Example
    from osa.authoring.convention import convention
    from osa.authoring.hook import hook

    @hook
    def detect(record: Record[SampleSchema]) -> list[_Pocket]:
        return []

    # Only one distinct trigger question — below OSA's mandatory minimum of 3.
    # (The gate may fire at convention() authoring or at build_cloud_manifests;
    # either way the deploy is blocked before any upload.)
    with pytest.raises(Exception) as exc:
        convention(
            title="Thin Docs",
            description="d",
            version="1.0.0",
            schema=SampleSchema,
            files={"accepted_types": [".cif"]},
            hooks=[detect],
            purpose="p",
            example_questions=["only one?"],
            examples=[Example(question="only one?", query="q", interpretation="i")],
        )
        build_cloud_manifests(tmp_path)
    assert "trigger" in str(exc.value).lower() or "docs" in str(exc.value).lower()
