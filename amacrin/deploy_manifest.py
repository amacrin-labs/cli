"""The Amacrin deploy manifest (``amacrin.yaml``).

Separates *how the cloud provisions an archive* — slug, org, and which server
config to ship — from *what the OSA server runs* (``osa.yaml``). This manifest is
owned by the CLI and the cloud; the OSA server never reads it, so ``osa.yaml``
stays pure, portable server config that runs identically local, self-hosted, or
in the cloud.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from amacrin.config import AmacrinError

MANIFEST_FILENAME = "amacrin.yaml"


class DeployManifest(BaseModel):
    """Declarative deploy settings read from ``amacrin.yaml``.

    ``extra='forbid'`` so a mistyped key fails loudly rather than being silently
    dropped. Slug *shape* is validated by the caller (a single validation point
    shared with the ``--slug`` flag and the interactive prompt), so the model
    stays a plain data carrier.
    """

    model_config = ConfigDict(extra="forbid")

    slug: str
    org: str | None = None
    # The server config `amacrin archive create` provisions with; deploy-time
    # convention builds don't read it.
    config: Path = Path("osa.yaml")


def load_deploy_manifest(
    project_dir: Path, path: Path | None = None
) -> DeployManifest | None:
    """Read ``amacrin.yaml`` (with ``${VAR}`` interpolation), or ``None`` if absent.

    Interpolation mirrors :func:`amacrin.config.load_config`: ``.env`` overlaid by
    the process environment (environment wins). Absence is not an error — the
    create flow falls back to ``--slug`` or an interactive prompt. A present but
    malformed manifest raises :class:`AmacrinError` with a remediation hint.
    """
    from amacrin.interpolation import interpolate_yaml, parse_dotenv

    manifest_path = path or project_dir / MANIFEST_FILENAME
    if not manifest_path.exists():
        return None

    env: dict[str, str] = {}
    dotenv_path = project_dir / ".env"
    if dotenv_path.exists():
        env.update(parse_dotenv(dotenv_path))
    env.update(os.environ)

    resolved = interpolate_yaml(manifest_path.read_text(), env)
    data = yaml.safe_load(resolved) or {}
    if not isinstance(data, dict):
        raise AmacrinError(
            f"{manifest_path.name} must be a YAML mapping",
            hint="Run `amacrin init` to scaffold the expected shape",
        )
    try:
        return DeployManifest.model_validate(data)
    except ValidationError as exc:
        raise AmacrinError(
            f"Invalid {manifest_path.name}: {_first_error(exc)}",
            hint="Expected keys: slug (required), org, config",
        ) from exc


def _first_error(exc: ValidationError) -> str:
    err = exc.errors()[0]
    loc = ".".join(str(part) for part in err["loc"]) or "(root)"
    return f"{loc}: {err['msg']}"
