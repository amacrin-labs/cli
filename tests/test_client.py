"""Tests for AmacrinClient: refresh rotation, error mapping, polling."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from amacrin.client import DEFAULT_API_BASE, AmacrinClient, resolve_api_base
from amacrin.config import AmacrinError
from amacrin.credentials import read_credentials, write_credentials

API = "https://api.test.com/api/v1"


def _me_body(email: str = "rory@rory.bio") -> dict:
    return {
        "user": {"id": "user_1", "email": email, "created_at": "2026-07-01T00:00:00Z"},
        "organisations": [
            {
                "id": "org_1",
                "name": "Personal",
                "role": "owner",
                "created_at": "2026-07-01T00:00:00Z",
            }
        ],
    }


def _archive_body(**overrides: object) -> dict:
    body: dict = {
        "id": "arch_1",
        "organisation_id": "org_1",
        "name": "Cultivarium",
        "slug": "cultivarium",
        "domain": "cultivarium.amacr.in",
        "config": {},
        "status": "deploying",
        "created_at": "2026-07-01T00:00:00Z",
        "updated_at": "2026-07-01T00:00:00Z",
    }
    body.update(overrides)
    return body


def _deployment_body(status: str = "pending", **overrides: object) -> dict:
    body: dict = {
        "id": "deploy_1",
        "archive_id": "arch_1",
        "provider": "aws_eks",
        "status": status,
        "started_at": "2026-07-01T00:00:00Z",
    }
    body.update(overrides)
    return body


def _client(
    handler: Callable[[httpx.Request], httpx.Response], cred_path: Path
) -> AmacrinClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return AmacrinClient(API, cred_path=cred_path, http=http)


@pytest.fixture
def cred_path(tmp_path: Path) -> Path:
    path = tmp_path / "credentials.json"
    write_credentials(API, access_token="old-at", refresh_token="old-rt", path=path)
    return path


class TestResolveApiBase:
    def test_chain(self, monkeypatch):
        monkeypatch.delenv("AMACRIN_API", raising=False)
        assert resolve_api_base("https://x.test/api/v1/") == "https://x.test/api/v1"
        assert resolve_api_base() == DEFAULT_API_BASE
        monkeypatch.setenv("AMACRIN_API", "https://env.test/api/v1")
        assert resolve_api_base() == "https://env.test/api/v1"
        assert resolve_api_base("https://arg.test") == "https://arg.test"


class TestRefreshRotation:
    def test_expired_then_refresh_then_retry_once(self, cred_path, monkeypatch):
        monkeypatch.delenv("AMACRIN_TOKEN", raising=False)
        calls: list[tuple[str, str | None]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            auth = request.headers.get("Authorization")
            calls.append((request.url.path, auth))
            if request.url.path.endswith("/auth/refresh"):
                body = json.loads(request.content)
                # the old refresh token, exactly once, never the new one
                assert body == {"refresh_token": "old-rt"}
                return httpx.Response(
                    200, json={"access_token": "new-at", "refresh_token": "new-rt"}
                )
            if auth == "Bearer old-at":
                return httpx.Response(401, json={"reason": "expired"})
            # by the time the retry lands, the rotated pair must already be
            # on disk — losing it would burn the session
            stored = read_credentials(API, path=cred_path)
            assert stored == {"access_token": "new-at", "refresh_token": "new-rt"}
            assert auth == "Bearer new-at"
            return httpx.Response(200, json=_me_body())

        client = _client(handler, cred_path)
        result = client.me()

        assert result.user.email == "rory@rory.bio"
        assert result.personal_organisation().id == "org_1"
        refresh_calls = [c for c in calls if c[0].endswith("/auth/refresh")]
        assert len(refresh_calls) == 1

    def test_refresh_rejected_raises_session_expired(self, cred_path, monkeypatch):
        monkeypatch.delenv("AMACRIN_TOKEN", raising=False)

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/auth/refresh"):
                return httpx.Response(401, json={"request_id": "req-9"})
            return httpx.Response(401, json={"reason": "expired"})

        client = _client(handler, cred_path)
        with pytest.raises(AmacrinError, match="Session expired") as excinfo:
            client.me()
        assert "amacrin login" in (excinfo.value.hint or "")

    def test_admin_token_without_refresh_cannot_rotate(self, tmp_path, monkeypatch):
        monkeypatch.delenv("AMACRIN_TOKEN", raising=False)
        cred_path = tmp_path / "credentials.json"
        write_credentials(API, access_token="admin-at", path=cred_path)
        refresh_attempted = False

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal refresh_attempted
            if request.url.path.endswith("/auth/refresh"):
                refresh_attempted = True
            return httpx.Response(401, json={"reason": "expired"})

        client = _client(handler, cred_path)
        with pytest.raises(AmacrinError, match="Session expired"):
            client.me()
        assert not refresh_attempted

    def test_env_token_never_refreshes(self, cred_path, monkeypatch):
        monkeypatch.setenv("AMACRIN_TOKEN", "env-at")
        seen_tokens: list[str | None] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_tokens.append(request.headers.get("Authorization"))
            return httpx.Response(401, json={"reason": "expired"})

        client = _client(handler, cred_path)
        with pytest.raises(AmacrinError, match="Token expired"):
            client.me()
        assert seen_tokens == ["Bearer env-at"]

    def test_invalid_and_missing_reasons_fail_immediately(self, cred_path, monkeypatch):
        monkeypatch.delenv("AMACRIN_TOKEN", raising=False)
        for reason, message in (
            ("invalid", "Invalid token"),
            ("missing", "Not authenticated"),
        ):

            def handler(request: httpx.Request) -> httpx.Response:
                assert not request.url.path.endswith("/auth/refresh")
                return httpx.Response(401, json={"reason": reason})  # noqa: B023

            client = _client(handler, cred_path)
            with pytest.raises(AmacrinError, match=message) as excinfo:
                client.me()
            assert "amacrin login" in (excinfo.value.hint or "")

    def test_not_authenticated_without_credentials(self, tmp_path, monkeypatch):
        monkeypatch.delenv("AMACRIN_TOKEN", raising=False)
        client = _client(
            lambda request: httpx.Response(200), tmp_path / "credentials.json"
        )
        with pytest.raises(AmacrinError, match="Not authenticated") as excinfo:
            client.me()
        assert "amacrin login" in (excinfo.value.hint or "")


class TestFreshAccessToken:
    def test_returns_post_refresh_token(self, cred_path, monkeypatch):
        monkeypatch.delenv("AMACRIN_TOKEN", raising=False)

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/auth/refresh"):
                return httpx.Response(
                    200, json={"access_token": "new-at", "refresh_token": "new-rt"}
                )
            if request.headers.get("Authorization") == "Bearer old-at":
                return httpx.Response(401, json={"reason": "expired"})
            return httpx.Response(200, json=_me_body())

        client = _client(handler, cred_path)
        assert client.fresh_access_token() == "new-at"


class TestArchiveCreate:
    def test_org_scoped_payload_and_202(self, cred_path, monkeypatch):
        monkeypatch.delenv("AMACRIN_TOKEN", raising=False)
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["body"] = json.loads(request.content)
            return httpx.Response(
                202,
                json={"archive": _archive_body(), "deployment": _deployment_body()},
            )

        client = _client(handler, cred_path)
        config = {"name": "Cultivarium", "slug": "cultivarium", "auth": {}}
        result = client.create_archive("org_1", config)

        assert captured["path"] == "/api/v1/organisations/org_1/archives"
        assert captured["body"] == {"config": config}
        assert result.archive.id == "arch_1"
        assert result.deployment.status == "pending"

    def test_slug_conflict_409_is_clean(self, cred_path, monkeypatch):
        monkeypatch.delenv("AMACRIN_TOKEN", raising=False)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                409,
                json={
                    "error": "conflict",
                    "message": "slug already exists",
                    "request_id": "req-42",
                },
            )

        client = _client(handler, cred_path)
        with pytest.raises(AmacrinError, match="'cultivarium' is taken") as excinfo:
            client.create_archive("org_1", {"slug": "cultivarium"})
        assert excinfo.value.hint is not None
        assert excinfo.value.request_id == "req-42"


class TestOrganisations:
    def test_list_unwraps_envelope(self, cred_path, monkeypatch):
        monkeypatch.delenv("AMACRIN_TOKEN", raising=False)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "organisations": [
                        {
                            "id": "org_1",
                            "name": "Personal",
                            "role": "owner",
                            "created_at": "2026-07-01T00:00:00Z",
                        }
                    ]
                },
            )

        orgs = _client(handler, cred_path).list_organisations()
        assert [o.id for o in orgs] == ["org_1"]
        assert orgs[0].role == "owner"

    def test_create_returns_bare_object(self, cred_path, monkeypatch):
        monkeypatch.delenv("AMACRIN_TOKEN", raising=False)

        def handler(request: httpx.Request) -> httpx.Response:
            assert json.loads(request.content) == {"name": "Lab"}
            return httpx.Response(
                201,
                json={
                    "id": "org_2",
                    "name": "Lab",
                    "role": "owner",
                    "created_at": "2026-07-01T00:00:00Z",
                },
            )

        org = _client(handler, cred_path).create_organisation("Lab")
        assert org.id == "org_2"


class TestErrorMapping:
    def test_api_error_carries_message_and_request_id(self, cred_path, monkeypatch):
        monkeypatch.delenv("AMACRIN_TOKEN", raising=False)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                500,
                json={
                    "error": "internal",
                    "message": "something broke",
                    "request_id": "req-7",
                },
            )

        client = _client(handler, cred_path)
        with pytest.raises(AmacrinError, match="something broke") as excinfo:
            client.list_archives()
        assert excinfo.value.request_id == "req-7"
        assert "req-7" in (excinfo.value.cause or "")
        assert excinfo.value.status == 500

    def test_transport_error_is_wrapped(self, cred_path, monkeypatch):
        monkeypatch.delenv("AMACRIN_TOKEN", raising=False)

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom")

        client = _client(handler, cred_path)
        with pytest.raises(AmacrinError, match="Could not reach") as excinfo:
            client.list_archives()
        assert "network" in (excinfo.value.hint or "")


class TestLogout:
    def test_revokes_refresh_token(self, cred_path, monkeypatch):
        monkeypatch.delenv("AMACRIN_TOKEN", raising=False)
        revoked: list[dict[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path.endswith("/auth/logout")
            revoked.append(json.loads(request.content))
            return httpx.Response(204)

        client = _client(handler, cred_path)
        client.logout()
        assert revoked == [{"refresh_token": "old-rt"}]

    def test_no_refresh_token_skips_call(self, tmp_path, monkeypatch):
        monkeypatch.delenv("AMACRIN_TOKEN", raising=False)
        cred_path = tmp_path / "credentials.json"
        write_credentials(API, access_token="admin-at", path=cred_path)

        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("no request expected")

        _client(handler, cred_path).logout()


class TestWaitForDeployment:
    def test_polls_to_succeeded(self, cred_path, monkeypatch):
        monkeypatch.delenv("AMACRIN_TOKEN", raising=False)
        bodies = iter(
            [
                _deployment_body("pending"),
                _deployment_body("in_progress"),
                _deployment_body("succeeded", url="https://cultivarium.amacr.in"),
            ]
        )

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/v1/archives/arch_1/status"
            return httpx.Response(200, json=next(bodies))

        client = _client(handler, cred_path)
        seen: list[str] = []
        sleeps: list[float] = []
        result = client.wait_for_deployment(
            "arch_1",
            interval=3.0,
            on_status=lambda d: seen.append(d.status),
            sleep=sleeps.append,
            clock=lambda: 0.0,
        )
        assert result.status == "succeeded"
        assert result.url == "https://cultivarium.amacr.in"
        assert seen == ["pending", "in_progress", "succeeded"]
        assert sleeps == [3.0, 3.0]

    def test_failed_deployment_raises_with_error_message(self, cred_path, monkeypatch):
        monkeypatch.delenv("AMACRIN_TOKEN", raising=False)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json=_deployment_body("failed", error_message="quota exceeded")
            )

        client = _client(handler, cred_path)
        with pytest.raises(AmacrinError, match="Deployment failed") as excinfo:
            client.wait_for_deployment("arch_1", sleep=lambda s: None)
        assert "quota exceeded" in (excinfo.value.cause or "")

    def test_timeout_raises_with_hint(self, cred_path, monkeypatch):
        monkeypatch.delenv("AMACRIN_TOKEN", raising=False)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_deployment_body("in_progress"))

        ticks = iter([0.0, 10.0, 20.0])
        client = _client(handler, cred_path)
        with pytest.raises(AmacrinError, match="Timed out") as excinfo:
            client.wait_for_deployment(
                "arch_1",
                timeout=15.0,
                sleep=lambda s: None,
                clock=lambda: next(ticks),
            )
        assert "archive status" in (excinfo.value.hint or "")
