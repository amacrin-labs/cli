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
