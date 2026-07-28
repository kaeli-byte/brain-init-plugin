"""Shared deterministic verification helpers for runtime adapters.

These helpers are operation-agnostic: frontmatter parsing, wikilink extraction,
vault confinement, and check-result construction. Operation-specific enums and
workflow checks stay in their own adapters.
"""
from pathlib import Path
import re
from typing import Any

import yaml

from ..contracts import CheckResult


WIKILINK = re.compile(r"\[\[([^|\]#]+)")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def read_frontmatter(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("missing YAML frontmatter")
    try:
        closing = next(
            index for index, line in enumerate(lines[1:], start=1)
            if line.strip() == "---"
        )
    except StopIteration as error:
        raise ValueError("unterminated YAML frontmatter") from error
    loaded = yaml.safe_load("\n".join(lines[1:closing]))
    if not isinstance(loaded, dict):
        raise ValueError("frontmatter must be a YAML mapping")
    return loaded, "\n".join(lines[closing + 1:])


def check_result(
    check_id: str,
    passed: bool,
    *,
    artifact: str | None = None,
    message: str = "",
    severity: str = "critical",
) -> CheckResult:
    return CheckResult(
        id=check_id,
        passed=passed,
        severity=severity,
        artifact=artifact,
        message="" if passed else message,
    )


def missing_fields(data: dict[str, Any], required: set[str]) -> list[str]:
    return sorted(field for field in required if field not in data)


def wikilinks(value: Any, prefix: str) -> list[str]:
    if isinstance(value, str):
        return [
            target for target in WIKILINK.findall(value)
            if target.startswith(prefix)
        ]
    if isinstance(value, dict):
        links: list[str] = []
        for child in value.values():
            links.extend(wikilinks(child, prefix))
        return links
    if isinstance(value, list):
        links = []
        for child in value:
            links.extend(wikilinks(child, prefix))
        return links
    return []


def normalized_text(text: str) -> str:
    return " ".join(text.split())


def confined_path(vault: Path, path_text: str) -> Path | None:
    requested = Path(path_text)
    if requested.is_absolute():
        return None
    resolved = (vault / requested).resolve()
    try:
        resolved.relative_to(vault)
    except ValueError:
        return None
    return resolved
