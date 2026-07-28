import json
from pathlib import Path
import re
from typing import Any

import yaml

from ..contracts import ArtifactRef, CheckResult
from ..run import sha256_file
from ..trace import read_events, read_json_nofollow
from .common import (
    SHA256,
    WIKILINK,
    check_result,
    confined_path,
    missing_fields,
    normalized_text,
    read_frontmatter,
    wikilinks,
)


CLAIM_REQUIRED = {
    "claim_id", "claim_text", "confidence", "status", "source_evidence",
    "first_seen", "last_verified", "last_reviewed",
}
CLAIM_CONFIDENCE = {"high", "medium", "low"}
CLAIM_STATUS = {"confirmed", "plausible", "disputed", "debunked", "superseded"}

SOURCE_REQUIRED = {
    "source_id", "raw_path", "source_type", "publisher", "date_published",
    "date_ingested", "last_reviewed", "reliability", "materiality", "key_claims",
}
SOURCE_TYPE = {
    "10k-filing", "annual-report", "patent", "industry-report", "tech-paper",
    "white-paper", "earnings-call", "press-release",
}
SOURCE_RELIABILITY = {
    "audited", "peer-reviewed", "expert-opinion", "industry-consensus",
    "company-claim", "speculative", "unverified",
}
MATERIALITY = {"high", "medium", "low"}
COMPANY_REQUIRED = {"company_id", "legal_name", "last_reviewed"}

RECOGNIZED_LONG_PROFILES = {"annual-report-v1", "sec-filing-v1"}


def _evidence_checks(
    vault: Path,
    artifact_path: str,
    evidence: Any,
    declared: set[str],
) -> list[CheckResult]:
    checks: list[CheckResult] = []
    links = wikilinks(evidence, "src-")
    checks.append(check_result(
        "claim.source_evidence",
        bool(links),
        artifact=artifact_path,
        message="claim must include at least one source evidence link",
    ))
    source_paths = [f"wiki/sources/{target}.md" for target in links]
    sources_exist = bool(source_paths) and all(
        path_text in declared
        and (vault / path_text).is_file()
        for path_text in source_paths
    )
    checks.append(check_result(
        "claim.source_page_exists",
        sources_exist,
        artifact=artifact_path,
        message="linked source page is missing or undeclared",
    ))

    critical_messages: list[str] = []
    converted_unavailable = False
    entries = evidence if isinstance(evidence, list) else [evidence]
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("passage"):
            continue
        entry_links = wikilinks(entry.get("source"), "src-")
        if not entry_links:
            critical_messages.append("structured evidence source link is missing")
            continue
        source_relative = f"wiki/sources/{entry_links[0]}.md"
        if source_relative not in declared:
            critical_messages.append("linked source page is missing or undeclared")
            continue
        try:
            source_data, _ = read_frontmatter(vault / source_relative)
        except (OSError, ValueError, yaml.YAMLError):
            critical_messages.append("linked source frontmatter is unavailable")
            continue
        raw_path = source_data.get("raw_path")
        raw_file = confined_path(vault, raw_path) if isinstance(raw_path, str) else None
        converted = raw_file.with_suffix(".md") if raw_file is not None else None
        if converted is None or not converted.is_file():
            converted_unavailable = True
            continue
        if normalized_text(str(entry["passage"])) not in normalized_text(
            converted.read_text(encoding="utf-8")
        ):
            critical_messages.append(
                "evidence passage not found in converted markdown"
            )
    locator_passed = not critical_messages and not converted_unavailable
    if critical_messages:
        locator_message = "; ".join(dict.fromkeys(critical_messages))
        locator_severity = "critical"
    elif converted_unavailable:
        locator_message = (
            "converted markdown unavailable; locator not mechanically checked"
        )
        locator_severity = "warning"
    else:
        locator_message = ""
        locator_severity = "critical"
    checks.append(check_result(
        "evidence.locator_resolves",
        locator_passed,
        artifact=artifact_path,
        message=locator_message,
        severity=locator_severity,
    ))
    return checks


def _claim_checks(
    vault: Path,
    artifact: ArtifactRef,
    data: dict[str, Any],
    declared: set[str],
) -> list[CheckResult]:
    missing = missing_fields(data, CLAIM_REQUIRED)
    checks = [
        check_result(
            "claim.required_fields",
            not missing,
            artifact=artifact.path,
            message=f"missing required fields: {', '.join(missing)}",
        ),
        check_result(
            "claim.confidence_enum",
            data.get("confidence") in CLAIM_CONFIDENCE,
            artifact=artifact.path,
            message="invalid claim confidence",
        ),
        check_result(
            "claim.status_enum",
            data.get("status") in CLAIM_STATUS,
            artifact=artifact.path,
            message="invalid claim status",
        ),
    ]
    checks.extend(_evidence_checks(
        vault,
        artifact.path,
        data.get("source_evidence"),
        declared,
    ))
    return checks


def _source_checks(
    vault: Path,
    artifact: ArtifactRef,
    data: dict[str, Any],
    body: str,
    declared: set[str],
) -> list[CheckResult]:
    missing = missing_fields(data, SOURCE_REQUIRED)
    enums_valid = (
        data.get("source_type") in SOURCE_TYPE
        and data.get("reliability") in SOURCE_RELIABILITY
        and data.get("materiality") in MATERIALITY
    )
    company_links = wikilinks(body, "company-")
    backlink_valid = bool(company_links)
    for company_target in company_links:
        company_relative = f"wiki/companies/{company_target}.md"
        if company_relative not in declared or not (vault / company_relative).is_file():
            backlink_valid = False
            continue
        try:
            _, company_body = read_frontmatter(vault / company_relative)
        except (OSError, ValueError, yaml.YAMLError):
            backlink_valid = False
            continue
        if f"[[{Path(artifact.path).stem}]]" not in company_body:
            backlink_valid = False
    return [
        check_result(
            "source.required_fields",
            not missing,
            artifact=artifact.path,
            message=f"missing required fields: {', '.join(missing)}",
        ),
        check_result(
            "source.enum_values",
            enums_valid,
            artifact=artifact.path,
            message="invalid source enum value",
        ),
        check_result(
            "source.company_link",
            bool(company_links),
            artifact=artifact.path,
            message="source page must link at least one company",
        ),
        check_result(
            "company.source_backlink",
            backlink_valid,
            artifact=artifact.path,
            message="linked company must contain a source backlink",
        ),
    ]


def _workflow_checks(vault: Path, run_dir: Path) -> list[CheckResult]:
    manifest = read_json_nofollow(run_dir / "manifest.json")
    metadata = manifest.get("metadata") or {}
    inputs = manifest.get("inputs") or []
    source_type = metadata.get("source_type")
    plan_path = run_dir / "plan.json"
    plan: dict[str, Any] = {}
    if plan_path.exists() or plan_path.is_symlink():
        try:
            loaded_plan = read_json_nofollow(plan_path)
            if isinstance(loaded_plan, dict):
                plan = loaded_plan
        except (OSError, json.JSONDecodeError):
            plan = {}
    exceeds_one_context = metadata.get(
        "exceeds_one_context",
        plan.get("exceeds_one_context"),
    )
    normalized_inputs = [
        re.sub(r"[^a-z0-9]+", "-", item.get("path", "").lower()).strip("-")
        for item in inputs
    ]
    annual_report_input = (
        source_type in {
            "annual-report", "10k-filing", "10-k-filing", "sec-filing",
        }
        or any(
            "annual-report" in path
            or "sec-filing" in path
            or re.search(r"(?:^|-)10-?k(?:-|$)", path)
            for path in normalized_inputs
        )
    )
    long_capture = annual_report_input and exceeds_one_context is not False
    profile_valid = not long_capture or manifest.get("profile") in RECOGNIZED_LONG_PROFILES
    plan_valid = not long_capture or plan_path.is_file()

    events = read_events(run_dir)
    qmd_events = [event for event in events if event.kind == "workflow.qmd"]
    qmd_valid = bool(qmd_events) and qmd_events[-1].data.get("passed") is True
    log_valid = any(
        event.kind == "workflow.log" and event.data.get("passed") is True
        for event in events
    )
    return [
        check_result(
            "capture.profile_recognized",
            profile_valid,
            message="long annual-report/10-K capture requires a recognized profile",
        ),
        check_result(
            "capture.section_plan",
            plan_valid,
            message="section plan was not recorded",
            severity="warning",
        ),
        check_result(
            "workflow.qmd_refresh",
            qmd_valid,
            message="qmd refresh unavailable, absent, or failed",
            severity="warning",
        ),
        check_result(
            "workflow.log_completed",
            log_valid,
            message="finalized capture log completion was not recorded",
        ),
    ]


def _claim_id_from_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    links = wikilinks(value, "claim-")
    return links[0] if links else None


def _staged_reconciliation_checks(
    vault: Path,
    run_dir: Path,
    artifacts: list[ArtifactRef],
    declared: set[str],
) -> list[CheckResult] | None:
    """Staged-capture contract when the run reconciles through a record.

    Triggered by a declared reconciliation artifact or by run metadata that
    advertises staged reconcile. Returns None for legacy captures so the old
    claim-count contract applies instead.
    """
    records = [artifact for artifact in artifacts if artifact.kind == "reconciliation"]
    manifest = read_json_nofollow(run_dir / "manifest.json")
    metadata = manifest.get("metadata") or {}
    staged = bool(records) or metadata.get("reconcile") == "staged"
    if not staged:
        return None
    checks: list[CheckResult] = []
    checks.append(check_result(
        "capture.reconciliation_declared",
        len(records) == 1,
        message=f"staged capture must declare exactly one reconciliation record, found {len(records)}",
    ))
    if len(records) != 1:
        return checks

    record_artifact = records[0]
    record_path = confined_path(vault, record_artifact.path)
    data: dict[str, Any] = {}
    if record_path is not None and record_path.is_file():
        try:
            data, _ = read_frontmatter(record_path)
        except (OSError, ValueError, yaml.YAMLError):
            data = {}
    record_parse_ok = bool(data)
    checks.append(check_result(
        "capture.reconciliation_declared",
        record_parse_ok,
        artifact=record_artifact.path,
        message="declared reconciliation record is missing or unparsable",
    ))
    if not record_parse_ok:
        return checks

    checks.append(check_result(
        "capture.reconciliation_origin",
        data.get("origin") == "capture",
        artifact=record_artifact.path,
        message="staged capture reconciliation record must have origin: capture",
    ))

    status = data.get("status")
    checks.append(check_result(
        "capture.reconcile_status",
        status in {"complete", "staged"},
        artifact=record_artifact.path,
        message=f"capture finished with reconciliation status: {status}",
    ))
    checks.append(check_result(
        "capture.review_pending",
        status != "pending_review",
        artifact=record_artifact.path,
        message="capture finished with candidates pending human review",
    ))

    candidates = data.get("candidates")
    candidates = candidates if isinstance(candidates, list) else []
    count = len(candidates)
    checks.append(check_result(
        "capture.candidate_count_min",
        count >= 2,
        artifact=record_artifact.path,
        message="staged capture requires at least two candidates",
    ))
    checks.append(check_result(
        "capture.candidate_count_max",
        count <= 6,
        artifact=record_artifact.path,
        message="staged capture declares more than six candidates",
        severity="warning",
    ))

    record_source_links = wikilinks(data.get("source"), "src-")
    record_source_id = record_source_links[0] if record_source_links else ""
    source_artifacts = [artifact for artifact in artifacts if artifact.kind == "source"]
    source_data: dict[str, Any] = {}
    if source_artifacts:
        source_path = confined_path(vault, source_artifacts[0].path)
        if source_path is not None and source_path.is_file():
            try:
                source_data, _ = read_frontmatter(source_path)
            except (OSError, ValueError, yaml.YAMLError):
                source_data = {}
    checks.append(check_result(
        "capture.reconciliation_source_match",
        bool(record_source_id)
        and source_data.get("source_id") == record_source_id,
        artifact=record_artifact.path,
        message="reconciliation record source link must match the declared source page",
    ))

    record_stem = Path(record_artifact.path).stem
    source_recon_links = wikilinks(source_data.get("reconciliation"), "reconcile-")
    checks.append(check_result(
        "capture.reconciliation_link",
        record_stem in source_recon_links,
        artifact=source_artifacts[0].path if source_artifacts else record_artifact.path,
        message="source page reconciliation link must reference the declared record",
    ))

    applied_results: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if candidate.get("action_state") != "applied":
            continue
        result_id = _claim_id_from_value(candidate.get("result_claim"))
        if result_id is not None:
            applied_results.add(result_id)
        result_declared = (
            result_id is not None
            and f"wiki/claims/{result_id}.md" in declared
        )
        checks.append(check_result(
            "capture.result_declared",
            result_declared,
            artifact=record_artifact.path,
            message=f"applied result claim wiki/claims/{result_id}.md is not declared",
        ))

    key_claims = source_data.get("key_claims")
    key_claim_ids: set[str] = set()
    if isinstance(key_claims, list):
        for entry in key_claims:
            claim_id = _claim_id_from_value(entry) if not isinstance(entry, str) else (
                entry if entry.startswith("claim-") else _claim_id_from_value(entry)
            )
            if claim_id:
                key_claim_ids.add(claim_id)
    elif isinstance(key_claims, str):
        key_claim_ids = set(wikilinks(key_claims, "claim-"))
    checks.append(check_result(
        "capture.key_claims_match_results",
        key_claim_ids == applied_results,
        artifact=source_artifacts[0].path if source_artifacts else record_artifact.path,
        message=(
            f"source key_claims {sorted(key_claim_ids)} must equal the applied "
            f"result claim set {sorted(applied_results)}"
        ),
    ))
    return checks


def capture_checks(
    vault: Path,
    run_dir: Path,
    artifacts: list[ArtifactRef],
) -> list[CheckResult]:
    vault_root = vault.resolve()
    declared = {artifact.path for artifact in artifacts}
    checks: list[CheckResult] = []
    kinds = {"claim": 0, "source": 0, "company": 0}
    seen_claim_ids: set[str] = set()
    seen_source_ids: set[str] = set()

    for artifact in artifacts:
        if artifact.kind in kinds:
            kinds[artifact.kind] += 1
        path = confined_path(vault_root, artifact.path)
        exists = path is not None and path.is_file()
        digest_valid = (
            exists
            and bool(SHA256.fullmatch(artifact.sha256))
            and sha256_file(path) == artifact.sha256
        )
        checks.extend([
            check_result(
                "artifact.exists",
                exists,
                artifact=artifact.path,
                message="declared artifact does not exist within the vault",
            ),
            check_result(
                "artifact.sha256",
                digest_valid,
                artifact=artifact.path,
                message=(
                    "artifact SHA-256 must be 64 lowercase hexadecimal "
                    "characters and match the current file bytes"
                ),
            ),
        ])
        if not exists or not artifact.path.startswith("wiki/"):
            continue
        try:
            data, body = read_frontmatter(path)
        except (OSError, ValueError, yaml.YAMLError) as error:
            checks.append(check_result(
                "frontmatter.valid_yaml",
                False,
                artifact=artifact.path,
                message=str(error),
            ))
            continue
        checks.append(check_result(
            "frontmatter.valid_yaml",
            True,
            artifact=artifact.path,
        ))
        if artifact.kind == "claim":
            claim_id = data.get("claim_id")
            if isinstance(claim_id, str) and claim_id:
                duplicate = claim_id in seen_claim_ids
                checks.append(check_result(
                    "claim.id_unique",
                    not duplicate,
                    artifact=artifact.path,
                    message=f"duplicate claim_id: {claim_id}",
                ))
                seen_claim_ids.add(claim_id)
            checks.extend(_claim_checks(vault_root, artifact, data, declared))
        elif artifact.kind == "source":
            source_id = data.get("source_id")
            if isinstance(source_id, str) and source_id:
                duplicate = source_id in seen_source_ids
                checks.append(check_result(
                    "source.id_unique",
                    not duplicate,
                    artifact=artifact.path,
                    message=f"duplicate source_id: {source_id}",
                ))
                seen_source_ids.add(source_id)
            checks.extend(_source_checks(
                vault_root,
                artifact,
                data,
                body,
                declared,
            ))
        elif artifact.kind == "company":
            missing = missing_fields(data, COMPANY_REQUIRED)
            checks.append(check_result(
                "company.required_fields",
                not missing,
                artifact=artifact.path,
                message=f"missing required fields: {', '.join(missing)}",
            ))
        elif artifact.path == "wiki/log.md":
            # The append-only root log is completed by the capture workflow.
            # workflow.log_completed is its authoritative integrity signal.
            continue
        else:
            checks.append(check_result(
                "page.last_reviewed",
                "last_reviewed" in data,
                artifact=artifact.path,
                message="wiki page must include last_reviewed",
            ))

    staged_checks = _staged_reconciliation_checks(vault_root, run_dir, artifacts, declared)
    if staged_checks is not None:
        checks.extend(staged_checks)
    else:
        checks.extend([
            check_result(
                "capture.claim_count_min",
                kinds["claim"] >= 2,
                message="capture must declare at least two claim pages",
            ),
            check_result(
                "capture.claim_count_max",
                kinds["claim"] <= 6,
                message="capture declares more than six claims",
                severity="warning",
            ),
        ])
    checks.extend([
        check_result(
            "capture.source_count",
            kinds["source"] == 1,
            message="capture must declare exactly one source page",
        ),
        check_result(
            "capture.company_count",
            staged_checks is not None or kinds["company"] >= 1,
            message="capture must declare at least one company page",
        ),
    ])
    checks.extend(_workflow_checks(vault_root, run_dir))
    return checks
