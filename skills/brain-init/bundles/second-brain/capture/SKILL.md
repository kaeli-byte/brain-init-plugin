---
name: second-brain-capture
description: >
  Ingest a source (10-K, patent, report, paper) into the wiki. Extracts claims, writes source summary,
  updates entities, and ensures bidirectional source-company wikilinks.
version: 1.1.0
tools: [Read, Edit, Grep, Glob, Bash, Write]
---

# Capture -- Source Ingestion Pipeline

## Overview

Ingest a new source into the wiki. The capture pipeline converts raw sources into structured
intelligence -- claims (the atomic unit), source summaries, entity pages, and the critical
bidirectional source-company wikilinks that make the wiki graph navigable.

## Workflow

1. **Determine source type** -- 10K, China annual report, patent, report, paper, white-paper, etc.
2. **Save original** to `raw/{type}/{company}-{year}-{title}.{ext}`
3. **Convert to markdown** using `mineru` (primary). Split documents over 200 pages into ranges
   (1-200, 201-400, ...) and stitch. Fallback: `pdftotext -layout`. Both PDF and `.md` are
   git-excluded (rebuildable).
4. **Locate high-signal sections before reading** -- for annual reports and 10-Ks, use the
   section-heading patterns in `raw/assets/high-signal-sections.md`.
   - Use grep as a **navigation tool**, not as the extraction step.
   - Keep only section names and line numbers in context.
   - Build a compact section map before loading section bodies.
   - Use the US/10-K locator set for SEC-style filings and the China locator set for Chinese listed-company annual reports.
   - Generic keyword grep may be used later for targeted follow-up, but not as the primary navigation method.
5. **Read only high-signal sections** -- never read a large annual report sequentially or load the
   full markdown into context.
   - **Tier 1:** always inspect.
   - **Tier 2:** inspect when material, referenced by Tier 1, or needed to resolve an open research question.
   - **Tier 3:** inspect only when specifically relevant.
   - Read bounded line ranges from one located heading to the next heading of equal or higher level.
   - Extract useful evidence and candidate claims from each section before reading the next section.
   - Stop retrieval when the material research questions in the active extraction profile are sufficiently answered.
6. **Write a WIP log entry** (see CLAUDE.md for recovery pattern).
7. **Extract claims** -- write each significant claim to
   `wiki/claims/claim-{kebab}-{uuid}.md`. Target 5-6 claims per source (minimum 2), but do not
   create low-value claims merely to satisfy a quota. Set `last_reviewed` to today's date on every
   new claim. Follow materiality policy.
8. **Write source summary** to `wiki/sources/src-{kebab-title}.md`. Set `last_reviewed`.
9. **Update all relevant entity pages** and bump `last_reviewed` on every modified page:
   companies, technologies, people, industries, markets, regulations, standards, products,
   patent-families, concepts.
10. **Link source -- company** -- mandatory bidirectional wikilinks:
    - Source page: `## Company` section with `[[company-*]]`
    - Company page: `## Source` section with `[[src-*]]`
11. **Update** `wiki/index.md` -- add new entries, update counts.
12. **Finalize log entry** -- replace WIP with completed summary in `wiki/log.md`.
13. **Quick lint** -- check for contradictions with existing claims, verify zero orphans,
    confirm source-company link integrity.
14. **Re-index qmd** -- run `qmd update && qmd embed`. New pages are invisible to hybrid
    search until indexed.

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
5. Extract candidate claims immediately after each section.
6. If a material signal appears (for example a new product, customer, impairment, plant, technology,
   or strategy), run a narrow follow-up grep for that topic and inspect only the relevant ranges.
7. Do not read low-signal sections merely for completeness.
8. The full converted markdown remains the source of truth and can be revisited when verification is needed.

## Batch Mode

Ingest multiple sources at once. **CRITICAL: Each source gets the full deep extraction treatment --
no lightweight/skim profiles.** Run the complete capture workflow for every file.

**Flow:**
1. Glob all files matching pattern
2. For each: run complete workflow (convert -- locate high-signal sections -- targeted read -- extract claims -- write source + company -- update index)
3. Process **one by one sequentially** -- never batch-create lightweight profiles
4. Generate summary report: sources processed, claims extracted, pages updated, contradictions flagged
5. Update `index.md` and `log.md`

**Anti-pattern:** Creating source and company pages without reading the relevant extracted markdown and
extracting claims. Every source must produce claims -- that's how the brain compounds.

## Specialist Delegation

When the source is large or complex, spawn specialist subagents:

- **Curator**: `Agent(subagent_type: "curator")` -- for entity resolution, claim classification,
  page creation, index updates. Give it candidate claims, target entities, and the source summary.
- **Analyst**: `Agent(subagent_type: "analyst")` -- for testing extracted claims against existing
  wiki knowledge. Returns confidence-calibrated findings with counterevidence.
- **Researcher**: `Agent(subagent_type: "researcher")` -- read-only evidence gathering. Use for
  searching existing wiki pages for related claims before creating duplicates.

## Output Contract

When capture completes, these must exist:
- Source page in `wiki/sources/src-{kebab-title}.md` with `[[company-*]]` link
- 2-6 claim pages in `wiki/claims/claim-{kebab}-{uuid}.md` with `source_evidence` (target 5-6; fewer than 5 only when materiality does not support more -- never pad to hit a quota)
- Company page created or updated in `wiki/companies/company-{name}.md` with `[[src-*]]` link
- Log entry finalized in `wiki/log.md`
- `wiki/index.md` updated with new counts
- qmd re-indexed (`qmd update && qmd embed`)

## Examples

```
/second-brain:capture --profile annual-report-v1 raw/10k/apple-2025-10k.pdf
-- Converts source to markdown
-- Builds high-signal section map
-- Reads only material Tier 1 / Tier 2 sections
-- Extracts material claims
-- Updates company, market, product, technology and source pages as relevant
-- Logs the operation
```

```
/second-brain:capture raw/patents/us12345678.pdf
  1. Convert PDF via mineru
  2. Read extracted markdown
  3. Determine: patent, assignee=Apple, tech=neural-engine
  4. Write WIP log entry
  5. Extract claims:
     - "NPU with 38 TOPS performance" -- claim-apple-npu-38-tops
     - "Dynamic precision switching" -- claim-apple-npu-dynamic-precision
  6. Write: wiki/sources/src-apple-npu-patent-2025.md
  7. Update: wiki/companies/company-apple.md (patent portfolio section)
  8. Update: wiki/technologies/technology-neural-engine.md (patent refs)
  9. Update: wiki/patent-families/patent-family-apple-npu.md
  10. Update: wiki/index.md (add patent family entry)
  11. Finalize log entry
  12. Lint: check if "38 TOPS" contradicts existing claim-qualcomm-npu-45-tops
  13. Report: "Ingested 1 patent, extracted 2 claims, updated 4 pages, flagged 1 contradiction"
```
