# Capture Loop-Graph Runtime — Plan Review Amendment

This amendment is **normative for implementation** and must be executed together with `2026-07-26-capture-loop-graph-runtime.md`. It closes the spec-coverage gap found during the required writing-plans self-review.

## Amendment A — Deterministic workflow checks are verified, not only traced

In **Task 3, Step 3**, add these tests to `CaptureVerifyTests`:

```python
def test_long_annual_report_requires_recorded_section_plan(self): ...
def test_annual_report_requires_recognized_profile(self): ...
def test_missing_qmd_completion_is_warning_not_rejection(self): ...
def test_failed_qmd_refresh_is_warning_not_rejection(self): ...
def test_missing_completed_log_signal_is_critical(self): ...
def test_artifact_declaration_always_contains_sha256(self): ...
```

Add these check IDs to the asserted capture contract:

```text
capture.section_plan
capture.profile_recognized
workflow.qmd_refresh
workflow.log_completed
artifact.sha256
```

In **Task 3, Step 7**, `capture_checks(vault, run_dir, artifacts)` must also read the minimum runtime state needed to perform workflow checks:

1. Read `manifest.json` for `profile` and input metadata.
2. Read `plan.json` only when it exists.
3. Read compact `events.jsonl` through `trace.read_events()`; never read Claude transcripts or source bodies for workflow checks.
4. For `annual-report-v1` and `sec-filing-v1`:
   - `capture.profile_recognized` is **critical** when profile is not one of those recognized values for a long annual-report/10-K capture.
   - `capture.section_plan` is **warning** when no `plan.json` exists in shadow v1. The capture is still authoritative, but the instrumentation gap must be visible.
5. `workflow.qmd_refresh`:
   - PASS when the most recent `workflow.qmd` event has `passed: true`.
   - WARNING when event is absent, qmd is unavailable, or `passed: false`.
   - Never reject knowledge solely because qmd is unavailable.
6. `workflow.log_completed`:
   - PASS when a `workflow.log` event with `passed: true` exists.
   - CRITICAL failure when absent or false because a finalized capture log is part of the capture output contract.
7. `artifact.sha256` is CRITICAL for every declared artifact and validates a lowercase 64-character SHA-256 value.

The generic `verify_run()` remains operation-agnostic; these checks belong only in `adapters/capture.py`.

## Amendment B — Record workflow events before verification

In **Task 6, Step 6**, the following events are mandatory before `cli verify` when runtime instrumentation is active:

```bash
# WIP log successfully finalized
... cli event --kind workflow.log --label capture.log --data-json '{"passed":true}'

# qmd successful
... cli event --kind workflow.qmd --label qmd.refresh --data-json '{"passed":true}'

# OR qmd unavailable/failed
... cli event --kind workflow.qmd --label qmd.refresh --data-json '{"passed":false,"reason":"unavailable"}'
```

If finalizing the capture log itself failed, record `workflow.log` with `passed:false` if possible, but **do not let the runtime change current capture behavior in shadow mode**. The deterministic verifier will surface this as a critical shadow finding.

## Amendment C — Fixture typo is removed from the implementation instruction

When creating `fixtures/valid-source.md`, use this exact valid frontmatter; do not reproduce the accidental indentation shown in the first plan draft:

```markdown
---
source_id: src-acme-2025-annual-report
raw_path: raw/annual-reports/acme-2025-annual-report.pdf
source_type: annual-report
publisher: Acme Corporation
date_published: 2026-04-01
date_ingested: 2026-07-26
last_reviewed: 2026-07-26
reliability: audited
materiality: high
key_claims: [claim-acme-revenue-12345678]
entities_covered: [entity-acme]
technologies_covered: []
industries_covered: [industry-fluid-handling]
---
# Acme 2025 Annual Report
## Company
[[company-acme]]
```

## Amendment D — Final acceptance adds workflow evidence

Add these assertions to the **Final Acceptance Walkthrough**:

```text
- verification.json includes capture.section_plan for annual-report profiles.
- verification.json includes workflow.log_completed and it passes for the valid run.
- verification.json includes workflow.qmd_refresh; qmd-unavailable produces warning only.
- every ArtifactRef in artifacts.json has a valid SHA-256.
```

## Self-review result

With these amendments:

- every approved deterministic workflow check has an implementation task and regression test;
- workflow tracing and workflow verification are no longer conflated;
- qmd unavailability remains operational rather than evidentiary;
- finalized logging remains part of the capture integrity contract;
- the plan contains no unresolved design decisions for the capture-only shadow pilot.
