"""OAuth loopback sign-in for the Amacrin CLI.

Runs a one-shot HTTP listener on 127.0.0.1 (literal loopback IP — the server's
redirect allowlist rejects hostnames), sends the browser to the platform's
login endpoint, receives the handoff code on `/cb`, and exchanges it for an
access + refresh token pair which is persisted to the global credential store.
"""

from __future__ import annotations

import threading
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

import httpx

from amacrin.config import AmacrinError
from amacrin.credentials import _DEFAULT_PATH, write_credentials

_LOGIN_TIMEOUT = 300.0
_CALLBACK_PATH = "/cb"

_PAGE = """<!doctype html>
<html>
  <head><meta charset="utf-8"><title>Amacrin CLI</title></head>
  <body style="font-family: system-ui, sans-serif; margin: 4rem auto; max-width: 30rem;">
    <h1 style="font-size: 1.2rem;">{headline}</h1>
    <p>{detail}</p>
  </body>
</html>
"""

_SUCCESS_PAGE = _PAGE.format(
    headline="Signed in to Amacrin",
    detail="You can close this tab and return to your terminal.",
)
_DENIED_PAGE = _PAGE.format(
    headline="Sign-in was not completed",
    detail="You can close this tab. Run <code>amacrin login</code> to try again.",
)


@dataclass
class _CallbackResult:
    """What the loopback listener received on /cb."""

    code: str | None = None
    error: str | None = None


class _LoopbackListener:
    """One-shot HTTP server on 127.0.0.1:<ephemeral> awaiting the OAuth callback."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self.result: _CallbackResult | None = None
        listener = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                if parsed.path != _CALLBACK_PATH:
                    self.send_error(404)
                    return
                params = parse_qs(parsed.query)
                code = params.get("code", [None])[0]
                error = params.get("error", [None])[0]
                body = _SUCCESS_PAGE if code else _DENIED_PAGE
                payload = body.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                if listener.result is None:
                    listener.result = _CallbackResult(code=code, error=error)
                    listener._event.set()

            def log_message(self, format: str, *args: Any) -> None:
                pass  # keep server chatter out of the CLI output

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    def __enter__(self) -> _LoopbackListener:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._server.shutdown()
        self._server.server_close()

    def wait(self, timeout: float) -> _CallbackResult | None:
        if self._event.wait(timeout):
            return self.result
        return None


def login_url(api_base: str, port: int) -> str:
    """The browser URL that starts the OIDC flow for a loopback listener."""
    redirect_uri = quote(f"http://127.0.0.1:{port}{_CALLBACK_PATH}", safe="")
    return f"{api_base}/auth/login?redirect_uri={redirect_uri}"


def _exchange_code(api_base: str, code: str, http: Any) -> dict[str, Any]:
    try:
        resp = http.post(f"{api_base}/auth/token", json={"code": code}, timeout=30.0)
    except httpx.HTTPError as exc:
        raise AmacrinError(
            f"Could not reach {api_base}",
            hint="Check your network connection and AMACRIN_API",
        ) from exc
    if resp.status_code != 200:
        raise AmacrinError(
            f"Token exchange failed ({resp.status_code})",
            cause=resp.text[:500],
            hint="Run `amacrin login` to try again",
        )
    data: dict[str, Any] = resp.json()
    if "access_token" not in data or "refresh_token" not in data:
        raise AmacrinError(
            "Token exchange returned an unexpected response",
            cause=str(data)[:500],
            hint="Run `amacrin login` to try again",
        )
    return data


def run_login_flow(
    *,
    api_base: str,
    ui: Any,
    cred_path: Path = _DEFAULT_PATH,
    timeout: float = _LOGIN_TIMEOUT,
    open_browser: Callable[[str], object] = webbrowser.open,
    http: Any = httpx,
) -> None:
    """Browser sign-in: loopback listener → consent → code exchange → store tokens.

    `open_browser` and `http` are injectable for tests.
    """
    with _LoopbackListener() as listener:
        url = login_url(api_base, listener.port)
        opened = False
        try:
            opened = bool(open_browser(url))
        except Exception:
            opened = False
        if opened:
            ui.info("Opening your browser to sign in…")
            ui.detail(url)
        else:
            ui.info(f"Open this URL in your browser to sign in:\n  {url}")

        with ui.task("Waiting for browser sign-in") as task:
            result = listener.wait(timeout)
            if result is None:
                task.fail("timed out — run `amacrin login` to try again")
                raise AmacrinError(
                    "Login timed out",
                    hint="Run `amacrin login` to try again",
                )
            if result.code is None:
                task.fail("sign-in was cancelled or denied")
                raise AmacrinError(
                    "Sign-in was cancelled or denied",
                    cause=result.error,
                    hint="Run `amacrin login` to try again",
                )
            task.detail("exchanging code")
            tokens = _exchange_code(api_base, result.code, http)
            task.done()

    write_credentials(
        api_base,
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        path=cred_path,
    )


def login_with_token(
    token: str,
    *,
    api_base: str,
    cred_path: Path = _DEFAULT_PATH,
) -> None:
    """Break-glass admin path: store a static bearer with no refresh token."""
    write_credentials(api_base, access_token=token, refresh_token=None, path=cred_path)
