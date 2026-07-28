---
reconciliation_id: reconcile-src-acme-2026-annual-report
source: "[[src-acme-2026-annual-report]]"
origin: capture
status: complete
search_method: qmd
coverage_complete: true
created: 2026-07-27
last_reviewed: 2026-07-27
candidates:
  - candidate_id: candidate-e563869d0def
    claim_text: "Acme's 2026 revenue reached RMB 12 billion."
    source_evidence:
      - source: "[[src-acme-2026-annual-report]]"
        passage: "Revenue for 2026 was RMB 12 billion."
        context: "Page 12, Results of Operations"
    entities: ["[[company-acme]]"]
    disposition: new
    target_claim:
    reason: "No existing claim covers 2026 revenue."
    confidence_effect: unchanged
    review_state: not_required
    action_state: applied
    result_claim: "[[claim-acme-revenue-2026]]"
    reviewed_by:
    reviewed_at:
    review_note:
  - candidate_id: candidate-1cccc6651796
    claim_text: "Acme's 2026 operating margin increased to 14 percent."
    source_evidence:
      - source: "[[src-acme-2026-annual-report]]"
        passage: "Operating margin increased to 14 percent in 2026."
        context: "Page 38, Management Discussion and Analysis"
    entities: ["[[company-acme]]"]
    disposition: corroborating
    target_claim: "[[claim-acme-operating-margin]]"
    reason: "Existing claim makes the same material proposition."
    confidence_effect: unchanged
    review_state: not_required
    action_state: applied
    result_claim: "[[claim-acme-operating-margin]]"
    reviewed_by:
    reviewed_at:
    review_note:
---
# Reconciliation: Acme 2026 Annual Report

## Summary

Two candidates reconciled from the 2026 annual report: one new revenue claim and
one corroborating operating-margin update.

## Pending Review

None.

## Changelog

- Applied `new` candidate as [[claim-acme-revenue-2026]].
- Corroborated [[claim-acme-operating-margin]] with 2026 evidence.
