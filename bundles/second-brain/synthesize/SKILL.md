---
name: synthesize
description: >
  Generate cross-source syntheses on topics or weekly intelligence digests. Identifies patterns,
  contradictions, gaps, and produces strategic assessments across multiple sources.
tools: [Read, Edit, Grep, Glob, Bash, Write]
---

# Synthesize — Cross-Source Synthesis & Digests

## Overview

Generate cross-source syntheses. When you have 5+ sources on a topic, synthesize patterns,
contradictions, and strategic signals into a coherent assessment.

## Synthesis Workflow

1. Search wiki for all pages related to topic
2. Read claims, sources, analyses, and entity pages
3. Identify patterns, contradictions, and gaps
4. Write `syntheses/synthesis-{kebab-topic}-{date}.md`
5. Update `index.md` and `log.md`

**Use when:** You have 5+ sources on a topic and want a strategic assessment.

## Weekly Digest (/digest)

1. Read `wiki/log.md` for the past 7 days
2. Read all new/updated pages from that period
3. Summarize: new sources, new claims, contradictions found, analyses completed
4. Identify emerging themes and knowledge gaps
5. Write `syntheses/weekly-digest-{date}.md`
6. Update `index.md`

## Specialist Delegation

- **Researcher**: `Agent(subagent_type: "researcher")` — for finding all pages related
  to the synthesis topic across the wiki before writing begins.
- **Analyst**: `Agent(subagent_type: "analyst")` — for identifying patterns, contradictions,
  and confidence-calibrated strategic implications from the gathered evidence.

## Output Contract

- Synthesis: `syntheses/synthesis-{kebab-topic}-{date}.md` with patterns, contradictions, gaps
- Digest: `syntheses/weekly-digest-{date}.md` with emerging themes and knowledge gaps
- `index.md` and `log.md` updated

## Example

```
/second-brain:synthesize "BEV thermal management supply chain"
-> Searches wiki for all pages related to topic
-> Reads claims, sources, analyses, and entity pages
-> Identifies patterns, contradictions, and gaps
-> Writes syntheses/synthesis-bev-thermal-mgmt-2026-07-24.md
```
