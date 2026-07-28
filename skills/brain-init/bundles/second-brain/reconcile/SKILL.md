---
name: second-brain-reconcile
description: >
  Reconcile a source against canonical wiki knowledge through a staged reconciliation
  record. Classifies every candidate claim into one of six dispositions — new,
  corroborating, updating, contradicting, superseding, or irrelevant — applies safe
  actions automatically, and gates sensitive actions behind inline human review.
  This is the compounding step.
version: 1.3.0
tools: [Read, Edit, Grep, Glob, Bash, Write]
---

# Reconcile — Source vs. Knowledge Reconciliation

## Overview

The compounding step. Every source is reconciled through one canonical, git-tracked
**reconciliation record** (`wiki/reconciliations/reconcile-<source-id>.md`) whose YAML
frontmatter is machine-authoritative. Reconcile loads or builds that record, classifies
every candidate into exactly one of six dispositions, applies safe actions
(`new`, `corroborating`, `irrelevant`) automatically, and gates sensitive actions
(`updating`, `contradicting`, `superseding`) behind inline human review. The brain
compounds; it doesn't duplicate — and it never deletes a canonical claim.

Reconcile is **one mutating orchestrator**. Entity resolution, comparator search,
classification, review, and page mutation happen in this single workflow — never fanned
out to parallel agents. The Brain Runtime observes the workflow in shadow mode only; it
never chooses a disposition and never blocks an authoritative change.

Read these references before acting:

- `references/reconciliation-record.md` — record schema, deterministic candidate IDs,
  status lifecycle, disposition effects.
- `references/automatic-handoff.md` — the exact 17-step sequence for capture handoffs.

## Input and recovery modes

`/second-brain-reconcile <source-id|reconciliation-id>` distinguishes four modes:

1. **Source with a `reconciliation` link** → load the linked record and resume it.
2. **Reconciliation ID** (`reconcile-<source-id>`) → load that record directly.
3. **Legacy source without a record** → safe bootstrap (see Legacy Safety below):
   derive candidates from the source page's `key_claims` with `origin: legacy`.
4. **Staged automatic handoff** → capture has just written a record with
   `status: staged`; process that record following
   `references/automatic-handoff.md` exactly.

Resume rules:

- **`pending_review`** — skip every candidate whose action is already terminal
  (`applied`, `not_applicable`, or `rejected`). Never repeat an applied action.
  Continue with the candidates still `pending`.
- **`incomplete`** — repeat comparator discovery only for unresolved candidates; do
  not reclassify or re-apply resolved ones.

## Candidate construction (deterministic)

Candidate IDs are content-derived, never model-generated UUIDs:

1. Normalize `claim_text` (trim, collapse internal whitespace to one space).
2. SHA-256 of `source_id + "\n" + normalized_claim_text`.
3. First 12 lowercase hex chars: `candidate-<hash>`.

Prefer the runtime implementation:

```bash
PYTHONPATH="$PWD/.brain/runtime" python3 -c \
  'from brain_runtime.reconcile_contract import candidate_id; import sys; print(candidate_id(sys.argv[1], sys.argv[2]))' \
  "$SOURCE_ID" "$CLAIM_TEXT"
```

When the runtime package is unavailable, use the equivalent standard-library SHA-256
snippet from `references/reconciliation-record.md`. New capture records stage 2–6
material candidates without padding. Legacy bootstrap records process every linked
claim without truncation.

## Comparator coverage and classification

Before classification, assemble a **bounded list of comparator claim paths**
(`wiki/claims/*.md`) via qmd search, falling back to filesystem `Grep`/`Glob` when qmd
is unavailable or fails. Record the method actually used in `search_method`.

Classification records, per candidate:

- exact disposition;
- `target_claim` (required for corroborating/updating/contradicting/superseding;
  forbidden for new/irrelevant);
- `reason`;
- `confidence_effect`;
- search method and coverage state on the record.

**No candidate may be classified `new` while `coverage_complete` is false.** If
comparator coverage could not be completed safely, set the record
`status: incomplete` and stop before any mutation.

## Runtime checkpoints (shadow, best-effort)

`BRAIN_RUNTIME_MODE=off` bypasses runtime calls entirely but **never** bypasses
reconciliation — the authoritative workflow is identical with or without
instrumentation. Every runtime command is best-effort: if `start` fails, abandon
instrumentation for this reconcile without retrying initialization.

```bash
PYTHONPATH="$PWD/.brain/runtime" python3 -m brain_runtime.cli start \
  --vault "$PWD" --operation reconcile --mode shadow \
  --max-workers 1 --max-semantic-verifier-calls 0 \
  --input wiki/reconciliations/reconcile-src-acme.md \
    wiki/sources/src-acme.md wiki/claims/claim-existing.md

PYTHONPATH="$PWD/.brain/runtime" python3 -m brain_runtime.cli snapshot \
  --vault "$PWD" --run-id <run-id> --root wiki
```

Emit compact events only — paths, hashes, counts, candidate IDs, dispositions; never
source bodies, passages, transcripts, or chain-of-thought:

- `reconcile.search` with method and `coverage_complete`;
- `reconcile.classified` with disposition counts only;
- `review.decision` per approved/rejected sensitive candidate (candidate ID + decision);
- `workflow.qmd` and `workflow.log` with success/failure.

After mutation, declare exact artifacts (reconciliation page, source page when links
changed, every created/modified claim, affected entity pages, `wiki/index.md`,
`wiki/log.md`), then `verify` and `finish`. Report the one-line verdict as-is; a shadow
REJECT never rolls back authoritative changes.

## Dispositions

| Disposition | Definition | Action |
|---|---|---|
| `new` | No existing claim addresses this proposition | Create one claim page; `result_claim` = new page; automatic |
| `corroborating` | Existing claim makes the same material proposition | Add structured source evidence to target; `result_claim` = target; no duplicate page; automatic |
| `irrelevant` | Not material per `config/materiality.md` | Create no claim; `action_state: not_applicable`; automatic |
| `updating` | Same metric/proposition for a later effective period | **Human review.** Replacement gets `valid_from`; target gets `valid_to`, `status: superseded`, `superseded_by` |
| `contradicting` | Cannot both be true for the same scope/period | **Human review.** Both claims `status: disputed`, opposing `counter_evidence`, reciprocal `## Related Claims` links |
| `superseding` | Newer/better evidence replaces a current proposition | **Human review.** Target `status: superseded` with `superseded_by`; old page and evidence preserved |

## Inline human review

For each sensitive candidate (`updating`, `contradicting`, `superseding`), ask **one**
inline review question presenting:

- the candidate claim and its source evidence;
- the target claim and its evidence;
- the disposition and reason;
- the exact proposed mutations;
- choices: **Approve**, **Reject**, **Defer**.

Persist the decision in the record (`review_state`, `reviewed_by: human`,
`reviewed_at`, `review_note`) **before** applying an approved action. Rejection
requires a human rationale (`review_note` non-empty) and leaves all pages unchanged.
Defer leaves the record `pending_review` and stops at a resumable boundary. An approved
action is applied exactly once.

## Legacy safety

Legacy bootstrap (`origin: legacy`):

- derives candidates from the source page's `key_claims`;
- records already-existing claims that remain `new` as already applied;
- never truncates linked claims — every one is processed;
- never deletes a page;
- gates conflict marking, retirement, supersession, and confidence reduction behind
  inline human approval;
- records deletion requests as manual follow-ups only, leaving the canonical page
  unchanged.

## Rules

- Later silence never invalidates an earlier claim.
- Duplicate or dependent sources must not automatically raise confidence.
- Only declared affected pages may change; every changed wiki page is declared.
- `new` requires `coverage_complete: true`.
- Sensitive dispositions never mutate targets before inline approval.
- Resume never repeats a terminal action.
- Reconciliation never deletes a canonical claim; history lives in `valid_from`,
  `valid_to`, `superseded_by`, and links.
- Runtime events and files contain no source bodies, transcripts, or chain-of-thought.

## Output contract

- The reconciliation record with every candidate at a terminal or pending state.
- Applied result claims and mutated targets, each declared as run artifacts.
- Source page with `reconciliation` link and `key_claims` containing only applied
  result claims.
- Exact counts reported back: applied, pending, rejected — plus the record path.
- `index.md` (with `## Reconciliations`) and `log.md` updated.
- Shadow verdict reported verbatim when the runtime is enabled.

## Example

```
/second-brain-reconcile src-acme-2026-annual-report
→ Loads wiki/reconciliations/reconcile-src-acme-2026-annual-report.md (staged by capture)
→ qmd search over 42 comparator claims; coverage_complete: true
→ 4 candidates: 1 new (applied), 2 corroborating (applied), 1 updating
→ updating → human approves → target closed with valid_to, replacement created with valid_from
→ Source linked to record; index and log updated; shadow: ACCEPT
→ Report: "Reconciled 4 candidates: 3 applied, 0 pending, 0 rejected"
```
