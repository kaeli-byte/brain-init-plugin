import json
from pathlib import Path
import re
from typing import Any

import yaml

from ..contracts import ArtifactRef, CheckResult
from ..trace import read_events


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

WIKILINK = re.compile(r"\[\[([^|\]#]+)")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
RECOGNIZED_LONG_PROFILES = {"annual-report-v1", "sec-filing-v1"}


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


def _check(
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


def _missing(data: dict[str, Any], required: set[str]) -> list[str]:
    return sorted(field for field in required if field not in data)


def _links(value: Any, prefix: str) -> list[str]:
    if isinstance(value, str):
        return [
            target for target in WIKILINK.findall(value)
            if target.startswith(prefix)
        ]
    if isinstance(value, dict):
        links: list[str] = []
        for child in value.values():
            links.extend(_links(child, prefix))
        return links
    if isinstance(value, list):
        links = []
        for child in value:
            links.extend(_links(child, prefix))
        return links
    return []


def _normalized(text: str) -> str:
    return " ".join(text.split())


def _confined_path(vault: Path, path_text: str) -> Path | None:
    requested = Path(path_text)
    if requested.is_absolute():
        return None
    resolved = (vault / requested).resolve()
    try:
        resolved.relative_to(vault)
    except ValueError:
        return None
    return resolved


def _evidence_checks(
    vault: Path,
    artifact_path: str,
    evidence: Any,
    declared: set[str],
) -> list[CheckResult]:
    checks: list[CheckResult] = []
    links = _links(evidence, "src-")
    checks.append(_check(
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
    checks.append(_check(
        "claim.source_page_exists",
        sources_exist,
        artifact=artifact_path,
        message="linked source page is missing or undeclared",
    ))

    locator_passed = True
    locator_warning = False
    locator_message = ""
    entries = evidence if isinstance(evidence, list) else [evidence]
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("passage"):
            continue
        entry_links = _links(entry.get("source"), "src-")
        if not entry_links:
            locator_passed = False
            locator_message = "structured evidence source link is missing"
            continue
        source_relative = f"wiki/sources/{entry_links[0]}.md"
        if source_relative not in declared:
            locator_passed = False
            locator_message = "linked source page is missing or undeclared"
            continue
        try:
            source_data, _ = read_frontmatter(vault / source_relative)
        except (OSError, ValueError, yaml.YAMLError):
            locator_passed = False
            locator_message = "linked source frontmatter is unavailable"
            continue
        raw_path = source_data.get("raw_path")
        raw_file = _confined_path(vault, raw_path) if isinstance(raw_path, str) else None
        converted = raw_file.with_suffix(".md") if raw_file is not None else None
        if converted is None or not converted.is_file():
            locator_passed = False
            locator_warning = True
            locator_message = "converted markdown unavailable; locator not mechanically checked"
            continue
        if _normalized(str(entry["passage"])) not in _normalized(
            converted.read_text(encoding="utf-8")
        ):
            locator_passed = False
            locator_warning = False
            locator_message = "evidence passage not found in converted markdown"
    checks.append(_check(
        "evidence.locator_resolves",
        locator_passed,
        artifact=artifact_path,
        message=locator_message,
        severity="warning" if locator_warning else "critical",
    ))
    return checks


def _claim_checks(
    vault: Path,
    artifact: ArtifactRef,
    data: dict[str, Any],
    declared: set[str],
) -> list[CheckResult]:
    missing = _missing(data, CLAIM_REQUIRED)
    checks = [
        _check(
            "claim.required_fields",
            not missing,
            artifact=artifact.path,
            message=f"missing required fields: {', '.join(missing)}",
        ),
        _check(
            "claim.confidence_enum",
            data.get("confidence") in CLAIM_CONFIDENCE,
            artifact=artifact.path,
            message="invalid claim confidence",
        ),
        _check(
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
    missing = _missing(data, SOURCE_REQUIRED)
    enums_valid = (
        data.get("source_type") in SOURCE_TYPE
        and data.get("reliability") in SOURCE_RELIABILITY
        and data.get("materiality") in MATERIALITY
    )
    company_links = _links(body, "company-")
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
        _check(
            "source.required_fields",
            not missing,
            artifact=artifact.path,
            message=f"missing required fields: {', '.join(missing)}",
        ),
        _check(
            "source.enum_values",
            enums_valid,
            artifact=artifact.path,
            message="invalid source enum value",
        ),
        _check(
            "source.company_link",
            bool(company_links),
            artifact=artifact.path,
            message="source page must link at least one company",
        ),
        _check(
            "company.source_backlink",
            backlink_valid,
            artifact=artifact.path,
            message="linked company must contain a source backlink",
        ),
    ]


def _workflow_checks(vault: Path, run_dir: Path) -> list[CheckResult]:
    with (run_dir / "manifest.json").open(encoding="utf-8") as manifest_file:
        manifest = json.load(manifest_file)
    metadata = manifest.get("metadata") or {}
    inputs = manifest.get("inputs") or []
    source_type = metadata.get("source_type")
    plan_path = run_dir / "plan.json"
    plan: dict[str, Any] = {}
    if plan_path.is_file():
        try:
            with plan_path.open(encoding="utf-8") as plan_file:
                loaded_plan = json.load(plan_file)
            if isinstance(loaded_plan, dict):
                plan = loaded_plan
        except (OSError, json.JSONDecodeError):
            plan = {}
    exceeds_one_context = metadata.get(
        "exceeds_one_context",
        plan.get("exceeds_one_context"),
    )
    annual_report_input = (
        source_type in {"annual-report", "10k-filing"}
        or any("annual-report" in item.get("path", "") for item in inputs)
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
        _check(
            "capture.profile_recognized",
            profile_valid,
            message="long annual-report/10-K capture requires a recognized profile",
        ),
        _check(
            "capture.section_plan",
            plan_valid,
            message="section plan was not recorded",
            severity="warning",
        ),
        _check(
            "workflow.qmd_refresh",
            qmd_valid,
            message="qmd refresh unavailable, absent, or failed",
            severity="warning",
        ),
        _check(
            "workflow.log_completed",
            log_valid,
            message="finalized capture log completion was not recorded",
        ),
    ]


def capture_checks(
    vault: Path,
    run_dir: Path,
    artifacts: list[ArtifactRef],
) -> list[CheckResult]:
    vault_root = vault.resolve()
    declared = {artifact.path for artifact in artifacts}
    checks: list[CheckResult] = []
    kinds = {"claim": 0, "source": 0, "company": 0}

    for artifact in artifacts:
        if artifact.kind in kinds:
            kinds[artifact.kind] += 1
        path = _confined_path(vault_root, artifact.path)
        exists = path is not None and path.is_file()
        checks.extend([
            _check(
                "artifact.exists",
                exists,
                artifact=artifact.path,
                message="declared artifact does not exist within the vault",
            ),
            _check(
                "artifact.sha256",
                bool(SHA256.fullmatch(artifact.sha256)),
                artifact=artifact.path,
                message="artifact SHA-256 must be 64 lowercase hexadecimal characters",
            ),
        ])
        if not exists or not artifact.path.startswith("wiki/"):
            continue
        try:
            data, body = read_frontmatter(path)
        except (OSError, ValueError, yaml.YAMLError) as error:
            checks.append(_check(
                "frontmatter.valid_yaml",
                False,
                artifact=artifact.path,
                message=str(error),
            ))
            continue
        checks.append(_check(
            "frontmatter.valid_yaml",
            True,
            artifact=artifact.path,
        ))
        if artifact.kind == "claim":
            checks.extend(_claim_checks(vault_root, artifact, data, declared))
        elif artifact.kind == "source":
            checks.extend(_source_checks(
                vault_root,
                artifact,
                data,
                body,
                declared,
            ))
        elif artifact.kind == "company":
            missing = _missing(data, COMPANY_REQUIRED)
            checks.append(_check(
                "company.required_fields",
                not missing,
                artifact=artifact.path,
                message=f"missing required fields: {', '.join(missing)}",
            ))
        else:
            checks.append(_check(
                "page.last_reviewed",
                "last_reviewed" in data,
                artifact=artifact.path,
                message="wiki page must include last_reviewed",
            ))

    checks.extend([
        _check(
            "capture.claim_count_min",
            kinds["claim"] >= 2,
            message="capture must declare at least two claim pages",
        ),
        _check(
            "capture.claim_count_max",
            kinds["claim"] <= 6,
            message="capture declares more than six claims",
            severity="warning",
        ),
        _check(
            "capture.source_count",
            kinds["source"] == 1,
            message="capture must declare exactly one source page",
        ),
        _check(
            "capture.company_count",
            kinds["company"] >= 1,
            message="capture must declare at least one company page",
        ),
    ])
    checks.extend(_workflow_checks(vault_root, run_dir))
    return checks
