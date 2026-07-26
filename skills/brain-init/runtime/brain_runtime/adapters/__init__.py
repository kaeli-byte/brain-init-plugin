"""Operation-specific deterministic verification adapters."""
from pathlib import Path
from typing import Callable

from ..contracts import ArtifactRef, CheckResult
from .capture import capture_checks


VerificationAdapter = Callable[
    [Path, Path, list[ArtifactRef]],
    list[CheckResult],
]

_VERIFICATION_ADAPTERS: dict[str, VerificationAdapter] = {
    "capture": capture_checks,
}


def verification_adapter_for(operation: str) -> VerificationAdapter:
    try:
        return _VERIFICATION_ADAPTERS[operation]
    except KeyError as error:
        raise ValueError(
            f"unsupported verification operation: {operation}"
        ) from error
