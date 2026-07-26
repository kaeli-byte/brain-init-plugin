import json
from pathlib import Path
import tempfile
from typing import Callable

from .contracts import ArtifactRef, CheckResult, VerificationReport
from .run import _timestamp, load_manifest, run_dir_for
from .trace import TraceEvent, append_event


VerificationAdapter = Callable[
    [Path, Path, list[ArtifactRef]],
    list[CheckResult],
]


def _compact_failure(check: CheckResult) -> dict[str, str]:
    result = {"check": check.id, "message": check.message}
    if check.artifact is not None:
        result["artifact"] = check.artifact
    return result


def verify_run(
    vault: Path,
    run_id: str,
    adapter: VerificationAdapter,
) -> VerificationReport:
    vault_root = vault.resolve()
    run_dir = run_dir_for(vault_root, run_id)
    manifest = load_manifest(vault_root, run_id)
    operation = manifest["operation"]
    append_event(run_dir, TraceEvent(
        ts=_timestamp(),
        kind="verify.start",
        operation=operation,
        run_id=run_id,
        label="verification started",
        data={},
    ))

    with (run_dir / "artifacts.json").open(encoding="utf-8") as artifacts_file:
        payload = json.load(artifacts_file)
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

    failed_critical = [
        check for check in checks
        if not check.passed and check.severity == "critical"
    ]
    failed_warnings = [
        check for check in checks
        if not check.passed and check.severity == "warning"
    ]
    report = VerificationReport(
        accepted=not failed_critical,
        checks=checks,
        failures=[_compact_failure(check) for check in failed_critical],
        warnings=[_compact_failure(check) for check in failed_warnings],
    )
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

    append_event(run_dir, TraceEvent(
        ts=_timestamp(),
        kind="verify.finish",
        operation=operation,
        run_id=run_id,
        label="verification finished",
        data={
            "accepted": report.accepted,
            "critical": len(failed_critical),
            "warning": len(failed_warnings),
        },
    ))
    return report
