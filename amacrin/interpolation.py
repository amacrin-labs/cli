"""YAML ${VAR} interpolation and .env file parsing.

Resolves ${VAR} references in raw YAML text against a provided environment
dictionary. Fails hard with a clear error listing all unresolved variables.
"""

from __future__ import annotations

import re
from pathlib import Path

_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")


class ConfigInterpolationError(Exception):
    """Raised when YAML interpolation fails due to unresolved variables."""


def interpolate_yaml(raw_yaml: str, env: dict[str, str]) -> str:
    refs = _VAR_PATTERN.findall(raw_yaml)
    if not refs:
        return raw_yaml

    unresolved = [var for var in refs if var not in env]
    if unresolved:
        vars_list = ", ".join(sorted(set(unresolved)))
        raise ConfigInterpolationError(
            f"Unresolved variable(s) in config: {vars_list}. "
            "Set them as environment variables or in your .env file."
        )

    return _VAR_PATTERN.sub(lambda m: env[m.group(1)], raw_yaml)


def parse_dotenv(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        result[key] = value
    return result
