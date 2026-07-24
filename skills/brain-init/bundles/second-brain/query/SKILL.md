---
name: second-brain-query
description: Answer questions against wiki knowledge using hybrid search (qmd + lexical) with evidence citations and confidence calibration.
version: 1.0.0
tools: [Read, Edit, Grep, Glob, Bash, Write]
---

# Query — Wiki Knowledge Retrieval

## Overview

Answer questions against the wiki. Uses qmd hybrid queries (lexical + semantic) to find
relevant pages, reads full pages (never treats snippets as evidence), follows wikilinks
to trace evidence chains, synthesizes answers with confidence calibration, and files
results back as persistent wiki pages.

## Workflow

1. Read `wiki/index.md` to find relevant pages
2. Run **qmd hybrid query** across all collections with `--format json` (see `config/retrieval.md` for protocol):
   - One lexical query (exact terms, names, IDs)
   - One semantic query (intent + conceptual framing)
   - Rerank results, discard misfires
3. Read the top 5-8 returned pages in full (never treat snippets as evidence)
4. Follow claim-to-source wikilinks to retrieve exact evidence passages
5. Synthesize answer with `[[wikilink]]` citations and evidence locators
6. Assess confidence (high/medium/low) and flag knowledge gaps
7. **File the answer:** Write to `queries/query-{kebab-question}-{date}.md`
8. If the answer reveals new insights: also create `analyses/` or `syntheses/` page
9. Append to `log.md`

### Search (lightweight fallback)

When qmd is unavailable or the query is simple:

1. Search page titles and content via `index.md` + grep across wiki files
2. Return ranked results with context snippets
3. Suggest related pages and claims

## Specialist Delegation

- **Researcher**: `Agent(subagent_type: "researcher")` — for running qmd hybrid queries,
  gathering evidence from matching pages, and returning findings with exact citations.
  Use when the question spans multiple entities or requires cross-source evidence.
- **Curator**: `Agent(subagent_type: "curator")` — if the query reveals new claims or
  contradictions that should be formalized as canonical pages.
- **Analyst**: `Agent(subagent_type: "analyst")` — for answering complex decision-adjacent
  questions where confidence calibration and counterevidence matter.

## Output Contract

- Answer filed to `queries/query-{kebab-question}-{date}.md`
- If insights warrant: new `analyses/` or `syntheses/` page created
- Log entry appended to `wiki/log.md`
- All evidence cited with `[[wikilink]]` and evidence locators

## Example

```
/second-brain:query "How does Apple's M4 NPU compare to Qualcomm's Hexagon for on-device LLM inference?"
1. Read index.md → finds technology-apple-neural-engine, technology-qualcomm-hexagon
2. Run qmd hybrid query: lexical + semantic, rerank
3. Read those pages + related claims
4. Follow claim-to-source wikilinks for exact evidence passages
5. Synthesize comparison with citations
6. Confidence: medium (limited head-to-head benchmarks)
7. File to queries/query-m4-vs-hexagon-2026-07-17.md
8. Suggest: create analysis-m4-hexagon-comparison.md
```

## Query Walkthrough

```
Human: /second-brain:query "What is the competitive landscape for on-device LLM inference chips?"

Agent:
  1. Read index.md → find relevant: technology-apple-neural-engine, technology-qualcomm-hexagon,
     technology-mediatek-dimensity-npu, market-ai-inference-edge
  2. Run qmd hybrid query across all collections
  3. Read those pages + related claims
  4. Synthesize:
     - Apple: M4 NPU, 38 TOPS, tight integration [[claim-apple-m4-npu-38-tops]]
     - Qualcomm: Hexagon, 45 TOPS, broader OEM adoption [[claim-qualcomm-hexagon-45-tops]]
     - MediaTek: Dimensity 9400 NPU, 50 TOPS, cost leadership [[claim-mediatek-dimensity-50-tops]]
     - Market: $X by 2027, growing at XX% CAGR [[market-ai-inference-edge]]
  5. File: queries/query-on-device-llm-chip-landscape-2026-07-17.md
  6. Suggest: "Create analysis/analysis-on-device-llm-competitive-landscape.md?"
```
