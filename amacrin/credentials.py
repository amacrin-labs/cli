"""Global credential storage for Amacrin CLI.

Stores and retrieves authentication tokens keyed by API base URL.
Credentials file: ~/.config/amacrin/credentials.json (0600 permissions).

This module is pure storage — no HTTP. Token refresh logic lives elsewhere.
Admin/static tokens are stored without a refresh_token, which marks the
credential as non-refreshable.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_DEFAULT_PATH = Path.home() / ".config" / "amacrin" / "credentials.json"


def _normalize(api_base: str) -> str:
    """Normalize an API base URL by stripping trailing slashes."""
    return api_base.rstrip("/")


def _read_file(path: Path) -> dict[str, Any]:
    """Read the credentials file, returning {} if missing or invalid."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _write_file(path: Path, data: dict[str, Any]) -> None:
    """Write data to the credentials file with 0600 permissions.

    Uses os.open with O_CREAT to create the file with 0600 from the start,
    avoiding a TOCTOU window where the file is briefly world-readable.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, indent=2).encode()
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, content)
    finally:
        os.close(fd)


def write_credentials(
    api_base: str,
    *,
    access_token: str,
    refresh_token: str | None = None,
    path: Path = _DEFAULT_PATH,
) -> None:
    """Store credentials for an API base URL.

    Creates the file if it doesn't exist. Overwrites the existing entry for
    the same API base. Preserves entries for other servers.

    When ``refresh_token`` is None the stored entry does NOT contain a
    ``refresh_token`` key — this marks the credential as non-refreshable
    (e.g. an admin/static token).
    """
    api_base = _normalize(api_base)
    data = _read_file(path)
    entry: dict[str, str] = {"access_token": access_token}
    if refresh_token is not None:
        entry["refresh_token"] = refresh_token
    data[api_base] = entry
    _write_file(path, data)


def read_credentials(
    api_base: str,
    *,
    path: Path = _DEFAULT_PATH,
) -> dict[str, str] | None:
    """Read credentials for an API base URL.

    Returns the entry dict (with access_token and optional refresh_token),
    or None if no entry exists or the entry lacks an access_token.
    """
    api_base = _normalize(api_base)
    data = _read_file(path)
    entry = data.get(api_base)
    if entry and "access_token" in entry:
        return entry
    return None


def remove_credentials(
    api_base: str,
    *,
    path: Path = _DEFAULT_PATH,
) -> bool:
    """Remove credentials for an API base URL.

    Returns True if credentials were removed, False if not found.
    """
    api_base = _normalize(api_base)
    data = _read_file(path)
    if api_base not in data:
        return False
    del data[api_base]
    _write_file(path, data)
    return True
