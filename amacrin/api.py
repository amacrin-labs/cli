"""Amacrin API client.

Manages archives on the Amacrin cloud platform: create, list, status,
deploy, destroy.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx
import yaml

from amacrin.config import (
    AmacrinError,
    delete_state,
    read_state,
    require_account_id,
    require_archive_id,
    require_token,
    write_state,
)
from amacrin.interpolation import interpolate_yaml, parse_dotenv

DEFAULT_API_BASE = "https://api.amacrin.com/api/v1"


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _api_base(api_base: str | None) -> str:
    if api_base:
        return api_base.rstrip("/")
    return os.environ.get("AMACRIN_API", DEFAULT_API_BASE).rstrip("/")


def _handle_error(resp: httpx.Response) -> None:
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        raise AmacrinError(f"API error ({resp.status_code}): {detail}") from exc


def load_config(config_path: Path, *, project_dir: Path) -> dict[str, Any]:
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    raw = config_path.read_text()

    env: dict[str, str] = {}
    dotenv_path = project_dir / ".env"
    if dotenv_path.exists():
        env.update(parse_dotenv(dotenv_path))
    env.update(os.environ)

    resolved = interpolate_yaml(raw, env)
    return yaml.safe_load(resolved)


def login(token: str, *, project_dir: Path) -> None:
    write_state("token", token, project_dir=project_dir)


def set_account(account_id: str, *, project_dir: Path) -> None:
    write_state("account-id", account_id, project_dir=project_dir)


def create(
    *,
    config_path: Path | None,
    project_dir: Path,
    api_base: str | None = None,
) -> dict[str, Any]:
    token = require_token(project_dir=project_dir)
    account_id = require_account_id(project_dir=project_dir)

    if config_path is None:
        config_path = project_dir / "osa.yaml"

    config = load_config(config_path, project_dir=project_dir)

    payload: dict[str, Any] = {
        "account_id": account_id,
        "config": config,
    }

    base = _api_base(api_base)
    resp = httpx.post(
        f"{base}/archives",
        json=payload,
        headers=_auth_headers(token),
        timeout=30.0,
    )
    _handle_error(resp)
    data = resp.json()

    archive_id = data.get("archive", {}).get("id")
    if archive_id:
        write_state("archive-id", archive_id, project_dir=project_dir)

    return data


def list_archives(
    *,
    project_dir: Path,
    api_base: str | None = None,
) -> list[dict[str, Any]]:
    token = require_token(project_dir=project_dir)
    account_id = read_state("account-id", project_dir=project_dir)

    base = _api_base(api_base)
    url = f"{base}/archives"
    if account_id:
        url += f"?account_id={account_id}"

    resp = httpx.get(url, headers=_auth_headers(token), timeout=30.0)
    _handle_error(resp)
    return resp.json()


def status(
    *,
    project_dir: Path,
    api_base: str | None = None,
) -> dict[str, Any]:
    token = require_token(project_dir=project_dir)
    archive_id = require_archive_id(project_dir=project_dir)

    base = _api_base(api_base)
    resp = httpx.get(
        f"{base}/archives/{archive_id}/status",
        headers=_auth_headers(token),
        timeout=30.0,
    )
    _handle_error(resp)
    return resp.json()


def resolve_archive_url(
    *,
    project_dir: Path,
    api_base: str | None = None,
) -> str:
    """Return the linked archive's URL, erroring if it isn't ready.

    Resolves through `status()`, which requires a linked archive — so an
    unlinked project raises a clear `AmacrinError` here.
    """
    archive_status = status(project_dir=project_dir, api_base=api_base)
    url = archive_status.get("url")
    if not url:
        raise AmacrinError(
            "Archive has no URL yet — it may still be provisioning. "
            "Run `amacrin archive status` to check."
        )
    return url


def redeploy(
    *,
    config_path: Path | None,
    project_dir: Path,
    api_base: str | None = None,
) -> dict[str, Any]:
    token = require_token(project_dir=project_dir)
    archive_id = require_archive_id(project_dir=project_dir)

    payload: dict[str, Any] = {}
    if config_path is not None:
        config = load_config(config_path, project_dir=project_dir)
        payload["config"] = config

    base = _api_base(api_base)
    resp = httpx.post(
        f"{base}/archives/{archive_id}/deploy",
        json=payload,
        headers=_auth_headers(token),
        timeout=30.0,
    )
    _handle_error(resp)
    return resp.json()


def destroy(
    *,
    force: bool = False,
    project_dir: Path,
    api_base: str | None = None,
) -> None:
    token = require_token(project_dir=project_dir)
    archive_id = require_archive_id(project_dir=project_dir)

    base = _api_base(api_base)
    url = f"{base}/archives/{archive_id}/destroy"
    if force:
        url += "?force=true"

    resp = httpx.post(url, headers=_auth_headers(token), timeout=30.0)
    _handle_error(resp)

    delete_state("archive-id", project_dir=project_dir)
