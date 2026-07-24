# Page Type Templates

One YAML schema per page type under `templates/schemas/`. Each file is self-documenting — open it to see every field, valid values, body sections, and key rules for that page type.

**Load when:** creating or validating a page. Read only the schema file for the type you need.

## Quick Reference

| # | Page Type | Schema File | Directory |
|---|-----------|------------|-----------|
| 3.1 | sources | `templates/schemas/source.yaml` | wiki/sources/ |
| 3.2 | claims | `templates/schemas/claim.yaml` | wiki/claims/ |
| 3.3 | companies | `templates/schemas/company.yaml` | wiki/companies/ |
| 3.4 | technologies | `templates/schemas/technology.yaml` | wiki/technologies/ |
| 3.5 | patent-families | `templates/schemas/patent-family.yaml` | wiki/patent-families/ |
| 3.6 | markets | `templates/schemas/market.yaml` | wiki/markets/ |
| 3.7 | analyses | `templates/schemas/analysis.yaml` | wiki/analyses/ |
| 3.8 | queries | `templates/schemas/query.yaml` | wiki/queries/ |
| 3.9 | industries | `templates/schemas/industry.yaml` | wiki/industries/ |
| 3.10 | regulations | `templates/schemas/regulation.yaml` | wiki/regulations/ |
| 3.11 | standards | `templates/schemas/standard.yaml` | wiki/standards/ |
| 3.12 | applications | `templates/schemas/application.yaml` | wiki/applications/ |
| 3.13 | processes | `templates/schemas/process.yaml` | wiki/processes/ |
| 3.14 | people | `templates/schemas/person.yaml` | wiki/people/ |
| 3.15 | products | `templates/schemas/product.yaml` | wiki/products/ |
| 3.16 | concepts | `templates/schemas/concept.yaml` | wiki/concepts/ |
| 7.1 | index | `templates/schemas/index.yaml` | wiki/index.md |
| 7.2 | log | `templates/schemas/log.yaml` | wiki/log.md |

## Critical Rules (across all page types)

1. **Every claim must link to at least one source.** No unsourced claims.
2. **Source ↔ Company linkage is MANDATORY.** Every source page MUST contain a `[[company-*]]` wikilink in a `## Company` section. Every company page MUST contain a `[[src-*]]` wikilink in a `## Source` section.
3. **Confidence and status are distinct.** `confidence` = subjective certainty (may change). `status` = position in evidentiary lifecycle: plausible → confirmed/debunked → superseded. When sources disagree: `status: disputed`, populate both `source_evidence` and `counter_evidence`.
4. **UUID generation:** Content-hash-based. First 8 chars of SHA-256 of kebab-title: `{type}-$(echo -n "kebab-title" | shasum -a 256 | cut -c1-8)`. Reproducible — same title always same ID.
5. **Metadata complete.** Every page has YAML frontmatter. Unreliable data → `quality: degraded` + warning.
6. **Changelog maintained.** Every edit appends a changelog entry.
