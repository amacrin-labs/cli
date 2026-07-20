"""Tests for the server-side build path: client upload/poll + deploy handling."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from amacrin import deploy as deploy_mod
from amacrin.client import AmacrinClient
from amacrin.config import AmacrinError
from amacrin.credentials import write_credentials
from amacrin.models import Build

API = "https://api.test.com/api/v1"


def _client(
    handler: Callable[[httpx.Request], httpx.Response], cred_path: Path
) -> AmacrinClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return AmacrinClient(API, cred_path=cred_path, http=http)


@pytest.fixture
def cred_path(tmp_path: Path) -> Path:
    path = tmp_path / "credentials.json"
    write_credentials(API, access_token="at", refresh_token="rt", path=path)
    return path


def _build_body(status: str = "queued", **overrides: object) -> dict:
    body: dict = {
        "id": "build_1",
        "archive_id": "arch_1",
        "convention_slug": "proteins",
        "status": status,
        "components": [],
        "created_at": "2026-07-20T00:00:00Z",
        "updated_at": "2026-07-20T00:00:00Z",
    }
    body.update(overrides)
    return body


# ---- client.submit_build (multipart) --------------------------------------


def test_submit_build_posts_multipart(cred_path: Path) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["ctype"] = request.headers["content-type"]
        captured["body"] = request.content
        return httpx.Response(202, json={"build_id": "build_1", "status": "queued"})

    client = _client(handler, cred_path)
    submitted = client.submit_build(
        "arch_1", {"slug": "proteins", "title": "Proteins"}, b"TARBALL-BYTES"
    )

    assert submitted.build_id == "build_1"
    assert captured["url"].endswith("/archives/arch_1/builds")
    assert captured["ctype"].startswith("multipart/form-data")
    body = captured["body"]
    assert b'name="manifest"' in body
    assert b'"slug": "proteins"' in body or b'"slug":"proteins"' in body
    assert b'name="tarball"' in body
    assert b"TARBALL-BYTES" in body


def test_get_build_parses_components(cred_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_build_body(
                status="building",
                components=[
                    {
                        "kind": "hook",
                        "name": "detect",
                        "status": "building",
                        "source_ref": "build:build_1",
                    }
                ],
            ),
        )

    client = _client(handler, cred_path)
    build = client.get_build("build_1")
    assert build.status == "building"
    assert build.components[0].name == "detect"


# ---- client.wait_for_build ------------------------------------------------


def test_wait_for_build_polls_to_terminal(cred_path: Path) -> None:
    statuses = iter(["queued", "building", "published"])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_build_body(status=next(statuses)))

    client = _client(handler, cred_path)
    seen: list[str] = []
    build = client.wait_for_build(
        "build_1",
        interval=0,
        on_status=lambda b: seen.append(b.status),
        sleep=lambda _: None,
    )
    assert build.status == "published"
    assert seen == ["queued", "building", "published"]


def test_wait_for_build_times_out(cred_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_build_body(status="building"))

    client = _client(handler, cred_path)
    clock = iter([0.0, 100.0, 200.0])
    with pytest.raises(AmacrinError, match="Timed out"):
        client.wait_for_build(
            "build_1",
            timeout=50.0,
            sleep=lambda _: None,
            clock=lambda: next(clock),
        )


# ---- deploy._raise_if_failed ----------------------------------------------


def _build(status: str, **overrides: object) -> Build:
    return Build.model_validate(_build_body(status=status, **overrides))


def test_raise_if_failed_published_is_ok() -> None:
    deploy_mod._raise_if_failed(_build("published"), "Proteins")  # no raise


def test_raise_if_failed_publish_failed_surfaces_tenant_error() -> None:
    build = _build("publish_failed", error_message="instance returned 422: bad docs")
    with pytest.raises(AmacrinError) as exc:
        deploy_mod._raise_if_failed(build, "Proteins")
    assert "422" in (exc.value.cause or "")


def test_raise_if_failed_build_failed_lists_components() -> None:
    build = _build(
        "build_failed",
        components=[
            {
                "kind": "hook",
                "name": "detect",
                "status": "failed",
                "source_ref": "s",
                "error_message": "pip install failed",
            }
        ],
    )
    with pytest.raises(AmacrinError) as exc:
        deploy_mod._raise_if_failed(build, "Proteins")
    assert "pip install failed" in (exc.value.cause or "")


def test_raise_if_failed_cancelled() -> None:
    build = _build("cancelled", cancel_reason="archive destroyed")
    with pytest.raises(AmacrinError, match="cancelled"):
        deploy_mod._raise_if_failed(build, "Proteins")


# ---- deploy._cloud_deploy orchestration -----------------------------------


class _FakeUI:
    def info(self, *_: object) -> None: ...
    def success(self, *_: object) -> None: ...
    def error(self, *_: object, **__: object) -> None: ...


class _FakeArchive:
    def __init__(self, status: str) -> None:
        self.status = status


class _FakeClient:
    def __init__(self, archive_status: str, terminal: Build) -> None:
        self._archive = _FakeArchive(archive_status)
        self._terminal = terminal
        self.submitted: list[tuple[str, dict, bytes]] = []

    def archive(self, _id: str) -> _FakeArchive:
        return self._archive

    def submit_build(self, archive_id, manifest, tarball):  # noqa: ANN001
        from amacrin.models import SubmitBuild

        self.submitted.append((archive_id, manifest, tarball))
        return SubmitBuild(build_id="build_1", status="queued")

    def wait_for_build(self, _build_id, **_kw):  # noqa: ANN001
        return self._terminal


def test_cloud_deploy_happy_path(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(deploy_mod, "require_archive_id", lambda **_: "arch_1")
    monkeypatch.setattr(
        "amacrin.manifest.build_cloud_manifests",
        lambda _p: [("Proteins", {"slug": "proteins", "hooks": [{"name": "detect"}]})],
    )
    monkeypatch.setattr("amacrin.manifest.build_source_tarball", lambda _p: b"TAR")

    client = _FakeClient("running", _build("published", convention_ref="proteins"))
    result = deploy_mod._cloud_deploy(client, project_dir=tmp_path, ui=_FakeUI())

    assert client.submitted[0][0] == "arch_1"
    assert result["builds"][0]["status"] == "published"


def test_cloud_deploy_rejects_archive_not_running(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(deploy_mod, "require_archive_id", lambda **_: "arch_1")
    client = _FakeClient("deploying", _build("published"))
    with pytest.raises(AmacrinError, match="not running"):
        deploy_mod._cloud_deploy(client, project_dir=tmp_path, ui=_FakeUI())
