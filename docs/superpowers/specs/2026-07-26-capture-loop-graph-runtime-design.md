# Capture Loop-Graph Runtime — Design

**Date:** 2026-07-26

**Status:** Approved design

**Scope:** `second-brain-capture` pilot only; runtime interfaces are intentionally operation-agnostic so `reconcile`, `investigate`, and `synthesize` can adopt them later.

## 1. Goal

Add the useful disciplines from `Archive228/loop-graph-harness` to the Industrial Intelligence Brain **without creating a second agent framework**.

Claude Code remains responsible for reasoning, tools, subagents, and context windows. A small Python runtime adds deterministic control around those capabilities:

- run lifecycle and manifests;
- verification contracts;
- verify/retry feedback structures;
- fan-out advice and budgets;
- structured tracing;
- clean worker handoff contracts;
- independent verification hooks;
- future grader calibration.

The first release is **capture-only shadow mode**. Existing `second-brain-capture` remains authoritative. The runtime observes, records, verifies, and reports what it would have accepted or rejected, but it does not block or mutate the current capture result.

## 2. Non-goals

This pilot will not:

- replace Claude Code's `Agent(...)` mechanism;
- implement its own LLM client, scheduler, or agent framework;
- make graphs the default execution model;
- change canonical wiki schemas merely to fit the runtime;
- automatically repair or overwrite wiki pages in shadow mode;
- wrap `reconcile`, `investigate`, or `synthesize` yet;
- introduce n8n as a dependency of the runtime.

n8n remains external legwork infrastructure. The brain runtime governs intelligence-work execution inside the initialized vault.

## 3. Core design rule

> **Claude reasons; Python enforces invariants.**

The runtime must never duplicate reasoning already expressed in skills or agents. It should encode only what benefits from deterministic execution: contracts, budgets, state, traces, validation, and run control.

The conceptual stack is:

```text
Brain harness
  └── operation graph
       └── worker loop
            gather -> act -> verify -> feedback
```

For v1, only the capture adapter is implemented.

## 4. Rollout model

### Phase 1 — shadow mode (this design)

`/second-brain-capture` continues its current workflow and writes the wiki exactly as today.

The runtime:

1. starts a capture run;
2. records source/profile/run metadata;
3. receives the compact high-signal section map;
4. computes a non-binding single-vs-fan-out recommendation;
5. records worker/subagent events when the skill delegates work;
6. records the set of pages created or modified;
7. verifies the completed capture;
8. writes a structured verification report and concise comparison summary;
9. never blocks or rewrites the capture.

### Phase 2 — active mode (future, explicitly out of v1)

Once the verifier is calibrated, the same contracts support:

```text
stage -> verify -> feedback/retry -> verify -> commit
```

Canonical wiki mutation occurs only after acceptance. No runtime interface introduced in the pilot should need redesign to enable this.

## 5. Runtime location and ownership

### Plugin source

```text
skills/brain-init/runtime/
└── brain_runtime/
    ├── __init__.py
    ├── cli.py
    ├── contracts.py
    ├── run.py
    ├── trace.py
    ├── budget.py
    ├── verify.py
    └── adapters/
        ├── __init__.py
        └── capture.py
```

### Initialized vault

```text
.brain/
├── runtime/              # vendor-owned runtime copied by brain-init
├── runs/                 # generated execution records; gitignored by default
│   └── <run-id>/
│       ├── manifest.json
│       ├── events.jsonl
│       ├── plan.json
│       ├── artifacts.json
│       └── verification.json
└── evals/                # later human-labelled verifier fixtures
```

`.brain/runtime/` is harness-owned and upgradeable. `.brain/runs/` is generated state and must never be treated as canonical knowledge.

## 6. General runtime contracts

The interfaces are operation-agnostic from day one.

### `RunSpec`

```json
{
  "operation": "capture",
  "mode": "shadow",
  "input_refs": ["raw/10k/example.pdf"],
  "profile": "annual-report-v1",
  "budget": {
    "max_workers": 4,
    "max_attempts": 3
  }
}
```

Future operations can use the same shape with operation-specific metadata.

### `ArtifactRef`

Represents an input or output without loading its content into the orchestrator context.

```json
{
  "kind": "claim",
  "path": "wiki/claims/claim-example.md",
  "sha256": "..."
}
```

### `FanoutDecision`

```json
{
  "mode": "single",
  "reason": "fits bounded context",
  "slices": [],
  "max_workers": 1
}
```

or:

```json
{
  "mode": "fanout",
  "reason": "independent Tier-1 sections exceed one practical context",
  "slices": [
    {"id": "business", "range": "420:610"},
    {"id": "mda", "range": "1820:2350"},
    {"id": "segments", "range": "3110:3440"}
  ],
  "max_workers": 3
}
```

The decision is advisory in shadow mode and binding only in a future active mode.

### `VerificationReport`

```json
{
  "accepted": false,
  "checks": [
    {"id": "claim.required_fields", "passed": true, "severity": "critical"},
    {"id": "evidence.locator_resolves", "passed": false, "severity": "critical"}
  ],
  "failures": [
    {
      "check": "evidence.locator_resolves",
      "artifact": "wiki/claims/claim-example.md",
      "message": "source passage could not be resolved"
    }
  ]
}
```

Failure text is deliberately structured so it can later become retry context without passing the entire previous attempt back to a worker.

### `TraceEvent`

Every event is append-only JSONL:

```json
{"ts":"...","kind":"verify.check","operation":"capture","run_id":"...","label":"evidence.locator_resolves","passed":false}
```

Event payloads must be compact; full source passages and model transcripts do not belong in the trace.

## 7. Capture adapter

The runtime wraps the existing capture workflow at explicit checkpoints rather than rewriting it.

### Checkpoint A — start

After source type/profile resolution:

```text
brain-runtime start --operation capture --mode shadow ...
```

Returns a `run_id` and writes `manifest.json`.

### Checkpoint B — section plan

After the existing heading-first locator produces the compact section map, the capture skill passes **only the map**, not the full report, to the runtime planner.

Inputs include:

- source type;
- profile;
- number of Tier 1/Tier 2 ranges;
- approximate bounded range sizes;
- whether ranges are semantically independent;
- configured worker budget.

The planner writes `plan.json` and returns `single` or `fanout` advice.

The planner does **not** judge financial materiality. Materiality remains a reasoning/policy concern.

### Checkpoint C — worker handoff

When capture uses a Claude subagent, every worker gets a bounded task contract:

```yaml
operation: capture
slice_id: mda
source_ref: raw/10k/example.md
range: 1820:2350
profile: annual-report-v1
questions:
  - What changed in revenue and why?
  - What changed in margin and why?
return:
  - candidate_claims
  - evidence_refs
  - followups
  - uncertainties
```

Workers do not inherit the orchestrator's accumulated research context. They receive the task, bounded material reference/range, and required output contract.

The worker returns distilled structured findings, not narrative chain-of-thought or full source text.

### Checkpoint D — artifact declaration

Immediately before current capture completion, the skill declares the files it created or modified. The runtime stores them in `artifacts.json` with hashes.

This makes verification scope explicit and prevents a verifier from silently scanning unrelated parts of the vault.

### Checkpoint E — shadow verification

The runtime verifies the declared capture artifacts and writes `verification.json`.

The normal capture result remains authoritative regardless of shadow verdict.

The command output adds only a concise line such as:

```text
Runtime shadow: REJECT (2 critical, 1 warning) — .brain/runs/<id>/verification.json
```

No verbose verification dump is injected into the main Claude context unless the agent needs to inspect a failure.

## 8. Verification strategy

Verification uses **diverse signals**, not one monolithic grader.

### Tier 1 — deterministic structural checks

These should become the strongest gates because they are objective and reproducible:

- valid frontmatter/YAML;
- page type matches expected schema;
- required fields exist;
- enum values are valid;
- every claim has `source_evidence`;
- referenced source page exists;
- evidence locator resolves where mechanically possible;
- claim/source IDs are unique;
- mandatory source ↔ company bidirectional link exists;
- declared output contract is satisfied;
- only declared artifacts are evaluated;
- source and converted-markdown provenance/checksums are present when available.

The implementation should reuse these checks later as the basis of a repository-wide `brain-check` command rather than creating separate validation logic.

### Tier 2 — deterministic workflow checks

- section map exists for long annual reports/10-Ks;
- annual-report capture used a recognized extraction profile;
- qmd refresh completed or is explicitly reported as unavailable;
- completed capture log exists;
- artifact hashes were recorded.

### Tier 3 — semantic independent checks

Only use a fresh Claude verifier for questions rules cannot reliably answer, such as:

- does the evidence actually support the candidate claim?
- is the claim material under `config/materiality.md`?
- did the capture introduce a likely duplicate of an existing claim?
- does the source summary materially misrepresent the source?

The semantic verifier sees the artifact, the minimum cited evidence, and the rubric. It must not see the producing worker's rationale or conversation history.

In shadow v1, semantic verification is optional/configurable so the deterministic verifier can be evaluated independently.

## 9. Fan-out policy

Fan-out is a costed exception, not the default.

Recommend `fanout` only when all are true:

1. there are at least two independently answerable source slices;
2. those slices can be processed without shared mutable state;
3. the work would otherwise create excessive context pressure **or** has high enough value to justify the overhead;
4. worker budget remains available.

For capture, high-signal annual-report sections are a natural candidate because `Business`, `MD&A`, `Segments`, and `R&D` can often be read independently before candidate claims are merged.

Do not fan out:

- small documents;
- entity resolution;
- final page mutation;
- duplicate/contradiction reconciliation requiring shared canonical state;
- tasks where each worker depends heavily on the previous worker's result.

The final merge remains a single orchestrator responsibility.

## 10. Budget model

The first budget model is intentionally simple:

```yaml
max_workers: 4
max_attempts: 3
max_semantic_verifier_calls: 1
```

The runtime also records proxy cost signals such as:

- worker count;
- section/range bytes assigned;
- verifier calls;
- loop attempts.

It does not attempt to emulate provider billing.

In shadow mode, budget exhaustion produces a trace/report warning only. In future active mode, it becomes fail-closed for the affected runtime stage.

## 11. Retry interface

The pilot defines retry semantics but does not yet apply repair mutations.

A failed verifier produces compact feedback:

```json
{
  "attempt": 1,
  "retryable": true,
  "failures": [
    {
      "artifact": "claim-example.md",
      "check": "evidence.locator_resolves",
      "message": "locator points outside source range"
    }
  ]
}
```

Future active mode passes only this feedback plus the affected artifact/material reference into a fresh repair worker.

This contract is important now because it prevents future retry loops from reinjecting the entire previous context.

## 12. Observability

Each run should answer five questions without reading a Claude transcript:

1. What operation ran?
2. What inputs and profile were used?
3. Was fan-out recommended/used?
4. What artifacts changed?
5. What checks passed or failed?

Required event kinds for the pilot:

```text
run.start
plan.section_map
plan.fanout
worker.start
worker.finish
artifact.declare
verify.start
verify.check
verify.finish
run.finish
```

Tracing must remain local, append-only, grep-friendly JSONL.

## 13. Human calibration and graduation criteria

Shadow mode exists to measure whether the verifier deserves authority.

After representative captures, a human can label verifier findings as:

- true positive;
- false positive;
- false negative;
- not applicable.

A later `evals` command can calculate agreement by check/rubric. The contract for storing these labels should be compatible with `.brain/evals/`, but the UI/tooling is not required in the first implementation.

The runtime may graduate from shadow to active capture control only when:

- deterministic critical checks have regression fixtures and pass consistently;
- no known schema/status/command drift remains in the checks;
- semantic verifier false-positive behavior is acceptable on representative annual reports, patents, and industry reports;
- active mode has a staging/commit boundary so rejected output cannot partially mutate canonical wiki state.

No fixed number of runs is hard-coded; graduation is evidence-based.

## 14. Error handling

### Runtime unavailable

Capture proceeds exactly as before and emits a concise warning. Shadow instrumentation must never make the existing workflow unusable.

### Runtime internal error

Write the error to the run trace when possible; do not retry blindly and do not block capture.

### Verifier rejects output

Record the verdict and failures. Do not mutate or roll back canonical pages in shadow mode.

### qmd unavailable

Treat as an operational warning, not proof that the captured knowledge is invalid. Structural verification still runs.

### Semantic verifier unavailable

Record `skipped` with reason; deterministic verification remains valid.

## 15. Testing strategy

### Unit tests

- contract serialization/deserialization;
- fan-out decision boundaries;
- budget exhaustion;
- trace JSONL output;
- claim schema/required-field checks;
- invalid status enum rejection;
- source evidence resolution;
- bidirectional link validation.

### Fixture tests

Add synthetic capture fixtures covering:

- valid annual-report capture;
- claim missing `source_evidence`;
- invalid claim status;
- broken evidence locator;
- missing company backlink;
- duplicate claim ID;
- long report section map that should recommend fan-out;
- small report that must stay single-worker.

### Integration test

Run brain-init into a temporary vault, execute the verifier against a synthetic completed capture, and assert:

- `.brain/runs/<id>/` is created;
- manifest and event trace are valid;
- artifact hashes are stable;
- expected failures appear in `verification.json`;
- shadow rejection does not alter or delete captured wiki files.

### Backward-compatibility test

A capture performed with the runtime disabled must still follow the current capture contract.

## 16. Upgrade path to shared runtime

The runtime core must not contain capture-specific branches. Operation-specific behavior lives behind adapters:

```text
brain_runtime/adapters/capture.py
brain_runtime/adapters/reconcile.py      # future
brain_runtime/adapters/investigate.py    # future
brain_runtime/adapters/synthesize.py     # future
```

All operations share:

- `RunSpec`;
- `ArtifactRef`;
- `VerificationReport`;
- `TraceEvent`;
- budget interface;
- loop feedback contract;
- fan-out decision interface.

Future mappings are straightforward:

```text
capture      locate/read -> extract -> verify
reconcile    compare -> classify -> verify manifest
investigate  retrieve -> analyze -> adversarial verify
synthesize   compose -> evidence audit -> verify
```

The pilot is therefore narrow in **behavior**, not narrow in **architecture**.

## 17. Acceptance criteria for the pilot

The implementation is complete when all are true:

1. `second-brain-capture` works unchanged when the runtime is unavailable or disabled.
2. Shadow mode creates one structured run directory per capture.
3. The runtime can ingest a compact high-signal section map without receiving the full source text.
4. Fan-out advice is recorded but does not alter authoritative behavior.
5. Created/modified capture artifacts are explicitly declared and hashed.
6. Deterministic verification produces machine-readable pass/fail results.
7. Shadow rejection cannot block, roll back, or rewrite canonical wiki artifacts.
8. Traces contain no chain-of-thought and avoid full source-body duplication.
9. Runtime modules contain no LLM/provider implementation.
10. Capture-specific policy is isolated in the capture adapter.
11. Tests cover valid and invalid capture fixtures plus runtime-disabled backward compatibility.
12. The interfaces can support a future staged active mode without changing their public shapes.

## 18. Key design decisions

- **Hybrid**, not a Python agent framework.
- **Capture first**, but shared contracts from day one.
- **Shadow first**, active enforcement only after calibration.
- **Rule-first verification**, independent model verifier only for semantic judgments.
- **Fan-out by policy**, never by reflex.
- **Clean handoffs**, compact artifacts, no inherited research transcript.
- **Trace runs outside the wiki**, keeping operational state separate from canonical knowledge.
- **Future fail-closed active mode**, but no blocking behavior in the pilot.
