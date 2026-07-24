---
name: investigate
description: >
  Open a structured investigation against the wiki. Researcher gathers evidence, analyst tests
  the thesis. Produces a decision-ready document with thesis, counterevidence, unknowns, and
  invalidation conditions. Includes /decide for converting approved investigations to
  audience-specific decision documents.
version: 1.0.0
tools: [Read, Edit, Grep, Glob, Bash, Write]
---

# Investigate — Structured Decision Investigations

## Overview

Open a structured investigation against the wiki for decision questions.
Default framework: the 10 Questions from `raw/assets/How to read an annual report in 30 minutes.md`.
Researcher gathers evidence across all collections. Analyst tests the thesis with
counterevidence, alternative explanations, and logical gaps. Produces a decision-ready
document with explicit unknowns and invalidation conditions.

## Workflow

1. Create `wiki/investigations/investigation-{kebab-question}.md` from `templates/investigation.md`
2. Map the decision question to the relevant 10 Questions (which of the 10 does this investigation need to answer?)
3. **Researcher** gathers evidence: qmd queries across all collections, reads relevant claims and sources, retrieves exact passages. For each claim used, verify cash conversion, organic vs acquired growth decomposition, and management-quality signals if available.
4. **Analyst** tests the thesis: checks for counterevidence, alternative explanations, logical gaps, inconsistent definitions. Applies the moat assessment (widening or narrowing?) and capital allocation sensibility check.
5. Write the investigation with all required sections: Decision question, Scope, Thesis, Supporting evidence, Counterevidence, Alternative explanations, Unknowns, Invalidation conditions, Implications by audience lens, Change history
6. Run `/second-brain:lint` — ensure all evidence locators resolve, all claim/source IDs exist
7. Flag for human review — investigations always require human approval before becoming decision inputs

## Specialist Delegation

- **Researcher**: `Agent(subagent_type: "researcher")` — Step 3. Gathers evidence across all
  qmd collections. Returns structured findings with exact evidence locators and source quality.
- **Analyst**: `Agent(subagent_type: "analyst")` — Step 4. Tests the thesis against evidence.
  Returns confidence-calibrated findings, counterevidence, alternative explanations.

## Decision Documents (/second-brain:investigate — decision sub-workflow)

> `/decide` is a sub-workflow of investigate, invoked via the same skill with a decision flag or as a follow-up. Use `/second-brain:investigate` with the decision flag.

Convert an approved investigation into audience-specific decision documents. **Run only after human review approves the investigation.**

**Flow:**
1. Read the approved investigation (must have `review_state: analyst_approved`)
2. **Analyst** produces a **neutral synthesis** — audience-agnostic summary of findings, confidence, and unknowns
3. **Analyst** then produces **four audience-lens documents**, each with three seniority depths:

| Lens | Leadership (1 paragraph) | Manager (3-5 bullets) | Specialist (technical depth) |
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

## Output Contract

- Investigation in `investigations/investigation-{kebab-question}.md` with all 10 required sections
- `/second-brain:lint` confirms all evidence locators resolve
- Flagged for human review before `/second-brain:investigate --action decide` runs (`/decide` is a sub-workflow of investigate, invoked via the same skill with a decision flag)
- If approved: 4 audience-lens decision documents in `analyses/decision-{slug}-{lens}-{date}.md`

## Example

```
/second-brain:investigate "Does vehicle electrification increase coolant connector content per platform?"
-> Researcher finds 12 claims, 3 sources
-> Analyst identifies mechanism: separate cooling loops for battery/motor/electronics
-> Conclusion: Supported — BEV platforms use ~22 connectors vs ~8 for ICE

/second-brain:investigate --action decide ev-coolant-connector-content
(`/decide` is a sub-workflow of investigate, invoked via the same skill with a decision flag)
-> Reads approved investigation (review_state: analyst_approved)
-> Produces neutral synthesis + 4 lens documents (Executive, BD, Product, Industrialization)
```
