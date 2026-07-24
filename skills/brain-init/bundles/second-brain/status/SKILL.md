---
name: second-brain-status
description: Show wiki health dashboard — page counts, sources ingested, claims by confidence, active contradictions, orphans, stale pages, and knowledge gaps.
version: 1.0.0
tools: [Read, Grep, Glob, Bash]
---

# Status — Wiki Health Dashboard

## Overview

Display a read-only health dashboard for the wiki. Pure information — no writes, no modifications.

## Dashboard Sections

- Total pages by category (from `wiki/index.md` counts)
- Sources ingested (last 30 days, from `wiki/log.md`)
- Claims by confidence level (high/medium/low)
- Active contradictions (grep for `status: disputed`)
- Orphan pages (zero inbound `[[wikilinks]]`)
- Stale pages (>90 days since `last_reviewed`)
- Knowledge gaps identified
- Last lint date (from `wiki/log.md`)
- Storage size (`du -sh wiki/ raw/`)

## Workflow

1. Read `wiki/index.md` for page counts
2. Read `wiki/log.md` for recent activity
3. Grep wiki for confidence distribution, contradictions, orphans
4. Check `last_reviewed` frontmatter for staleness
5. Present as a formatted dashboard

## Specialist Delegation

None. Status is bash + grep + read-only. No agents needed.
