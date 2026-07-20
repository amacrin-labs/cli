"""Cloud-build manifest + source tarball for `POST /archives/{id}/builds`.

The Amacrin cloud builds a convention's OCI images server-side, so `amacrin
deploy` uploads a **source tarball** plus a **cloud manifest** describing the
convention — instead of building images locally and POSTing to the OSA instance
directly (the `--local` path).

The cloud manifest is OSA's `DeployConvention` body (title, description,
file_requirements, schema, docs, hooks, ingester) — reused verbatim from the
OSA SDK's payload builder so the two never drift — **minus** the release blocks
(the cloud fills `image`/`digest`/`source_ref` after building), **plus** the
build-only fields the cloud needs and then strips before calling OSA: top-level
`slug` (the convention's FR-017 supersession key) + `runtime_version` (the
Dockerfile base), and each ingester's `name`/`runner` (OSA's ingester has no such
fields). The receiving-side contract lives in the cloud repo's
`assemble_convention_body` + `Manifest` doc-comments.
"""

from __future__ import annotations

import io
import re
import tarfile
import tomllib
from pathlib import Path
from typing import Any

from amacrin.config import AmacrinError

# Source trees never need these in the build context; excluding them keeps the
# 100 MB upload lean and avoids shipping local secrets/venvs.
_TARBALL_EXCLUDES = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    "node_modules",
    ".DS_Store",
}
_TARBALL_EXCLUDE_SUFFIXES = (".pyc", ".pyo")

_SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
_DEFAULT_RUNTIME_VERSION = "3.13"


def slugify(title: str) -> str:
    """Derive a convention slug from a title (cloud FR-017 key).

    Cloud-internal grouping key — it need not byte-match OSA's own
    title-derived slug, but must satisfy the cloud's ``^[a-z][a-z0-9-]{2,63}$``.
    Raises with a clear hint if the title can't produce a valid slug.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    if not _SLUG_RE.match(slug):
        raise AmacrinError(
            f"Cannot derive a valid archive slug from convention title {title!r}",
            hint="Use a title of 3+ characters starting with a letter (a–z, 0–9, spaces)",
        )
    return slug


def runtime_version(project_dir: Path) -> str:
    """Major.minor Python version from the project's ``requires-python``.

    Interpolated into the cloud's Dockerfile ``FROM python:{v}-slim``. Falls
    back to the cloud default when unset or unparseable.
    """
    pyproject = project_dir / "pyproject.toml"
    if not pyproject.is_file():
        return _DEFAULT_RUNTIME_VERSION
    try:
        data = tomllib.loads(pyproject.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return _DEFAULT_RUNTIME_VERSION
    requires = data.get("project", {}).get("requires-python", "")
    match = re.search(r"(\d+\.\d+)", requires)
    return match.group(1) if match else _DEFAULT_RUNTIME_VERSION


def _release_less(payload: dict[str, Any]) -> None:
    """Strip the release fields the cloud fills in, in place.

    Hooks keep `release.config`/`limits` (client-authored, forwarded to OSA);
    the cloud injects `image`/`digest`/`source_ref`. The ingester keeps its
    scheduling/config; the cloud injects `image`/`digest` (no `runner`, which
    OSA rejects).
    """
    for hook in payload.get("hooks") or []:
        release = hook.get("release")
        if isinstance(release, dict):
            for k in ("image", "digest", "source_ref"):
                release.pop(k, None)
    ingester = payload.get("ingester")
    if isinstance(ingester, dict):
        for k in ("image", "digest", "runner", "source_ref"):
            ingester.pop(k, None)


def build_cloud_manifests(project_dir: Path) -> list[tuple[str, dict[str, Any]]]:
    """One `(title, cloud-manifest)` per registered convention.

    Reuses the OSA SDK's payload builder (so the OSA-body portion never drifts
    from `osa deploy`), then makes it release-less and adds the build-only
    fields. Convention modules must already be imported (registered) — the
    caller loads them via the `osa.conventions` entry points.
    """
    # Imported here so a missing/old osa-py surfaces at call time, not import.
    from osa._registry import _conventions, _hooks
    from osa.cli.deploy import (
        _check_docs_gate,
        _convention_to_payload,
        _hook_to_definition,
    )

    if not _conventions:
        raise AmacrinError(
            "No conventions registered",
            hint="Ensure the convention package is installed and exposes an "
            "`osa.conventions` entry point",
        )

    # Mandatory-docs pre-flight (mirror of OSA's server-side gate) for fast
    # local feedback before we build a tarball or hit the network. OSA remains
    # the enforcing authority (a violation is a 422 at publish time).
    _check_docs_gate(_conventions)

    hooks_by_name = {h.name: h for h in _hooks}
    manifests: list[tuple[str, dict[str, Any]]] = []
    for conv in _conventions:
        # Release-less hook definitions: real feature/columns, placeholder
        # image/digest that `_release_less` then drops.
        hook_defs = [
            _hook_to_definition(hooks_by_name[h.__name__], "", "", "")
            for h in conv.hooks
            if h.__name__ in hooks_by_name
        ]
        ingester_placeholder = ("", "") if conv.ingester_info is not None else None
        payload = _convention_to_payload(conv, hook_defs, ingester_placeholder)

        _release_less(payload)
        payload["slug"] = slugify(conv.title)
        payload["runtime_version"] = runtime_version(project_dir)
        # OSA's ingester has no `name`; the cloud needs it to fan out the build.
        if conv.ingester_info is not None and isinstance(payload.get("ingester"), dict):
            payload["ingester"]["name"] = conv.ingester_info.name

        manifests.append((conv.title, payload))
    return manifests


def build_source_tarball(project_dir: Path) -> bytes:
    """Gzip tarball of the project source for the cloud builder.

    Excludes VCS/venv/cache/build junk. Deterministic-ish (sorted walk); the
    cloud only needs the buildable source, not reproducible bytes.
    """

    def _keep(path: Path) -> bool:
        parts = set(path.relative_to(project_dir).parts)
        if parts & _TARBALL_EXCLUDES:
            return False
        return path.suffix not in _TARBALL_EXCLUDE_SUFFIXES

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path in sorted(project_dir.rglob("*")):
            if path.is_file() and _keep(path):
                tar.add(path, arcname=str(path.relative_to(project_dir)))
    return buf.getvalue()
