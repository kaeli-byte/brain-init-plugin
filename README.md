# brain-init — Industrial Intelligence Brain Scaffolding

Initialize a complete Industrial Intelligence Brain vault. Creates the full harness —
directory tree, 18 YAML schemas, Obsidian vault config, Claude Code hooks, agent
definitions, qmd collections, Base views, 5 supporting skills, and a domain-adapted
`CLAUDE.md`. **Self-contained — no external template repo required.**

## Installation

brain-init is distributed as a Claude Code plugin. Install once:

```
/plugin marketplace add https://github.com/kaeli-byte/brain-init-plugin
/plugin install brain-init@brain-init
```

The plugin bundles ~348 KB of scaffolding assets internally.

## Quick Start

```
/brain-init:brain-init ~/my-brain
```

This scaffolds a full `industrial-intelligence` vault at `~/my-brain` with all
defaults. You'll be walked through an onboarding flow (domain, name, git remote,
tools, tokens) before anything is written.

## Commands

### `/brain-init:brain-init <path> [options]`

Initialize a new brain vault.

```
/brain-init:brain-init ~/brain-semiconductors --domain semiconductor
/brain-init:brain-init ~/quick-experiment --bare
/brain-init:brain-init ~/custom --domain-custom "Renewable energy supply chains"
```

### `/brain-init:brain-init --validate <path>`

Health-check an existing vault. Runs 11 validation sections covering directory
structure, schema YAML, types.json coverage, hook integrity, agent definitions,
skill health, the Brain Runtime, qmd health, wiki/root integrity, external
dependencies, and git state. The validator reports granular pass, failure, and
warning totals.

```text
/brain-init:brain-init --validate ~/brain-semiconductors
→ Validation Complete
  Passed:   <checks passed>
  Failed:   0
  Warnings: <environment-dependent warnings>
```

### `/brain-init:brain-init --upgrade-harness <path>`

Update harness files from the plugin's bundled assets while preserving all wiki content.

```
/brain-init:brain-init --upgrade-harness ~/brain-semiconductors
→ Updated 23 harness files. Wiki content preserved (142 pages).
```

## Capture → staged reconcile → canonical claim flow

Capture and reconcile form one loop over each source:

1. **Capture stages candidates.** `/second-brain-capture` converts a source,
   extracts 2–6 material candidate claims, and writes them into a canonical
   reconciliation record at `wiki/reconciliations/reconcile-<source-id>.md`.
   The source page links the record via its `reconciliation` field and starts
   with `key_claims: []`.
2. **Reconcile decides.** `/second-brain-reconcile` classifies every candidate
   against the canonical graph into one of six dispositions and mutates the
   graph accordingly. Reconcile is the only mutating orchestrator.
3. **Capture settles.** The source page's `key_claims` are settled from the
   terminal applied results, and entities, index, and log are updated.

Dispositions split into two classes:

| Disposition | Effect | Review |
|---|---|---|
| `new` | Creates a new claim page | Applied automatically |
| `corroborating` | Adds source evidence to the target claim | Applied automatically |
| `irrelevant` | Recorded as rejected; no graph mutation | Applied automatically |
| `updating` | Sets `valid_from`/`valid_to` bounds or `superseded_by` links on the target | **Inline human review** |
| `contradicting` | Marks both claims `disputed` with opposing `counter_evidence` and reciprocal `## Related Claims` links | **Inline human review** |
| `superseding` | Links the new claim via `superseded_by`; the old claim is preserved, never deleted | **Inline human review** |

Sensitive dispositions (`updating`, `contradicting`, `superseding`) are gated
behind one inline **Approve / Reject / Defer** question per candidate. The
decision is persisted in the record (`reviewed_by`, `reviewed_at`,
`review_note`) **before** any mutation, so the graph never changes without a
recorded human decision.

If review is deferred or the run stops early, the record stays
`pending_review` or `incomplete` and can be resumed with:

```
/second-brain-reconcile <source-id>
```

**Legacy bootstrap.** A source that predates the reconcile contract (linked
claims in `key_claims` but no record) is bootstrapped: candidates are derived
from the linked claims with `origin: legacy`, every linked claim is
represented without truncation, existing claim bytes are unchanged before
approval, and the resulting record is resumable like any other.

**Shadow runtime.** When the Brain Runtime is installed, both capture and
reconcile run under shadow instrumentation (`RunSpec.mode == "shadow"`): the
runtime snapshots `wiki/`, validates declared artifacts and run events, and
reports `Runtime shadow: ACCEPT` or `REJECT`. A shadow `REJECT` is advisory —
it never alters, removes, or rolls back the authoritative reconciliation.
`BRAIN_RUNTIME_MODE=off` is a skill-level contract: with it, the skill never
invokes the runtime CLI, but staging, classification, review, and apply still
run unchanged.

**Ownership.** The reconciliation record under `wiki/reconciliations/` is
canonical, git-tracked knowledge. Run snapshots under `.brain/runs/<run-id>/`
are operational records — git-ignored, never containing source bodies, model
transcripts, or chain-of-thought.

## Domain Presets

| Preset | Focus |
|---|---|
| `industrial-intelligence` | Automotive, fluid handling, thermal management, supply chains |
| `semiconductor` | Chip design, fabs, EDA, process nodes, foundry competition |
| `biotech` | Drug development, clinical trials, FDA/EMA, patent cliffs |
| `energy` | Generation, storage, grid, renewables, policy drivers |
| `materials` | Advanced materials, composites, metallurgy, specialty chemicals |
| Custom | Free-text description — `CLAUDE.md` + `purpose.md` are LLM-generated |

## Options

| Flag | Effect |
|---|---|
| `--domain <preset>` | Domain template (default: `industrial-intelligence`) |
| `--domain-custom "..."` | LLM generates domain-adapted config from your description |
| `--bare` | Minimal: directories + stubs + .gitignore only |
| `--no-git` | Skip `git init` and initial commit |
| `--no-qmd` | Skip qmd collection initialization |
| `--no-obsidian` | Skip Obsidian vault config and plugins |
| `--no-supporting-skills` | Skip mineru-batch, cfi-filings, sec-edgar, tianyancha |
| `--name "My Brain"` | Vault display name (default: basename of path) |
| `--template-path <dir>` | Override template source |
| `--git-remote <url>` | Set `git remote origin` after init |
| `--force` | Proceed into non-empty directory |

## What Gets Created

```
my-brain/
├── wiki/            # 18 category directories (claims, companies, sources, reconciliations, ...)
├── raw/             # 11 source directories (10k, patents, reports, ...)
├── templates/       # 18 YAML schemas + Base views
├── config/          # purpose.md, materiality.md, retrieval.md
├── .claude/         # hooks, agents (3), skills (7)
├── .obsidian/       # vault config, plugins (dataview, templater, obsidian-git)
├── CLAUDE.md        # Domain-adapted schema
├── .env.example     # Token placeholders
└── .gitignore
```

## What's Bundled (348 KB, 59 files)

| Asset Group | Files | Size |
|---|---|---|
| YAML schemas | 18 | ~45 KB |
| Domain templates (CLAUDE.md + purpose.md) | 10 | ~50 KB |
| Hooks, settings, agents | 5 | ~25 KB |
| Obsidian config (JSON) | 6 | ~3 KB |
| Config docs + Base views | 6 | ~35 KB |
| Supporting skills (5) | 12 | ~175 KB |
| Shell scripts | 2 | ~18 KB |

No external template repo required. No network access needed during init.

## Dependencies Checked

| Dependency | Severity | Purpose |
|---|---|---|
| `python3` | WARN | All tooling |
| `yaml`, `requests` | WARN | Schema parsing, HTTP |
| `qmd` | WARN | Semantic search |
| `pdftotext` | WARN | PDF fallback converter |
| `agent_gw` | WARN | sec-edgar + tianyancha data sources |
| `KIMI_API_KEY` | WARN | Kimi data source auth |
| `MINERU_TOKEN` | WARN | PDF extraction via MinerU |

All are WARN-level — none block vault initialization.

## Post-Init

1. **Open in Obsidian** — Obsidian auto-downloads dataview, templater, and obsidian-git on first open.
2. **Set tokens** — edit `.env` with real API keys
3. **Run `/second-brain-capture`** on your first source
4. **Run `/second-brain-lint`** to establish baseline health
5. **Commit** — the initial commit is done for you if git is enabled

## Supporting Skills (All Bundled)

| Skill | Coverage |
|---|---|
| `second-brain` | Wiki operations (7 scoped skills) — /second-brain-capture, /second-brain-query, /second-brain-lint, /second-brain-synthesize, /second-brain-investigate, /second-brain-reconcile, /second-brain-status |
| `mineru-batch` | PDF → Markdown conversion (all languages) |
| `cfi-filings` | Chinese A-share periodic filings |
| `sec-edgar` | US SEC EDGAR — company info, financials, XBRL |
| `tianyancha` | 天眼查 — Chinese enterprise registry |

Use `--no-supporting-skills` to skip data-source skills (second-brain is always installed).

## Updating

```
/plugin install brain-init@brain-init                        # Get latest plugin
/brain-init:brain-init --upgrade-harness ~/my-brain          # Update existing vault
```

## Backward Compatibility

If you have a legacy `~/deep-tech-wiki` clone, it still works as a fallback template source.
The plugin takes priority when both are available. Use `--template-path` for explicit control.

## Automated PR Review

Pull requests are reviewed automatically by [OpenCodeReview](https://open-codereview.ai/docs/cicd)
(`.github/workflows/ai-review.yml`). The review is advisory: it posts one sticky
summary comment plus inline findings, and never blocks merging. It runs on
opened/updated non-draft PRs, or when a maintainer comments `/review`.

To enable it, set in **Settings → Secrets and variables → Actions**:

| Kind | Name | Value |
|---|---|---|
| Secret | `OCR_LLM_URL` | LLM API endpoint |
| Secret | `OCR_LLM_AUTH_TOKEN` | LLM auth token |
| Variable | `OCR_LLM_MODEL` | Model name |
| Variable | `OCR_LLM_USE_ANTHROPIC` | `true` for Anthropic, `false` for OpenAI-compatible |

Without these, the workflow logs a warning and skips cleanly.

## Examples

```bash
# Minimal — just directories and stubs
/brain-init:brain-init ~/scratch-pad --bare

# Full semiconductor brain with git remote
/brain-init:brain-init ~/brain-chips --domain semiconductor --git-remote git@github.com:alice/brain-chips.git

# Custom domain
/brain-init:brain-init ~/brain-solar --domain-custom "Solar panel manufacturing and photovoltaic supply chains" --no-supporting-skills

# Validate
/brain-init:brain-init --validate ~/brain-chips

# Upgrade
/brain-init:brain-init --upgrade-harness ~/brain-chips
```

---
See `SKILL.md` for the full agent-facing specification.
