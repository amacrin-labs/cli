"""Unit tests for archive-slug derivation and validation."""

from __future__ import annotations

import pytest

from amacrin.config import AmacrinError
from amacrin.slug import slugify, validate_archive_slug


class TestSlugify:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("My Lab Archive", "my-lab-archive"),
            ("Cultivarium", "cultivarium"),
            ("  Trim  Me  ", "trim-me"),
            ("Weird!!!Chars", "weird-chars"),
            ("under_scores", "under-scores"),
            ("123 Numbers", "123-numbers"),
            ("Already-Hyphenated", "already-hyphenated"),
        ],
    )
    def test_slugify(self, name: str, expected: str) -> None:
        assert slugify(name) == expected

    def test_unsluggable_returns_empty(self) -> None:
        # All punctuation → nothing usable; caller validates and reprompts.
        assert slugify("!!!") == ""

    def test_truncates_to_63(self) -> None:
        result = slugify("a" * 80)
        assert len(result) == 63
        assert validate_archive_slug(result) == result  # still a valid label


class TestValidateArchiveSlug:
    @pytest.mark.parametrize(
        "slug",
        ["my-lab", "cultivarium", "a", "1lab", "lab1", "a-b-c", "0", "x" * 63],
    )
    def test_valid(self, slug: str) -> None:
        assert validate_archive_slug(slug) == slug

    @pytest.mark.parametrize(
        "slug",
        ["", "-lab", "lab-", "My-Lab", "under_score", "a b", "x" * 64, "café"],
    )
    def test_invalid_raises(self, slug: str) -> None:
        with pytest.raises(AmacrinError):
            validate_archive_slug(slug)
