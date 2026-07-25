# Capture Loop-Graph Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a capture-only, shadow-mode loop/graph runtime that gives `second-brain-capture` deterministic run state, fan-out advice, artifact hashing, verification, retry feedback, and traces without replacing Claude Code's reasoning or agent system.

**Architecture:** Claude Code remains the reasoning/orchestration layer. A small Python 3.11 runtime under `skills/brain-init/runtime/brain_runtime/` owns only deterministic contracts, run files, budgets, fan-out policy, verification, and tracing. `second-brain-capture` calls that runtime at explicit checkpoints; any runtime failure or rejection is observational only and never blocks the existing capture workflow.

**Tech Stack:** Python 3.11 standard library, PyYAML, Bash, Claude Code skills, JSON/JSONL, existing GitHub Actions CI.

## Global Constraints

- Runtime mode for this release is `shadow`; `off` is supported as an explicit disable value. No active/blocking mode is implemented.
- Claude Code continues to own model calls, tools, subagents, and context windows. The runtime contains no LLM/provider SDK and no scheduler.
- Python runtime dependencies are standard library + `PyYAML` only; do not add Pydantic, LangGraph, CrewAI, or another agent framework.
- Default budget is exactly `max_workers: 4`, `max_attempts: 3`, `max_semantic_verifier_calls: 1`.
- Runtime-generated state lives under `.brain/runs/` and is gitignored by default. `.brain/runtime/` is harness-owned/upgradeable. `.brain/evals/` is preserved across upgrades.
- Traces are append-only, grep-friendly JSONL and must not contain chain-of-thought, full model transcripts, or full source bodies.
- Capture-specific rules live in `brain_runtime/adapters/capture.py`; generic runtime modules must not branch on `operation == "capture"`.
- A shadow verifier rejection returns a successful process exit if verification itself ran correctly; rejection is data, not a runtime error.
- If the runtime is missing, disabled, or errors internally, `second-brain-capture` completes exactly as it does today.
- Fan-out remains advisory in this release. It never changes how many Claude subagents are actually spawned.
- Semantic verification is a feed-in contract only in this pilot. The runtime accepts an externally produced semantic report but does not call a model itself.
- Current Claude Code skill naming is flat: `/second-brain-capture`, `/second-brain-lint`, etc. Do not introduce the deprecated `/second-brain:capture` form.
- Keep shell changes portable across macOS and Linux; do not add GNU-only parsing to the runtime integration.

---

## File Structure

Create these focused runtime files:

```text
skills/brain-init/runtime/
├── brain_runtime/
│   ├── __init__.py          # runtime package version only
│   ├── contracts.py         # serializable operation-agnostic dataclasses
│   ├── trace.py             # compact append-only TraceEvent JSONL
│   ├── run.py               # run lifecycle, manifests, artifact declaration/hashing
│   ├── budget.py            # fan-out decision + budget accounting helpers
│   ├── verify.py            # generic verification engine + report persistence
│   ├── cli.py               # start/plan/event/declare/verify/semantic/finish commands
│   └── adapters/
│       ├── __init__.py
│       └── capture.py       # capture-specific artifact rules and verification checks
└── tests/
    ├── __init__.py
    ├── helpers.py
    ├── test_contracts_run.py
    ├── test_budget.py
    ├── test_capture_verify.py
    ├── test_cli.py
    └── fixtures/
        ├── valid-claim.md
        ├── invalid-claim-no-source.md
        ├── invalid-claim-status.md
        ├── valid-source.md
        ├── valid-company.md
        ├── example-annual-report.md
        ├── section-map-fanout.json
        └── section-map-single.json
```

Modify these existing integration files:

```text
skills/brain-init/scripts/brain-init.sh
skills/brain-init/scripts/validate-vault.sh
skills/brain-init/bundles/second-brain/capture/SKILL.md
.github/workflows/ci.yml
.claude-plugin/plugin.json
.claude-plugin/marketplace.json
skills/brain-init/SKILL.md
README.md
```

Do not create a second orchestration configuration language. Runtime inputs are small JSON files or CLI arguments derived from the existing capture workflow.

---

### Task 1: Runtime Contracts, Tracing, and Run Lifecycle

**Files:**
- Create: `skills/brain-init/runtime/brain_runtime/__init__.py`
- Create: `skills/brain-init/runtime/brain_runtime/contracts.py`
- Create: `skills/brain-init/runtime/brain_runtime/trace.py`
- Create: `skills/brain-init/runtime/brain_runtime/run.py`
- Create: `skills/brain-init/runtime/tests/__init__.py`
- Create: `skills/brain-init/runtime/tests/test_contracts_run.py`

**Interfaces:**
- Produces: `BudgetSpec`, `RunSpec`, `ArtifactRef`, `FanoutDecision`, `CheckResult`, `VerificationReport`, `RetryFeedback`, `TraceEvent`.
- Produces: `create_run(vault: Path, spec: RunSpec) -> str`, `finish_run(vault: Path, run_id: str, shadow_verdict: bool | None = None) -> None`.
- Produces: `append_event(run_dir: Path, event: TraceEvent) -> None`, `read_events(run_dir: Path) -> list[TraceEvent]`.
- Later tasks depend on the JSON field names defined here; do not rename them after this task.

- [ ] **Step 1: Write contract round-trip tests**

Create `test_contracts_run.py` with these first tests:

```python
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from brain_runtime.contracts import BudgetSpec, RetryFeedback, RunSpec
from brain_runtime.run import create_run, finish_run
from brain_runtime.trace import read_events


class ContractRunTests(unittest.TestCase):
    def test_run_spec_round_trip(self):
        spec = RunSpec(
            operation="capture",
            mode="shadow",
            input_refs=["raw/annual-reports/acme-2025.pdf"],
            profile="annual-report-v1",
            budget=BudgetSpec(),
            metadata={"source_type": "annual-report"},
        )
        restored = RunSpec.from_dict(spec.to_dict())
        self.assertEqual(restored, spec)

    def test_retry_feedback_is_compact_and_serializable(self):
        feedback = RetryFeedback(
            attempt=1,
            retryable=True,
            failures=[{
                "artifact": "wiki/claims/claim-acme.md",
                "check": "evidence.locator_resolves",
                "message": "passage not found in converted markdown",
            }],
        )
        payload = feedback.to_dict()
        self.assertEqual(payload["attempt"], 1)
        self.assertNotIn("messages", payload)
        self.assertNotIn("transcript", payload)
```

- [ ] **Step 2: Write failing run-lifecycle tests**

Append:

```python
    def test_create_run_writes_manifest_and_start_event(self):
        with TemporaryDirectory() as td:
            vault = Path(td)
            src = vault / "raw/annual-reports/acme-2025.pdf"
            src.parent.mkdir(parents=True)
            src.write_bytes(b"fixture-pdf")
            spec = RunSpec(
                operation="capture",
                mode="shadow",
                input_refs=["raw/annual-reports/acme-2025.pdf"],
                profile="annual-report-v1",
                budget=BudgetSpec(),
            )

            run_id = create_run(vault, spec)
            run_dir = vault / ".brain/runs" / run_id
            manifest = json.loads((run_dir / "manifest.json").read_text())

            self.assertEqual(manifest["operation"], "capture")
            self.assertEqual(manifest["mode"], "shadow")
            self.assertEqual(len(manifest["inputs"]), 1)
            self.assertRegex(manifest["inputs"][0]["sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(read_events(run_dir)[0].kind, "run.start")

    def test_finish_run_marks_manifest_completed(self):
        with TemporaryDirectory() as td:
            vault = Path(td)
            spec = RunSpec("capture", "shadow", [], "annual-report-v1", BudgetSpec())
            run_id = create_run(vault, spec)
            finish_run(vault, run_id, shadow_verdict=False)
            manifest = json.loads((vault / ".brain/runs" / run_id / "manifest.json").read_text())
            self.assertEqual(manifest["status"], "completed")
            self.assertFalse(manifest["shadow_verdict"])
            self.assertEqual(read_events(vault / ".brain/runs" / run_id)[-1].kind, "run.finish")
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```bash
PYTHONPATH=skills/brain-init/runtime \
python3 -m unittest skills.brain-init.runtime.tests.test_contracts_run -v
```

Because the directory name `brain-init` is not importable as a Python package, use the discovery form in practice:

```bash
PYTHONPATH=skills/brain-init/runtime \
python3 -m unittest discover -s skills/brain-init/runtime/tests -p 'test_contracts_run.py' -v
```

Expected: import failure because `brain_runtime` does not exist yet.

- [ ] **Step 4: Implement the serializable contracts**

In `contracts.py`, implement dataclasses with exact public fields:

```python
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
        payload = asdict(self)
        return payload

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


@dataclass(frozen=True)
class FanoutDecision:
    mode: str
    reason: str
    slices: list[dict[str, Any]]
    max_workers: int


@dataclass(frozen=True)
class CheckResult:
    id: str
    passed: bool
    severity: str
    artifact: str | None = None
    message: str = ""
    source: str = "deterministic"


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


@dataclass(frozen=True)
class RetryFeedback:
    attempt: int
    retryable: bool
    failures: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
```

Add `to_dict()` helpers to `ArtifactRef`, `FanoutDecision`, `CheckResult`, and `VerificationReport` using `asdict()` so persistence code never reaches into dataclass internals.

- [ ] **Step 5: Implement compact trace events**

In `trace.py`, implement:

```python
FORBIDDEN_TRACE_KEYS = {
    "messages", "transcript", "chain_of_thought", "source_text", "material", "full_text"
}
MAX_EVENT_BYTES = 8192

@dataclass(frozen=True)
class TraceEvent:
    ts: str
    kind: str
    operation: str
    run_id: str
    label: str
    data: dict[str, Any] = field(default_factory=dict)
```

`append_event()` must:

1. reject any forbidden key in `event.data`;
2. serialize one JSON object per line;
3. reject serialized events over `MAX_EVENT_BYTES`;
4. append to `<run_dir>/events.jsonl` without rewriting prior lines.

`read_events()` must parse each non-empty line back into `TraceEvent` objects.

- [ ] **Step 6: Implement run creation and completion**

In `run.py`, implement these exact helpers:

```python
def sha256_file(path: Path) -> str: ...
def run_dir_for(vault: Path, run_id: str) -> Path: ...
def create_run(vault: Path, spec: RunSpec) -> str: ...
def load_manifest(vault: Path, run_id: str) -> dict[str, Any]: ...
def save_manifest(vault: Path, run_id: str, manifest: dict[str, Any]) -> None: ...
def finish_run(vault: Path, run_id: str, shadow_verdict: bool | None = None) -> None: ...
```

Run IDs must match:

```text
YYYYMMDDTHHMMSSZ-<operation>-<8 lowercase hex chars>
```

`create_run()` must create `.brain/runs/<run-id>/`, hash each existing `input_ref`, write `manifest.json`, and emit `run.start`. The manifest must include:

```json
{
  "run_id": "...",
  "runtime_version": "0.1.0",
  "operation": "capture",
  "mode": "shadow",
  "profile": "annual-report-v1",
  "status": "running",
  "started_at": "...",
  "completed_at": null,
  "budget": {"max_workers": 4, "max_attempts": 3, "max_semantic_verifier_calls": 1},
  "inputs": [{"path": "raw/...", "sha256": "..."}],
  "metadata": {},
  "metrics": {"workers": 0, "attempts": 0, "semantic_verifier_calls": 0}
}
```

Use atomic JSON replacement (`tempfile.NamedTemporaryFile` in the same directory + `Path.replace`) for manifest rewrites.

- [ ] **Step 7: Add package version and rerun tests**

`brain_runtime/__init__.py`:

```python
__version__ = "0.1.0"
```

Run:

```bash
PYTHONPATH=skills/brain-init/runtime \
python3 -m unittest discover -s skills/brain-init/runtime/tests -p 'test_contracts_run.py' -v
```

Expected: all Task 1 tests PASS.

- [ ] **Step 8: Commit Task 1**

```bash
git add skills/brain-init/runtime/brain_runtime \
        skills/brain-init/runtime/tests/test_contracts_run.py \
        skills/brain-init/runtime/tests/__init__.py
git commit -m "feat(runtime): add run contracts and tracing"
```

---

### Task 2: Fan-Out Advice and Budget Discipline

**Files:**
- Create: `skills/brain-init/runtime/brain_runtime/budget.py`
- Create: `skills/brain-init/runtime/tests/test_budget.py`

**Interfaces:**
- Consumes: `BudgetSpec`, `FanoutDecision` from Task 1.
- Produces: `FanoutRequest`, `advise_fanout(request: FanoutRequest, budget: BudgetSpec) -> FanoutDecision`.
- Produces: `record_budget_metric(manifest: dict, metric: str, increment: int = 1) -> dict` for later CLI event accounting.

- [ ] **Step 1: Write fan-out decision tests**

Create `test_budget.py`:

```python
import unittest
from brain_runtime.budget import FanoutRequest, advise_fanout
from brain_runtime.contracts import BudgetSpec


class BudgetTests(unittest.TestCase):
    def test_one_slice_stays_single(self):
        req = FanoutRequest(
            slices=[{"id": "mda"}],
            parallelizable=True,
            exceeds_one_context=True,
            high_value=True,
        )
        decision = advise_fanout(req, BudgetSpec())
        self.assertEqual(decision.mode, "single")
        self.assertEqual(decision.max_workers, 1)

    def test_dependent_slices_stay_single(self):
        req = FanoutRequest(
            slices=[{"id": "business"}, {"id": "mda"}],
            parallelizable=False,
            exceeds_one_context=True,
            high_value=True,
        )
        self.assertEqual(advise_fanout(req, BudgetSpec()).mode, "single")

    def test_parallel_context_pressure_recommends_fanout(self):
        req = FanoutRequest(
            slices=[{"id": "business"}, {"id": "mda"}, {"id": "segments"}],
            parallelizable=True,
            exceeds_one_context=True,
            high_value=False,
        )
        decision = advise_fanout(req, BudgetSpec(max_workers=2))
        self.assertEqual(decision.mode, "fanout")
        self.assertEqual(decision.max_workers, 2)

    def test_parallel_low_value_work_that_fits_context_stays_single(self):
        req = FanoutRequest(
            slices=[{"id": "business"}, {"id": "mda"}],
            parallelizable=True,
            exceeds_one_context=False,
            high_value=False,
        )
        self.assertEqual(advise_fanout(req, BudgetSpec()).mode, "single")
```

- [ ] **Step 2: Run and verify failure**

```bash
PYTHONPATH=skills/brain-init/runtime \
python3 -m unittest discover -s skills/brain-init/runtime/tests -p 'test_budget.py' -v
```

Expected: FAIL because `brain_runtime.budget` does not exist.

- [ ] **Step 3: Implement the policy exactly once**

In `budget.py`:

```python
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
        return FanoutDecision("single", "fits bounded context and fan-out cost is not justified", request.slices, 1)
    workers = min(n, budget.max_workers)
    return FanoutDecision(
        "fanout",
        "parallel slices plus context pressure or high value justify fan-out",
        request.slices,
        workers,
    )
```

Do not add token-price simulation. The runtime records proxy counts only.

- [ ] **Step 4: Add budget metric helper**

`record_budget_metric()` accepts only `workers`, `attempts`, or `semantic_verifier_calls`; return a copied manifest with the selected metric incremented. Invalid metric names raise `ValueError`.

- [ ] **Step 5: Run tests**

```bash
PYTHONPATH=skills/brain-init/runtime \
python3 -m unittest discover -s skills/brain-init/runtime/tests -p 'test_budget.py' -v
```

Expected: PASS.

- [ ] **Step 6: Commit Task 2**

```bash
git add skills/brain-init/runtime/brain_runtime/budget.py \
        skills/brain-init/runtime/tests/test_budget.py
git commit -m "feat(runtime): add costed fanout policy"
```

---

### Task 3: Artifact Declaration and Deterministic Capture Verification

**Files:**
- Create: `skills/brain-init/runtime/brain_runtime/verify.py`
- Create: `skills/brain-init/runtime/brain_runtime/adapters/__init__.py`
- Create: `skills/brain-init/runtime/brain_runtime/adapters/capture.py`
- Modify: `skills/brain-init/runtime/brain_runtime/run.py`
- Create: `skills/brain-init/runtime/tests/helpers.py`
- Create: `skills/brain-init/runtime/tests/test_capture_verify.py`
- Create fixtures under: `skills/brain-init/runtime/tests/fixtures/`

**Interfaces:**
- Consumes: `ArtifactRef`, `CheckResult`, `VerificationReport`.
- Produces: `declare_artifacts(vault: Path, run_id: str, paths: list[str]) -> list[ArtifactRef]`.
- Produces: `verify_run(vault: Path, run_id: str, adapter: VerificationAdapter) -> VerificationReport`.
- Produces capture adapter entry point: `capture_checks(vault: Path, run_dir: Path, artifacts: list[ArtifactRef]) -> list[CheckResult]`.
- Runtime verifier evaluates only paths present in `artifacts.json`.

- [ ] **Step 1: Add regression fixture contents**

Create `fixtures/valid-claim.md`:

```markdown
---
claim_id: claim-acme-revenue-12345678
claim_text: "Acme generated RMB 10 billion of revenue in 2025"
confidence: high
status: confirmed
source_evidence:
  - source: "[[src-acme-2025-annual-report]]"
    passage: "Revenue for 2025 was RMB 10 billion."
    context: "Page 12, Results of Operations"
first_seen: 2026-07-26
last_verified: 2026-07-26
last_reviewed: 2026-07-26
---
# Evidence
## Supporting
[[src-acme-2025-annual-report]]
```

Create `fixtures/invalid-claim-no-source.md` as the same frontmatter with `source_evidence: []`.

Create `fixtures/invalid-claim-status.md` as the valid claim with `status: supported`.

Create `fixtures/valid-source.md`:

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

When creating the actual file, remove the accidental leading spaces before `date_published`, `date_ingested`, and `last_reviewed` shown above so those are top-level YAML keys.

Create `fixtures/valid-company.md`:

```markdown
---
company_id: entity-acme
legal_name: Acme Corporation
last_reviewed: 2026-07-26
---
# Company Profile
Acme Corporation.

## Sources
[[src-acme-2025-annual-report]]
```

Create `fixtures/example-annual-report.md`:

```markdown
# Results of Operations
Revenue for 2025 was RMB 10 billion.
Operating margin improved because of pricing and mix.
```

Create `section-map-fanout.json`:

```json
{
  "slices": [
    {"id":"business","tier":1,"start":100,"end":420},
    {"id":"mda","tier":1,"start":900,"end":1600},
    {"id":"segments","tier":1,"start":2200,"end":2700}
  ],
  "parallelizable": true,
  "exceeds_one_context": true,
  "high_value": true
}
```

Create `section-map-single.json` with one `mda` slice and `parallelizable: true`, `exceeds_one_context: false`, `high_value: true`.

- [ ] **Step 2: Write a test helper that builds a minimal vault**

`tests/helpers.py` must expose:

```python
def build_capture_vault(root: Path, claim_fixture: str = "valid-claim.md") -> list[str]:
    """Create raw/, wiki/{claims,sources,companies}, templates/schemas and return declared wiki paths."""
```

It must copy the repository's existing `claim.yaml`, `source.yaml`, and `company.yaml` into `templates/schemas/`, create a dummy `raw/annual-reports/acme-2025-annual-report.pdf`, copy `example-annual-report.md` beside it, and populate the three wiki pages from fixtures.

- [ ] **Step 3: Write artifact safety and verification tests**

`test_capture_verify.py` must contain at least:

```python
class CaptureVerifyTests(unittest.TestCase):
    def test_declare_artifacts_hashes_only_vault_relative_files(self): ...
    def test_declare_artifacts_rejects_parent_traversal(self): ...
    def test_valid_capture_is_accepted(self): ...
    def test_missing_source_evidence_is_rejected(self): ...
    def test_invalid_claim_status_is_rejected(self): ...
    def test_missing_source_company_backlink_is_rejected(self): ...
    def test_missing_evidence_passage_is_rejected_when_markdown_exists(self): ...
    def test_two_claim_minimum_is_a_critical_output_contract_check(self): ...
```

For the valid fixture test, create a second valid claim by copying the first fixture and changing both filename and `claim_id`; this satisfies the capture minimum without introducing unrelated fixture prose.

Expected critical check IDs used by assertions:

```text
artifact.exists
frontmatter.valid_yaml
claim.required_fields
claim.confidence_enum
claim.status_enum
claim.source_evidence
claim.source_page_exists
evidence.locator_resolves
source.required_fields
source.enum_values
source.company_link
company.source_backlink
capture.claim_count_min
capture.source_count
capture.company_count
```

- [ ] **Step 4: Run and verify failure**

```bash
PYTHONPATH=skills/brain-init/runtime \
python3 -m unittest discover -s skills/brain-init/runtime/tests -p 'test_capture_verify.py' -v
```

Expected: FAIL because declaration and verification functions are not implemented.

- [ ] **Step 5: Implement artifact declaration with path confinement**

In `run.py`, add:

```python
def declare_artifacts(vault: Path, run_id: str, paths: list[str]) -> list[ArtifactRef]:
    ...
```

Requirements:

1. every path is interpreted relative to resolved `vault`;
2. reject absolute paths;
3. reject any resolved path outside `vault`;
4. require the file to exist;
5. classify `kind` from `wiki/<category>/...` (`claim`, `source`, `company`, otherwise the category singularized only when unambiguous; use `wiki_page` as safe fallback);
6. hash file bytes with SHA-256;
7. write `artifacts.json` as `{"artifacts": [...]}`;
8. emit `artifact.declare` with only count and relative paths, never file bodies.

- [ ] **Step 6: Implement the generic verifier shell**

In `verify.py`, define a protocol-like callable rather than a framework class hierarchy:

```python
VerificationAdapter = Callable[[Path, Path, list[ArtifactRef]], list[CheckResult]]


def verify_run(vault: Path, run_id: str, adapter: VerificationAdapter) -> VerificationReport:
    ...
```

`verify_run()` must:

- emit `verify.start`;
- load `artifacts.json` and call only the supplied adapter;
- emit one `verify.check` event per check with `passed`, `severity`, and check ID only;
- define acceptance as `no failed check where severity == "critical"`;
- build compact `failures` and `warnings` lists from failed checks;
- write `verification.json` atomically;
- emit `verify.finish` with accepted/critical/warning counts;
- return the report without raising merely because `accepted == False`.

- [ ] **Step 7: Implement capture-specific checks in the adapter**

In `adapters/capture.py`, keep required fields and enums explicit and small:

```python
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
```

Implement a local `read_frontmatter(path) -> tuple[dict, str]` using `yaml.safe_load` on the first `--- ... ---` block.

Evidence behavior:

- Parse `[[src-*]]` links from structured or legacy `source_evidence`.
- Resolve them to `wiki/sources/<link-target>.md`.
- For structured entries with a `passage`, read the source page's `raw_path`, derive the sibling `.md` path by replacing its suffix with `.md`, normalize whitespace in both strings, and require the passage to appear when that markdown file exists.
- If the converted `.md` does not exist, emit a **warning** `evidence.locator_resolves` with message `converted markdown unavailable; locator not mechanically checked` rather than a critical failure.
- Do not OCR or inspect PDFs inside the verifier.

Bidirectional link behavior:

- A source page must contain at least one `[[company-*]]` link.
- Each linked company page must exist and contain `[[<source-page-stem>]]` anywhere in its body. Do not enforce `## Source` versus `## Sources`; the link is the invariant.

Output-contract behavior:

- exactly one declared source page is critical;
- at least one declared company page is critical;
- fewer than two declared claim pages is critical;
- more than six claims is a warning, not a rejection, because materiality may justify additional claims.

Other declared wiki page types receive YAML-parse + `last_reviewed` checks only; do not duplicate all 18 schemas in this pilot.

- [ ] **Step 8: Run verifier tests**

```bash
PYTHONPATH=skills/brain-init/runtime \
python3 -m unittest discover -s skills/brain-init/runtime/tests -p 'test_capture_verify.py' -v
```

Expected: PASS.

- [ ] **Step 9: Commit Task 3**

```bash
git add skills/brain-init/runtime/brain_runtime/run.py \
        skills/brain-init/runtime/brain_runtime/verify.py \
        skills/brain-init/runtime/brain_runtime/adapters \
        skills/brain-init/runtime/tests/helpers.py \
        skills/brain-init/runtime/tests/test_capture_verify.py \
        skills/brain-init/runtime/tests/fixtures
git commit -m "feat(runtime): verify capture artifacts deterministically"
```

---

### Task 4: Runtime CLI and Semantic Feed-In Contract

**Files:**
- Create: `skills/brain-init/runtime/brain_runtime/cli.py`
- Create: `skills/brain-init/runtime/tests/test_cli.py`
- Modify: `skills/brain-init/runtime/brain_runtime/verify.py`
- Modify: `skills/brain-init/runtime/brain_runtime/run.py`

**Interfaces:**
- CLI commands: `start`, `plan`, `event`, `declare`, `verify`, `semantic`, `finish`.
- All commands accept `--vault` explicitly; no command depends on the caller's home directory.
- `start` prints only the run ID on stdout when successful.
- `verify` prints a one-line shadow verdict and exits `0` whether accepted or rejected; internal/runtime errors exit non-zero.

- [ ] **Step 1: Write CLI end-to-end tests using `subprocess`**

Test flow:

```text
start -> plan -> event(worker.start/finish) -> declare -> verify -> semantic -> finish
```

Use:

```python
cmd = [sys.executable, "-m", "brain_runtime.cli", ...]
env = {**os.environ, "PYTHONPATH": str(RUNTIME_ROOT)}
subprocess.run(cmd, env=env, text=True, capture_output=True, check=True)
```

Required assertions:

- `start` stdout matches the run-ID pattern;
- `plan` writes `plan.json` containing `mode: fanout` for `section-map-fanout.json`;
- `event` appends `worker.start` and `worker.finish` and increments `manifest.metrics.workers` only on `worker.finish`;
- `declare` writes artifact hashes;
- `verify` exits `0` on a deliberately invalid claim and prints `Runtime shadow: REJECT`;
- `semantic` merges externally produced checks without invoking a model;
- a second semantic submission beyond the default budget is recorded as `budget.warning` and skipped;
- `finish` sets `status: completed`.

- [ ] **Step 2: Run and verify failure**

```bash
PYTHONPATH=skills/brain-init/runtime \
python3 -m unittest discover -s skills/brain-init/runtime/tests -p 'test_cli.py' -v
```

Expected: FAIL because the CLI does not exist.

- [ ] **Step 3: Implement `argparse` command surface**

The CLI parser must expose exactly:

```text
brain_runtime.cli start    --vault PATH --operation NAME --mode shadow [--profile PROFILE] [--input PATH ...] [budget flags]
brain_runtime.cli plan     --vault PATH --run-id ID --request-file JSON
brain_runtime.cli event    --vault PATH --run-id ID --kind KIND --label LABEL [--data-json JSON]
brain_runtime.cli declare  --vault PATH --run-id ID --paths-file JSON
brain_runtime.cli verify   --vault PATH --run-id ID
brain_runtime.cli semantic --vault PATH --run-id ID --report-file JSON
brain_runtime.cli finish   --vault PATH --run-id ID
```

`--paths-file` contains a JSON array of relative artifact paths. `--request-file` contains the `FanoutRequest` shape from Task 2.

`plan` must write:

```json
{
  "decision": {
    "mode": "fanout",
    "reason": "...",
    "slices": [],
    "max_workers": 3
  }
}
```

and emit both `plan.section_map` (slice count only) and `plan.fanout`.

- [ ] **Step 4: Implement generic event recording with trace protection**

`event` may record compact metadata only. Passing `--data-json` with forbidden trace keys defined in Task 1 must fail non-zero rather than silently storing them.

For `worker.finish`, increment `manifest.metrics.workers`. For labels beginning `attempt.`, increment `attempts`. Do not infer token billing.

- [ ] **Step 5: Implement semantic report ingestion**

Accepted file shape:

```json
{
  "checks": [
    {
      "id": "semantic.evidence_supports_claim",
      "passed": true,
      "severity": "warning",
      "artifact": "wiki/claims/claim-acme.md",
      "message": ""
    }
  ]
}
```

Rules:

- no model/provider call occurs;
- reject unknown severities outside `critical|warning|info` as an input error;
- force `source: semantic` on imported checks;
- merge checks into `verification.json` and recalculate `accepted` using critical failures from both deterministic and semantic checks;
- increment `semantic_verifier_calls` once per accepted semantic submission;
- if the budget is exhausted, leave the prior report untouched, emit `budget.warning`, print a concise skip message, and exit `0` in shadow mode.

This provides the independent-verifier interface without prematurely adding a verifier agent or SDK.

- [ ] **Step 6: Make `verify` rejection non-fatal**

A successful verification command returns process exit `0` in both cases:

```text
Runtime shadow: ACCEPT (0 critical, 2 warnings) — .brain/runs/<id>/verification.json
Runtime shadow: REJECT (2 critical, 1 warning) — .brain/runs/<id>/verification.json
```

Only malformed inputs, missing run state, or internal exceptions return non-zero.

- [ ] **Step 7: Run CLI tests and full runtime suite**

```bash
PYTHONPATH=skills/brain-init/runtime \
python3 -m unittest discover -s skills/brain-init/runtime/tests -v
```

Expected: all tests PASS.

- [ ] **Step 8: Commit Task 4**

```bash
git add skills/brain-init/runtime/brain_runtime/cli.py \
        skills/brain-init/runtime/brain_runtime/run.py \
        skills/brain-init/runtime/brain_runtime/verify.py \
        skills/brain-init/runtime/tests/test_cli.py
git commit -m "feat(runtime): add shadow runtime CLI"
```

---

### Task 5: Install and Upgrade the Runtime with `brain-init`

**Files:**
- Modify: `skills/brain-init/scripts/brain-init.sh:36-51, 116-139, 168-187, 330-433, 500-739`
- Modify: `skills/brain-init/scripts/validate-vault.sh:43-70, 219-249, 275-284, 289-328`
- Modify: `.github/workflows/ci.yml:221-244, 328-345`

**Interfaces:**
- Fresh full vault contains `.brain/runtime/brain_runtime`, `.brain/runs`, `.brain/evals`.
- Bare mode does not install the runtime.
- `--upgrade-harness` replaces `.brain/runtime/brain_runtime` but preserves `.brain/runs/` and `.brain/evals/`.
- Vault validation imports the installed runtime using `PYTHONPATH="$VAULT_PATH/.brain/runtime"`.

- [ ] **Step 1: Extend smoke tests before changing the installer**

In the full-scaffold smoke step, after `brain-init.sh` runs, add assertions:

```bash
[ -f "$TMP/test-full/.brain/runtime/brain_runtime/cli.py" ] || { echo "FAIL: brain runtime missing"; exit 1; }
[ -d "$TMP/test-full/.brain/runs" ] || { echo "FAIL: .brain/runs missing"; exit 1; }
[ -d "$TMP/test-full/.brain/evals" ] || { echo "FAIL: .brain/evals missing"; exit 1; }
grep -q '^/.brain/runs/' "$TMP/test-full/.gitignore" || { echo "FAIL: runtime runs are not gitignored"; exit 1; }
PYTHONPATH="$TMP/test-full/.brain/runtime" python3 -c 'import brain_runtime; print(brain_runtime.__version__)'
```

In the bare smoke step, assert:

```bash
[ ! -d "$TMP/test-bare/.brain/runtime" ] || { echo "FAIL: bare mode installed runtime"; exit 1; }
```

In the upgrade smoke step, before upgrading:

```bash
mkdir -p "$TMP/test-vault/.brain/runs/preserve-me" "$TMP/test-vault/.brain/evals"
echo keep > "$TMP/test-vault/.brain/runs/preserve-me/marker.txt"
echo labels > "$TMP/test-vault/.brain/evals/human-labels.jsonl"
```

After upgrading:

```bash
[ -f "$TMP/test-vault/.brain/runs/preserve-me/marker.txt" ] || { echo "FAIL: upgrade deleted run history"; exit 1; }
[ -f "$TMP/test-vault/.brain/evals/human-labels.jsonl" ] || { echo "FAIL: upgrade deleted eval labels"; exit 1; }
PYTHONPATH="$TMP/test-vault/.brain/runtime" python3 -c 'import brain_runtime'
```

- [ ] **Step 2: Run the targeted smoke job locally and confirm failure**

```bash
TMP="$(mktemp -d)"
export CLAUDE_PLUGIN_ROOT="$PWD"
bash skills/brain-init/scripts/brain-init.sh \
  "$TMP/test-runtime" --domain industrial-intelligence \
  --no-git --no-qmd --no-obsidian --no-supporting-skills
[ -f "$TMP/test-runtime/.brain/runtime/brain_runtime/cli.py" ]
```

Expected: final assertion FAILS because runtime installation is not implemented.

- [ ] **Step 3: Add runtime source resolution without breaking legacy mode**

In plugin mode set:

```bash
RUNTIME_SRC="$PLUGIN_ROOT/skills/brain-init/runtime"
```

In legacy mode set:

```bash
RUNTIME_SRC="$TEMPLATE_SOURCE/.brain/runtime"
```

Do the equivalent in the early `--upgrade-harness` path using `$_early_plugin_root`.

A missing runtime source in legacy mode is a warning, not a fatal error, because older legacy templates do not contain it.

- [ ] **Step 4: Create runtime state directories only for full mode**

Inside the existing `if [ "$BARE_MODE" = false ]` harness-directory block add:

```bash
mkdir -p "$VAULT_PATH/.brain/runtime"
mkdir -p "$VAULT_PATH/.brain/runs"
mkdir -p "$VAULT_PATH/.brain/evals"
```

Add to generated `.gitignore`:

```gitignore
# Brain runtime generated execution traces
/.brain/runs/
```

Add to generated `.claudeignore`:

```text
# Runtime execution history — inspect explicitly, never preload
.brain/runs/
```

Do not ignore `.brain/runtime/` or `.brain/evals/`.

- [ ] **Step 5: Install vendor-owned runtime in Phase 2**

After agent definitions and before/adjacent to skill installation:

```bash
if [ -d "$RUNTIME_SRC/brain_runtime" ]; then
  rm -rf "$VAULT_PATH/.brain/runtime/brain_runtime"
  cp -R "$RUNTIME_SRC/brain_runtime" "$VAULT_PATH/.brain/runtime/brain_runtime"
  find "$VAULT_PATH/.brain/runtime" -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
  echo "  brain runtime: installed (shadow mode)"
else
  echo "  WARNING: brain runtime source not found; capture will run without shadow instrumentation."
fi
```

Do not copy the runtime's repository tests into initialized vaults.

- [ ] **Step 6: Upgrade runtime code without deleting state**

In `--upgrade-harness`, replace only:

```text
.brain/runtime/brain_runtime/
```

Never remove `.brain/runs` or `.brain/evals`. Increment the harness-updated component count only when runtime code was actually copied.

- [ ] **Step 7: Extend vault validation**

Add a `Brain Runtime` validation section that checks:

```bash
[ -d "$VAULT_PATH/.brain/runs" ]
[ -d "$VAULT_PATH/.brain/evals" ]
[ -f "$VAULT_PATH/.brain/runtime/brain_runtime/cli.py" ]
PYTHONPATH="$VAULT_PATH/.brain/runtime" python3 -c 'import brain_runtime; import brain_runtime.cli'
```

A full vault missing the runtime is a warning during the pilot, not a hard fail, because backward compatibility requires capture to continue without it.

Do not add another `grep -P` dependency while editing this script.

- [ ] **Step 8: Run installer and validator tests**

```bash
bash -n skills/brain-init/scripts/brain-init.sh
bash -n skills/brain-init/scripts/validate-vault.sh

TMP="$(mktemp -d)"
export CLAUDE_PLUGIN_ROOT="$PWD"
bash skills/brain-init/scripts/brain-init.sh \
  "$TMP/test-runtime" --domain industrial-intelligence \
  --no-git --no-qmd --no-obsidian --no-supporting-skills
bash skills/brain-init/scripts/validate-vault.sh "$TMP/test-runtime"
PYTHONPATH="$TMP/test-runtime/.brain/runtime" python3 -m brain_runtime.cli --help
rm -rf "$TMP"
```

Expected: syntax checks PASS; runtime imports; validator reports runtime present.

- [ ] **Step 9: Commit Task 5**

```bash
git add skills/brain-init/scripts/brain-init.sh \
        skills/brain-init/scripts/validate-vault.sh \
        .github/workflows/ci.yml
git commit -m "feat(brain-init): install shadow runtime"
```

---

### Task 6: Instrument `second-brain-capture` in Shadow Mode

**Files:**
- Modify: `skills/brain-init/bundles/second-brain/capture/SKILL.md:20-59, 79-129, 131-160`

**Interfaces:**
- Consumes the Task 4 CLI.
- The capture skill retains one small `run_id` in context; it never loads `events.jsonl` or complete runtime reports unless troubleshooting a runtime failure.
- Runtime commands are best-effort and do not replace any existing capture step.

- [ ] **Step 1: Add a Shadow Runtime section before the workflow**

Add this operational contract to the skill:

```markdown
## Shadow Runtime

Capture remains authoritative. When `.brain/runtime/brain_runtime` exists and
`BRAIN_RUNTIME_MODE` is not `off`, instrument the capture with the local runtime.
Every runtime command is best-effort: on a runtime error, note the error briefly and continue the
normal capture workflow. A runtime `REJECT` is a shadow verdict and never rolls back or blocks wiki writes.

Invoke the runtime with:
`PYTHONPATH="$PWD/.brain/runtime" python3 -m brain_runtime.cli ...`

Do not send source bodies, Claude transcripts, or chain-of-thought into runtime events.
```

Default behavior when `BRAIN_RUNTIME_MODE` is unset is `shadow` if the runtime package exists.

- [ ] **Step 2: Add Checkpoint A immediately after source/profile resolution**

The skill should instruct Claude to run, with actual resolved values:

```bash
PYTHONPATH="$PWD/.brain/runtime" python3 -m brain_runtime.cli start \
  --vault "$PWD" \
  --operation capture \
  --mode shadow \
  --profile annual-report-v1 \
  --input raw/annual-reports/acme-2025-annual-report.pdf
```

Retain the returned run ID only. If the command fails, set runtime instrumentation aside for the rest of this capture; do not repeatedly retry initialization.

For non-profile sources, omit `--profile` rather than inventing one.

- [ ] **Step 3: Add Checkpoint B after the compact high-signal section map**

For long annual reports/10-Ks, write a temporary JSON request containing only bounded slice metadata:

```json
{
  "slices": [
    {"id":"business","tier":1,"start":395,"end":811},
    {"id":"mda","tier":1,"start":812,"end":1587}
  ],
  "parallelizable": true,
  "exceeds_one_context": true,
  "high_value": true
}
```

Then call `plan --request-file`. The model determines `parallelizable`, `exceeds_one_context`, and `high_value`; Python enforces the decision rule and worker cap. In shadow mode the returned recommendation is recorded only. **Do not alter the existing read/delegation behavior based on it yet.**

For patents and small documents with no section map, either pass a single-slice request or skip planning; do not fabricate annual-report sections.

- [ ] **Step 4: Record worker events around existing specialist delegation**

Only when capture already chooses to delegate:

```bash
... cli event --vault "$PWD" --run-id <id> --kind worker.start  --label researcher.mda
... cli event --vault "$PWD" --run-id <id> --kind worker.finish --label researcher.mda
```

The handoff contract in the skill must be tightened to pass only:

```yaml
operation: capture
slice_id: mda
source_ref: raw/annual-reports/acme-2025-annual-report.md
range: 812:1587
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

State explicitly that a worker receives a bounded task/material reference and returns structured findings, not the parent's accumulated research history.

- [ ] **Step 5: Add Checkpoint D artifact declaration after canonical writes**

After claims, source, company/entity pages, index, and log are written, create a temporary JSON array of exactly the files created or modified by this capture, for example:

```json
[
  "wiki/claims/claim-acme-revenue-12345678.md",
  "wiki/claims/claim-acme-margin-87654321.md",
  "wiki/sources/src-acme-2025-annual-report.md",
  "wiki/companies/company-acme.md",
  "wiki/index.md",
  "wiki/log.md"
]
```

Call `declare --paths-file`. The list is explicit; do not ask the runtime to scan the whole vault for changes.

- [ ] **Step 6: Record workflow completion signals and run shadow verification**

After qmd refresh succeeds:

```bash
... cli event --kind workflow.qmd --label qmd.refresh --data-json '{"passed":true}'
```

If qmd is unavailable/skipped:

```bash
... cli event --kind workflow.qmd --label qmd.refresh --data-json '{"passed":false,"reason":"unavailable"}'
```

After the WIP log has been finalized, record `workflow.log` with `passed: true`.

Then run:

```bash
PYTHONPATH="$PWD/.brain/runtime" python3 -m brain_runtime.cli verify \
  --vault "$PWD" --run-id <id>
```

Display only the CLI's one-line `Runtime shadow: ACCEPT/REJECT ...` summary. Do not paste `verification.json` into context unless a human asks or the agent is debugging a runtime error.

Finally call `finish --run-id <id>`.

- [ ] **Step 7: Keep semantic verification disabled by default**

Document that the `semantic` CLI command is only a feed-in point in this pilot. `second-brain-capture` must not automatically spawn a model verifier yet. This isolates evaluation of deterministic checks before semantic grader behavior is introduced.

- [ ] **Step 8: Correct command-name drift while touching the skill**

Replace all examples of:

```text
/second-brain:capture
```

with:

```text
/second-brain-capture
```

Also ensure references to lint use `/second-brain-lint`.

- [ ] **Step 9: Review the skill for context discipline**

Confirm the edited skill still says:

- grep is navigation, not extraction;
- section map first;
- only compact map enters runtime planning;
- runtime outputs are not injected wholesale into Claude context;
- fan-out advice is non-binding;
- normal capture continues on runtime failure/rejection.

- [ ] **Step 10: Commit Task 6**

```bash
git add skills/brain-init/bundles/second-brain/capture/SKILL.md
git commit -m "feat(capture): add shadow runtime checkpoints"
```

---

### Task 7: CI Regression Coverage, Documentation, and Release Consistency

**Files:**
- Modify: `.github/workflows/ci.yml:124-187, 207-345`
- Modify: `README.md`
- Modify: `.claude-plugin/plugin.json`
- Modify: `.claude-plugin/marketplace.json`
- Modify: `skills/brain-init/SKILL.md`
- Modify: `skills/brain-init/bundles/second-brain/capture/SKILL.md`
- Modify: `skills/brain-init/scripts/brain-init.sh`

**Interfaces:**
- CI runs the runtime unit/fixture suite on Python 3.11.
- Plugin release version becomes `1.2.0` consistently across the three files already enforced by `.github/scripts/check-versions.py`.
- `brain-init.sh` uses one `BRAIN_INIT_VERSION` variable instead of stale `v1.0.0` literals.

- [ ] **Step 1: Add runtime tests to `bundle-check`**

After Python syntax compilation, add:

```yaml
      - name: Runtime unit and fixture tests
        run: |
          PYTHONPATH=skills/brain-init/runtime \
          python3 -m unittest discover -s skills/brain-init/runtime/tests -v
```

Do not add pytest merely for this feature.

- [ ] **Step 2: Strengthen smoke tests for shadow rejection safety**

Add a smoke step that scaffolds a temporary vault, creates one deliberately invalid declared claim, runs the runtime `verify` command, and asserts:

1. command exit code is `0`;
2. output contains `Runtime shadow: REJECT`;
3. the invalid wiki file still exists afterward;
4. `verification.json` has `accepted: false`.

This test proves the central shadow-mode guarantee: rejection cannot delete, roll back, or block canonical artifacts.

- [ ] **Step 3: Add README operational documentation**

Add a concise `Capture runtime (shadow mode)` section showing:

```bash
# default when the runtime is installed
/second-brain-capture raw/annual-reports/acme-2025.pdf

# explicitly disable shadow instrumentation for a session
BRAIN_RUNTIME_MODE=off
```

Document run artifacts:

```text
.brain/runs/<run-id>/manifest.json
.brain/runs/<run-id>/events.jsonl
.brain/runs/<run-id>/plan.json
.brain/runs/<run-id>/artifacts.json
.brain/runs/<run-id>/verification.json
```

State clearly that these are operational records, not canonical wiki knowledge, and that shadow `REJECT` does not alter capture results.

- [ ] **Step 4: Centralize the installer version string**

Near the defaults at the top of `brain-init.sh` add:

```bash
BRAIN_INIT_VERSION="1.2.0"
```

Replace user-visible/log literals such as:

```text
brain-init v1.0.0
```

with:

```bash
brain-init v${BRAIN_INIT_VERSION}
```

including validate mode, upgrade mode, startup banner, template-source description, and wiki log entries. Do not change unrelated data/schema version strings such as `Schema: v1.1` unless their schema actually changed.

- [ ] **Step 5: Bump release versions consistently**

Set:

```text
.claude-plugin/plugin.json                     -> 1.2.0
.claude-plugin/marketplace.json                -> 1.2.0
skills/brain-init/SKILL.md                     -> 1.2.0
skills/brain-init/bundles/second-brain/capture/SKILL.md -> 1.2.0
```

The first three are required to satisfy the existing version gate. The capture skill bump advertises the runtime-aware workflow.

- [ ] **Step 6: Run all local verification commands**

```bash
# Python runtime
PYTHONPATH=skills/brain-init/runtime \
python3 -m unittest discover -s skills/brain-init/runtime/tests -v

# Python syntax
find . -name '*.py' -not -path './.git/*' -print0 | \
  while IFS= read -r -d '' f; do python3 -m py_compile "$f"; done

# Shell syntax
find . -name '*.sh' -not -path './.git/*' -print0 | \
  while IFS= read -r -d '' f; do bash -n "$f"; done

# Version gate
python3 .github/scripts/check-versions.py

# Full scaffold + vault validation
TMP="$(mktemp -d)"
export CLAUDE_PLUGIN_ROOT="$PWD"
bash skills/brain-init/scripts/brain-init.sh \
  "$TMP/final" --domain industrial-intelligence \
  --no-git --no-qmd --no-obsidian --no-supporting-skills
bash skills/brain-init/scripts/validate-vault.sh "$TMP/final"
PYTHONPATH="$TMP/final/.brain/runtime" python3 -m brain_runtime.cli --help
rm -rf "$TMP"
```

Expected: all runtime tests PASS; all Python and shell files compile/parse; version gate PASS; scaffold validator completes with no runtime failure.

- [ ] **Step 7: Inspect generated vault ownership boundaries**

After a fresh scaffold, confirm manually with shell assertions:

```bash
# vendor-owned and present
[ -f "$TMP/final/.brain/runtime/brain_runtime/cli.py" ]

# generated state ignored
 grep -q '^/.brain/runs/' "$TMP/final/.gitignore"

# evaluation state is not ignored
! grep -q '^/.brain/evals/' "$TMP/final/.gitignore"
```

If the prior step already removed `$TMP`, rerun the scaffold in a new temporary directory for these assertions; do not weaken the assertions.

- [ ] **Step 8: Commit Task 7**

```bash
git add .github/workflows/ci.yml README.md \
        .claude-plugin/plugin.json .claude-plugin/marketplace.json \
        skills/brain-init/SKILL.md \
        skills/brain-init/bundles/second-brain/capture/SKILL.md \
        skills/brain-init/scripts/brain-init.sh
git commit -m "chore: release capture shadow runtime v1.2.0"
```

---

## Final Acceptance Walkthrough

After all seven tasks, perform one end-to-end synthetic capture-runtime run without changing the actual Claude capture behavior:

- [ ] Scaffold a new full vault with qmd/Obsidian/supporting-skills disabled.
- [ ] Confirm `.brain/runtime`, `.brain/runs`, and `.brain/evals` ownership layout.
- [ ] Run `brain_runtime.cli start` for an annual-report source.
- [ ] Feed `section-map-fanout.json` into `plan`; confirm advice is recorded and no workers are automatically launched.
- [ ] Declare a valid source, two valid claims, and one company page.
- [ ] Run `verify`; confirm `ACCEPT` and machine-readable `verification.json`.
- [ ] Replace one claim with `status: supported`; rerun in a new run; confirm shadow `REJECT` while the bad page remains untouched.
- [ ] Confirm `events.jsonl` contains `run.start`, `plan.section_map`, `plan.fanout`, `artifact.declare`, `verify.start`, `verify.check`, `verify.finish`, `run.finish` and contains none of `messages`, `transcript`, `chain_of_thought`, or full report text.
- [ ] Run `--upgrade-harness`; confirm old run history and `.brain/evals` content are preserved while runtime code is refreshed.
- [ ] Run the repository CI-equivalent commands from Task 7 and confirm all pass.

## Design-to-Plan Coverage

This plan covers the approved design as follows:

- **Shadow rollout / backward compatibility:** Tasks 5-7.
- **Operation-agnostic contracts:** Task 1.
- **Runtime location and ownership:** Task 5.
- **Capture checkpoints A-E:** Task 6.
- **Rule-first deterministic verification:** Task 3.
- **Independent semantic-verifier boundary without an LLM client:** Task 4.
- **Costed fan-out decision:** Task 2.
- **Budgets and proxy metrics:** Tasks 1, 2, and 4.
- **Compact retry feedback contract:** Task 1.
- **Structured observability:** Tasks 1 and 4.
- **Human calibration storage boundary:** Task 5 (`.brain/evals/`), with calibration tooling intentionally outside this pilot.
- **Error handling and fail-open shadow behavior:** Tasks 4-7.
- **Unit, fixture, integration, upgrade, and backward-compatibility tests:** Tasks 1-7.
- **Future shared runtime path:** generic modules in Tasks 1-4 plus capture-only adapter in Task 3.

The resulting pilot is narrow in behavior but not in architecture: a later `reconcile`, `investigate`, or `synthesize` adapter can reuse the same run, trace, budget, artifact, verification, retry, and CLI contracts without changing their public shapes.
