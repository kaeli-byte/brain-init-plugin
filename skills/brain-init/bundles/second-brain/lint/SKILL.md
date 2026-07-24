---
name: lint
description: Health-check the entire wiki — orphans, contradictions, stale pages, missing cross-references, index freshness, and source drift.
version: 1.0.0
tools: [Read, Edit, Grep, Glob, Bash, Write]
---

# Lint — Wiki Health Check

## Overview

Run 11 health checks against the entire wiki. Detects orphans, contradictions (shallow + deep),
stale pages (>90 days since last_reviewed), missing last_reviewed fields, thin coverage,
missing cross-references, data gaps, source drift (checksum mismatch), and index freshness.

Produces a severity-ranked report (critical/warning/info) with suggested fixes.
Apply fixes with human approval.

## Checks

| # | Check | Severity | Detection Method |
|---|---|---|---|
| 1 | **Orphans** | critical | Zero inbound [[wikilinks]]; missing [[company-*]]/[[src-*]] links |
| 2 | **Unresolved links (backlog)** | info | Wikilinks pointing to non-existent pages (creation candidates, not errors) |
| 3 | **Contradictions (shallow)** | critical | grep for `contradicts`, `disputed`, `inconsistent` markers |
| 4 | **Contradictions (deep)** | critical | Read pairs of claims about same entity/tech with different sources; assess semantic conflict |
| 5 | **Stale pages** | warning | `last_reviewed` > 90 days ago; flag plausible/low claims gone stale |
| 6 | **Missing `last_reviewed`** | warning | Page lacks `last_reviewed` frontmatter field |
| 7 | **Thin coverage** | info | Concept mentioned 3+ times across wiki but no dedicated page |
| 8 | **Missing cross-references** | warning | Pages that should link to each other but don't |
| 9 | **Data gaps** | warning | Important questions with insufficient evidence |
| 10 | **Source drift** | critical | Raw source modified after ingestion (checksum mismatch) |
| 11 | **Index freshness** | info | `index.md` does not reflect actual page counts |

### Contradiction Checking

- **Shallow** — pattern-based scan: grep for explicit contradiction markers (`contradicts`, `disputed`, `inconsistent`) in page content. Fast, low-noise, catches pages where the author self-tagged a conflict.
- **Deep** — semantic scan: for claims about the same entity or technology backed by different sources, read both source pages and assess whether they are in genuine conflict. Catches untagged logical contradictions (e.g., two source pages about the same API version with different supported operations). Slower but catches what shallow misses.

## Workflow

1. Glob all `wiki/` files
2. Build inbound link graph (count inbound [[wikilinks]] per page)
3. Check each page for: orphans, missing frontmatter, broken wikilinks, claims without sources, stale `last_reviewed`, missing `last_reviewed` field
4. Report unresolved wikilinks as creation candidates (not errors — per CLAUDE.md section 5)
5. Run shallow contradiction scan (grep)
6. Run deep contradiction scan (read paired claims)
7. Check `index.md` freshness against actual page count
8. Generate severity-ranked report with suggested fixes
9. Present report to human for approval
10. Apply approved fixes
11. Update `log.md`

## Output Contract

- Lint report with severity (critical/warning/info) per finding
- Suggested fixes for each issue
- Fixes applied only with human approval
- `log.md` updated with run timestamp, findings count, and approvals

## Specialist Delegation

Lint is bash-forward and read-only except for fix application. No specialist agents needed
for detection. Use **Curator** for applying batched fixes if the human approves many changes.
