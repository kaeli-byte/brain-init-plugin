---
name: second-brain-capture
description: >
  Ingest a source (10-K, patent, report, paper) into the wiki. Extracts material candidate
  claims, writes the source summary, stages a reconciliation record, and hands every
  candidate to reconcile before any claim page exists.
version: 1.3.0
tools: [Read, Edit, Grep, Glob, Bash, Write]
---

# Capture -- Source Ingestion Pipeline

## Overview

Ingest a new source into the wiki. Capture no longer writes claim pages directly: it
converts the raw source, extracts **2-6 material candidate claim structures**, writes the
source summary with an empty `key_claims` list and a reconciliation link, stages one
**reconciliation record** (`wiki/reconciliations/reconcile-<source-id>.md`), and hands the
candidates to `/second-brain-reconcile` through the shared automatic handoff. Reconcile
classifies every candidate, applies safe dispositions automatically, and gates sensitive
ones behind inline human review. Only after reconcile does capture fill in `key_claims`
from the terminal applied results and finish the entity/index/log updates.

This is the loop: capture stages; reconcile decides; the graph grows without duplicates.

Read `../reconcile/references/reconciliation-record.md` for the record schema and
`../reconcile/references/automatic-handoff.md` for the exact handoff sequence. Capture
executes that handoff inline as the one mutating orchestrator — it never fans the
reconcile phase out to parallel agents.

## Shadow Runtime

Capture and its reconcile handoff remain authoritative. When `.brain/runtime/brain_runtime` exists and `BRAIN_RUNTIME_MODE` is not `off`, instrument the capture with the local runtime. Default behavior when `BRAIN_RUNTIME_MODE` is unset is `shadow` if the runtime package exists. If
`BRAIN_RUNTIME_MODE=off`, bypass the runtime entirely: do not invoke or start it — see
Runtime-off behavior below.

Every runtime command is best-effort: if the runtime is absent, disabled, initialization fails, a
later runtime command errors, or verification rejects, note the error briefly and continue the
normal capture workflow exactly as before. If `start` fails, set runtime instrumentation aside for
the rest of this capture; do not repeatedly retry initialization. A runtime `REJECT` is a shadow verdict and never rolls back or blocks wiki writes.

Invoke the runtime with:
`PYTHONPATH="$PWD/.brain/runtime" python3 -m brain_runtime.cli ...`

Retain only the returned `run_id` in working context. Never load `events.jsonl`, complete runtime
reports, or `verification.json` into context unless a human asks or you are debugging a runtime
error. Do not send source bodies, Claude transcripts, or chain-of-thought into runtime events.

## Workflow

1. **Source/profile resolution** -- determine source type (10-K, China annual report, patent,
   report, paper, white-paper, etc.) and resolve an applicable extraction profile. Do not invent a
   profile for a source that has none.
2. **Shadow checkpoint A: start** -- only while runtime instrumentation is active, start one run
   immediately after source/profile resolution, with actual resolved values. Mark the run as a
   staged capture through metadata (`--metadata-json '{"reconcile":"staged","source_type":"<type>"}'`),
   because the capture verifier distinguishes staged runs from legacy claim-writing runs through
   declared artifacts and this metadata. For example:

   ```bash
   PYTHONPATH="$PWD/.brain/runtime" python3 -m brain_runtime.cli start \
     --vault "$PWD" \
     --operation capture \
     --mode shadow \
     --profile annual-report-v1 \
     --input raw/annual-reports/acme-2026-annual-report.pdf \
     --metadata-json '{"reconcile":"staged","source_type":"annual-report"}'
   ```

   Retain the returned run ID only. For non-profile sources, omit `--profile` rather than inventing one. If this command fails, continue capture without runtime instrumentation.
3. **Save original** to `raw/{type}/{company}-{year}-{title}.{ext}`
4. **Convert to markdown** using `mineru` (primary). Split documents over 200 pages into ranges
   (1-200, 201-400, ...) and stitch. Fallback: `pdftotext -layout`. Both PDF and `.md` are
   git-excluded (rebuildable).
5. **Locate high-signal sections before reading** -- for annual reports and 10-Ks, use the
   section-heading patterns in `raw/assets/high-signal-sections.md`.
   - Use grep as a **navigation tool**, not as the extraction step.
   - Keep only section names and line numbers in context.
   - Build a compact section map before loading section bodies.
   - Use the US/10-K locator set for SEC-style filings and the China locator set for Chinese listed-company annual reports.
   - Generic keyword grep may be used later for targeted follow-up, but not as the primary navigation method.
   - **Shadow checkpoint B: plan** -- for long annual reports and 10-Ks, write a temporary JSON
     request containing only bounded slice metadata, then call `plan --request-file`:

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

     ```bash
     PYTHONPATH="$PWD/.brain/runtime" python3 -m brain_runtime.cli plan --request-file \
       <temporary-section-map-request.json> --vault "$PWD" --run-id <run-id>
     ```

     The model determines `parallelizable`, `exceeds_one_context`, and `high_value`; Python
     enforces the decision rule and worker cap. Only the compact map enters runtime planning. In
     shadow mode the returned recommendation is recorded only: fan-out advice is non-binding. Do not alter the existing read/delegation behavior based on it yet. For patents and small documents with no section map,
     either pass a single-slice request or skip planning; do not fabricate annual-report sections.
6. **Read only high-signal sections** -- never read a large annual report sequentially or load the
   full markdown into context.
   - **Tier 1:** always inspect.
   - **Tier 2:** inspect when material, referenced by Tier 1, or needed to resolve an open research question.
   - **Tier 3:** inspect only when specifically relevant.
   - Read bounded line ranges from one located heading to the next heading of equal or higher level.
   - Extract useful evidence and candidate claim structures from each section before reading the next section.
   - Stop retrieval when the material research questions in the active extraction profile are sufficiently answered.
7. **Write a WIP log entry** (see CLAUDE.md for recovery pattern).

## Candidate staging and the reconcile handoff

Steps 8-15 are the authoritative capture sequence. **Do not create candidate claim pages
before reconciliation.** Claim pages come into existence only as applied reconcile results.

8. **Extract 2-6 material candidate structures** -- for each significant claim, build a
   candidate structure: `claim_text`, structured `source_evidence` (source link, passage,
   context), and entity links. Target 5-6 candidates per source (minimum 2), but do not
   create low-value candidates merely to satisfy a quota. Follow materiality policy. These
   structures live in the reconciliation record, not in `wiki/claims/`.
9. **Write the source summary** to `wiki/sources/src-{kebab-title}.md` with:
   - `key_claims: []` (empty -- filled in at step 13 from applied results);
   - `reconciliation: "[[reconcile-<source-id>]]"` linking the staged record;
   - `last_reviewed` set to today;
   - the mandatory `## Company` section with `[[company-*]]` (step 14's backlink target).
10. **Write the staged reconciliation record** to
    `wiki/reconciliations/reconcile-<source-id>.md` with `origin: capture`,
    `status: staged`, `source` linking the source page, and the candidates from step 8.
    Compute each `candidate_id` deterministically (SHA-256 of
    `source_id + "\n" + normalized claim_text`, first 12 hex chars) -- prefer the runtime
    helper and fall back to the stdlib snippet, exactly as documented in
    `../reconcile/references/reconciliation-record.md`. Classification fields
    (`disposition`, `target_claim`, `review_state`, `action_state`, `result_claim`) stay
    null while `staged`.
11. **Execute the shared automatic handoff** -- run the exact sequence in
    `../reconcile/references/automatic-handoff.md`: resolve entities, search comparators,
    shadow-start the reconcile run, snapshot, classify (no `new` while
    `coverage_complete` is false), emit events, apply safe dispositions, run one inline
    review per sensitive candidate, persist each decision before mutating, apply approved
    actions exactly once. The handoff ends with the record `complete` (all candidates
    terminal) or `pending_review` (a review was deferred) or `incomplete` (coverage could
    not be completed safely).
12. **Settle the record status** -- if the handoff ended `pending_review` (deferred
    review), finalize this source as **partial**: keep the record `pending_review`, set
    source `key_claims` to only the already-applied results, and report the resume
    command `/second-brain-reconcile <source-id>` so a human can finish it later. If the
    record ended `incomplete`, report the coverage gap and the same resume command. Never
    fabricate classifications to force completion.
13. **Update the source `key_claims`** from the terminal applied results: the set of
    `result_claim` targets for candidates whose `action_state` is `applied`, in candidate
    order, deduplicated. Nothing else belongs in `key_claims`.
14. **Update all relevant entity pages** and bump `last_reviewed` on every modified page:
    companies, technologies, people, industries, markets, regulations, standards, products,
    patent-families, concepts. **Link source -- company** -- mandatory bidirectional wikilinks:
    source page `## Company` with `[[company-*]]` (written at step 9); company page
    `## Source` with `[[src-*]]` now.
15. **Update** `wiki/index.md` -- add new entries (including the `## Reconciliations`
    section entry for the record), update counts. **Finalize the log entry** -- replace
    WIP with the completed summary in `wiki/log.md`, including applied / pending /
    rejected candidate counts and the record path.

## Runtime checkpoints after reconciliation

16. **Shadow checkpoint D: declare artifacts** -- after reconcile, entity pages, index, and
    log are written, create a temporary JSON array of exactly the files created or modified
    by this capture, including the reconciliation record and every applied result claim.
    Do not ask the runtime to scan the whole vault for changes.

    ```json
    [
      "wiki/reconciliations/reconcile-src-acme-2026-annual-report.md",
      "wiki/sources/src-acme-2026-annual-report.md",
      "wiki/claims/claim-acme-revenue-2026-12345678.md",
      "wiki/claims/claim-acme-operating-margin-87654321.md",
      "wiki/companies/company-acme.md",
      "wiki/index.md",
      "wiki/log.md"
    ]
    ```

    ```bash
    PYTHONPATH="$PWD/.brain/runtime" python3 -m brain_runtime.cli declare --paths-file \
      <temporary-capture-artifacts.json> --vault "$PWD" --run-id <run-id>
    ```

    A source where every candidate was `irrelevant` declares zero claim pages -- that is
    valid. A partial (`pending_review`) source declares the record, source, entity pages,
    index, log, and any already-applied result claims.
17. **Quick lint** -- run `/second-brain-lint` to check for contradictions with existing claims,
    verify zero orphans, and confirm source-company link integrity.
18. **Re-index qmd** -- run `qmd update && qmd embed`. New pages are invisible to hybrid
    search until indexed.
19. **Shadow checkpoint E: completion and verification** -- only while runtime instrumentation is
    active, record the qmd result after re-indexing. On success:

    ```bash
    PYTHONPATH="$PWD/.brain/runtime" python3 -m brain_runtime.cli event --vault "$PWD" \
      --run-id <run-id> --kind workflow.qmd --label qmd.refresh --data-json '{"passed":true}'
    ```

    If qmd is unavailable, skipped, or fails, record it best-effort instead:

    ```bash
    PYTHONPATH="$PWD/.brain/runtime" python3 -m brain_runtime.cli event --vault "$PWD" \
      --run-id <run-id> --kind workflow.qmd --label qmd.refresh \
      --data-json '{"passed":false,"reason":"unavailable"}'
    ```

    After the WIP log has been finalized, record the mandatory workflow-log completion signal:

    ```bash
    PYTHONPATH="$PWD/.brain/runtime" python3 -m brain_runtime.cli event --vault "$PWD" \
      --run-id <run-id> --kind workflow.log --label capture.log --data-json '{"passed":true}'
    ```

    If finalizing the capture log itself failed, record `workflow.log` with `passed:false` if
    possible, but do not let the runtime change current capture behavior in shadow mode:

    ```bash
    PYTHONPATH="$PWD/.brain/runtime" python3 -m brain_runtime.cli event --vault "$PWD" \
      --run-id <run-id> --kind workflow.log --label capture.log --data-json '{"passed":false}'
    ```

    Then verify and finish the run:

    ```bash
    PYTHONPATH="$PWD/.brain/runtime" python3 -m brain_runtime.cli verify --vault "$PWD" \
      --run-id <run-id>
    PYTHONPATH="$PWD/.brain/runtime" python3 -m brain_runtime.cli finish --vault "$PWD" \
      --run-id <run-id>
    ```

    Display only the CLI's one-line `Runtime shadow: ACCEPT/REJECT ...` summary. Do not paste
    `verification.json` into context unless a human asks or the agent is debugging a runtime error.

The `semantic` CLI command is only a feed-in point in this pilot. Capture must not automatically spawn a model verifier yet; deterministic checks are evaluated before semantic grader behavior is
introduced.

## Batch Mode

Ingest multiple sources at once. **CRITICAL: Each source gets the full deep extraction treatment --
no lightweight/skim profiles.** Run the complete capture workflow for every file.

**Flow:**
1. Glob all files matching pattern
2. For each: run the complete workflow (convert -- locate high-signal sections -- targeted read --
   stage candidates -- execute the reconcile handoff -- settle `key_claims` -- update entities/index/log)
3. Process **one by one sequentially**: one source goes fully through its reconcile handoff
   before the next source begins. Each source gets exactly **one reconciliation record and
   one reconcile run** -- never share a record across sources and never re-run reconcile for
   a source whose record is already terminal.
4. If a review is deferred mid-batch, finalize the current source as **partial** (step 12),
   report the resume command `/second-brain-reconcile <source-id>`, and continue with the next
   source. Do not block the batch on a pending human decision.
5. Generate summary report: sources processed, candidates staged, claims applied, reviews
   pending/rejected, contradictions flagged
6. Update `index.md` and `log.md`

**Anti-pattern:** Creating source and company pages without reading the relevant extracted markdown and
staging candidates. Every source must produce candidates -- that's how the brain compounds.
An equally bad anti-pattern: writing claim pages directly and skipping the reconciliation
record. Claims exist only through reconcile.

## Runtime-off behavior

When `BRAIN_RUNTIME_MODE=off`, make **no** runtime calls at all -- no `start`, `snapshot`,
`plan`, `event`, `declare`, `verify`, or `finish`, for either the capture or the reconcile
handoff. Everything else is identical: candidate staging, the staged record, comparator
classification, inline human review for sensitive dispositions, applied mutations,
`key_claims` settlement, entity/index/log updates, lint, and qmd re-indexing all still run.
`BRAIN_RUNTIME_MODE=off` bypasses instrumentation, never the authoritative workflow.

## Extraction Profiles

Use `--profile` to apply source-type-specific extraction guidance. **All profiles follow the
interrogative method from `raw/assets/How to read an annual report in 30 minutes.md` -- don't read,
interrogate.**

For annual reports, the profile defines **what questions to answer** while
`raw/assets/high-signal-sections.md` defines **where to look first**. Keep those concerns separate:
profiles drive analysis; the high-signal file drives navigation.

| Profile | Source Types | Key Extraction Targets |
|---|---|---|
| `annual-report-v1` | Annual reports, 10-Ks | **Business model** (2-sentence explainability test). **Revenue decomposition** (organic vs acquired vs price vs FX). **Margin trends + WHY** (3-5yr). **Cash conversion** (FCF vs net income). **Debt vs cash + maturities**. **Management quality** (did they deliver? how explain failures?). **Company-specific risks** (not boilerplate). **Moat assessment** (widening/narrowing). **Capital allocation** (buybacks/dividends/reinvestment/M&A follow-through). R&D spend, CapEx, segment performance. |
| `sec-filing-v1` | SEC filings | Same as annual-report-v1 plus: legal proceedings, related-party transactions, executive compensation structure, stock-based compensation dilution. |
| `patent-v1` | Patent PDFs | Title, abstract, independent claims, assignee, inventors, priority date, IPC classes, cited patents, family relationships, competitive significance (moat contribution). |
| `industry-report-v1` | McKinsey, Gartner, etc. | Market sizing, growth rates, competitive dynamics, technology trends, forecast methodology, author incentives/bias assessment. |
| `tech-paper-v1` | arXiv, IEEE, ACM | Key innovation, performance claims, methodology, benchmarks, limitations, comparison to prior art, commercial readiness assessment. |

## Annual Report Retrieval Rules

These rules apply to `annual-report-v1` and `sec-filing-v1` when the source is a long annual report.

1. Build a **section map first** using headings from `raw/assets/high-signal-sections.md`.
2. Do not paste large grep outputs into context; retain only `line_number: heading` entries.
3. Prefer 8-15 targeted section reads over broad sequential reading -- a soft target, not a cap.
   Adjacent Tier 1 headings may be covered by a single bounded read, and inspecting every Tier 1
   section takes precedence over staying within the read-count range.
4. For every selected heading, determine a bounded line range and read only that range.
5. Extract candidate claim structures immediately after each section.
6. If a material signal appears (for example a new product, customer, impairment, plant, technology,
   or strategy), run a narrow follow-up grep for that topic and inspect only the relevant ranges.
7. Do not read low-signal sections merely for completeness.
8. The full converted markdown remains the source of truth and can be revisited when verification is needed.

## Specialist Delegation

Capture may still delegate **read-only evidence gathering** for large sources. Delegation never
covers the reconcile phase: entity resolution, classification, review, and page mutation happen
in the single capture orchestrator through the automatic handoff. When capture already chooses to
delegate a read slice, runtime instrumentation may record the existing delegation without changing
that decision:

```bash
PYTHONPATH="$PWD/.brain/runtime" python3 -m brain_runtime.cli event --vault "$PWD" \
  --run-id <run-id> --kind worker.start --label researcher.mda
# Perform the existing bounded researcher task.
PYTHONPATH="$PWD/.brain/runtime" python3 -m brain_runtime.cli event --vault "$PWD" \
  --run-id <run-id> --kind worker.finish --label researcher.mda
```

Use the specialist name and slice identifier actually assigned. If either event fails, continue the
delegation and normal capture unchanged.

A worker receives a bounded task/material reference and returns structured findings, not the
parent's accumulated research history. The following is the exclusive handoff contract: substitute
resolved values, but pass no additional parent history, source body, or transcript.

```yaml
operation: capture
slice_id: mda
source_ref: raw/annual-reports/acme-2026-annual-report.md
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

- **Researcher**: `Agent(subagent_type: "researcher")` -- read-only evidence gathering over the
  bounded material reference. Returns candidate claim structures that the orchestrator stages.
- **Curator / Analyst**: do not fan these out for the reconcile phase. Their reconcile-time
  boundaries live in the curator agent definition and apply to the single orchestrator.

## Output Contract

When capture completes, these must exist:
- Source page in `wiki/sources/src-{kebab-title}.md` with `[[company-*]]` link, a
  `reconciliation` link to the record, and `key_claims` equal to the applied result claims
  (empty only when nothing was applied)
- One reconciliation record in `wiki/reconciliations/reconcile-{source-id}.md` with
  `origin: capture` and status `complete` (or `pending_review` / `incomplete` for a
  partial finalize with the resume command reported)
- Applied result claim pages in `wiki/claims/claim-{kebab}-{uuid}.md` with
  `source_evidence`, created by reconcile -- zero is valid when every candidate was
  `irrelevant`
- Company page created or updated in `wiki/companies/company-{name}.md` with `[[src-*]]` link
- Log entry finalized in `wiki/log.md`
- `wiki/index.md` updated with new counts and the `## Reconciliations` entry
- qmd re-indexed (`qmd update && qmd embed`)

## Examples

```
/second-brain-capture --profile annual-report-v1 raw/10k/apple-2026-10k.pdf
-- Converts source to markdown
-- Builds high-signal section map
-- Reads only material Tier 1 / Tier 2 sections
-- Stages 5 material candidates into wiki/reconciliations/reconcile-src-apple-2026-10k.md
-- Executes the automatic handoff: 3 new applied, 1 corroborating applied, 1 updating approved inline
-- Settles key_claims, updates company, market, product, technology pages as relevant
-- Logs the operation with applied/pending/rejected counts
```

```
/second-brain-capture raw/patents/us12345678.pdf
  1. Convert PDF via mineru
  2. Read extracted markdown
  3. Determine: patent, assignee=Apple, tech=neural-engine
  4. Write WIP log entry
  5. Stage candidates into reconcile-src-apple-npu-patent-2026.md:
     - "NPU with 38 TOPS performance"
     - "Dynamic precision switching"
  6. Write: wiki/sources/src-apple-npu-patent-2026.md (key_claims empty, reconciliation link set)
  7. Execute the automatic handoff -- both candidates classified new and applied:
     - claim-apple-npu-38-tops
     - claim-apple-npu-dynamic-precision
  8. Settle key_claims from applied results
  9. Update: wiki/companies/company-apple.md (patent portfolio section + source backlink)
  10. Update: wiki/technologies/technology-neural-engine.md (patent refs)
  11. Update: wiki/patent-families/patent-family-apple-npu.md
  12. Update: wiki/index.md (add patent family + reconciliation entries)
  13. Finalize log entry
  14. Lint: check if "38 TOPS" contradicts existing claim-qualcomm-npu-45-tops
  15. Report: "Ingested 1 patent, staged 2 candidates, applied 2 claims, updated 4 pages, flagged 1 contradiction"
```
