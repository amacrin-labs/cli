"""Project scaffolding for ``amacrin init``.

Renders the three project files (``osa.yaml``, ``amacrin.yaml``,
``.env.example``) as strings (pure, unit-testable) and writes them without
clobbering existing files. ``osa.yaml`` is pure OSA-server config;
``amacrin.yaml`` is the deploy manifest that owns the archive slug.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from amacrin.deploy_manifest import MANIFEST_FILENAME

ENV_EXAMPLE_FILENAME = ".env.example"
OSA_CONFIG_FILENAME = "osa.yaml"


@dataclass(frozen=True)
class ScaffoldedFile:
    """One file `write_project_files` considered: written, or skipped (existed)."""

    path: Path
    written: bool


def _yaml_str(value: str) -> str:
    """A YAML double-quoted scalar with proper escaping.

    JSON string syntax is a subset of YAML's double-quoted style, so
    ``json.dumps`` gives a scalar that round-trips through ``yaml.safe_load``
    even when the value contains quotes or backslashes.
    """
    return json.dumps(value)


def render_osa_yaml(name: str) -> str:
    """The OSA server config — no slug or cloud settings (those live in the
    deploy manifest). ``domain``/``base_url`` come from the environment per
    deployment (localhost locally, ``{slug}.amacr.in`` in the cloud)."""
    return (
        f"name: {_yaml_str(name)}\n"
        "\n"
        "auth:\n"
        '  base_role: "DEPOSITOR"\n'
        "  # providers:\n"
        "  #   orcid:\n"
        "  #     client_id: ${ORCID_CLIENT_ID}\n"
        "  #     client_secret: ${ORCID_CLIENT_SECRET}\n"
        "  # admins:\n"
        "  #   orcid:\n"
        '  #     - "0000-0002-1234-5678"\n'
    )


def render_amacrin_yaml(slug: str, org: str | None = None) -> str:
    """The deploy manifest — how Amacrin provisions this archive. The OSA server
    never reads this file."""
    lines = [
        "# Amacrin deploy manifest — how the cloud provisions this archive.",
        "# The OSA server never reads this; its own config is osa.yaml.",
        "",
        f'slug: "{slug}"        # your archive is served at {slug}.amacr.in',
        f"config: {OSA_CONFIG_FILENAME}      # server config used by `amacrin archive create`",
    ]
    if org:
        lines.append(f"org: {_yaml_str(org)}")
    else:
        lines.append('# org: "<org-id>"   # optional; omit to use your Personal org')
    return "\n".join(lines) + "\n"


def render_env_example() -> str:
    return (
        "# Secrets referenced by osa.yaml via ${VAR}. Copy to .env and fill in.\n"
        "# ORCID_CLIENT_ID=APP-XXXXXXXX\n"
        "# ORCID_CLIENT_SECRET=your-secret\n"
    )


def write_project_files(
    project_dir: Path,
    *,
    name: str,
    slug: str,
    org: str | None = None,
    force: bool = False,
) -> list[ScaffoldedFile]:
    """Scaffold ``osa.yaml`` + ``amacrin.yaml`` + ``.env.example`` into
    *project_dir*. Existing files are left untouched unless ``force``."""
    contents = {
        OSA_CONFIG_FILENAME: render_osa_yaml(name),
        MANIFEST_FILENAME: render_amacrin_yaml(slug, org),
        ENV_EXAMPLE_FILENAME: render_env_example(),
    }
    return [
        _write_if_absent(project_dir / filename, content, force=force)
        for filename, content in contents.items()
    ]


def save_manifest(
    project_dir: Path, *, slug: str, org: str | None = None, force: bool = False
) -> ScaffoldedFile:
    """Write just ``amacrin.yaml`` — used by ``archive create`` to persist a
    slug the user entered interactively."""
    return _write_if_absent(
        project_dir / MANIFEST_FILENAME, render_amacrin_yaml(slug, org), force=force
    )


def _write_if_absent(path: Path, content: str, *, force: bool) -> ScaffoldedFile:
    if path.exists() and not force:
        return ScaffoldedFile(path, written=False)
    path.write_text(content)
    return ScaffoldedFile(path, written=True)
