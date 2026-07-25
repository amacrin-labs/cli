"""Archive slug — the globally-unique DNS label that drives ``{slug}.amacr.in``.

Distinct from the *convention* slug in :mod:`amacrin.manifest` (a cloud grouping
key, FR-017, with its own rules). An archive slug is a DNS label: lowercase
alphanumerics and hyphens, no leading/trailing hyphen, 1–63 characters.
"""

from __future__ import annotations

import re

from amacrin.config import AmacrinError

# DNS label: a–z / 0–9 / hyphen, not starting or ending with a hyphen, ≤63 chars.
ARCHIVE_SLUG_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def slugify(name: str) -> str:
    """Best-effort archive slug from a display name.

    Lowercases, maps runs of non-alphanumerics to a single hyphen, trims, and
    bounds to 63 chars. May return ``""`` for an un-sluggable name (e.g. all
    punctuation) — callers validate before use rather than trusting the shape.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:63].rstrip("-")


def validate_archive_slug(slug: str) -> str:
    """Return ``slug`` if it is a valid archive subdomain label, else raise."""
    if not ARCHIVE_SLUG_PATTERN.match(slug):
        raise AmacrinError(
            f"{slug!r} is not a valid archive slug",
            hint=(
                "Use 1–63 lowercase letters, digits, or hyphens with no leading "
                "or trailing hyphen — it becomes <slug>.amacr.in"
            ),
        )
    return slug
