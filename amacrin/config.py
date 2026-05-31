"""Project-local state for Amacrin CLI.

Reads and writes state files in `.amacrin/` within the project directory.
State includes admin token, account ID, and archive ID.
"""

from __future__ import annotations

import os
from pathlib import Path


class AmacrinError(Exception):
    """Raised when an Amacrin operation fails."""


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


def require_token(*, project_dir: Path) -> str:
    token = os.environ.get("AMACRIN_TOKEN")
    if token:
        return token
    token = read_state("token", project_dir=project_dir)
    if token:
        return token
    raise AmacrinError(
        "No Amacrin token found. Set AMACRIN_TOKEN env var or run: amacrin login --token <token>"
    )


def require_archive_id(*, project_dir: Path) -> str:
    archive_id = read_state("archive-id", project_dir=project_dir)
    if archive_id:
        return archive_id
    raise AmacrinError(
        "No archive linked. Run `amacrin archive create` or "
        "`amacrin link --archive <id>` first."
    )


def require_account_id(*, project_dir: Path) -> str:
    account_id = read_state("account-id", project_dir=project_dir)
    if account_id:
        return account_id
    raise AmacrinError(
        "No account ID found. Run `amacrin set-account --id <account-id>` first."
    )
