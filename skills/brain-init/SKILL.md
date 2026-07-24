---
name: brain-init
version: 1.1.2
description: >
  Initialize a new Industrial Intelligence Brain vault. Creates the full harness —
  directory tree, 18 page-type schemas, Obsidian vault config, ECC hooks, agent
  definitions, qmd collections, Base views, and domain-adapted CLAUDE.md. Supports
  5 domain presets, bare-minimal mode, vault validation, and harness upgrades.
  Self-contained plugin — no external template repo required.
tools: ["Bash", "Read", "Write", "Edit", "Grep", "Glob"]
---

# Brain Init — Industrial Intelligence Brain Initialization

## Installation

This skill is distributed as a Claude Code plugin. Install once:

```
/plugin marketplace add https://github.com/kaeli-byte/brain-init-plugin
/plugin install brain-init@brain-init
```

Then invoke as `/brain-init:brain-init <vault-path>`.

## Overview

This skill initializes a new wiki vault with the full Industrial Intelligence Brain harness.
All scaffolding assets (schemas, hooks, agents, skills, Obsidian config, qmd collections,
domain templates) are bundled inside the plugin — no external template repository is required.

If you have a legacy `~/deep-tech-wiki` clone, it is still supported as a fallback template source.
The plugin takes priority when both are available.

## Commands

### `/brain-init:brain-init <vault-path> [options]`

Initialize a new brain vault.

**Options:**

| Flag | Description |
|------|-------------|
| `<vault-path>` | Where to create the brain (required, positional) |
| `--domain <preset>` | Domain template: `industrial-intelligence` (default), `semiconductor`, `biotech`, `energy`, `materials` |
| `--domain-custom "...description..."` | Custom domain — LLM generates adapted CLAUDE.md + purpose.md |
| `--bare` | Minimal mode: directories + stubs + .gitignore only |
| `--no-git` | Skip git init and initial commit |
| `--no-qmd` | Skip qmd collection initialization |
| `--no-obsidian` | Skip Obsidian vault config and plugins |
| `--no-supporting-skills` | Skip mineru-batch, cfi-filings, sec-edgar, tianyancha |
| `--name "My Brain"` | Vault display name (default: basename of vault-path) |
| `--template-path <dir>` | Override template source |
| `--git-remote <url>` | Set git remote 'origin' after init |
| `--force` | Proceed even if target directory is non-empty |

**Examples:**
```
/brain-init:brain-init ~/brain-semiconductors --domain semiconductor
/brain-init:brain-init ~/brain-biotech --domain biotech --no-supporting-skills
/brain-init:brain-init ~/quick-notes --bare
/brain-init:brain-init ~/custom-brain --domain-custom "Renewable energy supply chains and battery technology"
```

---

### `/brain-init:brain-init --validate <vault-path>`

Validate an existing brain vault for correctness. Runs 9 checks: directory structure,
schema YAML validity, types.json coverage, hook integrity, agent definitions, skill health,
qmd health, external dependencies, and git state.

```
/brain-init:brain-init --validate ~/brain-semiconductors
→ PASS: 9/9 checks passed. Vault is healthy.
```

---

### `/brain-init:brain-init --upgrade-harness <vault-path>`

Update harness files (hooks, agents, schemas, skill, config, Obsidian types) from the
plugin's bundled assets while preserving all wiki content.

```
/brain-init:brain-init --upgrade-harness ~/brain-semiconductors
→ Updated 23 harness files. Wiki content preserved (142 pages).
```

---

## Onboarding

**Do NOT run the shell script immediately.** Before scaffolding, gather everything from the user
using AskUserQuestion. Six questions: vault path, domain preset, display name, git remote,
supporting tools (which of the 4 bundled skills), and API tokens (MINERU_TOKEN warning).

Present a confirmation summary before running `brain-init.sh`.

The shell script is the implementation — the agent gathers inputs, confirms, then runs the
script with the right flags. Do not re-implement the script's logic inline.

---

## Walkthrough: Full Init (8 Phases)

The `brain-init.sh` script executes 8 phases from the plugin's bundled assets:

- **Phase 0** — Preflight: dependency check, template resolution (plugin → legacy fallback → error)
- **Phase 1** — Scaffold: directory tree, .gitignore, .claudeignore, .env.example, wiki stubs
- **Phase 2** — Harness: hooks.json, settings.json, 3 agent definitions, 7 second-brain skills
- **Phase 3** — Schemas: 18 YAML schemas, 3 config docs, 3 Base views
- **Phase 4** — Obsidian: 6 JSON configs, community plugins declared (auto-download on first open)
- **Phase 5** — Domain: CLAUDE.md + purpose.md from preset template with variable substitution
- **Phase 6** — Skills: 4 supporting skills copied from `skills/brain-init/bundles/` into vault's `.claude/skills/`
- **Phase 7** — Post-init: git init, qmd collections, indexing
- **Phase 8** — Validation: 12 inline checks

## Domain Preset Reference

| Preset | Focus | Supporting Skills |
|--------|-------|-------------------|
| `industrial-intelligence` | Automotive, fluid handling, thermal management | All 4 (bundled) |
| `semiconductor` | Chip design, fabs, EDA, process nodes | mineru-batch (bundled) |
| `biotech` | Drug development, clinical trials, FDA | mineru-batch (bundled) |
| `energy` | Generation, storage, grid, renewables | mineru-batch (bundled) |
| `materials` | Advanced materials, composites, metallurgy | mineru-batch (bundled) |

## Plugin Asset Layout

The brain-init plugin is self-contained:

```
$PLUGIN_ROOT/
└── skills/brain-init/
    ├── SKILL.md     # This file
    ├── assets/      # Copy-to-vault: schemas, hooks.json, settings.json, agents, obsidian, config, bases
    ├── bundles/     # Supporting skills copied into vault .claude/skills/
    ├── scripts/     # brain-init.sh, validate-vault.sh
    └── templates/   # Domain-adapted CLAUDE.md + purpose.md (5 variants each)
```

## Edge Cases

- **No template source:** Error with install instructions: `/plugin install brain-init@brain-init`
- **Existing brain vault:** Offer `--upgrade-harness` mode
- **qmd not installed:** Skip with instructions; vault works without it
- **Obsidian plugins:** Not bundled (2.3 MB). User opens vault in Obsidian once to auto-download.
- **Legacy `~/deep-tech-wiki` clone:** Still works as fallback; plugin takes priority

## Tips

1. Start with `industrial-intelligence` — the most complete preset.
2. Run `--validate` after init to confirm every component is healthy.
3. Set MINERU_TOKEN immediately in `.env`.
4. Open in Obsidian right away — graph view and Bases are the quality feedback loop.
5. Re-run `--upgrade-harness` after `/plugin install brain-init@brain-init` to update vaults.

## Changelog

- v1.0.0 (2026-07-23): Initial release as self-contained Claude Code plugin. Plugin-aware path resolution with legacy fallback. All scaffolding assets bundled. Obsidian plugins declared but not bundled.
