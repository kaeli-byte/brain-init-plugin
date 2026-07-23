---
name: deep-tech-wiki
version: 1.1.0
description: >
  Maintain a deep-tech industry intelligence wiki following Karpathy's LLM Wiki pattern.
  Handles 10K filings, patents, industry reports, tech papers, and white papers.
  Compounds knowledge across sources through structured ingest, query, lint, reconciliation,
  investigation, and decision-output workflows. Pure skills + markdown + qmd — no n8n/webhooks.
tools: ["Read", "Edit", "Grep", "Glob", "Bash", "Write"]
---

# Deep-Tech Industry Intelligence Wiki — Skill

## Overview

This skill implements the **Karpathy LLM Wiki pattern** for deep-tech industry intelligence:
- **Raw sources** (10Ks, patents, reports, papers) → immutable, read-only
- **Wiki** (analyses, claims, companies, technologies, etc.) → LLM-maintained, compounding
- **Schema** (CLAUDE.md) → conventions that evolve with the domain

The wiki is a **persistent, compounding artifact**. Every source strengthens or challenges existing knowledge. Nothing is re-derived from scratch.

> **Schema reference:** See `CLAUDE.md` for the full directory architecture (§2), page type templates with YAML frontmatter (§3), linking conventions (§5), and quality standards (§6). This skill focuses on *how* to execute commands — CLAUDE.md defines *what* to produce.
>
> **Specialist agents:** Three subagents are available for parallel orchestration — Researcher (search + evidence gathering, read-only), Analyst (thesis testing + implications, writes analyses only), and Curator (entity resolution + merge + index maintenance, full wiki write). Spawn via `Agent(subagent_type: "researcher|analyst|curator")`. See `.claude/agents/researcher.md`, `.claude/agents/analyst.md`, `.claude/agents/curator.md` for contracts. Role contracts in this skill directory provide additional detail.
>
> **Knowledge policies:** See `config/purpose.md` (what the brain is for), `config/materiality.md` (when a finding merits a wiki page), and `config/retrieval.md` (qmd query protocol and stopping conditions).

---

## Commands

### `/capture <source-path-or-url>`

Ingest a new source into the wiki.

**Flow:**
1. Determine source type (10K, patent, report, paper, white-paper, etc.)
2. Save/copy original to `raw/` with canonical naming: `{type}/{company}-{year}-{title}.{ext}`
3. **Convert to markdown** using `mineru` as the primary tool for all languages (handles both English and Chinese reliably). For documents exceeding 200 pages, split into ranges (1–200, 201–400, …) and stitch the results. **Fallback:** `pdftotext -layout raw/{type}/{file}.pdf raw/{type}/{file}.md` if mineru is unavailable or splitting is impractical.
   This produces clean, LLM-optimized markdown with proper tables and structure. Both the original PDF and derived `.md` are git-excluded (they're rebuildable).
4. **Grep before reading** — search the raw `.md` for financial patterns first (`grep -n -iE 'revenue|profit|margin|cash.flow|R&D|debt|risk'`) to locate the high-signal sections. Then read those sections first. This prevents context-budget destruction from reading multi-megabyte raw files cover-to-cover.
5. Read the markdown thoroughly (target the high-signal sections identified by grep)
6. Write a WIP log entry (see CLAUDE.md §4.1 for recovery pattern)
7. Extract **claims** — write each significant claim to `claims/claim-{kebab}-{uuid}.md`. **Target 5-6 claims per source** (minimum 2). A source without claims is an incomplete ingestion — the brain cannot compound on summaries alone. Claims are the atomic unit of intelligence. Follow `config/materiality.md` to determine what merits a claim. **Set `last_reviewed` to today's date on every new claim.**
8. Write `wiki/sources/src-{kebab-title}.md` summary. **Set `last_reviewed` to today's date.**
9. Update all relevant entity pages — **bump `last_reviewed` on every modified page:**
   - `companies/` — if company mentioned
   - `technologies/` — if technology discussed
   - `people/` — if key figures named
   - `industries/` — if industry context provided
   - `markets/` — if market data included
   - `regulations/` — if regulatory implications
   - `standards/` — if standards referenced
   - `products/` — if products discussed
   - `patent-families/` — if patents cited
   - `concepts/` — if abstract ideas introduced
10. **Link source ↔ company** — MANDATORY bidirectional wikilinks:
   - Add `## Company` section with `[[company-*]]` link to the source page
   - Add `## Source` section with `[[src-*]]` link to the company page
   - No source may exist without a company link. No company may exist without a source link.
11. Update `wiki/index.md` (add new entries, update counts)
12. Finalize log entry — replace WIP with completed summary in `wiki/log.md`
13. **Run quick lint** — check for contradictions with existing claims, verify zero orphans, confirm source↔company link integrity
14. **Re-index qmd** — run `qmd update && qmd embed`. Newly created pages are invisible to hybrid search until indexed. Mandatory — skip only if no pages changed.

**Example:**
```
/capture https://www.sec.gov/Archives/edgar/data/320193/000032019325000051/aapl-20250927.htm
→ Saves to raw/10k/apple-2025-10k.html
→ Extracts 15 claims → claims/claim-apple-revenue-xyz, etc.
→ Updates company-apple, market-consumer-electronics, technology-3nm
→ Logs the operation
```

**Extraction Profiles:**

Use `--profile` to apply source-type-specific extraction guidance. **All profiles follow the interrogative method from `raw/assets/How to read an annual report in 30 minutes.md` — don't read, interrogate.**

| Profile | Source Types | Key Extraction Targets |
|---|---|---|
| `annual-report-v1` | Annual reports, 10-Ks | **Business model** (2-sentence explainability test). **Revenue decomposition** (organic vs acquired vs price vs FX). **Margin trends + WHY** (3-5yr). **Cash conversion** (FCF vs net income). **Debt vs cash + maturities**. **Management quality** (did they deliver? how explain failures?). **Company-specific risks** (not boilerplate). **Moat assessment** (widening/narrowing). **Capital allocation** (buybacks/dividends/reinvestment/M&A follow-through). R&D spend, CapEx, segment performance. |
| `sec-filing-v1` | SEC filings | Same as annual-report-v1 plus: legal proceedings, related-party transactions, executive compensation structure, stock-based compensation dilution. |
| `patent-v1` | Patent PDFs | Title, abstract, independent claims, assignee, inventors, priority date, IPC classes, cited patents, family relationships, competitive significance (moat contribution). |
| `industry-report-v1` | McKinsey, Gartner, etc. | Market sizing, growth rates, competitive dynamics, technology trends, forecast methodology, author incentives/bias assessment. |
| `tech-paper-v1` | arXiv, IEEE, ACM | Key innovation, performance claims, methodology, benchmarks, limitations, comparison to prior art, commercial readiness assessment. |

**Example with profile:**
```
/capture --profile annual-report-v1 raw/10k/apple-2025-10k.pdf
→ Applies annual-report extraction profile
→ Focuses on financials, segments, risk factors, strategic signals
→ Extracts claims with financial evidence locators
```

---

### `/capture-batch <directory-or-pattern>`

Ingest multiple sources at once. **CRITICAL: Each source gets the full deep extraction treatment — no lightweight/skim profiles.** Run the complete `/capture` workflow for every file: convert to markdown, read thoroughly, extract all material claims (2-6 per source), write full source summary + company page, cross-reference with existing wiki pages.

**Flow:**
1. Glob all files in directory matching pattern
2. For each: run complete `/capture` workflow (convert → read → extract claims → write source + company → update index)
3. Process **one by one sequentially** — never batch-create lightweight profiles
4. Generate summary report: sources processed, claims extracted, pages updated, contradictions flagged
5. Update `index.md` and `log.md`

**Anti-pattern:** Creating source and company pages without reading the extracted markdown and extracting claims. Every source must produce claims — that's how the brain compounds.

---

### `/query "<question>"`

Answer a question against the wiki.

**Flow:**
1. Read `wiki/index.md` to find relevant pages
2. Run **qmd hybrid query** across all collections with `--format json` (see `config/retrieval.md` for protocol):
   - One lexical query (exact terms, names, IDs)
   - One semantic query (intent + conceptual framing)
   - Rerank results, discard misfires
3. Read the top 5-8 returned pages in full (never treat snippets as evidence)
4. Follow claim-to-source wikilinks to retrieve exact evidence passages
5. Synthesize answer with [[wikilink]] citations and evidence locators
6. Assess confidence (high/medium/low) and flag knowledge gaps
7. **File the answer:** Write to `queries/query-{kebab-question}-{date}.md`
8. If the answer reveals new insights: also create `analyses/` or `syntheses/` page
9. Append to `log.md`

**Example:**
```
/query "How does Apple's M4 NPU compare to Qualcomm's Hexagon for on-device LLM inference?"
→ Reads index.md → finds technology-apple-neural-engine, technology-qualcomm-hexagon
→ Reads those pages + related claims
→ Synthesizes comparison with citations
→ Files to queries/query-m4-vs-hexagon-2026-07-17.md
→ If valuable: creates analyses/analysis-m4-hexagon-comparison-2026-07-17.md
```

---

### `/lint`

Health-check the entire wiki.

**Checks:**
1. **Orphans** — pages with zero inbound [[wikilinks]]. Pay special attention to source pages missing `[[company-*]]` links and company pages missing `[[src-*]]` links — these are critical integrity failures.
2. **Unresolved links (backlog)** — wikilinks that point to pages that don't exist yet. These are intentional breadcrumbs per CLAUDE.md §5. Report them as creation candidates, not errors. A growing unresolved-link count with no new pages created is a signal that the backlog isn't being worked.
3. **Contradictions (shallow)** — grep for explicit markers
4. **Contradictions (deep)** — read pairs of claims about the same entity/tech with different sources; assess semantic conflict
5. **Stale pages** — pages where `last_reviewed` is older than 90 days. Check the frontmatter field directly — no more guessing from git history. Priority-flag claims with `status: plausible` or `confidence: low` that have gone stale.
6. **Missing `last_reviewed`** — pages without the `last_reviewed` frontmatter field. All wiki pages must have it (log.md excepted).
7. **Thin coverage** — concepts mentioned 3+ times but no dedicated page
8. **Missing cross-references** — pages that should link but don't
9. **Data gaps** — important questions with insufficient evidence
10. **Source drift** — raw sources modified after ingestion (checksum mismatch)
11. **Index freshness** — `index.md` reflects actual page counts

**Output:**
- Lint report with severity (critical/warning/info)
- Suggested fixes for each issue
- Apply fixes with human approval

---

### `/synthesize <topic>`

Generate a cross-source synthesis on a topic.

**Flow:**
1. Search wiki for all pages related to topic
2. Read claims, sources, analyses, and entity pages
3. Identify patterns, contradictions, and gaps
4. Write `syntheses/synthesis-{kebab-topic}-{date}.md`
5. Update `index.md` and `log.md`

**Use when:** You have 5+ sources on a topic and want a strategic assessment.

---

### `/digest`

Weekly intelligence digest.

**Flow:**
1. Read `wiki/log.md` for the past 7 days
2. Read all new/updated pages from that period
3. Summarize: new sources, new claims, contradictions found, analyses completed
4. Identify emerging themes and knowledge gaps
5. Write `syntheses/weekly-digest-{date}.md`
6. Update `index.md`

---

### `/search <query>`

Search the wiki.

**At small scale:** Use `index.md` + grep across wiki files.
**At medium scale:** Use `qmd` CLI if available.

**Flow:**
1. Search page titles and content
2. Return ranked results with context snippets
3. Suggest related pages and claims

---

### `/status`

Show wiki health dashboard.

**Output:**
- Total pages by category
- Sources ingested (last 30 days)
- Claims by confidence level
- Active contradictions
- Orphan pages
- Stale pages (>90 days since last_reviewed)
- Knowledge gaps identified
- Last lint date
- Storage size

---

### `/reconcile <source-slug>`

Reconcile a newly ingested source against existing knowledge. **This is the compounding step** — it ensures a second source updates rather than duplicates the brain.

**Flow:**
1. Read the source summary and extracted candidate claims from the new source
2. For each entity mentioned, read existing wiki pages (company, technology, etc.)
3. For each candidate claim, search for matching or related existing claims via qmd
4. Classify every candidate into exactly one disposition:

| Disposition | Definition | Action |
|---|---|---|
| `new` | No existing claim addresses this fact | Create claim page, link to source |
| `corroborating` | Matches existing claim with consistent evidence | Add supporting source, note corroboration |
| `updating` | Newer/precise data for existing claim | Update with new evidence, preserve prior as `valid_to` |
| `contradicting` | Conflicts with existing claim | Mark existing `status: disputed`, add counterevidence, flag for review |
| `superseding` | Replaces older claim entirely | Mark old `status: superseded`, set `superseded_by`, create new |
| `irrelevant` | Not material per `config/materiality.md` | Do not create wiki page; note in job record only |

5. Produce a **reconciliation manifest** listing every candidate with its disposition, target claim (if applicable), reason, and confidence effect
6. Delegate to **curator** to apply the manifest (see `curator.md` contract). **Every page touched by the curator must have `last_reviewed` bumped to today's date.**
7. Run `/lint` to validate — ensure only declared affected pages changed
8. Flag any `contradicting` or `superseding` dispositions for human review
9. Update `index.md` and `log.md`

**Rules:**
- Later silence never invalidates an earlier claim
- Duplicate or dependent sources must not automatically raise confidence
- Only declared affected pages may change
- Material conflict, inference, thesis change, claim weakening, and supersession require human review

**Example:**
```
/capture --profile annual-report-v1 raw/annual-reports/example-supplier-2026.pdf
/reconcile src-example-supplier-2026-annual-report
→ Compares 2026 report against existing 2025 claims
→ 8 candidates: 3 corroborating, 2 updating, 1 new, 1 contradicting, 1 irrelevant
→ Updates 4 claim pages, creates 1 new, flags 1 for review
```

---

### `/investigate "<decision-question>"`

Open a structured investigation against the wiki. **Default framework: The 10 Questions from `raw/assets/How to read an annual report in 30 minutes.md`.** See CLAUDE.md §4.5 for the full list — every investigation must be able to answer the relevant subset of the 10 questions from wiki evidence.

**Flow:**
1. Create `wiki/investigations/investigation-{kebab-question}.md` from `templates/investigation.md`
2. Map the decision question to the relevant 10 Questions (which of the 10 does this investigation need to answer?)
3. **Researcher** gathers evidence: qmd queries across all collections, reads relevant claims and sources, retrieves exact passages. For each claim used, verify cash conversion, organic vs acquired growth decomposition, and management-quality signals if available.
4. **Analyst** tests the thesis: checks for counterevidence, alternative explanations, logical gaps, inconsistent definitions. Applies the moat assessment (widening or narrowing?) and capital allocation sensibility check.
5. Write the investigation with all required sections (Decision question, Scope, Thesis, Supporting evidence, Counterevidence, Alternative explanations, Unknowns, Invalidation conditions, Implications by audience lens, Change history)
6. Run `/lint` — ensure all evidence locators resolve, all claim/source IDs exist
7. Flag for human review — investigations always require human approval before becoming decision inputs

**Example:**
```
/investigate "Does vehicle electrification increase coolant connector content per platform?"
→ Creates investigations/investigation-ev-coolant-connector-content.md
→ Researcher finds 12 relevant claims, 3 sources
→ Analyst identifies mechanism: separate cooling loops for battery/motor/electronics
→ Conclusion: Supported with high confidence — BEV platforms use ~22 connectors vs ~8 for ICE
→ Flags 1 unknown: content variation by vehicle architecture
```

---

### `/decide <investigation-slug>`

Convert an approved investigation into audience-specific decision documents. **Run only after human review approves the investigation.**

**Flow:**
1. Read the approved investigation (must have `review_state: analyst_approved`)
2. **Analyst** produces a **neutral synthesis** — audience-agnostic summary of findings, confidence, and unknowns
3. **Analyst** then produces **four audience-lens documents**, each with three seniority depths:

| Lens | Leadership (1¶) | Manager (3-5 bullets) | Specialist (technical depth) |
|---|---|---|---|
| **Executive** | Strategic significance, timing, magnitude | Investment requirements, competitive response | Market mechanisms, confidence boundaries |
| **Business Development** | Revenue/cost impact, positioning | Customer targets, partnership strategy | Deal structure, qualification timelines |
| **Product Development** | Technical direction, architecture impact | Feature roadmap, make-vs-buy | Performance specs, materials, standards |
| **Industrialization** | Manufacturing implications, scale requirements | Process changes, supplier qualification | Equipment, yield, cost modeling |

4. Validate: every recommendation must cite at least one canonical claim and its supporting source
5. Conflicted, inferred, and low-confidence claims must retain their labels in outputs
6. Write each lens document to `analyses/decision-{slug}-{lens}-{date}.md`
7. Update `index.md` and `log.md`

**Rules:**
- Deliverables reinterpret emphasis, never introduce new facts
- Canonical knowledge and investigation pages remain the factual authority
- Uncertainty is exposed, not hidden — "unknown" is a valid and valuable output

**Example:**
```
/decide ev-coolant-connector-content
→ Reads approved investigation
→ Produces neutral synthesis + 4 lens documents
→ Executive: "BEV transition expands connector TAM 2-3x per vehicle"
→ BD: "Target BEV platform RFQs; qualify multi-loop connector portfolio"
→ Product: "Design for higher temp/pressure in battery cooling loops"
→ Industrialization: "Plan for 3x connector volume; evaluate new seal materials"
```

---

## Workflows (Step-by-Step)

### Ingest Walkthrough

```
Human: /capture raw/patents/us12345678.pdf

Agent:
  1. Convert PDF: use mineru skill (primary) or pdftotext -layout (fallback) on raw/patents/us12345678.pdf
  2. Read the extracted markdown
  2. Determine: patent, assignee=Apple, tech=neural-engine
  3. Write WIP log entry
  4. Extract claims:
     - "NPU with 38 TOPS performance" → claim-apple-npu-38-tops
     - "Dynamic precision switching" → claim-apple-npu-dynamic-precision
  5. Write: wiki/sources/src-apple-npu-patent-2025.md
  6. Update: wiki/companies/company-apple.md (patent portfolio section)
  7. Update: wiki/technologies/technology-neural-engine.md (patent refs)
  8. Update: wiki/patent-families/patent-family-apple-npu.md
  9. Update: wiki/index.md (add patent family entry)
  10. Finalize log entry
  11. Lint: Check if "38 TOPS" contradicts existing claim-qualcomm-npu-45-tops
  12. Report: "Ingested 1 patent, extracted 2 claims, updated 4 pages, flagged 1 contradiction"
```

### Query Walkthrough

```
Human: /query "What is the competitive landscape for on-device LLM inference chips?"

Agent:
  1. Read index.md → find relevant: technology-apple-neural-engine, technology-qualcomm-hexagon,
     technology-mediatek-dimensity-npu, market-ai-inference-edge
  2. Read those pages + related claims
  3. Synthesize:
     - Apple: M4 NPU, 38 TOPS, tight integration [[claim-apple-m4-npu-38-tops]]
     - Qualcomm: Hexagon, 45 TOPS, broader OEM adoption [[claim-qualcomm-hexagon-45-tops]]
     - MediaTek: Dimensity 9400 NPU, 50 TOPS, cost leadership [[claim-mediatek-dimensity-50-tops]]
     - Market: $X by 2027, growing at XX% CAGR [[market-ai-inference-edge]]
  4. File: queries/query-on-device-llm-chip-landscape-2026-07-17.md
  5. Suggest: "Create analysis/analysis-on-device-llm-competitive-landscape.md?"
```

### Lint Walkthrough

```
Human: /lint

Agent:
  1. Glob all wiki/ files
  2. Build inbound link graph
  3. Check each page for:
     - Orphans (0 inbound links)
     - Missing frontmatter
     - Broken wikilinks
     - Claims without sources
     - Stale pages (last_reviewed > 90 days ago)
     - Missing last_reviewed field
  4. Report unresolved wikilinks as creation candidates (not errors — per CLAUDE.md §5)
  5. Shallow contradiction scan: grep for "contradicts", "disputed", "inconsistent"
  6. Deep contradiction scan: for claims about the same entity/tech with different sources,
     read both and assess semantic conflict
  7. Check index.md freshness
  8. Generate report with fixes
  9. Present to human for approval
  10. Apply approved fixes
  11. Update log.md
```

### Reconcile Walkthrough

```
Human: /reconcile src-cooper-standard-2025-annual-report

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
  6. Validate: /lint returns no critical issues
  7. Flag contradicting disposition for human review
  8. Report: "Reconciled 15 candidates: 6 corroborating, 3 updating, 2 new, 1 contradicting, 3 irrelevant"
```

### Investigate Walkthrough

```
Human: /investigate "Does vehicle electrification increase coolant connector content per platform?"

Coordinator:
  1. Create investigations/investigation-ev-coolant-connector-content.md from template
  2. Delegate to Researcher: "Find all claims and sources about connector content, BEV thermal management,
     cooling loop architecture. Budget: 10 qmd queries, 20 page reads."
  3. Researcher returns 12 findings with evidence locators:
     - BEV thermal management requires 3+ separate cooling loops [S-1111111111111111, p. 42]
     - Each cooling loop needs inlet/outlet quick connectors [S-3333333333333333, p. 18]
     - ICE platforms typically use 1-2 cooling loops [S-1111111111111111, p. 43]
  4. Delegate to Analyst: "Test thesis: BEV platforms increase connector content.
     Quantify if possible. Identify counterevidence."
  5. Analyst returns:
     - Thesis: Supported with high confidence
     - Mechanism: Separate cooling loops for battery, motor, power electronics
     - Quantification: ~22 connectors (BEV) vs ~8 connectors (ICE)
     - Counterevidence: None found; one source notes PHEV is intermediate (~14 connectors)
     - Invalidation: Evidence that BEV platforms use integrated cooling with fewer loops
  6. Write investigation with all required sections
  7. Flag for human review
```

### Decide Walkthrough

```
Human: /decide ev-coolant-connector-content

Coordinator:
  1. Read approved investigation (review_state: analyst_approved)
  2. Delegate to Analyst: "Produce neutral synthesis + 4 lens documents"
  3. Analyst produces neutral synthesis: BEV transition expands connector TAM 2-3x per vehicle
  4. Analyst produces 4 lens documents:
     - Executive: Strategic timing, investment thesis, competitive landscape
     - BD: Target OEM BEV platforms, qualify multi-loop portfolio, partnership strategy
     - Product: Higher temp/pressure specs, new seal materials, modular connector families
     - Industrialization: 3x volume planning, potential new materials qualification
  5. Validate evidence chains: every recommendation cites a canonical claim and source
  6. Write 4 decision documents to analyses/
  7. Update index.md and log.md
```

---

## Integration with ECC

### Agent Role Contracts

This skill includes three specialist agent contracts for delegation:

- **`researcher.md`** — Search internal + external knowledge, gather evidence with exact citations, identify gaps. Delegate to this agent when you need structured findings with evidence locators.
- **`analyst.md`** — Test theses against evidence, explain causal mechanisms, produce audience-lens implications. Delegate when you need confidence-calibrated analysis with counterevidence.
- **`curator.md`** — Resolve entities, classify candidates (new/corroborating/updating/contradicting/superseding/irrelevant), merge changes, maintain indexes. Delegate when reconciling a new source into the wiki.

These contracts are read by the coordinator at delegation time. Each defines bounded responsibility, forbidden actions, required output format, and a stopping condition.

### Knowledge Policies

- **`config/purpose.md`** — What the brain supports (executive, BD, product, industrialization, investment decisions)
- **`config/materiality.md`** — When a finding merits a canonical claim vs. staying in the source record
- **`config/retrieval.md`** — qmd query protocol: resolve → formulate → rerank → read → trace → expand

### Recommended ECC Skills

> **Note:** These are aspirational integrations. Verify availability with `/ecc:skill-health` before relying on them.

- `deep-research` — For source analysis and claim extraction
- `article-writing` — For synthesis and analysis pages
- `content-engine` — For multi-format outputs (slides, reports)
- `search-first` — For research-before-writing discipline
- `iterative-retrieval` — For progressive context refinement
- `strategic-compact` — For session management at wiki scale
- `continuous-learning-v2` — Extract patterns from your curation style

### Recommended ECC Agents

- `planner` — Design wiki architecture and analysis plans
- `doc-updater` — Maintain documentation and schema
- `loop-operator` — For autonomous lint and digest cycles
- `harness-optimizer` — Tune the wiki workflow over time

### Hooks

Hooks are configured in `.claude/hooks/hooks.json`. Key hooks include:
- **SessionStart** — loads wiki schema and index on every session
- **PostToolUse** — reminds to update index on wiki edits, validates claim sourcing and evidence locators, checks investigation section completeness
- **PostToolUse (qmd)** — reminds to refresh qmd index when 5+ wiki pages have been modified
- **Stop** — logs session end to wiki/log.md

See that file for the full hook definitions.

---

## Tips

1. **Start with one industry.** 10 sources. Let it compound.
2. **Ingest one at a time initially.** Guide the LLM on what to emphasize.
3. **Claims are the atomic unit.** Invest time in claim extraction — everything else builds on this.
4. **Reconcile, don't duplicate.** Always `/reconcile` after a second source about the same entity. The brain compounds; it doesn't accumulate.
5. **Delegate to specialists.** Use the researcher/analyst/curator contracts for non-trivial work. The coordinator orchestrates; specialists execute.
6. **Let the schema evolve.** Your first CLAUDE.md is a draft. Refine it.
7. **Use Obsidian's graph view.** It's the best way to see wiki shape, orphans, and unresolved links (the backlog).
8. **Use Base views for browsing.** `Templates/Bases/*.base` provide dynamic, filtered table views of companies, claims, and sources. Open any category page or embed `![[Claims.base#By Company]]` on a company page for auto-populated related content. Bases complement qmd — Bases are for structured browsing, qmd for semantic search.
9. **Keep `last_reviewed` current.** Every edit should bump this field. Staleness linting relies on it. A page with `last_reviewed` from 6 months ago signals rot regardless of what git says.
10. **Git commit weekly.** Version history is invaluable for a compounding knowledge base.
11. **Run `/lint` weekly.** The health check separates a living wiki from a rotting one.
12. **File answers back.** Every query answer is a potential wiki page. Don't let it disappear into chat.
13. **Use content-hash UUIDs.** First 8 chars of SHA-256 of the kebab-title ensures reproducible, deduplicating IDs (see CLAUDE.md §5).
14. **Evidence over snippets.** Never treat qmd result snippets as authoritative. Read the full page. Every supported claim must have an exact evidence locator.

---

## Changelog

- v1.2.0 (2026-07-22): Kepano vault practices integration — added `last_reviewed` to all page templates and workflows, unresolved-link backlog lint check, `Templates/Bases/` dynamic views, `.obsidian/types.json` property typing. Updated `/capture`, `/lint`, `/reconcile`, `/status` to use `last_reviewed` field. Added Tip #8 (Base views) and #9 (last_reviewed discipline).
- v1.1.0 (2026-07-17): Added `/reconcile`, `/investigate`, `/decide` commands. Added extraction profiles to `/capture`. Added qmd retrieval to `/query`. Created researcher/analyst/curator agent contracts. Created config/ (purpose, materiality, retrieval) and templates/. Added evidence-locator, investigation-integrity, and qmd-refresh hooks. Pure skills + markdown + qmd — no n8n or webhooks.
- v1.0.1 (2026-07-17): Deduplicated from CLAUDE.md — trimmed ~270 lines by referencing schema file. Updated workflows with deep contradiction check and WIP logging.
- v1.0.0 (2026-07-17): Initial release — 15 wiki categories, 8 commands, full schema
