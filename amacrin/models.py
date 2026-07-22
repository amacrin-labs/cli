"""Typed wire models for the Amacrin control-plane API.

Field names and shapes mirror the server's serde structs exactly. Optional
fields are omitted from the wire when absent (`skip_serializing_if`), so they
default to None here. Enum-ish strings (statuses, roles) are kept as plain
strings — the server may grow values and the CLI should not choke on them.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

ARCHIVE_STATUSES = ("deploying", "running", "stopped", "error", "destroying")
DEPLOYMENT_STATUSES = ("pending", "in_progress", "succeeded", "failed")
PERSONAL_ORGANISATION_NAME = "Personal"

# Parent build lifecycle (`builds.status`); the success terminal is `published`.
BUILD_TERMINAL_STATUSES = ("published", "build_failed", "publish_failed", "cancelled")


class TokenResponse(BaseModel):
    """POST /auth/token and /auth/refresh response."""

    access_token: str
    expires_in: int
    token_type: str = "Bearer"
    refresh_token: str | None = None


class MeUser(BaseModel):
    id: str
    email: str
    created_at: str


class MeOrganisation(BaseModel):
    id: str
    name: str
    role: str
    created_at: str


class Me(BaseModel):
    """GET /auth/me response: the caller and their organisations."""

    user: MeUser
    organisations: list[MeOrganisation]

    def personal_organisation(self) -> MeOrganisation | None:
        for org in self.organisations:
            if org.name == PERSONAL_ORGANISATION_NAME:
                return org
        return self.organisations[0] if self.organisations else None


class Organisation(BaseModel):
    """Bare organisation object (create / get); list is enveloped."""

    id: str
    name: str
    role: str | None = None
    created_at: str


class Archive(BaseModel):
    id: str
    organisation_id: str
    name: str
    slug: str
    domain: str
    config: dict[str, Any]
    status: str
    error_message: str | None = None
    created_at: str
    updated_at: str


class Deployment(BaseModel):
    """Also the GET /archives/{id}/status response (latest deployment)."""

    id: str
    archive_id: str
    provider: str
    status: str
    url: str | None = None
    error_message: str | None = None
    started_at: str
    completed_at: str | None = None

    @property
    def finished(self) -> bool:
        return self.status in ("succeeded", "failed")


class ArchiveCreated(BaseModel):
    """202 response of POST /organisations/{org}/archives."""

    archive: Archive
    deployment: Deployment


class SubmitBuild(BaseModel):
    """202 response of POST /archives/{id}/builds."""

    build_id: str
    status: str


class ComponentBuild(BaseModel):
    """One component's build sub-status within a Build."""

    kind: str
    name: str
    status: str
    image_ref: str | None = None
    digest: str | None = None
    source_ref: str
    error_message: str | None = None


class Build(BaseModel):
    """GET /builds/{id}: parent build + per-component breakdown.

    `status` is the single lifecycle field (queued|building|publishing|
    published|build_failed|publish_failed|cancelled); publication errors (a
    tenant 422) surface in `error_message`.
    """

    id: str
    archive_id: str
    convention_slug: str
    status: str
    error_message: str | None = None
    cancelled_by: str | None = None
    cancel_reason: str | None = None
    convention_ref: str | None = None
    components: list[ComponentBuild] = []
    published_at: str | None = None
    created_at: str
    updated_at: str

    @property
    def finished(self) -> bool:
        return self.status in BUILD_TERMINAL_STATUSES
