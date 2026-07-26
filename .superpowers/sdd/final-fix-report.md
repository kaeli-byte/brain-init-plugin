# Final Review Fix Report

## Scope

- Review base: `f0f0a842fbb0dd9743a305d465bda55d9f4d2a2a`
- Reviewed head before this fix wave: `54cf915`
- Source findings: `.superpowers/sdd/final-review-findings.md`
- Delivery shape: one consolidated fix commit after all verification below

## Resolved findings

1. Root `wiki/log.md` is now exempt from the generic `last_reviewed` page
   fallback. Its append-only completion contract remains enforced through
   `workflow.log_completed`.
2. Legacy harness upgrades now create `.brain/runs` and `.brain/evals`, append
   exact run-history ignore rules idempotently, replace stale runtime code, and
   preserve prior run/evaluation state.
3. Runtime paths now reject unsafe input references and symlinked ownership
   components. The installer validates canonical ownership directories,
   refuses symlinked runtime sources/targets, stages replacement, serializes
   installers with a lock directory, and retains the old runtime backup when
   rollback cannot complete.
4. `finish_run()` now performs its complete manifest/verdict/event transition
   under the run lock. Every run writer (plan, event, declare, deterministic
   verify, semantic verify, and finish) uses the same lock and rejects completed
   runs. Finish reads the current verification verdict while holding that lock.
5. `plan.json` now persists `exceeds_one_context`, including for single-slice
   annual-report plans.
6. CI now classifies validator warnings through an allowlist and proves that a
   legacy vault without runtime state remains warning-only with exit status 0.
7. README validator counts and the optional `plan.json` artifact description
   now match the shipped behavior.
8. Trailing Markdown hard-break whitespace was removed from the design spec.

## Additional review hardening

Two rounds of read-only review found additional edge cases. They were addressed
before delivery:

- `.lock` and `events.jsonl` are opened with `O_NOFOLLOW` and verified as
  regular files after opening.
- Finish-versus-semantic tests use deterministic entry barriers, and the
  manifest verdict is asserted against the report written by the winning
  transaction.
- Runtime sources containing symlinks are rejected before copying.
- Runtime replacement uses an atomic lock directory; a failed install attempts
  restoration, and a failed restoration retains the backup path instead of
  deleting the only old copy.
- All runtime-owned JSON reads use no-follow regular-file opens. Stable FIFOs
  and other non-regular files are rejected before opening, while `O_NONBLOCK`
  prevents a swap race from hanging the process.
- Plan, declaration, and deterministic verification transactions now share the
  terminal-state lock used by event, semantic, and finish transactions.
- A unique staged-package marker detects portable `mv source existing-dir`
  nesting. Every failed replacement path preserves and reports the old backup,
  and an active/stale lock diagnostic includes safe recovery guidance.

## Strict TDD evidence

### Review findings: RED

Focused regression tests were added before production changes.

```text
test_complete_capture_artifact_set_accepts_root_index_and_log
FAIL: expected accepted capture, generic page.last_reviewed rejected wiki/log.md

test_single_slice_plan_persists_context_flag_for_annual_report_verify
FAIL: plan.json did not contain exceeds_one_context

five input/run ownership regressions
FAIL: ValueError not raised for absolute, traversing, outward-symlinked,
      symlinked-runs, and symlinked-run-component cases

test_finish_run_serializes_with_event_writer
test_finish_run_serializes_with_semantic_writer
FAIL: finish loaded the manifest while the competing writer held the run lock
```

The new installer smoke cases also failed before the installer changes:

```text
FAIL: upgrade did not migrate .brain/runs
FAIL: upgrade accepted symlinked runtime ownership
FAIL: force install accepted symlinked runtime ownership
```

### Review findings: focused GREEN

```text
PYTHONPATH=skills/brain-init/runtime python3 -m unittest \
  skills.brain-init.runtime.tests.test_capture_verify.CaptureVerifyTests.test_complete_capture_artifact_set_accepts_root_index_and_log
Ran 1 test ... OK

PYTHONPATH=skills/brain-init/runtime python3 -m unittest \
  skills.brain-init.runtime.tests.test_cli.CliTests.test_single_slice_plan_persists_context_flag_for_annual_report_verify
Ran 1 test ... OK

PYTHONPATH=skills/brain-init/runtime python3 -m unittest \
  skills.brain-init.runtime.tests.test_contracts_run
ownership and finish race cases ... OK
```

The extracted upgrade, upgrade-symlink, and force-symlink CI steps all exited
0 after the production change.

### Additional hardening: RED

The post-fix reviewers' cases were also captured before their production
changes:

```text
test_record_event_rejects_symlinked_events_file
FAIL: ValueError not raised

test_record_event_rejects_symlinked_lock_file
FAIL: ValueError not raised

test_semantic_writer_rejects_completed_run_without_changing_verdict
FAIL: ValueError not raised

test_event_writer_rejects_completed_run_without_appending
FAIL: ValueError not raised

test_finish_run_serializes_with_semantic_writer
FAIL: final manifest shadow_verdict was None instead of False

FAIL: upgrade accepted symlinked runtime source
FAIL: upgrade ignored active replacement lock
ERROR: Could not install staged brain runtime code.
      (the injected failed rollback did not retain/report the backup)
```

### Additional hardening: focused GREEN

```text
PYTHONPATH=skills/brain-init/runtime python3 -m unittest \
  [five no-follow/terminal/verdict cases]
.....
Ran 5 tests in 0.124s
OK

PYTHONPATH=skills/brain-init/runtime python3 -m unittest \
  ...test_finish_run_serializes_with_event_writer
.
Ran 1 test in 0.110s
OK

OK: symlinked runtime source is refused
OK: active runtime replacement lock is refused
OK: failed rollback preserves the previous runtime backup
```

### Final review residuals: RED

A second read-only review reproduced post-finish mutation, following reads of
runtime-owned JSON symlinks, FIFO blocking, and a target-appearance installer
race. Six Python regressions failed before the final production changes:

```text
test_record_event_rejects_symlinked_manifest_file
FAIL: ValueError not raised

test_record_event_rejects_fifo_events_file_without_blocking
FAIL: opening a non-regular events file blocked waiting for a FIFO reader

test_plan_writer_rejects_completed_run_without_mutating_state
test_artifact_writer_rejects_completed_run_without_mutating_state
test_verify_writer_rejects_completed_run_without_mutating_state
FAIL: ValueError not raised

test_semantic_writer_rejects_symlinked_verification_file
FAIL: ValueError not raised
```

The installer regressions also failed before the final change:

```text
active-lock smoke: missing stale-lock recovery guidance
target-appearance failure: previous runtime backup was deleted
nested mv race: existing valid-looking directory could mask a nested install
```

### Final review residuals: focused GREEN

```text
......
Ran 6 tests in 0.012s
OK

OK: active runtime replacement lock is refused
OK: failed rollback preserves the previous runtime backup
```

The rollback smoke includes three injected `mv` paths: install and restore both
fail, a target appears while install fails, and a target appears while portable
`mv` would otherwise nest the staged package.

## Final verification

### Runtime suite

Command:

```bash
PYTHONPATH=skills/brain-init/runtime \
  python3 -m unittest discover -s skills/brain-init/runtime/tests -v
```

Result:

```text
Ran 68 tests in 2.784s
OK
```

### Static and repository checks

- All Python files: `python3 -m py_compile` — passed.
- Both shell scripts: `bash -n` — passed.
- CI workflow: `yaml.safe_load(.github/workflows/ci.yml)` — passed.
- Plugin, marketplace, hooks, and settings JSON parsing — passed.
- All 18 schemas — valid YAML.
- All 12 `SKILL.md` files — valid frontmatter.
- Version gate — four changed versioned files correctly bumped:
  `marketplace.json`, `plugin.json`, `brain-init/SKILL.md`, and capture
  `SKILL.md`.
- `git diff --check` for the fix wave and the full review range — passed.

### CI smoke matrix

All twelve repository smoke steps were extracted from
`.github/workflows/ci.yml` and executed locally:

```text
Validation: 18 passed, 0 failed
Standalone validator: 68 passed, 0 failed, 9 allowlisted warnings
OK: legacy missing runtime remains warning-only
OK: shadow rejection preserved the invalid canonical artifact
OK: all 5 presets scaffolded successfully
OK: --domain-custom + --name scaffolded successfully
OK: bare scaffold verified (no harness files)
OK: --force merged into non-empty directory
OK: legacy upgrade replaced runtime, migrated ownership, and preserved state
OK: upgrade refuses symlinked runtime ownership
OK: force install refuses symlinked runtime ownership
OK: symlinked runtime source is refused
OK: active runtime replacement lock is refused
OK: failed rollback preserves the previous runtime backup
```

The full scaffold also imported the installed runtime and reported runtime
version `0.1.0`.

### Synthetic capture walkthrough

A fresh full vault was used for real CLI start, plan, event, declare, verify,
finish, and upgrade operations:

```text
FINAL_ACCEPTANCE=PASS
VALID=Runtime shadow: ACCEPT (0 critical, 1 warning)
INVALID=Runtime shadow: REJECT (1 critical, 0 warnings)
```

The walkthrough additionally asserted:

- the valid run contained required lifecycle events, artifact SHA-256 values,
  plan state, zero automatically created workers, and no forbidden trace keys;
- the invalid canonical wiki artifact remained byte-preserved after rejection;
- upgrade preserved both run directories and human evaluation labels while
  replacing a stale runtime sentinel; and
- the upgraded runtime remained importable.

## Final independent review

Two final read-only re-reviews reported no remaining Critical or Important
findings. Both independently confirmed terminal-state serialization,
no-follow/nonblocking runtime-file handling, installer source and destination
validation, nesting detection, and backup preservation. Their fresh checks also
reported 68/68 runtime tests, shell syntax, CI YAML, and diff checks passing.

## Residual concerns

None known. The runtime remains intentionally shadow-only: verification reports
accept or reject, while canonical artifact mutation remains outside this
instrumentation layer.
