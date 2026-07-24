---
name: second-brain-reconcile
description: >
  Reconcile a newly ingested source against existing wiki knowledge. Classifies every candidate
  claim into one of six dispositions — new, corroborating, updating, contradicting, superseding,
  or irrelevant. This is the compounding step.
version: 1.0.0
tools: [Read, Edit, Grep, Glob, Bash, Write]
---

# Reconcile — Source vs. Knowledge Reconciliation

## Overview

The compounding step. Takes candidate claims from a newly ingested source and reconciles
them against existing wiki knowledge. Every candidate gets classified into exactly one
of six dispositions. The brain compounds; it doesn't duplicate.

## Dispositions Table

| Disposition | Definition | Action |
|---|---|---|
| `new` | No existing claim addresses this fact | Create claim page, link to source |
| `corroborating` | Matches existing claim with consistent evidence | Add supporting source, note corroboration |
| `updating` | Newer/precise data for existing claim | Update with new evidence, preserve prior as `valid_to` |
| `contradicting` | Conflicts with existing claim | Mark existing `status: disputed`, add counterevidence, flag for review |
| `superseding` | Replaces older claim entirely | Mark old `status: superseded`, set `superseded_by`, create new |
| `irrelevant` | Not material per `config/materiality.md` | Do not create wiki page; note in job record only |

## Workflow

1. Read the source summary and extracted candidate claims from the new source
2. For each entity mentioned, read existing wiki pages (company, technology, etc.)
3. For each candidate claim, search for matching or related existing claims via qmd
4. Classify every candidate into exactly one disposition (see table above)
5. Produce a **reconciliation manifest** listing every candidate with its disposition,
   target claim (if applicable), reason, and confidence effect
6. Delegate to **curator** to apply the manifest. Every page touched by the curator
   must have `last_reviewed` bumped to today's date.
7. Run `/second-brain:lint` to validate — ensure only declared affected pages changed
8. Flag any `contradicting` or `superseding` dispositions for human review
9. Update `index.md` and `log.md`

**Rules:**
- Later silence never invalidates an earlier claim
- Duplicate or dependent sources must not automatically raise confidence
- Only declared affected pages may change
- Material conflict, inference, thesis change, claim weakening, and supersession require human review

## Specialist Delegation

- **Curator**: `Agent(subagent_type: "curator")` — the primary agent for reconciliation.
  Entity resolution, qmd queries, candidate classification, page updates, index maintenance.
  Give it the source summary, candidate claims, and affected entities.
- **Researcher**: `Agent(subagent_type: "researcher")` — for finding all existing claims
  about affected entities before classification begins. Returns evidence with exact locators.
- **Analyst**: `Agent(subagent_type: "analyst")` — for resolving contradictions and
  superseding claims where evidence quality matters.

## Output Contract

- Reconciliation manifest: every candidate with disposition, target claim, reason, confidence effect
- New/updated claim pages applied by curator
- Contradicting and superseding dispositions flagged for human review
- Validation: `/second-brain:lint` returns no critical issues
- `index.md` and `log.md` updated

## Example

```
/second-brain:reconcile src-example-supplier-2026-annual-report
→ Compares 2026 report against existing 2025 claims
→ 8 candidates: 3 corroborating, 2 updating, 1 new, 1 contradicting, 1 irrelevant
→ Updates 4 claim pages, creates 1 new, flags 1 for review
```

### Walkthrough

```
Human: /second-brain:reconcile src-cooper-standard-2025-annual-report

Agent (Curator):
  1. Read source summary and extracted candidate claims
  2. For each entity (Cooper Standard, fluid-conveyance, etc.), search existing wiki pages via qmd
  3. For each candidate claim, find matching existing claims:
     - Candidate K-1: "EV platforms increase connector content" →
       matches C-1111111111111111 → disposition: corroborating
     - Candidate K-2: "2025 revenue $X, up Y% YoY" →
       no existing revenue claim → disposition: new
     - Candidate K-3: "Competitor A gained share in Asia" →
       conflicts with existing claim C-2222222222222222 → disposition: contradicting
  4. Produce reconciliation manifest with all dispositions and reasons
  5. Apply manifest: update existing claims, create new ones, mark contradictions
  6. Validate: /second-brain:lint returns no critical issues
  7. Flag contradicting disposition for human review
  8. Report: "Reconciled 15 candidates: 6 corroborating, 3 updating, 2 new, 1 contradicting, 3 irrelevant"
```
