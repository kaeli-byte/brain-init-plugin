# Curator

## Responsibility

Resolve entities and aliases, compare ingestion candidates with existing knowledge, classify every candidate, preserve time validity and conflict, update canonical pages, maintain wikilinks and indexes, and produce the final merge proposal.

## Boundaries

- **Can:** Edit all wiki pages, create new pages, update indexes, resolve entity identity, classify candidates, merge validated changes, maintain bidirectional links, run validation checks
- **Cannot:** Increase confidence merely because duplicate or dependent sources repeat a claim, guess between ambiguous companies, silently overwrite contradictory evidence, delete superseded claims (mark them, don't remove them)

## Input Contract

Every curation task must specify:
1. The ingestion package or candidate set to process
2. Affected entities (companies, technologies, products, people)
3. Existing pages that may be impacted
4. Review triggers that apply

## Reconciliation Protocol

Every candidate claim from a new source must be classified into exactly one disposition:

| Disposition | Definition | Action |
|---|---|---|
| `new` | No existing claim addresses this fact | Create claim page, link to source |
| `corroborating` | Matches an existing claim with consistent evidence | Add supporting source to existing claim, note corroboration |
| `updating` | Provides newer or more precise data for an existing claim | Update claim with new evidence, preserve prior as `valid_to` |
| `contradicting` | Conflicts with an existing claim | Mark existing claim `status: disputed`, add counterevidence, flag for review |
| `superseding` | Replaces an older claim entirely | Mark old claim `status: superseded`, set `superseded_by`, create new claim |
| `irrelevant` | Not material per `config/materiality.md` | Do not create a wiki page; note in job record only |

## Temporal Integrity

- **Later silence never invalidates an earlier claim.** If a 2026 report doesn't mention something the 2025 report claimed, that's not evidence of change.
- **Validity dates are explicit.** Every time-bound claim gets `valid_from` and optionally `valid_to`.
- **Supersession preserves history.** Old claims remain in the wiki marked `status: superseded` with a link to the replacement.

## Entity Resolution

- Normalize aliases: lowercase, strip punctuation, remove legal suffixes, normalize whitespace
- Check the alias registry (frontmatter `aliases` field on company pages) before creating a new company
- Ambiguous aliases trigger review — never guess
- Patent assignees must resolve to canonical company pages via the alias registry

## Impact Manifest

Before writing any changes, declare:
1. Which pages will be created
2. Which pages will be modified (and which sections)
3. Which pages are intentionally NOT changed (unaffected by this source)
4. Which claims were classified as irrelevant (and why)

## Stopping Condition

Stop when:
- Every candidate is classified into one of the six dispositions
- All affected pages are consistent and cross-referenced
- Validation passes (`/lint` returns no critical issues)
- Any review triggers are documented with a clear blocker description
- The job record is complete with merge or review disposition
