from dataclasses import dataclass
from typing import Any

from .contracts import BudgetSpec, FanoutDecision


@dataclass(frozen=True)
class FanoutRequest:
    slices: list[dict[str, Any]]
    parallelizable: bool
    exceeds_one_context: bool
    high_value: bool


def advise_fanout(request: FanoutRequest, budget: BudgetSpec) -> FanoutDecision:
    n = len(request.slices)
    if n <= 1:
        return FanoutDecision("single", "one slice - nothing to parallelize", request.slices, 1)
    if not request.parallelizable:
        return FanoutDecision("single", "slices depend on shared context", request.slices, 1)
    if not request.exceeds_one_context and not request.high_value:
        return FanoutDecision(
            "single",
            "fits bounded context and fan-out cost is not justified",
            request.slices,
            1,
        )
    workers = min(n, budget.max_workers)
    return FanoutDecision(
        "fanout",
        "parallel slices plus context pressure or high value justify fan-out",
        request.slices,
        workers,
    )


def record_budget_metric(manifest: dict, metric: str, increment: int = 1) -> dict:
    allowed_metrics = {"workers", "attempts", "semantic_verifier_calls"}
    if metric not in allowed_metrics:
        raise ValueError(f"unsupported budget metric: {metric}")
    updated = dict(manifest)
    metrics = dict(manifest.get("metrics", {}))
    metrics[metric] = metrics.get(metric, 0) + increment
    updated["metrics"] = metrics
    return updated
