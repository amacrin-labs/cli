"""Tests for YAML interpolation and .env parsing."""

from __future__ import annotations

import pytest

from amacrin.interpolation import interpolate_yaml, parse_dotenv


class TestInterpolateYaml:
    def test_resolves_var_from_env_dict(self) -> None:
        raw = "client_id: ${ORCID_CLIENT_ID}"
        result = interpolate_yaml(raw, {"ORCID_CLIENT_ID": "APP-TEST123"})
        assert result == "client_id: APP-TEST123"

    def test_missing_var_raises_error(self) -> None:
        raw = "secret: ${MISSING_VAR}"
        with pytest.raises(Exception) as exc_info:
            interpolate_yaml(raw, {})
        assert "MISSING_VAR" in str(exc_info.value)

    def test_multiple_missing_vars_single_error(self) -> None:
        raw = "a: ${VAR_A}\nb: ${VAR_B}"
        with pytest.raises(Exception) as exc_info:
            interpolate_yaml(raw, {})
        msg = str(exc_info.value)
        assert "VAR_A" in msg
        assert "VAR_B" in msg

    def test_yaml_without_vars_passes_through(self) -> None:
        raw = "name: My Archive\ndomain: localhost"
        result = interpolate_yaml(raw, {"SOME_VAR": "unused"})
        assert result == raw

    def test_var_in_non_string_context(self) -> None:
        raw = "sandbox: ${USE_SANDBOX}"
        result = interpolate_yaml(raw, {"USE_SANDBOX": "true"})
        assert result == "sandbox: true"


class TestParseDotenv:
    def test_parses_key_value(self, tmp_path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("FOO=bar\nBAZ=qux\n")
        result = parse_dotenv(env_file)
        assert result == {"FOO": "bar", "BAZ": "qux"}

    def test_skips_comments_and_empty_lines(self, tmp_path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("# comment\n\nFOO=bar\n  \n# another\nBAZ=qux\n")
        result = parse_dotenv(env_file)
        assert result == {"FOO": "bar", "BAZ": "qux"}

    def test_handles_quoted_values(self, tmp_path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("FOO=\"hello world\"\nBAR='single quoted'\n")
        result = parse_dotenv(env_file)
        assert result == {"FOO": "hello world", "BAR": "single quoted"}

    def test_env_merged_with_interpolation(self, tmp_path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("CLIENT_ID=APP-FROM-DOTENV\n")

        dotenv_vars = parse_dotenv(env_file)
        env = {**dotenv_vars, "OVERRIDE": "from-env"}

        raw = "client_id: ${CLIENT_ID}\noverride: ${OVERRIDE}"
        result = interpolate_yaml(raw, env)
        assert "APP-FROM-DOTENV" in result
        assert "from-env" in result
