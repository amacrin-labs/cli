"""Tests for Amacrin global credential storage."""

from __future__ import annotations

import json
import stat
from pathlib import Path

from amacrin.credentials import (
    read_credentials,
    remove_credentials,
    write_credentials,
)

API_A = "https://api.amacrin.com/api/v1"
API_B = "https://staging.amacrin.com/api/v1"


class TestRoundTrip:
    """Write then read credentials back."""

    def test_write_read_round_trip(self, tmp_path: Path) -> None:
        path = tmp_path / "credentials.json"
        write_credentials(
            API_A,
            access_token="acc_1",
            refresh_token="ref_1",
            path=path,
        )
        creds = read_credentials(API_A, path=path)
        assert creds is not None
        assert creds["access_token"] == "acc_1"
        assert creds["refresh_token"] == "ref_1"

    def test_keyed_independently_by_api_base(self, tmp_path: Path) -> None:
        path = tmp_path / "credentials.json"
        write_credentials(API_A, access_token="acc_a", path=path)
        write_credentials(API_B, access_token="acc_b", path=path)

        creds_a = read_credentials(API_A, path=path)
        creds_b = read_credentials(API_B, path=path)
        assert creds_a is not None and creds_a["access_token"] == "acc_a"
        assert creds_b is not None and creds_b["access_token"] == "acc_b"

    def test_trailing_slash_normalization(self, tmp_path: Path) -> None:
        path = tmp_path / "credentials.json"
        write_credentials(API_A + "///", access_token="acc_1", path=path)
        creds = read_credentials(API_A, path=path)
        assert creds is not None
        assert creds["access_token"] == "acc_1"


class TestOverwrite:
    """Overwriting an existing entry."""

    def test_overwrite_replaces_both_tokens(self, tmp_path: Path) -> None:
        path = tmp_path / "credentials.json"
        write_credentials(
            API_A, access_token="old_acc", refresh_token="old_ref", path=path
        )
        write_credentials(
            API_A, access_token="new_acc", refresh_token="new_ref", path=path
        )
        creds = read_credentials(API_A, path=path)
        assert creds is not None
        assert creds["access_token"] == "new_acc"
        assert creds["refresh_token"] == "new_ref"

    def test_write_without_refresh_token_omits_key(self, tmp_path: Path) -> None:
        path = tmp_path / "credentials.json"
        # First store a refreshable credential.
        write_credentials(API_A, access_token="acc_1", refresh_token="ref_1", path=path)
        # Then overwrite with a non-refreshable (admin/static) token.
        write_credentials(API_A, access_token="acc_2", path=path)

        creds = read_credentials(API_A, path=path)
        assert creds is not None
        assert creds["access_token"] == "acc_2"
        assert "refresh_token" not in creds


class TestFilePermissions:
    """Credentials file must be 0600."""

    def test_permissions_are_0600_after_write(self, tmp_path: Path) -> None:
        path = tmp_path / "credentials.json"
        write_credentials(API_A, access_token="acc_1", path=path)
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode == 0o600

    def test_permissions_remain_0600_after_second_write(self, tmp_path: Path) -> None:
        path = tmp_path / "credentials.json"
        write_credentials(API_A, access_token="acc_1", path=path)
        write_credentials(API_B, access_token="acc_2", path=path)
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode == 0o600


class TestReadEdgeCases:
    """Reading missing or corrupted files."""

    def test_read_missing_file_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "credentials.json"
        assert read_credentials(API_A, path=path) is None

    def test_corrupted_json_returns_none_and_write_recovers(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "credentials.json"
        path.write_text("{not valid json")
        assert read_credentials(API_A, path=path) is None

        # A subsequent write should recover cleanly.
        write_credentials(API_A, access_token="acc_1", path=path)
        creds = read_credentials(API_A, path=path)
        assert creds is not None
        assert creds["access_token"] == "acc_1"
        # File is valid JSON again.
        assert json.loads(path.read_text())


class TestRemove:
    """Removing credentials."""

    def test_remove_returns_true_when_present(self, tmp_path: Path) -> None:
        path = tmp_path / "credentials.json"
        write_credentials(API_A, access_token="acc_a", path=path)
        write_credentials(API_B, access_token="acc_b", path=path)

        assert remove_credentials(API_A, path=path) is True
        assert read_credentials(API_A, path=path) is None
        # Other server's entry survives.
        surviving = read_credentials(API_B, path=path)
        assert surviving is not None
        assert surviving["access_token"] == "acc_b"

    def test_remove_returns_false_when_absent(self, tmp_path: Path) -> None:
        path = tmp_path / "credentials.json"
        assert remove_credentials(API_A, path=path) is False
