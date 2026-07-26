import json
from pathlib import Path
import tempfile
from typing import Any, Callable

from .budget import record_budget_metric
from .contracts import ArtifactRef, CheckResult, VerificationReport
from .run import _timestamp, load_manifest, run_dir_for, run_lock, save_manifest
from .trace import TraceEvent, append_event, read_json_nofollow


VerificationAdapter = Callable[
    [Path, Path, list[ArtifactRef]],
    list[CheckResult],
]


def _compact_failure(check: CheckResult) -> dict[str, str]:
    result = {"check": check.id, "message": check.message}
    if check.artifact is not None:
        result["artifact"] = check.artifact
    return result


def _build_report(
    checks: list[CheckResult],
    *,
    semantic: dict[str, Any] | None = None,
) -> VerificationReport:
    failed_critical = [
        check for check in checks
        if not check.passed and check.severity == "critical"
    ]
    failed_warnings = [
        check for check in checks
        if not check.passed and check.severity == "warning"
    ]
    return VerificationReport(
        accepted=not failed_critical,
        checks=checks,
        failures=[_compact_failure(check) for check in failed_critical],
        warnings=[_compact_failure(check) for check in failed_warnings],
        semantic=semantic or {
            "status": "skipped",
            "reason": "semantic verifier not configured",
        },
    )


def _write_report(run_dir: Path, report: VerificationReport) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=run_dir,
        prefix=".verification-",
        suffix=".json",
        delete=False,
    ) as temporary_file:
        json.dump(report.to_dict(), temporary_file, indent=2, sort_keys=True)
        temporary_file.write("\n")
        temporary_path = Path(temporary_file.name)
    temporary_path.replace(run_dir / "verification.json")


def _semantic_checks(payload: Any) -> list[CheckResult]:
    if not isinstance(payload, dict) or not isinstance(payload.get("checks"), list):
        raise ValueError("semantic report must contain a checks array")
    checks: list[CheckResult] = []
    allowed_severities = {"critical", "warning", "info"}
    for index, item in enumerate(payload["checks"]):
        if not isinstance(item, dict):
            raise ValueError(f"semantic check {index} must be an object")
        severity = item.get("severity")
        if severity not in allowed_severities:
            raise ValueError(
                f"semantic check {index} severity must be critical, warning, or info"
            )
        check_id = item.get("id")
        passed = item.get("passed")
        artifact = item.get("artifact")
        message = item.get("message", "")
        if not isinstance(check_id, str) or not check_id:
            raise ValueError(f"semantic check {index} id must be a non-empty string")
        if len(check_id) > 256:
            raise ValueError(f"semantic check {index} id exceeds 256 characters")
        if not isinstance(passed, bool):
            raise ValueError(f"semantic check {index} passed must be a boolean")
        if artifact is not None and not isinstance(artifact, str):
            raise ValueError(f"semantic check {index} artifact must be a string or null")
        if not isinstance(message, str):
            raise ValueError(f"semantic check {index} message must be a string")
        checks.append(CheckResult(
            id=check_id,
            passed=passed,
            severity=severity,
            artifact=artifact,
            message=message,
            source="semantic",
        ))
    return checks


def merge_semantic_report(
    vault: Path,
    run_id: str,
    payload: Any,
) -> VerificationReport | None:
    imported = _semantic_checks(payload)
    vault_root = vault.resolve()
    run_dir = run_dir_for(vault_root, run_id)
    with run_lock(vault_root, run_id):
        manifest = load_manifest(vault_root, run_id)
        if manifest["status"] != "running":
            raise ValueError(f"run is already completed: {run_id}")
        calls = manifest["metrics"]["semantic_verifier_calls"]
        limit = manifest["budget"]["max_semantic_verifier_calls"]
        if calls >= limit:
            append_event(run_dir, TraceEvent(
                ts=_timestamp(),
                kind="budget.warning",
                operation=manifest["operation"],
                run_id=run_id,
                label="semantic verifier budget exhausted",
                data={
                    "metric": "semantic_verifier_calls",
                    "used": calls,
                    "limit": limit,
                },
            ))
            return None

        verification_path = run_dir / "verification.json"
        try:
            existing = read_json_nofollow(verification_path)
        except (FileNotFoundError, json.JSONDecodeError) as error:
            raise ValueError(
                "deterministic verification must complete before semantic verification"
            ) from error
        if (
            not isinstance(existing, dict)
            or not isinstance(existing.get("checks"), list)
        ):
            raise ValueError(
                "deterministic verification must complete before semantic verification"
            )
        deterministic_and_prior = [
            CheckResult(**item) for item in existing["checks"]
        ]
        checks = deterministic_and_prior + imported
        report = _build_report(
            checks,
            semantic={"status": "completed", "checks": len(imported)},
        )
        for check in imported:
            append_event(run_dir, TraceEvent(
                ts=_timestamp(),
                kind="verify.check",
                operation=manifest["operation"],
                run_id=run_id,
                label=check.id,
                data={
                    "id": check.id,
                    "passed": check.passed,
                    "severity": check.severity,
                    "source": "semantic",
                },
            ))
        _write_report(run_dir, report)
        save_manifest(
            vault_root,
            run_id,
            record_budget_metric(manifest, "semantic_verifier_calls"),
        )
        return report


def verify_run(
    vault: Path,
    run_id: str,
    adapter: VerificationAdapter,
) -> VerificationReport:
    vault_root = vault.resolve()
    with run_lock(vault_root, run_id):
        run_dir = run_dir_for(vault_root, run_id)
        manifest = load_manifest(vault_root, run_id)
        if manifest["status"] != "running":
            raise ValueError(f"run is already completed: {run_id}")
        operation = manifest["operation"]
        append_event(run_dir, TraceEvent(
            ts=_timestamp(),
            kind="verify.start",
            operation=operation,
            run_id=run_id,
            label="verification started",
            data={},
        ))

        payload = read_json_nofollow(run_dir / "artifacts.json")
        artifacts = [ArtifactRef(**item) for item in payload["artifacts"]]
        checks = adapter(vault_root, run_dir, artifacts)

        for check in checks:
            append_event(run_dir, TraceEvent(
                ts=_timestamp(),
                kind="verify.check",
                operation=operation,
                run_id=run_id,
                label=check.id,
                data={
                    "id": check.id,
                    "passed": check.passed,
                    "severity": check.severity,
                },
            ))

        report = _build_report(checks)
        _write_report(run_dir, report)

        append_event(run_dir, TraceEvent(
            ts=_timestamp(),
            kind="verify.finish",
            operation=operation,
            run_id=run_id,
            label="verification finished",
            data={
                "accepted": report.accepted,
                "critical": len(report.failures),
                "warning": len(report.warnings),
            },
        ))
        return report
