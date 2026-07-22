"""Project-local state and config loading for the Amacrin CLI.

Reads and writes state files in `.amacrin/` within the project directory.
Project-local state is just the archive ID — user-scoped auth lives in the
global credential store (`~/.config/amacrin/`), not here.

Also loads the OSA config (`osa.yaml`) with ${VAR} interpolation from `.env`
and the environment.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


class AmacrinError(Exception):
    """Raised when an Amacrin operation fails.

    Carries optional context for the CLI error renderer: a `cause` (captured
    detail such as an API response body), a `hint` (remediation the user can
    act on), and the API `request_id` when one was returned.
    """

    def __init__(
        self,
        message: str,
        *,
        cause: str | None = None,
        hint: str | None = None,
        request_id: str | None = None,
        status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.cause = cause
        self.hint = hint
        self.request_id = request_id
        self.status = status


def state_path(name: str, *, project_dir: Path) -> Path:
    return project_dir / ".amacrin" / name


def read_state(name: str, *, project_dir: Path) -> str | None:
    path = state_path(name, project_dir=project_dir)
    if not path.exists():
        return None
    return path.read_text().strip()


def write_state(name: str, value: str, *, project_dir: Path) -> Path:
    path = state_path(name, project_dir=project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)
    return path


def delete_state(name: str, *, project_dir: Path) -> None:
    path = state_path(name, project_dir=project_dir)
    path.unlink(missing_ok=True)


def require_archive_id(*, project_dir: Path) -> str:
    archive_id = read_state("archive-id", project_dir=project_dir)
    if archive_id:
        return archive_id
    raise AmacrinError(
        "No archive linked. Run `amacrin archive create` or "
        "`amacrin link --archive <id>` first."
    )


def load_config(
    config_path: Path | None = None, *, project_dir: Path
) -> dict[str, Any]:
    """Read and interpolate the OSA config (`osa.yaml`).

    Resolves ${VAR} references against `.env` (in `project_dir`) and the
    process environment, with the environment taking precedence. Defaults to
    `project_dir/osa.yaml` when no path is given.
    """
    # Imported lazily to avoid a circular import: interpolation imports
    # AmacrinError from this module for its error type.
    from amacrin.interpolation import interpolate_yaml, parse_dotenv

    if config_path is None:
        config_path = project_dir / "osa.yaml"

    if not config_path.exists():
        raise AmacrinError(
            f"No config file found at {config_path}",
            hint="Create an osa.yaml or pass --config",
        )

    raw = config_path.read_text()

    env: dict[str, str] = {}
    dotenv_path = project_dir / ".env"
    if dotenv_path.exists():
        env.update(parse_dotenv(dotenv_path))
    env.update(os.environ)

    resolved = interpolate_yaml(raw, env)
    return yaml.safe_load(resolved)
