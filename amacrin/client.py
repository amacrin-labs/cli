"""Amacrin control-plane API client.

One httpx client, bearer auth from the global credential store, and
transparent access-token refresh on `401 reason: expired`.

Refresh tokens rotate on every use and reuse is treated as theft, so the new
pair is persisted to disk *before* the original request is retried and the old
refresh token is never replayed.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from amacrin.config import AmacrinError
from amacrin.credentials import _DEFAULT_PATH, read_credentials, write_credentials
from amacrin.models import (
    Archive,
    ArchiveCreated,
    Deployment,
    Me,
    Organisation,
)

DEFAULT_API_BASE = "https://api.amacrin.com/api/v1"


def resolve_api_base(api_base: str | None = None) -> str:
    """Explicit arg → AMACRIN_API env → default; no trailing slash."""
    base = api_base or os.environ.get("AMACRIN_API") or DEFAULT_API_BASE
    return base.rstrip("/")


class AmacrinClient:
    """Typed access to the Amacrin API with automatic token refresh."""

    def __init__(
        self,
        api_base: str | None = None,
        *,
        cred_path: Path = _DEFAULT_PATH,
        http: httpx.Client | None = None,
    ) -> None:
        self.api_base = resolve_api_base(api_base)
        self._cred_path = cred_path
        self._http = http or httpx.Client(timeout=30.0)

    # -- token handling -----------------------------------------------------

    def _access_token(self) -> str:
        env_token = os.environ.get("AMACRIN_TOKEN")
        if env_token:
            return env_token
        creds = read_credentials(self.api_base, path=self._cred_path)
        if creds:
            return creds["access_token"]
        raise AmacrinError("Not authenticated", hint="Run `amacrin login`")

    def _refresh(self) -> None:
        """Rotate the token pair; persists the new pair before returning.

        Raises AmacrinError if there is no refresh token (env/admin token) or
        the refresh is rejected — in both cases the fix is to log in again.
        """
        if os.environ.get("AMACRIN_TOKEN"):
            raise AmacrinError(
                "Token expired",
                hint="AMACRIN_TOKEN is set — provide a fresh token",
            )
        creds = read_credentials(self.api_base, path=self._cred_path)
        refresh_token = (creds or {}).get("refresh_token")
        if not refresh_token:
            raise AmacrinError(
                "Session expired",
                hint="Run `amacrin login` to sign in again",
            )
        try:
            resp = self._http.post(
                f"{self.api_base}/auth/refresh",
                json={"refresh_token": refresh_token},
            )
        except httpx.HTTPError as exc:
            raise self._transport_error(exc) from exc
        if resp.status_code != 200:
            raise AmacrinError(
                "Session expired",
                cause=_request_id_cause(_safe_json(resp)),
                hint="Run `amacrin login` to sign in again",
            )
        data = resp.json()
        # Persist the rotated pair immediately — the old refresh token is now
        # burned; losing the new one here would log the user out.
        write_credentials(
            self.api_base,
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            path=self._cred_path,
        )

    def fresh_access_token(self) -> str:
        """A verified-fresh access token, for handing to osa's build/register.

        Probes `/auth/me`, which transparently refreshes on expiry, then
        returns whatever token is now current.
        """
        self.me()
        return self._access_token()

    # -- request core -------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any | None = None,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        resp = self._send(method, path, json=json, params=params)
        if resp.status_code == 401:
            body = _safe_json(resp)
            if body.get("reason") == "expired":
                self._refresh()
                resp = self._send(method, path, json=json, params=params)
            else:
                raise AmacrinError(
                    "Not authenticated"
                    if body.get("reason") == "missing"
                    else "Invalid token",
                    cause=_request_id_cause(body),
                    hint="Run `amacrin login`",
                )
        if resp.is_error:
            raise self._api_error(resp)
        return resp

    def _send(
        self,
        method: str,
        path: str,
        *,
        json: Any | None = None,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self._access_token()}"}
        try:
            return self._http.request(
                method,
                f"{self.api_base}{path}",
                json=json,
                params=params,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise self._transport_error(exc) from exc

    def _transport_error(self, exc: httpx.HTTPError) -> AmacrinError:
        return AmacrinError(
            f"Could not reach {self.api_base}",
            cause=str(exc),
            hint="Check your network connection and AMACRIN_API",
        )

    def _api_error(self, resp: httpx.Response) -> AmacrinError:
        body = _safe_json(resp)
        message = body.get("message") or f"API error ({resp.status_code})"
        return AmacrinError(
            message,
            cause=_request_id_cause(body) or resp.text[:500],
            request_id=body.get("request_id"),
            status=resp.status_code,
        )

    # -- typed endpoints ----------------------------------------------------

    def me(self) -> Me:
        return Me.model_validate(self._request("GET", "/auth/me").json())

    def logout(self) -> None:
        """Revoke the stored refresh token server-side, if there is one."""
        creds = read_credentials(self.api_base, path=self._cred_path)
        refresh_token = (creds or {}).get("refresh_token")
        if not refresh_token:
            return
        try:
            self._http.post(
                f"{self.api_base}/auth/logout",
                json={"refresh_token": refresh_token},
            )
        except httpx.HTTPError:
            pass  # local credential removal still proceeds; revocation is best-effort

    def list_organisations(self) -> list[Organisation]:
        # GET /organisations is enveloped: {"organisations": [...]}
        body = self._request("GET", "/organisations").json()
        return [Organisation.model_validate(o) for o in body["organisations"]]

    def create_organisation(self, name: str) -> Organisation:
        resp = self._request("POST", "/organisations", json={"name": name})
        return Organisation.model_validate(resp.json())

    def create_archive(self, org_id: str, config: dict[str, Any]) -> ArchiveCreated:
        """POST /organisations/{org}/archives → 202 {archive, deployment}."""
        resp = self._send_checked_create(org_id, config)
        return ArchiveCreated.model_validate(resp.json())

    def _send_checked_create(
        self, org_id: str, config: dict[str, Any]
    ) -> httpx.Response:
        try:
            return self._request(
                "POST",
                f"/organisations/{org_id}/archives",
                json={"config": config},
            )
        except AmacrinError as exc:
            slug = config.get("slug")
            if exc.status == 409 and slug:
                raise AmacrinError(
                    f"'{slug}' is taken — pick another slug",
                    cause=exc.cause,
                    hint="Change `slug` in osa.yaml and re-run",
                    request_id=exc.request_id,
                ) from None
            raise

    def list_archives(self) -> list[Archive]:
        body = self._request("GET", "/archives").json()
        return [Archive.model_validate(a) for a in body]

    def archive(self, archive_id: str) -> Archive:
        resp = self._request("GET", f"/archives/{archive_id}")
        return Archive.model_validate(resp.json())

    def archive_status(self, archive_id: str) -> Deployment:
        """The archive's latest deployment (status: pending|in_progress|succeeded|failed)."""
        resp = self._request("GET", f"/archives/{archive_id}/status")
        return Deployment.model_validate(resp.json())

    def redeploy(self, archive_id: str) -> Deployment:
        resp = self._request(
            "POST", f"/archives/{archive_id}/deploy", json={"config": {}}
        )
        return Deployment.model_validate(resp.json())

    def destroy_archive(self, archive_id: str, *, force: bool = False) -> Archive:
        params = {"force": "true"} if force else None
        resp = self._request("POST", f"/archives/{archive_id}/destroy", params=params)
        return Archive.model_validate(resp.json())

    def wait_for_deployment(
        self,
        archive_id: str,
        *,
        timeout: float = 1800.0,
        interval: float = 5.0,
        on_status: Callable[[Deployment], None] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> Deployment:
        """Poll the latest deployment until it succeeds.

        Raises AmacrinError on deployment failure or timeout.
        """
        deadline = clock() + timeout
        while True:
            deployment = self.archive_status(archive_id)
            if on_status is not None:
                on_status(deployment)
            if deployment.status == "succeeded":
                return deployment
            if deployment.status == "failed":
                raise AmacrinError(
                    "Deployment failed",
                    cause=deployment.error_message,
                    hint="Fix the reported problem and run `amacrin archive create` again",
                )
            if clock() >= deadline:
                raise AmacrinError(
                    "Timed out waiting for the archive to start",
                    hint="Run `amacrin archive status` to keep watching",
                )
            sleep(interval)


def _safe_json(resp: httpx.Response) -> dict[str, Any]:
    try:
        data = resp.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _request_id_cause(body: dict[str, Any]) -> str | None:
    request_id = body.get("request_id")
    return f"request_id: {request_id}" if request_id else None
