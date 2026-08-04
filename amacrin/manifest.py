"""Cloud-build manifest + source tarball for `POST /archives/{id}/builds`.

The Amacrin cloud builds a convention's OCI images server-side, so `amacrin
deploy` uploads a **source tarball** plus a **cloud manifest** describing the
convention — instead of building images locally and POSTing to the OSA instance
directly (the `--local` path).

The manifest is produced by running `osa manifest` in the **project's own
environment** (via `uv run`), because amacrin is typically an isolated tool that
does not have the convention package installed — so it cannot import the
convention itself. `osa manifest` emits each convention's release-less
`DeployConvention` body (the cloud fills `image`/`digest`/`source_ref` after
building). amacrin then layers on the two cloud-only fields it owns: top-level
`slug` (the convention's FR-017 supersession key) + `runtime_version` (the
Dockerfile base). The receiving-side contract lives in the cloud repo's
`assemble_convention_body` + `Manifest` doc-comments.
"""

from __future__ import annotations

import io
import json
import re
import subprocess
import tarfile
import tomllib
from pathlib import Path
from typing import Any

from amacrin.config import AmacrinError

# Source trees never need these in the build context; excluding them keeps the
# 100 MB upload lean and avoids shipping local secrets/venvs.
_TARBALL_EXCLUDES = {
    ".git",
    ".data",  # local OSA server datastore — ingest artifacts run to GBs
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


def _run_osa_manifest(project_dir: Path) -> dict[str, Any]:
    """Return the parsed `osa manifest` output, run in the project's own env.

    Uses `uv run osa manifest` when the project is a uv workspace (so the
    convention's editable install and its deps resolve), else falls back to
    `osa manifest` on PATH. amacrin is usually an isolated tool without the
    convention installed, so this subprocess is how we cross that boundary.
    """
    cmd = (
        ["uv", "run", "osa", "manifest"]
        if (project_dir / "uv.lock").is_file()
        else ["osa", "manifest"]
    )
    try:
        proc = subprocess.run(cmd, cwd=project_dir, capture_output=True, text=True)
    except FileNotFoundError as e:
        raise AmacrinError(
            f"Could not run `{cmd[0]}`",
            hint="Install uv (or put osa on PATH) in the project environment",
        ) from e
    if proc.returncode != 0:
        raise AmacrinError(
            "Failed to build the convention manifest",
            cause=(proc.stderr or proc.stdout or "").strip() or None,
            hint="Ensure the convention is installed and osa-py>=0.7.0 (which "
            "provides `osa manifest`) is in the project environment",
        )
    try:
        doc = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise AmacrinError(
            "`osa manifest` did not return valid JSON",
            cause=(proc.stdout or "")[:500].strip() or None,
        ) from e
    return doc


def build_cloud_manifests(project_dir: Path) -> list[tuple[str, dict[str, Any]]]:
    """One `(title, cloud-manifest)` per registered convention.

    Gets each convention's release-less body from `osa manifest` (run in the
    project env), then layers on the two cloud-only fields amacrin owns: `slug`
    and `runtime_version`.
    """
    doc = _run_osa_manifest(project_dir)
    if doc.get("manifest_version") != 1:
        raise AmacrinError(
            f"Unsupported osa manifest version: {doc.get('manifest_version')!r}",
            hint="Upgrade osa-py in your convention project",
        )

    version = runtime_version(project_dir)
    manifests: list[tuple[str, dict[str, Any]]] = []
    for payload in doc.get("conventions", []):
        payload["slug"] = slugify(payload["title"])
        payload["runtime_version"] = version
        manifests.append((payload["title"], payload))
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
