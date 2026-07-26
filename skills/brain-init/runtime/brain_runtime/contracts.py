from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class BudgetSpec:
    max_workers: int = 4
    max_attempts: int = 3
    max_semantic_verifier_calls: int = 1

    def __post_init__(self) -> None:
        if self.max_workers < 1 or self.max_attempts < 1 or self.max_semantic_verifier_calls < 0:
            raise ValueError("budget values must be non-negative and worker/attempt limits must be >= 1")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BudgetSpec":
        return cls(**data)


@dataclass(frozen=True)
class RunSpec:
    operation: str
    mode: str
    input_refs: list[str]
    profile: str | None
    budget: BudgetSpec = field(default_factory=BudgetSpec)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.operation:
            raise ValueError("operation is required")
        if self.mode not in {"shadow"}:
            raise ValueError(f"unsupported runtime mode: {self.mode}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunSpec":
        payload = dict(data)
        payload["budget"] = BudgetSpec.from_dict(payload.get("budget", {}))
        return cls(**payload)


@dataclass(frozen=True)
class ArtifactRef:
    kind: str
    path: str
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FanoutDecision:
    mode: str
    reason: str
    slices: list[dict[str, Any]]
    max_workers: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CheckResult:
    id: str
    passed: bool
    severity: str
    artifact: str | None = None
    message: str = ""
    source: str = "deterministic"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VerificationReport:
    accepted: bool
    checks: list[CheckResult]
    failures: list[dict[str, Any]]
    warnings: list[dict[str, Any]] = field(default_factory=list)
    semantic: dict[str, Any] = field(default_factory=lambda: {
        "status": "skipped",
        "reason": "semantic verifier not configured",
    })

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RetryFeedback:
    attempt: int
    retryable: bool
    failures: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
