"""Deterministic verification for reconcile runs.

Validates the canonical reconciliation record against the vault: structural
contract, candidate identifiers, disposition semantics, baseline/declared
scope, and workflow events. It never judges whether a semantic disposition
was wise — only whether recorded actions match files.
"""
from pathlib import Path
from typing import Any

import yaml

from ..contracts import ArtifactRef, CheckResult
from ..reconcile_contract import (
    ACTION_STATES,
    CONFIDENCE_EFFECTS,
    DISPOSITIONS,
    ORIGINS,
    RECORD_STATUSES,
    REVIEW_STATES,
    SEARCH_METHODS,
    SENSITIVE_DISPOSITIONS,
    candidate_id,
)
from ..run import sha256_file
from ..trace import read_events, read_json_nofollow
from .common import (
    SHA256,
    check_result,
    confined_path,
    missing_fields,
    read_frontmatter,
    wikilinks,
)


RECORD_REQUIRED = {
    "reconciliation_id", "source", "origin", "status", "search_method",
    "coverage_complete", "created", "last_reviewed", "candidates",
}
CANDIDATE_REQUIRED = {
    "candidate_id", "claim_text", "source_evidence", "entities", "disposition",
    "target_claim", "reason", "confidence_effect", "review_state", "action_state",
    "result_claim", "reviewed_by", "reviewed_at", "review_note",
}
TARGETED_DISPOSITIONS = {"corroborating", "updating", "contradicting", "superseding"}
UNTARGETED_DISPOSITIONS = {"new", "irrelevant"}
SAFE_DISPOSITIONS = {"new", "corroborating", "irrelevant"}
BODY_HEADINGS = ("# Reconciliation:", "## Summary", "## Pending Review", "## Changelog")


def _claim_id_from_link(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    links = wikilinks(value, "claim-")
    return links[0] if links else None


def _claim_path_for(claim_id_value: str) -> str:
    return f"wiki/claims/{claim_id_value}.md"


def _load_claim(vault: Path, claim_id_value: str) -> tuple[dict[str, Any], str] | None:
    path = confined_path(vault, _claim_path_for(claim_id_value))
    if path is None or not path.is_file():
        return None
    try:
        return read_frontmatter(path)
    except (OSError, ValueError, yaml.YAMLError):
        return None


def _record_checks(
    data: dict[str, Any],
    body: str,
    artifact_path: str,
) -> list[CheckResult]:
    missing = missing_fields(data, RECORD_REQUIRED)
    candidates = data.get("candidates")
    candidates_valid = isinstance(candidates, list) and all(
        isinstance(item, dict) for item in candidates
    )
    headings_missing = [
        heading for heading in BODY_HEADINGS if heading not in body
    ]
    coverage = data.get("coverage_complete")
    return [
        check_result(
            "reconcile.record.required_fields",
            not missing,
            artifact=artifact_path,
            message=f"missing required fields: {', '.join(missing)}",
        ),
        check_result(
            "reconcile.origin_enum",
            data.get("origin") in ORIGINS,
            artifact=artifact_path,
            message="invalid origin",
        ),
        check_result(
            "reconcile.record.status",
            data.get("status") in RECORD_STATUSES,
            artifact=artifact_path,
            message="invalid record status",
        ),
        check_result(
            "reconcile.search_method_enum",
            data.get("search_method") in SEARCH_METHODS,
            artifact=artifact_path,
            message="invalid search method",
        ),
        check_result(
            "reconcile.coverage_type",
            isinstance(coverage, bool),
            artifact=artifact_path,
            message="coverage_complete must be a boolean",
        ),
        check_result(
            "reconcile.candidates_shape",
            candidates_valid,
            artifact=artifact_path,
            message="candidates must be a list of mappings",
        ),
        check_result(
            "reconcile.record_body",
            not headings_missing,
            artifact=artifact_path,
            message=f"missing body headings: {', '.join(headings_missing)}",
        ),
    ]


def _candidate_contract_checks(
    data: dict[str, Any],
    source_id: str,
    artifact_path: str,
) -> list[CheckResult]:
    candidates = data.get("candidates")
    if not isinstance(candidates, list):
        return []
    origin = data.get("origin")
    status = data.get("status")
    coverage_complete = data.get("coverage_complete") is True
    unclassified_allowed = status in {"staged", "incomplete"}

    checks: list[CheckResult] = []
    seen_ids: set[str] = set()
    count = len(candidates)

    if origin == "capture":
        checks.append(check_result(
            "reconcile.candidate_count_min",
            count >= 2,
            artifact=artifact_path,
            message="capture-origin records require at least two candidates",
        ))
        checks.append(check_result(
            "reconcile.candidate_count_max",
            count <= 6,
            artifact=artifact_path,
            message="capture record declares more than six candidates",
            severity="warning",
        ))
    elif origin == "legacy":
        checks.append(check_result(
            "reconcile.candidate_count_min",
            count >= 1,
            artifact=artifact_path,
            message="legacy-origin records require at least one candidate",
        ))

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        cid = candidate.get("candidate_id")
        missing = missing_fields(candidate, CANDIDATE_REQUIRED)
        checks.append(check_result(
            "reconcile.candidate.required_fields",
            not missing,
            artifact=artifact_path,
            message=f"candidate missing required fields: {', '.join(missing)}",
        ))

        duplicate = isinstance(cid, str) and cid in seen_ids
        checks.append(check_result(
            "reconcile.candidate_ids_unique",
            not duplicate,
            artifact=artifact_path,
            message=f"duplicate candidate_id: {cid}",
        ))
        if isinstance(cid, str):
            seen_ids.add(cid)

        claim_text = candidate.get("claim_text")
        if isinstance(cid, str) and isinstance(claim_text, str) and claim_text.strip():
            try:
                expected = candidate_id(source_id, claim_text)
            except ValueError:
                expected = None
            checks.append(check_result(
                "reconcile.candidate_id_hash",
                expected is not None and cid == expected,
                artifact=artifact_path,
                message=f"candidate_id {cid} does not match source/text hash",
            ))

        disposition = candidate.get("disposition")
        if disposition is None:
            checks.append(check_result(
                "reconcile.disposition_enum",
                unclassified_allowed,
                artifact=artifact_path,
                message=(
                    "null disposition is allowed only while the record is "
                    "staged or incomplete"
                ),
            ))
        else:
            checks.append(check_result(
                "reconcile.disposition_enum",
                disposition in DISPOSITIONS,
                artifact=artifact_path,
                message=f"invalid disposition: {disposition}",
            ))

        for field, enum, check_id in (
            ("confidence_effect", CONFIDENCE_EFFECTS, "reconcile.confidence_effect_enum"),
            ("review_state", REVIEW_STATES, "reconcile.review_state_enum"),
            ("action_state", ACTION_STATES, "reconcile.action_state_enum"),
        ):
            value = candidate.get(field)
            if value is None:
                checks.append(check_result(
                    check_id,
                    unclassified_allowed,
                    artifact=artifact_path,
                    message=f"null {field} is allowed only for staged/incomplete records",
                ))
            else:
                checks.append(check_result(
                    check_id,
                    value in enum,
                    artifact=artifact_path,
                    message=f"invalid {field}: {value}",
                ))

        if disposition == "new" and not unclassified_allowed:
            checks.append(check_result(
                "reconcile.candidate_new_requires_coverage",
                coverage_complete,
                artifact=artifact_path,
                message="disposition 'new' requires coverage_complete: true",
            ))

        target = candidate.get("target_claim")
        if disposition in TARGETED_DISPOSITIONS:
            checks.append(check_result(
                "reconcile.target_contract",
                _claim_id_from_link(target) is not None,
                artifact=artifact_path,
                message=f"disposition {disposition} requires a target_claim link",
            ))
        elif disposition in UNTARGETED_DISPOSITIONS:
            checks.append(check_result(
                "reconcile.target_contract",
                target in (None, ""),
                artifact=artifact_path,
                message=f"disposition {disposition} forbids a target_claim",
            ))
    return checks


def _candidate_effect_checks(
    vault: Path,
    data: dict[str, Any],
    artifact_path: str,
    declared: set[str],
    input_hashes: dict[str, str],
) -> list[CheckResult]:
    candidates = data.get("candidates")
    if not isinstance(candidates, list):
        return []
    checks: list[CheckResult] = []
    source_links = wikilinks(data.get("source"), "src-")
    source_id = source_links[0] if source_links else ""

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        disposition = candidate.get("disposition")
        if disposition not in DISPOSITIONS:
            continue
        review_state = candidate.get("review_state")
        action_state = candidate.get("action_state")
        target_id = _claim_id_from_link(candidate.get("target_claim"))
        result_id = _claim_id_from_link(candidate.get("result_claim"))

        if disposition in SENSITIVE_DISPOSITIONS:
            if review_state == "rejected":
                note = candidate.get("review_note")
                checks.append(check_result(
                    "reconcile.review_contract",
                    isinstance(note, str) and bool(note.strip())
                    and candidate.get("reviewed_by") == "human"
                    and result_id is None,
                    artifact=artifact_path,
                    message=(
                        "rejected sensitive action requires reviewed_by: human, "
                        "a non-empty review_note, and a null result_claim"
                    ),
                ))
            elif review_state == "approved":
                checks.append(check_result(
                    "reconcile.review_contract",
                    candidate.get("reviewed_by") == "human"
                    and bool(candidate.get("reviewed_at")),
                    artifact=artifact_path,
                    message="approved sensitive action requires reviewed_by and reviewed_at",
                ))

        if action_state == "applied":
            if disposition == "new":
                result_ok = result_id is not None
                if result_ok:
                    result_path = _claim_path_for(result_id)
                    loaded = _load_claim(vault, result_id)
                    result_ok = (
                        result_path in declared
                        and loaded is not None
                        and loaded[0].get("claim_id") == result_id
                        and source_id in wikilinks(loaded[0].get("source_evidence"), "src-")
                    )
                checks.append(check_result(
                    "reconcile.result_contract",
                    result_ok,
                    artifact=artifact_path,
                    message=(
                        "applied 'new' requires a declared result claim under "
                        "wiki/claims/ whose source evidence links the reconciliation source"
                    ),
                ))
            elif disposition == "corroborating":
                result_ok = (
                    result_id is not None
                    and target_id is not None
                    and result_id == target_id
                    and _claim_path_for(target_id) in declared
                )
                if result_ok:
                    loaded = _load_claim(vault, target_id)
                    result_ok = loaded is not None and source_id in wikilinks(
                        loaded[0].get("source_evidence"), "src-"
                    )
                checks.append(check_result(
                    "reconcile.result_contract",
                    result_ok,
                    artifact=artifact_path,
                    message=(
                        "applied 'corroborating' requires result == declared target "
                        "containing the reconciliation source evidence"
                    ),
                ))
            elif disposition in {"updating", "superseding"}:
                result_ok = (
                    result_id is not None
                    and target_id is not None
                    and _claim_path_for(result_id) in declared
                    and _claim_path_for(target_id) in declared
                )
                checks.append(check_result(
                    "reconcile.result_contract",
                    result_ok,
                    artifact=artifact_path,
                    message=(
                        f"applied '{disposition}' requires declared result and target claims"
                    ),
                ))
                target_loaded = _load_claim(vault, target_id) if target_id else None
                result_loaded = _load_claim(vault, result_id) if result_id else None
                temporal_ok = (
                    target_loaded is not None
                    and result_loaded is not None
                    and target_loaded[0].get("status") == "superseded"
                    and _claim_id_from_link(target_loaded[0].get("superseded_by")) == result_id
                )
                if disposition == "updating":
                    temporal_ok = (
                        temporal_ok
                        and bool(target_loaded[0].get("valid_to"))
                        and bool(result_loaded[0].get("valid_from"))
                    )
                checks.append(check_result(
                    "reconcile.temporal_supersession",
                    temporal_ok,
                    artifact=artifact_path,
                    message=(
                        f"applied '{disposition}' requires target status superseded, "
                        "superseded_by equal to the result claim, and valid_to/valid_from"
                        if disposition == "updating"
                        else f"applied '{disposition}' requires target status superseded "
                        "with superseded_by equal to the result claim"
                    ),
                ))
            elif disposition == "contradicting":
                target_loaded = _load_claim(vault, target_id) if target_id else None
                result_loaded = _load_claim(vault, result_id) if result_id else None
                contradiction_ok = (
                    target_loaded is not None
                    and result_loaded is not None
                    and _claim_path_for(target_id) in declared
                    and _claim_path_for(result_id) in declared
                    and target_loaded[0].get("status") == "disputed"
                    and result_loaded[0].get("status") == "disputed"
                    and bool(target_loaded[0].get("counter_evidence"))
                    and bool(result_loaded[0].get("counter_evidence"))
                    and f"[[{result_id}]]" in target_loaded[1]
                    and f"[[{target_id}]]" in result_loaded[1]
                )
                checks.append(check_result(
                    "reconcile.contradiction_evidence",
                    contradiction_ok,
                    artifact=artifact_path,
                    message=(
                        "applied 'contradicting' requires both claims disputed, "
                        "non-empty opposing counter_evidence, and reciprocal "
                        "Related Claims links"
                    ),
                ))
        elif disposition == "irrelevant":
            checks.append(check_result(
                "reconcile.action_contract",
                action_state == "not_applicable" and result_id is None,
                artifact=artifact_path,
                message="irrelevant candidates require action_state: not_applicable and no result",
            ))

        if disposition in SENSITIVE_DISPOSITIONS:
            review_action_ok = (
                (review_state == "pending" and action_state == "pending")
                or (review_state == "approved" and action_state in {"applied", "pending"})
                or (review_state == "rejected" and action_state == "rejected")
            )
            checks.append(check_result(
                "reconcile.action_contract",
                review_action_ok,
                artifact=artifact_path,
                message=(
                    f"sensitive candidate has inconsistent review/action states: "
                    f"{review_state}/{action_state}"
                ),
            ))
        elif disposition in SAFE_DISPOSITIONS:
            safe_ok = (
                review_state == "not_required"
                and action_state in {"applied", "not_applicable"}
            )
            checks.append(check_result(
                "reconcile.action_contract",
                safe_ok,
                artifact=artifact_path,
                message=(
                    f"safe disposition {disposition} requires review_state "
                    "not_required and action_state applied/not_applicable"
                ),
            ))

        if target_id is not None:
            target_path = _claim_path_for(target_id)
            checks.append(check_result(
                "reconcile.target_snapshotted",
                target_path in input_hashes,
                artifact=artifact_path,
                message=f"target claim {target_path} must appear in run inputs",
            ))
            if action_state in {"pending", "rejected"}:
                current = confined_path(vault, target_path)
                unchanged = (
                    current is not None
                    and current.is_file()
                    and input_hashes.get(target_path) == sha256_file(current)
                )
                checks.append(check_result(
                    "reconcile.pending_target_unchanged",
                    unchanged,
                    artifact=artifact_path,
                    message=(
                        f"pending/rejected target {target_path} must retain its input SHA-256"
                    ),
                ))
        if action_state == "rejected":
            checks.append(check_result(
                "reconcile.result_contract",
                result_id is None,
                artifact=artifact_path,
                message="rejected candidates must have a null result_claim",
            ))
    return checks


def _scope_checks(
    vault: Path,
    run_dir: Path,
    declared: set[str],
) -> list[CheckResult]:
    baseline_path = run_dir / "baseline.json"
    baseline_exists = baseline_path.exists() and not baseline_path.is_symlink()
    checks = [check_result(
        "reconcile.baseline_present",
        baseline_exists,
        message="baseline.json snapshot is missing",
    )]
    if not baseline_exists:
        checks.append(check_result(
            "reconcile.declared_scope",
            False,
            message="cannot compare scope without a baseline snapshot",
        ))
        return checks
    try:
        payload = read_json_nofollow(baseline_path)
        files = payload["files"]
        root = payload["root"]
        baseline = {item["path"]: item["sha256"] for item in files}
        well_formed = (
            isinstance(root, str)
            and all(
                isinstance(item.get("path"), str)
                and isinstance(item.get("sha256"), str)
                and SHA256.fullmatch(item["sha256"])
                for item in files
            )
        )
    except (OSError, KeyError, TypeError, AttributeError) as error:
        checks.append(check_result(
            "reconcile.declared_scope",
            False,
            message=f"malformed baseline.json: {error}",
        ))
        return checks
    if not well_formed:
        checks.append(check_result(
            "reconcile.declared_scope",
            False,
            message="malformed baseline.json entries",
        ))
        return checks

    current: dict[str, str] = {}
    root_path = vault / root
    if root_path.is_dir():
        for path in sorted(root_path.rglob("*.md")):
            if path.is_file() and not path.is_symlink():
                current[path.relative_to(vault).as_posix()] = sha256_file(path)
    changed = {
        path for path in baseline.keys() & current.keys()
        if baseline[path] != current[path]
    }
    added = current.keys() - baseline.keys()
    removed = baseline.keys() - current.keys()
    undeclared = sorted((changed | added) - declared)
    scope_ok = not removed and not undeclared
    problems = []
    if removed:
        problems.append(f"removed wiki pages: {', '.join(sorted(removed))}")
    if undeclared:
        problems.append(f"undeclared changed/added pages: {', '.join(undeclared)}")
    checks.append(check_result(
        "reconcile.declared_scope",
        scope_ok,
        message="; ".join(problems),
    ))
    return checks


def _workflow_checks(
    run_dir: Path,
    data: dict[str, Any],
    artifact_path: str,
) -> list[CheckResult]:
    events = read_events(run_dir)
    checks: list[CheckResult] = []

    search_events = [event for event in events if event.kind == "reconcile.search"]
    search_valid = bool(search_events)
    coverage_agrees = True
    if search_valid:
        final = search_events[-1]
        recorded_coverage = final.data.get("coverage_complete")
        coverage_agrees = recorded_coverage == data.get("coverage_complete")
    checks.append(check_result(
        "workflow.reconcile_search",
        search_valid and coverage_agrees,
        message=(
            "final reconcile.search event is missing or its coverage_complete "
            "disagrees with the record"
        ),
    ))

    status = data.get("status")
    classified_events = [event for event in events if event.kind == "reconcile.classified"]
    classified_required = status in {"complete", "pending_review"}
    checks.append(check_result(
        "workflow.reconcile_classified",
        bool(classified_events) or not classified_required,
        message="reconcile.classified event is missing for a classified record",
    ))

    candidates = data.get("candidates") if isinstance(data.get("candidates"), list) else []
    decided = sum(
        1
        for candidate in candidates
        if isinstance(candidate, dict)
        and candidate.get("disposition") in SENSITIVE_DISPOSITIONS
        and candidate.get("review_state") in {"approved", "rejected"}
    )
    decision_events = [event for event in events if event.kind == "review.decision"]
    checks.append(check_result(
        "workflow.review_decision",
        len(decision_events) >= decided,
        artifact=artifact_path,
        message=(
            f"record has {decided} approved/rejected sensitive candidates but "
            f"only {len(decision_events)} review.decision events"
        ),
    ))

    qmd_events = [event for event in events if event.kind == "workflow.qmd"]
    qmd_valid = bool(qmd_events) and qmd_events[-1].data.get("passed") is True
    checks.append(check_result(
        "workflow.qmd_refresh",
        qmd_valid,
        message="qmd refresh unavailable, absent, or failed",
        severity="warning",
    ))
    log_valid = any(
        event.kind == "workflow.log" and event.data.get("passed") is True
        for event in events
    )
    checks.append(check_result(
        "workflow.log_completed",
        log_valid,
        message="finalized reconcile log completion was not recorded",
    ))
    return checks


def reconcile_checks(
    vault: Path,
    run_dir: Path,
    artifacts: list[ArtifactRef],
) -> list[CheckResult]:
    vault_root = vault.resolve()
    declared = {artifact.path for artifact in artifacts}
    checks: list[CheckResult] = []

    records = [artifact for artifact in artifacts if artifact.kind == "reconciliation"]
    checks.append(check_result(
        "reconcile.record_count",
        len(records) == 1,
        message=f"expected exactly one reconciliation artifact, found {len(records)}",
    ))
    if len(records) != 1:
        return checks

    record = records[0]
    for artifact in artifacts:
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

    record_path = confined_path(vault_root, record.path)
    if record_path is None or not record_path.is_file():
        return checks
    try:
        data, body = read_frontmatter(record_path)
    except (OSError, ValueError, yaml.YAMLError) as error:
        checks.append(check_result(
            "frontmatter.valid_yaml",
            False,
            artifact=record.path,
            message=str(error),
        ))
        return checks
    checks.append(check_result("frontmatter.valid_yaml", True, artifact=record.path))

    checks.extend(_record_checks(data, body, record.path))

    source_links = wikilinks(data.get("source"), "src-")
    source_id = source_links[0] if source_links else ""
    checks.extend(_candidate_contract_checks(data, source_id, record.path))

    manifest = read_json_nofollow(run_dir / "manifest.json")
    input_hashes = {
        item["path"]: item["sha256"]
        for item in manifest.get("inputs") or []
        if isinstance(item, dict) and "path" in item and "sha256" in item
    }
    checks.extend(_candidate_effect_checks(
        vault_root, data, record.path, declared, input_hashes,
    ))
    checks.extend(_scope_checks(vault_root, run_dir, declared))
    checks.extend(_workflow_checks(run_dir, data, record.path))
    return checks
