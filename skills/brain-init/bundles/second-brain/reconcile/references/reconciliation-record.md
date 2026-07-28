# Reconciliation Record Reference

One git-tracked record per source: `wiki/reconciliations/reconcile-<source-id>.md`.
The YAML frontmatter is **machine-authoritative**; the Markdown body is a concise human
view, never a second machine-authoritative copy.

## Frontmatter schema

```yaml
---
reconciliation_id: reconcile-src-acme-2026-annual-report   # reconcile-<source-id>
source: "[[src-acme-2026-annual-report]]"                  # wikilink to the source page
origin: capture                # capture | legacy
status: staged                 # staged | pending_review | complete | incomplete
search_method: qmd             # qmd | filesystem | mixed | unavailable
coverage_complete: true        # boolean; required before any `new` classification
created: 2026-07-27
last_reviewed: 2026-07-27
candidates:
  - candidate_id: candidate-71c0137b6d92
    claim_text: "Acme's 2026 operating margin increased to 14%."
    source_evidence:
      - source: "[[src-acme-2026-annual-report]]"
        passage: "Operating margin increased to 14% in 2026."
        context: "Page 38, Management Discussion and Analysis"
    entities: ["[[company-acme]]"]
    disposition: updating        # new | corroborating | updating | contradicting | superseding | irrelevant
    target_claim: "[[claim-acme-operating-margin-a12b34cd]]"  # required for the four targeted dispositions; forbidden for new/irrelevant
    reason: "Same metric and entity for a newer reporting period."
    confidence_effect: unchanged # increase | decrease | unchanged | not_applicable
    review_state: pending        # not_required | pending | approved | rejected
    action_state: pending        # pending | applied | not_applicable | rejected
    result_claim:                # applied result claim link; null otherwise
    reviewed_by:                 # human — set on approved/rejected decisions
    reviewed_at:                 # YYYY-MM-DD of the decision
    review_note:                 # human rationale; non-empty on rejection
---
```

Required record fields: `reconciliation_id`, `source`, `origin`, `status`,
`search_method`, `coverage_complete`, `created`, `last_reviewed`, `candidates`.

## Record status lifecycle

- `staged` — candidate extraction is complete; classification has not completed.
- `pending_review` — all candidates are classified and at least one human decision is
  pending. Resumable: terminal candidates are skipped on resume.
- `complete` — every candidate has a terminal action.
- `incomplete` — classification or comparator coverage could not be completed safely.
  Resume repeats comparator discovery only for unresolved candidates.

Unclassified candidate fields may be null **only** while the record is `staged` or
`incomplete`. A `complete` or `pending_review` record gives every candidate one of the
six final dispositions.

## Deterministic candidate identifiers

1. Normalize `claim_text` by trimming it and collapsing internal whitespace to one space.
2. Hash `source_id + "\n" + normalized_claim_text` with SHA-256.
3. Take the first 12 lowercase hexadecimal characters: `candidate-<12-char-hash>`.

Compute IDs through the runtime when available:

```bash
PYTHONPATH="$PWD/.brain/runtime" python3 -c \
  'from brain_runtime.reconcile_contract import candidate_id; import sys; print(candidate_id(sys.argv[1], sys.argv[2]))' \
  "$SOURCE_ID" "$CLAIM_TEXT"
```

Fallback (runtime package unavailable) — equivalent standard-library snippet:

```bash
python3 - "$SOURCE_ID" "$CLAIM_TEXT" <<'PY'
import hashlib, sys
payload = f"{sys.argv[1].strip()}\n{' '.join(sys.argv[2].split())}"
print("candidate-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12])
PY
```

Candidate identity must never depend on model-generated UUIDs. Duplicate candidate IDs
in one record are invalid.

## Candidate counts

- New capture records target **2–6 material candidates** without padding; more than six
  is a warning.
- Legacy bootstrap records process **every linked claim** without truncation and may
  exceed six.

## Disposition summary

| Disposition | Review | Effect |
|---|---|---|
| `new` | automatic | create one claim page; `result_claim` = new page |
| `corroborating` | automatic | add source evidence to target; `result_claim` = target; no duplicate page |
| `irrelevant` | automatic | no claim; `action_state: not_applicable` |
| `updating` | human | replacement gets `valid_from`; target gets `valid_to`, `status: superseded`, `superseded_by` |
| `contradicting` | human | both claims `status: disputed`, opposing `counter_evidence`, reciprocal `## Related Claims` links |
| `superseding` | human | target `status: superseded` with `superseded_by`; old page and evidence preserved |

Rejected sensitive actions: `review_state: rejected`, `action_state: rejected`,
`reviewed_by: human`, `reviewed_at` set, non-empty `review_note`, `result_claim` null,
and **no** canonical claim or entity mutation.

Reconciliation never deletes a canonical claim. History is preserved with lifecycle
fields and links.

## Required body

```markdown
# Reconciliation: <source title>

## Summary

## Pending Review

## Changelog
```

The body summarizes frontmatter for humans. `## Pending Review` lists candidates
awaiting a decision (with their review questions); `## Changelog` lists applied actions.
