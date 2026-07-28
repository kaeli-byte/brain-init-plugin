# Automatic Handoff: Capture → Reconcile

This reference defines the **exact** sequence reconcile follows when capture hands off one
staged reconciliation record. It is the authoritative workflow — the Brain Runtime only
observes it. Whether or not runtime instrumentation is available, every step runs in the
same order and produces the same canonical result.

## Hard rules

- **One mutating orchestrator.** Reconcile itself performs entity resolution, comparator
  search, classification, review, and page mutation. It never fans these out to parallel
  agents. Parallel canonical mutation is forbidden.
- **No inherited transcripts.** The handoff payload is the staged reconciliation record
  path and nothing else. Capture's conversation, extraction notes, and chain-of-thought
  are not inputs.
- **No source bodies in runtime events.** Runtime events carry paths, hashes, counts,
  candidate IDs, and dispositions — never passages, claim text, or model output.
- **Runtime is best-effort.** `BRAIN_RUNTIME_MODE=off` bypasses runtime calls entirely
  but never bypasses reconciliation. If `start` fails, abandon instrumentation for this
  reconcile without retrying initialization.

## Sequence

1. **Validate the staged record.** Read
   `wiki/reconciliations/reconcile-<source-id>.md`. Confirm required fields, that
   `origin` is set, `status: staged`, and that `source` links to an existing source
   page. Confirm every `candidate_id` matches the deterministic hash of source ID and
   normalized claim text (see `reconciliation-record.md`).
2. **Resolve entities.** For every entity linked from candidates, read the existing
   wiki pages (company, technology, industry, …). Missing entity pages are noted for
   creation during the apply step.
3. **Search comparators via qmd, then filesystem fallback.** Query qmd for existing
   claims bearing on each candidate's proposition. If qmd is unavailable or fails,
   fall back to `Grep`/`Glob` over `wiki/claims/`. Record the method actually used
   (`qmd`, `filesystem`, `mixed`, or `unavailable`).
4. **Assemble comparator paths.** Produce the bounded list of eligible comparator claim
   paths (`wiki/claims/*.md`) that classification will consider. This list is complete
   only when the search covered every claim that could address the same propositions;
   that completeness becomes `coverage_complete`.
5. **Start a shadow reconcile run** unless runtime is off or unavailable:

   ```bash
   PYTHONPATH="$PWD/.brain/runtime" python3 -m brain_runtime.cli start \
     --vault "$PWD" --operation reconcile --mode shadow \
     --max-workers 1 --max-semantic-verifier-calls 0 \
     --input wiki/reconciliations/reconcile-<source-id>.md \
       wiki/sources/<source-id>.md <comparator claim paths…>
   ```

   Every eligible target claim is a run input, so its pre-mutation hash is pinned.
6. **Snapshot the canonical wiki:**

   ```bash
   PYTHONPATH="$PWD/.brain/runtime" python3 -m brain_runtime.cli snapshot \
     --vault "$PWD" --run-id <run-id> --root wiki
   ```
7. **Classify every candidate.** Assign exactly one disposition
   (`new`, `corroborating`, `updating`, `contradicting`, `superseding`, `irrelevant`)
   with target (when required), reason, and confidence effect. No candidate may be
   classified `new` while `coverage_complete` is false — if coverage could not be
   completed safely, set the record `status: incomplete` and stop before any mutation.
8. **Emit compact events.** Record `reconcile.search` (method and `coverage_complete`)
   and `reconcile.classified` (disposition counts only) — best-effort, no claim text.
9. **Apply safe actions.** `new`, `corroborating`, and `irrelevant` candidates are
   applied immediately: create or update claim pages, set `action_state: applied` (or
   `not_applicable` for irrelevant), and record `result_claim`.
10. **Ask one inline review question per sensitive candidate.** `updating`,
    `contradicting`, and `superseding` each get exactly one human decision showing the
    candidate claim and evidence, the target claim and its evidence, the disposition and
    reason, and the exact proposed mutations, with Approve / Reject / Defer choices.
11. **Persist each decision before mutation.** Write `review_state`, `reviewed_by`,
    `reviewed_at`, and `review_note` (required on rejection) into the record, and emit
    `review.decision` (candidate ID and decision only) before touching any page.
12. **Apply approved actions once.** An approved action mutates pages exactly once.
    Updating closes the prior claim with `valid_to` and `superseded_by` and creates the
    replacement with `valid_from`; superseding marks the old claim superseded and links
    the replacement; contradicting marks both claims `disputed`, adds opposing
    `counter_evidence`, and cross-links them under `## Related Claims`. Reconciliation
    never deletes a canonical claim.
13. **Update source, entities, index, and log.** The source page gains
    `reconciliation: "[[reconcile-<source-id>]]"` and its `key_claims` contains only
    applied result claims. Create or update entity pages, the root index
    (`## Reconciliations` section), and `wiki/log.md`.
14. **Refresh qmd** so the next search sees the new state. Record `workflow.qmd`
    success or failure; failure is a warning, never a rollback.
15. **Declare exact artifacts** — the reconciliation page, the source page when its
    links changed, every created or modified claim, affected entity pages,
    `wiki/index.md`, and `wiki/log.md`:

    ```bash
    PYTHONPATH="$PWD/.brain/runtime" python3 -m brain_runtime.cli declare \
      --vault "$PWD" --run-id <run-id> --paths-file <paths.json>
    ```
16. **Verify and finish:**

    ```bash
    PYTHONPATH="$PWD/.brain/runtime" python3 -m brain_runtime.cli verify \
      --vault "$PWD" --run-id <run-id>
    PYTHONPATH="$PWD/.brain/runtime" python3 -m brain_runtime.cli finish \
      --vault "$PWD" --run-id <run-id>
    ```

    The verdict is reported as-is (`Runtime shadow: ACCEPT/REJECT …`). A REJECT never
    rolls back authoritative changes.
17. **Return counts to capture.** Report applied, pending, and rejected candidate
    counts plus the record path. Pending candidates leave the record in
    `pending_review`, resumable by `/second-brain-reconcile <reconciliation-id>`.
