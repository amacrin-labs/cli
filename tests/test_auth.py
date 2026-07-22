"""Tests for the OAuth loopback login flow."""

from __future__ import annotations

import io
import threading
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from amacrin.auth import login_url, login_with_token, run_login_flow
from amacrin.cli.ui import UI
from amacrin.config import AmacrinError
from amacrin.credentials import read_credentials

API = "https://api.test.com/api/v1"


def _ui() -> UI:
    return UI.create(file=io.StringIO(), force_plain=True)


def _fake_http(response: httpx.Response | None = None) -> MagicMock:
    http = MagicMock()
    http.post.return_value = response
    return http


def _token_response(status_code: int = 200, **overrides: Any) -> httpx.Response:
    body = {"access_token": "at-1", "refresh_token": "rt-1", **overrides}
    return httpx.Response(status_code, json=body)


def _visit_callback(url: str, *, query: str) -> None:
    """Simulate the browser: hit the loopback /cb endpoint in a thread."""
    port = url.split("127.0.0.1%3A")[1].split("%2F")[0]

    def visit() -> None:
        httpx.get(f"http://127.0.0.1:{port}/cb?{query}")

    threading.Thread(target=visit, daemon=True).start()


class TestLoginUrl:
    def test_uses_literal_loopback_ip_and_encodes_redirect(self) -> None:
        url = login_url(API, 8123)
        assert url.startswith(f"{API}/auth/login?redirect_uri=")
        assert "http%3A%2F%2F127.0.0.1%3A8123%2Fcb" in url
        assert "localhost" not in url


class TestRunLoginFlow:
    def test_happy_path_stores_both_tokens(self, tmp_path):
        cred_path = tmp_path / "credentials.json"
        http = _fake_http(_token_response())

        run_login_flow(
            api_base=API,
            ui=_ui(),
            cred_path=cred_path,
            timeout=5.0,
            open_browser=lambda url: (
                _visit_callback(url, query="code=handoff-123") or True
            ),
            http=http,
        )

        creds = read_credentials(API, path=cred_path)
        assert creds == {"access_token": "at-1", "refresh_token": "rt-1"}
        http.post.assert_called_once_with(
            f"{API}/auth/token", json={"code": "handoff-123"}, timeout=30.0
        )

    def test_denied_consent_raises_clean_error(self, tmp_path):
        cred_path = tmp_path / "credentials.json"
        http = _fake_http()

        with pytest.raises(AmacrinError, match="cancelled or denied") as excinfo:
            run_login_flow(
                api_base=API,
                ui=_ui(),
                cred_path=cred_path,
                timeout=5.0,
                open_browser=lambda url: (
                    _visit_callback(url, query="error=access_denied") or True
                ),
                http=http,
            )
        assert excinfo.value.hint is not None
        assert not cred_path.exists()
        http.post.assert_not_called()

    def test_timeout_raises_with_hint(self, tmp_path):
        with pytest.raises(AmacrinError, match="timed out") as excinfo:
            run_login_flow(
                api_base=API,
                ui=_ui(),
                cred_path=tmp_path / "credentials.json",
                timeout=0.05,
                open_browser=lambda url: True,
                http=_fake_http(),
            )
        assert "amacrin login" in (excinfo.value.hint or "")

    def test_failed_exchange_raises_and_stores_nothing(self, tmp_path):
        cred_path = tmp_path / "credentials.json"
        http = _fake_http(httpx.Response(400, json={"error": "invalid_grant"}))

        with pytest.raises(AmacrinError, match="Token exchange failed"):
            run_login_flow(
                api_base=API,
                ui=_ui(),
                cred_path=cred_path,
                timeout=5.0,
                open_browser=lambda url: (
                    _visit_callback(url, query="code=stale") or True
                ),
                http=http,
            )
        assert not cred_path.exists()

    def test_browser_open_failure_still_waits_for_callback(self, tmp_path):
        cred_path = tmp_path / "credentials.json"
        http = _fake_http(_token_response())
        captured: dict[str, str] = {}

        def failing_open(url: str) -> bool:
            captured["url"] = url
            _visit_callback(url, query="code=abc")
            raise RuntimeError("no browser available")

        run_login_flow(
            api_base=API,
            ui=_ui(),
            cred_path=cred_path,
            timeout=5.0,
            open_browser=failing_open,
            http=http,
        )
        assert read_credentials(API, path=cred_path) is not None
        assert captured["url"].startswith(API)


class TestLoginWithToken:
    def test_stores_access_only_no_refresh_key(self, tmp_path):
        cred_path = tmp_path / "credentials.json"
        login_with_token("admin-tok", api_base=API, cred_path=cred_path)
        creds = read_credentials(API, path=cred_path)
        assert creds == {"access_token": "admin-tok"}
        assert "refresh_token" not in (creds or {})
