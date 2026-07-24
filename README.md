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

Health-check an existing vault. Runs 9 checks: directory structure, schema YAML,
types.json coverage, hook integrity, agent definitions, skill health, qmd health,
external dependencies, and git state.

```
/brain-init:brain-init --validate ~/brain-semiconductors
→ PASS: 9/9 checks passed. Vault is healthy.
```

### `/brain-init:brain-init --upgrade-harness <path>`

Update harness files from the plugin's bundled assets while preserving all wiki content.

```
/brain-init:brain-init --upgrade-harness ~/brain-semiconductors
→ Updated 23 harness files. Wiki content preserved (142 pages).
```

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
├── wiki/            # 17 category directories (claims, companies, sources, ...)
├── raw/             # 11 source directories (10k, patents, reports, ...)
├── templates/       # 18 YAML schemas + Base views
├── config/          # purpose.md, materiality.md, retrieval.md
├── .claude/         # hooks, agents (3), skills (5)
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
| `second-brain` | Wiki operations — /second-brain-capture, /second-brain-query, /second-brain-lint, /second-brain-synthesize, /second-brain-investigate, /second-brain-reconcile, /second-brain-status |
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
