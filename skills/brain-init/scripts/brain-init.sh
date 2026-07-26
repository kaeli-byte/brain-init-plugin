#!/usr/bin/env bash
# brain-init.sh — Initialize a new Industrial Intelligence Brain vault
# Usage: brain-init.sh <vault-path> [--domain preset] [--bare] [--no-git] [--no-qmd] [--no-obsidian]
#                         [--no-supporting-skills] [--name "name"] [--template-path dir]
#                         [--git-remote url] [--force]
# Called by the /brain-init:brain-init skill. Not typically invoked directly.
#
# Can run in two contexts:
#   1. As an installed Claude Code plugin → finds assets via .claude-plugin/plugin.json
#   2. From a deep-tech-wiki clone → falls back to ~/deep-tech-wiki (backward compat)

set -euo pipefail

# ── Plugin root discovery ──────────────────────────────────────
# Walk up from script location looking for .claude-plugin/plugin.json
find_plugin_root() {
    local dir
    dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    while [ "$dir" != "/" ]; do
        if [ -f "$dir/.claude-plugin/plugin.json" ]; then
            echo "$dir"
            return 0
        fi
        dir="$(dirname "$dir")"
    done
    # Fallback: CLAUDE_PLUGIN_ROOT (set by Claude Code for plugin skills)
    if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -f "$CLAUDE_PLUGIN_ROOT/.claude-plugin/plugin.json" ]; then
        echo "$CLAUDE_PLUGIN_ROOT"
        return 0
    fi
    return 1
}

ensure_runtime_ownership_layout() {
    local requested_vault="$1"
    local vault_root
    local brain_root
    local ownership_path
    local canonical_path

    vault_root="$(cd "$requested_vault" 2>/dev/null && pwd -P)" || {
        echo "ERROR: Cannot resolve vault path: $requested_vault" >&2
        return 1
    }
    brain_root="$vault_root/.brain"
    for ownership_path in \
        "$brain_root" \
        "$brain_root/runtime" \
        "$brain_root/runs" \
        "$brain_root/evals"; do
        if [ -L "$ownership_path" ]; then
            echo "ERROR: Refusing symlinked runtime ownership path: $ownership_path" >&2
            return 1
        fi
        if [ -e "$ownership_path" ] && [ ! -d "$ownership_path" ]; then
            echo "ERROR: Runtime ownership path is not a directory: $ownership_path" >&2
            return 1
        fi
        mkdir -p "$ownership_path"
        canonical_path="$(cd "$ownership_path" 2>/dev/null && pwd -P)" || {
            echo "ERROR: Cannot resolve runtime ownership path: $ownership_path" >&2
            return 1
        }
        case "$canonical_path" in
            "$brain_root"|"$brain_root"/*) ;;
            *)
                echo "ERROR: Runtime ownership path escapes the vault: $ownership_path" >&2
                return 1
                ;;
        esac
    done
    printf '%s\n' "$vault_root"
}

append_ignore_rule() {
    local ignore_file="$1"
    local comment="$2"
    local rule="$3"

    if [ -L "$ignore_file" ]; then
        echo "ERROR: Refusing symlinked runtime ownership file: $ignore_file" >&2
        return 1
    fi
    if [ -e "$ignore_file" ] && [ ! -f "$ignore_file" ]; then
        echo "ERROR: Runtime ownership file is not a regular file: $ignore_file" >&2
        return 1
    fi
    if grep -qxF "$rule" "$ignore_file" 2>/dev/null; then
        return 0
    fi
    [ ! -s "$ignore_file" ] || printf '\n' >> "$ignore_file"
    printf '%s\n%s\n' "$comment" "$rule" >> "$ignore_file"
}

migrate_runtime_ownership() {
    local vault_root
    vault_root="$(ensure_runtime_ownership_layout "$1")" || return 1
    append_ignore_rule \
        "$vault_root/.gitignore" \
        "# Brain runtime generated execution traces" \
        "/.brain/runs/" || return 1
    append_ignore_rule \
        "$vault_root/.claudeignore" \
        "# Runtime execution history — inspect explicitly, never preload" \
        ".brain/runs/" || return 1
}

replace_runtime_code() (
    local requested_vault="$1"
    local runtime_source="$2"
    local vault_root
    local runtime_root
    local source_package
    local source_link
    local target
    local install_lock
    local stage_root
    local staged
    local stage_marker
    local backup

    vault_root="$(ensure_runtime_ownership_layout "$requested_vault")" || return 1
    runtime_root="$vault_root/.brain/runtime"
    source_package="$runtime_source/brain_runtime"
    target="$runtime_root/brain_runtime"

    if [ -L "$runtime_source" ] || [ -L "$source_package" ]; then
        echo "ERROR: Refusing symlinked runtime source: $source_package" >&2
        return 1
    fi
    if [ ! -d "$source_package" ]; then
        echo "ERROR: Runtime source package is missing: $source_package" >&2
        return 1
    fi
    source_link="$(find "$source_package" -type l -print 2>/dev/null)"
    if [ -n "$source_link" ]; then
        echo "ERROR: Refusing symlinked runtime source content: $source_link" >&2
        return 1
    fi

    if [ -L "$target" ]; then
        echo "ERROR: Refusing symlinked runtime ownership path: $target" >&2
        return 1
    fi
    if [ -e "$target" ] && [ ! -d "$target" ]; then
        echo "ERROR: Runtime package target is not a directory: $target" >&2
        return 1
    fi

    install_lock="$runtime_root/.brain-runtime-install.lock"
    if ! mkdir "$install_lock" 2>/dev/null; then
        echo "ERROR: Runtime replacement is already in progress: $install_lock" >&2
        echo "ERROR: If this lock is stale, remove it only after confirming no installer is active." >&2
        return 1
    fi
    cleanup_runtime_install_lock() {
        rm -f "$install_lock/owner"
        rmdir "$install_lock" 2>/dev/null || true
    }
    if ! printf 'pid=%s\ncreated_at=%s\n' "$$" "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
        > "$install_lock/owner"; then
        cleanup_runtime_install_lock
        echo "ERROR: Could not record runtime replacement lock ownership." >&2
        return 1
    fi
    trap cleanup_runtime_install_lock EXIT
    trap 'cleanup_runtime_install_lock; exit 1' HUP INT TERM

    stage_root="$(mktemp -d "$runtime_root/.brain-runtime-stage.XXXXXX")" || {
        echo "ERROR: Could not create a staged runtime directory." >&2
        return 1
    }
    staged="$stage_root/brain_runtime"
    if ! cp -R "$source_package" "$staged"; then
        rm -rf "$stage_root"
        echo "ERROR: Could not stage brain runtime code." >&2
        return 1
    fi
    find "$staged" -type d -name '__pycache__' -prune \
        -exec rm -rf {} + 2>/dev/null || true
    source_link="$(find "$staged" -type l -print 2>/dev/null)"
    if [ -L "$staged" ] || [ -n "$source_link" ] || [ ! -f "$staged/__init__.py" ]; then
        rm -rf "$stage_root"
        echo "ERROR: Staged brain runtime package is incomplete." >&2
        return 1
    fi
    stage_marker=".brain-runtime-install-id"
    if ! printf '%s\n' "$stage_root" > "$staged/$stage_marker"; then
        rm -rf "$stage_root"
        echo "ERROR: Could not mark the staged brain runtime package." >&2
        return 1
    fi

    backup=""
    if [ -d "$target" ]; then
        backup="$stage_root/previous-brain_runtime"
        if ! mv "$target" "$backup"; then
            rm -rf "$stage_root"
            echo "ERROR: Could not stage the previous brain runtime for replacement." >&2
            return 1
        fi
    fi
    if [ -e "$target" ] || [ -L "$target" ]; then
        echo "ERROR: Runtime target appeared during replacement." >&2
        if [ -n "$backup" ]; then
            echo "ERROR: Previous runtime preserved at: $backup" >&2
        fi
        return 1
    fi
    if ! mv "$staged" "$target"; then
        if [ -n "$backup" ] && [ -d "$backup" ]; then
            if [ ! -e "$target" ] && [ ! -L "$target" ]; then
                if mv "$backup" "$target" 2>/dev/null; then
                    rm -rf "$stage_root"
                    echo "ERROR: Could not install staged brain runtime code; previous runtime restored." >&2
                    return 1
                fi
            fi
            echo "ERROR: Previous runtime preserved at: $backup" >&2
            return 1
        fi
        rm -rf "$stage_root"
        echo "ERROR: Could not install staged brain runtime code." >&2
        return 1
    fi
    source_link="$(find "$target" -type l -print 2>/dev/null)"
    if \
        [ -L "$target" ] ||
        [ -n "$source_link" ] ||
        [ ! -f "$target/__init__.py" ] ||
        [ ! -f "$target/$stage_marker" ] ||
        ! grep -qxF "$stage_root" "$target/$stage_marker"; then
        echo "ERROR: Installed brain runtime package failed validation." >&2
        if [ -n "$backup" ] && [ -d "$backup" ]; then
            echo "ERROR: Previous runtime preserved at: $backup" >&2
        fi
        return 1
    fi
    if ! rm -f "$target/$stage_marker"; then
        echo "ERROR: Could not finalize the installed brain runtime package." >&2
        if [ -n "$backup" ] && [ -d "$backup" ]; then
            echo "ERROR: Previous runtime preserved at: $backup" >&2
        fi
        return 1
    fi
    rm -rf "$stage_root"
)

# ── Defaults ──────────────────────────────────────────────────
BRAIN_INIT_VERSION="1.2.0"
DOMAIN="${BRAIN_DOMAIN:-industrial-intelligence}"
DOMAIN_CUSTOM=""
VAULT_PATH=""
VAULT_NAME=""
TEMPLATE_PATH="${WIKI_TEMPLATE_PATH:-}"
BARE_MODE=false
NO_GIT=false
NO_QMD=false
NO_OBSIDIAN=false
NO_SUPPORTING_SKILLS=false
FORCE=false
GIT_REMOTE=""
UPGRADE_HARNESS=false
VALIDATE_MODE=false
TODAY=$(date +%Y-%m-%d)

# ── Parse arguments ───────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain)
      DOMAIN="$2"; shift 2 ;;
    --domain-custom)
      DOMAIN_CUSTOM="$2"; DOMAIN="custom"; shift 2 ;;
    --bare)
      BARE_MODE=true; shift ;;
    --no-git)
      NO_GIT=true; shift ;;
    --no-qmd)
      NO_QMD=true; shift ;;
    --no-obsidian)
      NO_OBSIDIAN=true; shift ;;
    --no-supporting-skills)
      NO_SUPPORTING_SKILLS=true; shift ;;
    --name)
      VAULT_NAME="$2"; shift 2 ;;
    --template-path)
      TEMPLATE_PATH="$2"; shift 2 ;;
    --force)
      FORCE=true; shift ;;
    --git-remote)
      GIT_REMOTE="$2"; shift 2 ;;
    --upgrade-harness)
      UPGRADE_HARNESS=true; shift ;;
    --validate)
      VALIDATE_MODE=true; shift ;;
    -*)
      echo "Unknown flag: $1" >&2; exit 1 ;;
    *)
      if [ -z "$VAULT_PATH" ]; then
        VAULT_PATH="$1"
      else
        echo "Unexpected argument: $1 (vault path already set to $VAULT_PATH)" >&2
        exit 1
      fi
      shift ;;
  esac
done

if [ -z "$VAULT_PATH" ]; then
  echo "Usage: brain-init.sh <vault-path> [options]" >&2
  echo "Run '/brain-init:brain-init --help' for full documentation." >&2
  exit 1
fi

# ═══════════════════════════════════════════════════════════════
# Special modes: --validate and --upgrade-harness
# ═══════════════════════════════════════════════════════════════

# Resolve plugin root early for these modes
_early_plugin_root="$(find_plugin_root 2>/dev/null || echo '')"
VALIDATE_SCRIPT=""
if [ -n "$_early_plugin_root" ] && [ -f "$_early_plugin_root/skills/brain-init/scripts/validate-vault.sh" ]; then
    VALIDATE_SCRIPT="$_early_plugin_root/skills/brain-init/scripts/validate-vault.sh"
elif [ -f "$(dirname "${BASH_SOURCE[0]}")/validate-vault.sh" ]; then
    VALIDATE_SCRIPT="$(dirname "${BASH_SOURCE[0]}")/validate-vault.sh"
elif [ -f "$HOME/deep-tech-wiki/.claude/skills/brain-init/scripts/validate-vault.sh" ]; then
    VALIDATE_SCRIPT="$HOME/deep-tech-wiki/.claude/skills/brain-init/scripts/validate-vault.sh"
fi

# ── --validate mode ───────────────────────────────────────────
if [ "$VALIDATE_MODE" = true ]; then
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  brain-init v${BRAIN_INIT_VERSION} — Validate mode"
    echo "  Vault:   $VAULT_PATH"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    if [ -n "$VALIDATE_SCRIPT" ]; then
        exec bash "$VALIDATE_SCRIPT" "$VAULT_PATH"
    else
        echo "ERROR: validate-vault.sh not found." >&2
        echo "  Expected at: skills/brain-init/scripts/validate-vault.sh (in plugin)" >&2
        echo "  Or: ~/deep-tech-wiki/.claude/skills/brain-init/scripts/validate-vault.sh (legacy)" >&2
        exit 1
    fi
fi

# ── --upgrade-harness mode ────────────────────────────────────
if [ "$UPGRADE_HARNESS" = true ]; then
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  brain-init v${BRAIN_INIT_VERSION} — Upgrade harness mode"
    echo "  Vault:   $VAULT_PATH"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    if [ ! -d "$VAULT_PATH/wiki" ]; then
        echo "ERROR: $VAULT_PATH doesn't appear to be a brain vault (no wiki/ directory)." >&2
        echo "  Use /brain-init:brain-init $VAULT_PATH to create a new vault." >&2
        exit 1
    fi

    # Resolve template source (same logic as Phase 0)
    if [ -n "$TEMPLATE_PATH" ]; then
        TEMPLATE_PATH="${TEMPLATE_PATH/#\~/$HOME}"
        [[ "$TEMPLATE_PATH" != /* ]] && TEMPLATE_PATH="$PWD/$TEMPLATE_PATH"
        TEMPLATE_PATH="${TEMPLATE_PATH//\\//}"; TEMPLATE_PATH="${TEMPLATE_PATH%/}"
        if [ ! -d "$TEMPLATE_PATH" ]; then
            echo "ERROR: --template-path '$TEMPLATE_PATH' does not exist." >&2
            exit 1
        fi
        TEMPLATE_SOURCE="$TEMPLATE_PATH"; TEMPLATE_IS_PLUGIN=false
    elif [ -n "$_early_plugin_root" ] && [ -d "$_early_plugin_root/skills/brain-init/assets/schemas" ]; then
        TEMPLATE_SOURCE="$_early_plugin_root"; TEMPLATE_IS_PLUGIN=true
    elif [ -d "$HOME/deep-tech-wiki/templates/schemas" ]; then
        TEMPLATE_SOURCE="$HOME/deep-tech-wiki"; TEMPLATE_IS_PLUGIN=false
    else
        echo "ERROR: No template source found." >&2
        echo "  Install the brain-init plugin: /plugin install brain-init@brain-init" >&2
        exit 1
    fi

    # Set asset paths (same logic as Phase 0)
    if [ "$TEMPLATE_IS_PLUGIN" = true ]; then
        SCHEMAS_SRC="$_early_plugin_root/skills/brain-init/assets/schemas"
        HOOKS_SRC="$_early_plugin_root/skills/brain-init/assets/hooks.json"
        SETTINGS_SRC="$_early_plugin_root/skills/brain-init/assets/settings.json"
        AGENTS_SRC="$_early_plugin_root/skills/brain-init/assets/agents"
        CONFIG_SRC="$_early_plugin_root/skills/brain-init/assets/config"
        BASES_SRC="$_early_plugin_root/skills/brain-init/assets/bases"
        OBSIDIAN_SRC="$_early_plugin_root/skills/brain-init/assets/obsidian"
        BUNDLES_SRC="$_early_plugin_root/skills/brain-init/bundles"
        DOMAIN_TEMPLATES_SRC="$_early_plugin_root/skills/brain-init/templates"
        RUNTIME_SRC="$_early_plugin_root/skills/brain-init/runtime"
        echo "  Template source: $_early_plugin_root (brain-init plugin)"
    else
        SCHEMAS_SRC="$TEMPLATE_SOURCE/templates/schemas"
        HOOKS_SRC="$TEMPLATE_SOURCE/.claude/hooks/hooks.json"
        SETTINGS_SRC="$TEMPLATE_SOURCE/.claude/settings.json"
        AGENTS_SRC="$TEMPLATE_SOURCE/.claude/agents"
        CONFIG_SRC="$TEMPLATE_SOURCE/config"
        BASES_SRC="$TEMPLATE_SOURCE/Templates/Bases"
        OBSIDIAN_SRC="$TEMPLATE_SOURCE/.obsidian"
        BUNDLES_SRC="$TEMPLATE_SOURCE/.claude/skills"
        DOMAIN_TEMPLATES_SRC="$TEMPLATE_SOURCE/.claude/skills/brain-init/templates"
        RUNTIME_SRC="$TEMPLATE_SOURCE/.brain/runtime"
        echo "  Template source: $TEMPLATE_SOURCE (legacy)"
    fi

    UPGRADED=0
    migrate_runtime_ownership "$VAULT_PATH"

    # Update hooks.json (preserve vault path)
    echo ""
    echo "Updating harness files..."
    if [ -f "$HOOKS_SRC" ]; then
        sed "s|~/deep-tech-wiki|$VAULT_PATH|g" "$HOOKS_SRC" > "$VAULT_PATH/.claude/hooks/hooks.json"
        echo "  hooks.json: updated"; UPGRADED=$((UPGRADED + 1))
    fi

    # Update settings.json
    if [ -f "$SETTINGS_SRC" ]; then
        cp "$SETTINGS_SRC" "$VAULT_PATH/.claude/settings.json"
        echo "  settings.json: updated"; UPGRADED=$((UPGRADED + 1))
    fi

    # Update agent definitions
    if [ -d "$AGENTS_SRC" ]; then
        AGENT_UPDATED=0
        for f in "$AGENTS_SRC"/*.md; do
            [ -f "$f" ] || continue
            cp "$f" "$VAULT_PATH/.claude/agents/"
            AGENT_UPDATED=$((AGENT_UPDATED + 1))
        done
        echo "  Agent definitions: $AGENT_UPDATED updated"; UPGRADED=$((UPGRADED + 1))
    fi

    # Replace vendor-owned runtime code without touching run or evaluation state
    if [ -d "$RUNTIME_SRC/brain_runtime" ]; then
        replace_runtime_code "$VAULT_PATH" "$RUNTIME_SRC"
        echo "  brain runtime: updated (shadow mode)"; UPGRADED=$((UPGRADED + 1))
    else
        echo "  WARNING: brain runtime source not found; capture will run without shadow instrumentation."
    fi

    # Update flat second-brain skills (7 skills in subdirectories)
    SECOND_BRAIN_SRC="$BUNDLES_SRC/second-brain"
    [ "$TEMPLATE_IS_PLUGIN" != true ] && [ -d "$TEMPLATE_SOURCE/.claude/skills/second-brain" ] && \
        SECOND_BRAIN_SRC="$TEMPLATE_SOURCE/.claude/skills/second-brain"
    SKILL_UPDATED=0
    if [ -d "$SECOND_BRAIN_SRC" ]; then
        # Clean up old monolith files if they exist (pre-split upgrade)
        rm -f "$VAULT_PATH/.claude/skills/second-brain/SKILL.md" 2>/dev/null
        for role in researcher analyst curator; do
            rm -f "$VAULT_PATH/.claude/skills/second-brain/${role}.md" 2>/dev/null
        done
        for skill_dir in "$SECOND_BRAIN_SRC"/*/; do
            [ -d "$skill_dir" ] || continue
            skill_name=$(basename "$skill_dir")
            skill_full_name="second-brain-$skill_name"
            if [ -f "$skill_dir/SKILL.md" ]; then
                # Clean up old nested structure
                rm -rf "$VAULT_PATH/.claude/skills/second-brain/$skill_name" 2>/dev/null
                # Deploy to flat path
                mkdir -p "$VAULT_PATH/.claude/skills/$skill_full_name"
                cp "$skill_dir/SKILL.md" "$VAULT_PATH/.claude/skills/$skill_full_name/"
                SKILL_UPDATED=$((SKILL_UPDATED + 1))
            fi
        done
        # Clean up old nested second-brain directory if empty
        rmdir "$VAULT_PATH/.claude/skills/second-brain" 2>/dev/null || true
    fi
    if [ "$SKILL_UPDATED" -gt 0 ]; then
        echo "  second-brain skills: $SKILL_UPDATED updated"; UPGRADED=$((UPGRADED + 1))
    fi

    # Update capture skill reference assets (high-signal section locators)
    HS_ASSET="$SECOND_BRAIN_SRC/capture/assets/high-signal-sections.md"
    if [ -d "$SECOND_BRAIN_SRC/capture/assets" ]; then
        if [ ! -f "$HS_ASSET" ]; then
            echo "  ERROR: capture reference asset missing: $HS_ASSET" >&2
            exit 1
        fi
        mkdir -p "$VAULT_PATH/raw/assets"
        cp "$HS_ASSET" "$VAULT_PATH/raw/assets/" || {
            echo "  ERROR: failed to copy high-signal-sections.md to $VAULT_PATH/raw/assets/" >&2
            exit 1
        }
        echo "  capture reference assets: updated"; UPGRADED=$((UPGRADED + 1))
    fi

    # Update schemas (add new, overwrite existing)
    if [ -d "$SCHEMAS_SRC" ]; then
        SCHEMA_NEW=$(ls "$SCHEMAS_SRC"/*.yaml 2>/dev/null | wc -l | tr -d ' ')
        cp "$SCHEMAS_SRC"/*.yaml "$VAULT_PATH/templates/schemas/" 2>/dev/null || true
        echo "  Schemas: $SCHEMA_NEW files updated"; UPGRADED=$((UPGRADED + 1))
    fi

    # Update Base views
    if [ -d "$BASES_SRC" ]; then
        BASE_UPDATED=0
        for f in "$BASES_SRC"/*.base; do
            [ -f "$f" ] || continue
            cp "$f" "$VAULT_PATH/Templates/Bases/"
            BASE_UPDATED=$((BASE_UPDATED + 1))
        done
        echo "  Base views: $BASE_UPDATED updated"; UPGRADED=$((UPGRADED + 1))
    fi

    # Update config docs
    for f in materiality.md retrieval.md page-templates.md; do
        [ -f "$CONFIG_SRC/$f" ] && cp "$CONFIG_SRC/$f" "$VAULT_PATH/config/"
    done
    echo "  Config docs: updated"; UPGRADED=$((UPGRADED + 1))

    # Update types.json
    if [ -f "$OBSIDIAN_SRC/types.json" ]; then
            mkdir -p "$VAULT_PATH/.obsidian"
        cp "$OBSIDIAN_SRC/types.json" "$VAULT_PATH/.obsidian/types.json"
        echo "  Obsidian types.json: updated"; UPGRADED=$((UPGRADED + 1))
    fi

    # Update supporting skills if they exist in the vault
    SKILLS_UPDATED=0
    for skill in mineru-batch cfi-filings sec-edgar tianyancha; do
        SKILL_SRC="$BUNDLES_SRC/$skill"
        if [ -d "$SKILL_SRC" ] && [ -d "$VAULT_PATH/.claude/skills/$skill" ]; then
            cp -r "$SKILL_SRC"/* "$VAULT_PATH/.claude/skills/$skill/" 2>/dev/null || true
            SKILLS_UPDATED=$((SKILLS_UPDATED + 1))
        fi
    done
    if [ "$SKILLS_UPDATED" -gt 0 ]; then
        echo "  Supporting skills: $SKILLS_UPDATED updated"; UPGRADED=$((UPGRADED + 1))
    fi

    # Append log entry
    LOG_LINE="## [${TODAY}] brain-init | Harness upgraded | brain-init v${BRAIN_INIT_VERSION}"
    if ! grep -qF "$LOG_LINE" "$VAULT_PATH/wiki/log.md" 2>/dev/null; then
        printf "\n%s\n- %d harness components updated from %s\n" "$LOG_LINE" "$UPGRADED" \
            "$([ "$TEMPLATE_IS_PLUGIN" = true ] && echo 'brain-init plugin' || echo "$TEMPLATE_SOURCE")" \
            >> "$VAULT_PATH/wiki/log.md"
    fi

    # Count preserved pages for the report
    PAGE_COUNT=$(find "$VAULT_PATH/wiki" -name '*.md' -type f 2>/dev/null | wc -l | tr -d ' ')
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Harness upgrade complete"
    echo "  Updated: $UPGRADED harness components"
    echo "  Preserved: $PAGE_COUNT wiki pages + raw/ content"
    echo ""
    echo "  Next: Run /second-brain-lint to verify vault health"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    exit 0
fi

# ── Resolve paths ─────────────────────────────────────────────
# Expand ~
VAULT_PATH="${VAULT_PATH/#\~/$HOME}"
# Resolve relative to absolute
if [[ "$VAULT_PATH" != /* ]]; then
  VAULT_PATH="$PWD/$VAULT_PATH"
fi
# Normalize Windows backslashes
VAULT_PATH="${VAULT_PATH//\\//}"
# Remove trailing slash
VAULT_PATH="${VAULT_PATH%/}"

VAULT_NAME="${VAULT_NAME:-$(basename "$VAULT_PATH")}"
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  brain-init v${BRAIN_INIT_VERSION}"
echo "  Vault:   $VAULT_PATH"
echo "  Name:    $VAULT_NAME"
echo "  Domain:  $DOMAIN"
echo "  Mode:    $([ "$BARE_MODE" = true ] && echo 'bare' || echo 'full')"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ═══════════════════════════════════════════════════════════════
# Phase 0: Preflight
# ═══════════════════════════════════════════════════════════════
echo "[Phase 0] Preflight..."

# Resolve template source. Order:
#   1. --template-path or $WIKI_TEMPLATE_PATH (explicit user override)
#   2. Plugin root (self-contained — the plugin IS the bundle)
#   3. ~/deep-tech-wiki (legacy backward compatibility)
#   4. Error

PLUGIN_ROOT=""
TEMPLATE_SOURCE=""
TEMPLATE_IS_PLUGIN=false

if [ -n "$TEMPLATE_PATH" ]; then
    # --template-path or $WIKI_TEMPLATE_PATH was set
    TEMPLATE_PATH="${TEMPLATE_PATH/#\~/$HOME}"
    if [[ "$TEMPLATE_PATH" != /* ]]; then
      TEMPLATE_PATH="$PWD/$TEMPLATE_PATH"
    fi
    TEMPLATE_PATH="${TEMPLATE_PATH//\\//}"
    TEMPLATE_PATH="${TEMPLATE_PATH%/}"
    if [ -d "$TEMPLATE_PATH" ]; then
        TEMPLATE_SOURCE="$TEMPLATE_PATH"
        echo "  Template source: $TEMPLATE_SOURCE (explicit --template-path)"
    else
        echo "ERROR: --template-path '$TEMPLATE_PATH' does not exist." >&2
        exit 1
    fi
else
    # Try plugin root first
    PLUGIN_ROOT="$(find_plugin_root 2>/dev/null || echo '')"
    if [ -n "$PLUGIN_ROOT" ] && [ -d "$PLUGIN_ROOT/skills/brain-init/assets/schemas" ]; then
        TEMPLATE_SOURCE="$PLUGIN_ROOT"
        TEMPLATE_IS_PLUGIN=true
        echo "  Template source: $TEMPLATE_SOURCE (brain-init plugin v${BRAIN_INIT_VERSION})"
    elif [ -d "$HOME/deep-tech-wiki/templates/schemas" ]; then
        TEMPLATE_SOURCE="$HOME/deep-tech-wiki"
        echo "  Template source: $TEMPLATE_SOURCE (legacy: ~/deep-tech-wiki)"
    else
        echo "" >&2
        echo "ERROR: No template source found." >&2
        echo "  The brain-init plugin bundles all scaffolding assets internally." >&2
        echo "  Install it once, then try again:" >&2
        echo "" >&2
        echo "    /plugin marketplace add https://github.com/kaeli-byte/brain-init-plugin" >&2
        echo "    /plugin install brain-init@brain-init" >&2
        echo "" >&2
        echo "  Or clone the legacy template repo:" >&2
        echo "    git clone <deep-tech-wiki-url> ~/deep-tech-wiki" >&2
        exit 1
    fi
fi

# For plugin mode: define asset paths
if [ "$TEMPLATE_IS_PLUGIN" = true ]; then
    SCHEMAS_SRC="$PLUGIN_ROOT/skills/brain-init/assets/schemas"
    HOOKS_SRC="$PLUGIN_ROOT/skills/brain-init/assets/hooks.json"
    SETTINGS_SRC="$PLUGIN_ROOT/skills/brain-init/assets/settings.json"
    AGENTS_SRC="$PLUGIN_ROOT/skills/brain-init/assets/agents"
    CONFIG_SRC="$PLUGIN_ROOT/skills/brain-init/assets/config"
    BASES_SRC="$PLUGIN_ROOT/skills/brain-init/assets/bases"
    OBSIDIAN_SRC="$PLUGIN_ROOT/skills/brain-init/assets/obsidian"
    BUNDLES_SRC="$PLUGIN_ROOT/skills/brain-init/bundles"
    DOMAIN_TEMPLATES_SRC="$PLUGIN_ROOT/skills/brain-init/templates"
    RUNTIME_SRC="$PLUGIN_ROOT/skills/brain-init/runtime"
else
    # Legacy mode: paths relative to deep-tech-wiki clone
    SCHEMAS_SRC="$TEMPLATE_SOURCE/templates/schemas"
    HOOKS_SRC="$TEMPLATE_SOURCE/.claude/hooks/hooks.json"
    SETTINGS_SRC="$TEMPLATE_SOURCE/.claude/settings.json"
    AGENTS_SRC="$TEMPLATE_SOURCE/.claude/agents"
    CONFIG_SRC="$TEMPLATE_SOURCE/config"
    BASES_SRC="$TEMPLATE_SOURCE/Templates/Bases"
    OBSIDIAN_SRC="$TEMPLATE_SOURCE/.obsidian"
    BUNDLES_SRC="$TEMPLATE_SOURCE/.claude/skills"
    DOMAIN_TEMPLATES_SRC="$TEMPLATE_SOURCE/.claude/skills/brain-init/templates"
    RUNTIME_SRC="$TEMPLATE_SOURCE/.brain/runtime"
fi

# Check target
if [ -d "$VAULT_PATH" ] && [ "$(ls -A "$VAULT_PATH" 2>/dev/null)" ]; then
  if [ -f "$VAULT_PATH/CLAUDE.md" ] || [ -d "$VAULT_PATH/wiki" ]; then
    echo "  WARNING: Target appears to be an existing brain vault."
    echo "  Use --upgrade-harness to update harness files while preserving wiki content."
    echo "  Use --force to merge scaffold into existing directory."
    if [ "$FORCE" != true ]; then
      exit 1
    fi
    echo "  --force: proceeding (wiki/ and raw/ will be preserved)"
  elif [ "$FORCE" != true ]; then
    echo "  WARNING: Target directory is not empty. Use --force to merge."
    exit 1
  else
    echo "  --force: merging into existing directory."
  fi
fi

# Write permission check
mkdir -p "$VAULT_PATH"
if ! touch "$VAULT_PATH/.brain-init-test" 2>/dev/null; then
  echo "ERROR: Cannot write to $VAULT_PATH. Check permissions." >&2
  exit 1
fi
rm -f "$VAULT_PATH/.brain-init-test"
echo "  Write permissions: OK"

# Dependencies check (warn but don't block init)
echo "  Checking dependencies..."
MISSING_DEPS=0

command -v python3 &>/dev/null || { echo "    [WARN] python3 not found — required for all tooling"; MISSING_DEPS=$((MISSING_DEPS+1)); }

for pkg in yaml requests; do
  python3 -c "import $pkg" 2>/dev/null || { echo "    [WARN] Python $pkg not found — pip install $pkg"; MISSING_DEPS=$((MISSING_DEPS+1)); }
done

command -v qmd &>/dev/null || { echo "    [WARN] qmd not found — semantic search disabled. Install: pip install qmd"; MISSING_DEPS=$((MISSING_DEPS+1)); }

command -v pdftotext &>/dev/null || { echo "    [WARN] pdftotext not found — PDF fallback unavailable. Install: brew install poppler"; MISSING_DEPS=$((MISSING_DEPS+1)); }

python3 -c "import agent_gw" 2>/dev/null || { echo "    [WARN] agent_gw not found — sec-edgar + tianyancha skills won't work"; MISSING_DEPS=$((MISSING_DEPS+1)); }

[ -n "${KIMI_API_KEY:-}" ] || { echo "    [WARN] KIMI_API_KEY not set — sec-edgar + tianyancha won't work"; MISSING_DEPS=$((MISSING_DEPS+1)); }
[ -n "${KIMI_BASE_URL:-}" ] || { echo "    [WARN] KIMI_BASE_URL not set — agent_gw defaults to dev endpoint"; MISSING_DEPS=$((MISSING_DEPS+1)); }
[ -n "${MINERU_TOKEN:-}" ] || { echo "    [WARN] MINERU_TOKEN not set — PDF extraction won't work"; MISSING_DEPS=$((MISSING_DEPS+1)); }

if [ "$MISSING_DEPS" -gt 0 ]; then
  echo "  $MISSING_DEPS dependency warning(s) — vault can init, but some features will be unavailable."
else
  echo "  All dependencies available."
fi

# ═══════════════════════════════════════════════════════════════
# Phase 1: Scaffold
# ═══════════════════════════════════════════════════════════════
echo ""
echo "[Phase 1] Scaffolding directory tree..."

# Wiki subdirectories (16 + _indexes)
for dir in analyses applications claims companies concepts industries \
           investigations markets patent-families people processes products \
           queries regulations sources standards syntheses technologies _indexes; do
  mkdir -p "$VAULT_PATH/wiki/$dir"
done

# Raw subdirectories (11)
for dir in 10k annual-reports patents industry-reports tech-papers white-papers \
           earnings-calls press-releases images assets; do
  mkdir -p "$VAULT_PATH/raw/$dir"
done

# Harness directories (skip if bare)
if [ "$BARE_MODE" = false ]; then
  mkdir -p "$VAULT_PATH/templates/schemas"
  mkdir -p "$VAULT_PATH/Templates/Bases"
  mkdir -p "$VAULT_PATH/config"
  mkdir -p "$VAULT_PATH/.claude/agents"
  mkdir -p "$VAULT_PATH/.claude/hooks"
  ensure_runtime_ownership_layout "$VAULT_PATH" >/dev/null
fi

WIKI_DIRS=$(find "$VAULT_PATH/wiki" -type d | wc -l | tr -d ' ')
RAW_DIRS=$(find "$VAULT_PATH/raw" -type d | wc -l | tr -d ' ')
echo "  Created $WIKI_DIRS wiki directories, $RAW_DIRS raw directories"

# Write .gitignore
cat > "$VAULT_PATH/.gitignore" << 'GITIGNORE'
# Obsidian
.obsidian/workspace*
.obsidian/cache

# qmd symlinks (collection directories → wiki paths)
/brain-knowledge
/brain-sources
/brain-investigations

# qmd refresh tracking
.qmd-last-refresh

# Brain runtime generated execution traces
/.brain/runs/

# Secrets & tokens
.env
.envrc

# OS
.DS_Store
Thumbs.db
GITIGNORE

# Write .claudeignore
cat > "$VAULT_PATH/.claudeignore" << 'CLAUDEIGNORE'
# Raw source materials — enormous, read only during explicit /capture
raw/

# IDE planning history — not agent-operational
.idea/plans/

# Runtime execution history — inspect explicitly, never preload
.brain/runs/

# Obsidian workspace config — not needed by agent
.obsidian/

# Binary files — never useful to agent
*.pdf

# OS artifacts
.DS_Store
Thumbs.db

# Git internals
.git/
CLAUDEIGNORE

# Write .env.example
cat > "$VAULT_PATH/.env.example" << 'ENVEXAMPLE'
# MinerU PDF Parser — Precision Parse API
# Get your token at: https://mineru.net/apiManage/token
# Required for PDFs >20 pages or >10 MB (annual reports, 10-Ks, etc.)
MINERU_TOKEN=

# Kimi agent-gw — SEC EDGAR data source access
KIMI_API_KEY=sk-kimi-...
KIMI_BASE_URL=https://agent-gw.kimi.com/coding
ENVEXAMPLE

touch "$VAULT_PATH/.qmd-last-refresh"
echo "  Wrote: .gitignore, .claudeignore, .env.example"

# Write wiki/index.md stub
cat > "$VAULT_PATH/wiki/index.md" << INDEXMD
---
title: "${VAULT_NAME} — Industrial Intelligence Brain"
domain: "${DOMAIN}"
created: ${TODAY}
last_reviewed: ${TODAY}
tags: [index]
---

# ${VAULT_NAME}

**Domain:** ${DOMAIN}
**Schema:** v1.1
**Created:** ${TODAY}

## Page Counts

| Category | Count |
|----------|-------|
| sources | 0 |
| claims | 0 |
| companies | 0 |
| technologies | 0 |
| patent-families | 0 |
| markets | 0 |
| industries | 0 |
| products | 0 |
| applications | 0 |
| processes | 0 |
| people | 0 |
| concepts | 0 |
| analyses | 0 |
| syntheses | 0 |
| queries | 0 |
| regulations | 0 |
| standards | 0 |
| investigations | 0 |
| **Total** | **0** |

_Ingest your first source with \`/second-brain-capture\` to begin compounding._
INDEXMD
echo "  Wrote: wiki/index.md"

# Write wiki/log.md
LOG_SOURCE_DESC="$([ "$TEMPLATE_IS_PLUGIN" = true ] && echo "brain-init plugin v${BRAIN_INIT_VERSION}" || echo "$TEMPLATE_SOURCE")"
cat > "$VAULT_PATH/wiki/log.md" << LOGMD
---
tags: [log]
created: ${TODAY}
---

# Operations Log

Append-only chronological record of all brain operations.

## [${TODAY}] brain-init | Vault created | brain-init v${BRAIN_INIT_VERSION}
- Domain: ${DOMAIN}
- Mode: $([ "$BARE_MODE" = true ] && echo 'bare' || echo 'full')
- Template: ${LOG_SOURCE_DESC}
LOGMD
echo "  Wrote: wiki/log.md"

# If bare mode, skip remaining phases
if [ "$BARE_MODE" = true ]; then
  echo ""
  echo "[Phase 1] Bare scaffold complete. Skipping harness phases."
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  Brain scaffold created (bare mode)"
  echo "  Vault: $VAULT_PATH"
  echo ""
  echo "  Next steps:"
  echo "    cd $VAULT_PATH"
  echo "    Open in Obsidian: Open folder as vault"
  echo "    Start capturing sources with /second-brain-capture"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  exit 0
fi

# ═══════════════════════════════════════════════════════════════
# Phase 2: Harness
# ═══════════════════════════════════════════════════════════════
echo ""
echo "[Phase 2] Installing Claude Code harness..."

# Copy hooks.json with path substitution
if [ -f "$HOOKS_SRC" ]; then
  sed "s|~/deep-tech-wiki|$VAULT_PATH|g" \
    "$HOOKS_SRC" \
    > "$VAULT_PATH/.claude/hooks/hooks.json"
  # Verify no hardcoded paths remain
  if grep -q '~/deep-tech-wiki' "$VAULT_PATH/.claude/hooks/hooks.json" 2>/dev/null; then
    echo "  WARNING: Some hardcoded ~/deep-tech-wiki paths remain in hooks.json" >&2
  fi
  HOOK_COUNT=$(python3 -c "import json; h=json.load(open('$VAULT_PATH/.claude/hooks/hooks.json')); print(len(h.get('hooks',[])))" 2>/dev/null || echo '0')
  echo "  hooks.json: $HOOK_COUNT hooks configured"
else
  echo "  WARNING: hooks.json not found. Creating empty hooks.json."
  echo '{"hooks":[]}' > "$VAULT_PATH/.claude/hooks/hooks.json"
fi

# Copy settings.json (vault-independent — no path substitution needed)
if [ -f "$SETTINGS_SRC" ]; then
  cp "$SETTINGS_SRC" "$VAULT_PATH/.claude/settings.json"
  echo "  settings.json: copied"
else
  echo "  WARNING: settings.json not found."
fi

# Copy agent definitions
AGENT_DEFS=0
if [ -d "$AGENTS_SRC" ]; then
  for f in "$AGENTS_SRC"/*.md; do
    if [ -f "$f" ]; then
      cp "$f" "$VAULT_PATH/.claude/agents/"
      AGENT_DEFS=$((AGENT_DEFS + 1))
    fi
  done
fi
echo "  Agent definitions: $AGENT_DEFS copied"

# Install vendor-owned runtime code without repository tests
if [ -d "$RUNTIME_SRC/brain_runtime" ]; then
  replace_runtime_code "$VAULT_PATH" "$RUNTIME_SRC"
  echo "  brain runtime: installed (shadow mode)"
else
  echo "  WARNING: brain runtime source not found; capture will run without shadow instrumentation."
fi

# Copy flat second-brain skills (7 skills in subdirectories)
SECOND_BRAIN_SRC="$BUNDLES_SRC/second-brain"
if [ "$TEMPLATE_IS_PLUGIN" != true ] && [ -d "$TEMPLATE_SOURCE/.claude/skills/second-brain" ]; then
  SECOND_BRAIN_SRC="$TEMPLATE_SOURCE/.claude/skills/second-brain"
fi
SKILL_INSTALLED=0
if [ -d "$SECOND_BRAIN_SRC" ]; then
  for skill_dir in "$SECOND_BRAIN_SRC"/*/; do
    [ -d "$skill_dir" ] || continue
    skill_name=$(basename "$skill_dir")
    skill_full_name="second-brain-$skill_name"
    if [ -f "$skill_dir/SKILL.md" ]; then
      mkdir -p "$VAULT_PATH/.claude/skills/$skill_full_name"
      cp "$skill_dir/SKILL.md" "$VAULT_PATH/.claude/skills/$skill_full_name/"
      SKILL_INSTALLED=$((SKILL_INSTALLED + 1))
    fi
  done
fi
if [ "$SKILL_INSTALLED" -gt 0 ]; then
  echo "  second-brain skills: $SKILL_INSTALLED installed"
else
  echo "  WARNING: no second-brain skills found."
fi

# Copy capture skill reference assets (high-signal section locators) into the vault
HS_ASSET="$SECOND_BRAIN_SRC/capture/assets/high-signal-sections.md"
if [ -d "$SECOND_BRAIN_SRC/capture/assets" ]; then
  if [ ! -f "$HS_ASSET" ]; then
    echo "  ERROR: capture reference asset missing: $HS_ASSET" >&2
    exit 1
  fi
  mkdir -p "$VAULT_PATH/raw/assets"
  cp "$HS_ASSET" "$VAULT_PATH/raw/assets/" || {
    echo "  ERROR: failed to copy high-signal-sections.md to $VAULT_PATH/raw/assets/" >&2
    exit 1
  }
  echo "  capture reference assets: installed to raw/assets/"
fi

# ═══════════════════════════════════════════════════════════════
# Phase 3: Schemas & Templates
# ═══════════════════════════════════════════════════════════════
echo ""
echo "[Phase 3] Installing schemas and templates..."

SCHEMA_COUNT=0
if [ -d "$SCHEMAS_SRC" ]; then
  SCHEMA_COUNT=$(ls "$SCHEMAS_SRC"/*.yaml 2>/dev/null | wc -l | tr -d ' ')
  cp "$SCHEMAS_SRC"/*.yaml "$VAULT_PATH/templates/schemas/" 2>/dev/null || true
fi
echo "  Schemas: $SCHEMA_COUNT YAML files"

# Copy config files (verbatim — purpose.md handled in Phase 5)
for f in materiality.md retrieval.md page-templates.md; do
  if [ -f "$CONFIG_SRC/$f" ]; then
    cp "$CONFIG_SRC/$f" "$VAULT_PATH/config/"
  fi
done
echo "  Config: materiality, retrieval, page-templates"

# Copy Base views
BASE_COUNT=0
if [ -d "$BASES_SRC" ]; then
  for f in "$BASES_SRC"/*.base; do
    if [ -f "$f" ]; then
      cp "$f" "$VAULT_PATH/Templates/Bases/"
      BASE_COUNT=$((BASE_COUNT + 1))
    fi
  done
fi
echo "  Base views: $BASE_COUNT files"

# ── detect_obsidian_version ────────────────────────────────────
# Returns the installed Obsidian version string (e.g. "1.12.7")
# or empty string if not found. Tries standard macOS/Windows/Linux paths.
detect_obsidian_version() {
  local plist="/Applications/Obsidian.app/Contents/Info.plist"
  if [ -f "$plist" ] && command -v plutil &>/dev/null; then
    plutil -p "$plist" 2>/dev/null | sed -n 's/.*"CFBundleShortVersionString".*"\(.*\)"/\1/p'
    return
  fi
  # Also check homebrew-installed Obsidian
  plist="/opt/homebrew/Caskroom/obsidian/latest/Obsidian.app/Contents/Info.plist"
  if [ -f "$plist" ] && command -v plutil &>/dev/null; then
    plutil -p "$plist" 2>/dev/null | sed -n 's/.*"CFBundleShortVersionString".*"\(.*\)"/\1/p'
    return
  fi
  # echo nothing if not found
}

# ── find_compatible_release ─────────────────────────────────────
# Given a GitHub repo and optional Obsidian version, prints the
# best compatible release tag. Falls back to latest if version
# detection fails or no compatible release is found.
# Uses python3 to fetch releases, download manifest.json from each,
# and compare minAppVersion against the installed Obsidian version.
find_compatible_release() {
  local repo="$1"
  local obs_version="$2"
  python3 -c "
import json, sys, subprocess

repo = '$repo'
obs_ver = '$obs_version'

def parse_ver(v):
    try:
        parts = v.strip().split('.')
        return tuple(int(p) if p.isdigit() else 0 for p in parts[:3])
    except Exception:
        return (0, 0, 0)

def is_compatible(min_ver_str):
    if not min_ver_str or min_ver_str.strip() == '':
        return True
    try:
        return parse_ver(obs_ver) >= parse_ver(min_ver_str)
    except Exception:
        return True

def curl_json(url):
    try:
        r = subprocess.run(
            ['curl', '-sSL', '--connect-timeout', '10', '--max-time', '30', url],
            capture_output=True, text=True, timeout=35
        )
        if r.returncode == 0 and r.stdout.strip():
            return json.loads(r.stdout)
    except Exception:
        pass
    return None

releases = curl_json('https://api.github.com/repos/' + repo + '/releases?per_page=20')
if not releases:
    print('', end='')
    sys.exit(0)

for rel in releases:
    tag = rel.get('tag_name', '')
    if not tag:
        continue
    manifest = curl_json(
        'https://github.com/' + repo + '/releases/download/' + tag + '/manifest.json'
    )
    if not manifest:
        continue
    min_ver = manifest.get('minAppVersion', '')
    if is_compatible(min_ver):
        print(tag, end='')
        sys.exit(0)

# No compatible release found — output latest tag
print(releases[0].get('tag_name', ''), end='')
" 2>/dev/null
}

# ── download_obsidian_plugins ──────────────────────────────────
# Downloads community plugins declared in community-plugins.json
# from their GitHub releases. Detects installed Obsidian version
# and selects the newest release compatible with it.
# Requires: python3, curl.
download_obsidian_plugins() {
  local vault_path="$1"
  local community_json="$vault_path/.obsidian/community-plugins.json"
  local plugins_dir="$vault_path/.obsidian/plugins"

  if [ ! -f "$community_json" ]; then
    echo "  Plugins: no community-plugins.json — nothing to download"
    return 0
  fi

  mkdir -p "$plugins_dir"

  # Parse plugin IDs
  local plugin_ids
  plugin_ids=$(python3 -c "
import json
with open('$community_json') as f:
    plugins = json.load(f)
for p in plugins:
    print(p)
" 2>/dev/null)

  if [ -z "$plugin_ids" ]; then
    echo "  Plugins: empty plugin list — nothing to download"
    return 0
  fi

  # Detect installed Obsidian version for compatibility checks
  local obs_version
  obs_version=$(detect_obsidian_version)
  if [ -n "$obs_version" ]; then
    echo "  Obsidian: v$obs_version detected — will select compatible plugin versions"
  else
    echo "  Obsidian: not detected — downloading latest plugin versions"
  fi

  # Fetch community plugins registry from Obsidian's official list
  echo "  Plugins: fetching community registry..."
  local registry
  registry=$(curl -sL --connect-timeout 10 --max-time 30 \
    "https://raw.githubusercontent.com/obsidianmd/obsidian-releases/master/community-plugins.json" 2>/dev/null)

  if [ -z "$registry" ]; then
    echo "  Plugins: WARNING — could not fetch community registry (network issue?)"
    echo "  Plugins: Open vault in Obsidian and install manually: dataview, templater-obsidian, obsidian-git"
    return 1
  fi

  local installed=0
  local skipped=0
  local failed=0

  while IFS= read -r plugin_id; do
    [ -z "$plugin_id" ] && continue

    # Skip if already installed (main.js + manifest.json present)
    if [ -f "$plugins_dir/$plugin_id/main.js" ] && [ -f "$plugins_dir/$plugin_id/manifest.json" ]; then
      installed=$((installed + 1))
      continue
    fi

    # Resolve plugin ID to GitHub repo
    local repo
    repo=$(echo "$registry" | python3 -c "
import json, sys
registry = json.load(sys.stdin)
for p in registry:
    if p.get('id') == '$plugin_id':
        print(p.get('repo', ''))
        break
" 2>/dev/null)

    if [ -z "$repo" ]; then
      echo "  Plugins: $plugin_id — not found in community registry, skipping"
      skipped=$((skipped + 1))
      continue
    fi

    # Find the best release tag (compatible with installed Obsidian, or latest)
    local tag
    tag=$(find_compatible_release "$repo" "$obs_version")

    if [ -z "$tag" ]; then
      # Fallback: try /releases/latest directly
      tag=$(curl -sL --connect-timeout 10 --max-time 30 \
        "https://api.github.com/repos/$repo/releases/latest" 2>/dev/null | \
        python3 -c "import json,sys; print(json.load(sys.stdin).get('tag_name',''))" 2>/dev/null)
    fi

    if [ -z "$tag" ]; then
      echo "  Plugins: $plugin_id — could not fetch release tag, skipping"
      failed=$((failed + 1))
      continue
    fi

    # Download required files: main.js, manifest.json, styles.css (optional)
    mkdir -p "$plugins_dir/$plugin_id"
    local dl_ok=true

    for file in main.js manifest.json styles.css; do
      local url="https://github.com/$repo/releases/download/$tag/$file"
      if ! curl -fsSL --connect-timeout 10 --max-time 30 \
        -o "$plugins_dir/$plugin_id/$file" "$url" 2>/dev/null; then
        # styles.css is optional — only fail if main.js or manifest.json is missing
        if [ "$file" = "main.js" ] || [ "$file" = "manifest.json" ]; then
          dl_ok=false
          break
        fi
        # Remove empty file from failed optional download
        rm -f "$plugins_dir/$plugin_id/$file"
      fi
    done

    if [ "$dl_ok" = true ] && [ -f "$plugins_dir/$plugin_id/main.js" ] && [ -f "$plugins_dir/$plugin_id/manifest.json" ]; then
      echo "  Plugins: $plugin_id v$tag installed"
      installed=$((installed + 1))
    else
      echo "  Plugins: $plugin_id — download failed, skipping"
      rm -rf "$plugins_dir/$plugin_id"
      failed=$((failed + 1))
    fi
  done <<< "$plugin_ids"

  local summary="installed=$installed"
  [ "$skipped" -gt 0 ] && summary="$summary, skipped=$skipped"
  [ "$failed" -gt 0 ] && summary="$summary, failed=$failed"
  echo "  Plugins: $summary"
}

# ═══════════════════════════════════════════════════════════════
# Phase 4: Obsidian
# ═══════════════════════════════════════════════════════════════
if [ "$NO_OBSIDIAN" = false ]; then
  echo ""
  echo "[Phase 4] Installing Obsidian vault config..."

  if [ -d "$OBSIDIAN_SRC" ]; then
    mkdir -p "$VAULT_PATH/.obsidian"
    OBS_FILES=0
    for f in app.json appearance.json graph.json core-plugins.json community-plugins.json types.json; do
      if [ -f "$OBSIDIAN_SRC/$f" ]; then
        cp "$OBSIDIAN_SRC/$f" "$VAULT_PATH/.obsidian/"
        OBS_FILES=$((OBS_FILES + 1))
      fi
    done
    echo "  Obsidian config: $OBS_FILES files"

    # Community plugins: copied from source if available, otherwise user auto-downloads in Obsidian
    if [ -d "$OBSIDIAN_SRC/plugins" ]; then
      mkdir -p "$VAULT_PATH/.obsidian/plugins"
      cp -r "$OBSIDIAN_SRC/plugins"/* "$VAULT_PATH/.obsidian/plugins/" 2>/dev/null || true
      PLUGIN_COUNT=$(ls -d "$VAULT_PATH/.obsidian/plugins"/*/ 2>/dev/null | wc -l | tr -d ' ')
      echo "  Plugins: $PLUGIN_COUNT installed"
    else
      download_obsidian_plugins "$VAULT_PATH"
    fi
  else
    echo "  WARNING: No Obsidian template directory found."
  fi
else
  echo ""
  echo "[Phase 4] Obsidian: skipped (--no-obsidian)"
fi

# ═══════════════════════════════════════════════════════════════
# Phase 5: Domain Configuration
# ═══════════════════════════════════════════════════════════════
echo ""
echo "[Phase 5] Generating domain configuration..."

# CLAUDE.md — look for domain-specific variant first
CLAUDE_SRC=""
for candidate in \
  "$DOMAIN_TEMPLATES_SRC/claude-md/${DOMAIN}.md" \
  "$SKILL_DIR/templates/claude-md/${DOMAIN}.md"; do
  if [ -f "$candidate" ]; then
    CLAUDE_SRC="$candidate"
    break
  fi
done

# Legacy fallback: raw CLAUDE.md from deep-tech-wiki if no domain variant found
if [ -z "$CLAUDE_SRC" ] && [ "$TEMPLATE_IS_PLUGIN" != true ] && [ -f "$TEMPLATE_SOURCE/CLAUDE.md" ]; then
  CLAUDE_SRC="$TEMPLATE_SOURCE/CLAUDE.md"
fi

# Fallback: use industrial-intelligence template for custom or unknown domains
if [ -z "$CLAUDE_SRC" ]; then
  for candidate in \
    "$DOMAIN_TEMPLATES_SRC/claude-md/industrial-intelligence.md" \
    "$SKILL_DIR/templates/claude-md/industrial-intelligence.md"; do
    if [ -f "$candidate" ]; then
      CLAUDE_SRC="$candidate"
      echo "  (using industrial-intelligence template as fallback for '$DOMAIN')"
      break
    fi
  done
fi

if [ -n "$CLAUDE_SRC" ] && [ -f "$CLAUDE_SRC" ]; then
  sed -e "s|{{DOMAIN}}|${DOMAIN_CUSTOM:-$DOMAIN}|g" \
      -e "s|{{DATE}}|${TODAY}|g" \
      -e "s|{{WIKI_NAME}}|${VAULT_NAME}|g" \
      -e "s|deep-tech-wiki|${VAULT_NAME}|g" \
      "$CLAUDE_SRC" > "$VAULT_PATH/CLAUDE.md"
  SCHEMA_VER=$(grep -oP 'Schema v\K[^ ]*' "$VAULT_PATH/CLAUDE.md" 2>/dev/null || echo '?')
  echo "  CLAUDE.md: generated (schema $SCHEMA_VER)"
else
  echo "  ERROR: No CLAUDE.md template found. Vault will lack its master schema."
fi

# purpose.md
PURPOSE_SRC=""
for candidate in \
  "$DOMAIN_TEMPLATES_SRC/purpose/${DOMAIN}.md" \
  "$SKILL_DIR/templates/purpose/${DOMAIN}.md"; do
  if [ -f "$candidate" ]; then
    PURPOSE_SRC="$candidate"
    break
  fi
done

# Legacy fallback
if [ -z "$PURPOSE_SRC" ] && [ "$TEMPLATE_IS_PLUGIN" != true ] && [ -f "$TEMPLATE_SOURCE/config/purpose.md" ]; then
  PURPOSE_SRC="$TEMPLATE_SOURCE/config/purpose.md"
fi

# Fallback: use industrial-intelligence template for custom or unknown domains
if [ -z "$PURPOSE_SRC" ]; then
  for candidate in \
    "$DOMAIN_TEMPLATES_SRC/purpose/industrial-intelligence.md" \
    "$SKILL_DIR/templates/purpose/industrial-intelligence.md"; do
    if [ -f "$candidate" ]; then
      PURPOSE_SRC="$candidate"
      echo "  (using industrial-intelligence purpose template as fallback for '$DOMAIN')"
      break
    fi
  done
fi

if [ -n "$PURPOSE_SRC" ] && [ -f "$PURPOSE_SRC" ]; then
  sed -e "s|{{DOMAIN}}|${DOMAIN_CUSTOM:-$DOMAIN}|g" \
      -e "s|{{DATE}}|${TODAY}|g" \
      -e "s|{{WIKI_NAME}}|${VAULT_NAME}|g" \
      "$PURPOSE_SRC" > "$VAULT_PATH/config/purpose.md"
  echo "  purpose.md: generated"
fi

# ═══════════════════════════════════════════════════════════════
# Phase 6: Supporting Skills
# ═══════════════════════════════════════════════════════════════
if [ "$NO_SUPPORTING_SKILLS" = false ]; then
  echo ""
  echo "[Phase 6] Installing supporting skills..."

  SKILL_INSTALLED=0
  for skill in mineru-batch cfi-filings sec-edgar tianyancha; do
    SKILL_SRC="$BUNDLES_SRC/$skill"
    if [ -d "$SKILL_SRC" ]; then
      mkdir -p "$VAULT_PATH/.claude/skills/$skill"
      cp -r "$SKILL_SRC"/* "$VAULT_PATH/.claude/skills/$skill/" 2>/dev/null || true
      SKILL_INSTALLED=$((SKILL_INSTALLED + 1))
    fi
  done
  echo "  Supporting skills: $SKILL_INSTALLED installed"
else
  echo ""
  echo "[Phase 6] Supporting skills: skipped (--no-supporting-skills)"
fi

# ═══════════════════════════════════════════════════════════════
# Phase 7: Post-init
# ═══════════════════════════════════════════════════════════════
echo ""
echo "[Phase 7] Post-initialization..."

# Git init
if [ "$NO_GIT" = false ]; then
  cd "$VAULT_PATH"
  if git rev-parse --git-dir >/dev/null 2>&1; then
    echo "  Git: already initialized. Adding files..."
    git add -A
    if git diff --cached --quiet 2>/dev/null; then
      echo "  Git: no changes to commit."
    else
      git commit -m "brain-init: new vault scaffold (${DOMAIN})" || true
      echo "  Git: committed."
    fi
  else
    git init -q
    git add -A
    git commit -q -m "brain-init: new vault scaffold (${DOMAIN})"
    echo "  Git: initialized and committed."
  fi

  # Set up remote if provided
  if [ -n "$GIT_REMOTE" ] && git rev-parse --git-dir >/dev/null 2>&1; then
    if ! git remote get-url origin >/dev/null 2>&1; then
      git remote add origin "$GIT_REMOTE"
      echo "  Git: remote 'origin' set to $GIT_REMOTE"
    else
      echo "  Git: remote 'origin' already exists — skipping"
    fi
  fi
else
  echo "  Git: skipped (--no-git)"
fi

# qmd init
if [ "$NO_QMD" = false ]; then
  if command -v qmd &>/dev/null; then
    cd "$VAULT_PATH"

    # Create qmd symlinks (qmd uses the symlink path as collection identity)
    ln -sf wiki brain-knowledge 2>/dev/null || true
    ln -sf wiki/sources brain-sources 2>/dev/null || true
    ln -sf wiki/investigations brain-investigations 2>/dev/null || true

    # Step 1: Register each symlink as a qmd collection
    qmd collection add ./brain-knowledge 2>/dev/null || true
    qmd collection add ./brain-sources 2>/dev/null || true
    qmd collection add ./brain-investigations 2>/dev/null || true

    # Step 2: Mark collections as wiki type (enables wiki-lint, wiki-index, etc.)
    qmd wiki init brain-knowledge 2>/dev/null || true
    qmd wiki init brain-sources 2>/dev/null || true
    qmd wiki init brain-investigations 2>/dev/null || true

    # Step 3: Set collection contexts for better query routing
    qmd context add brain-knowledge "Canonical claims, companies, technologies, markets, and analyses" 2>/dev/null || true
    qmd context add brain-sources "Primary source records with evidence maps and interpretation warnings" 2>/dev/null || true
    qmd context add brain-investigations "Strategic questions, theses, counterevidence, and audience-lens decisions" 2>/dev/null || true

    # Step 4: Index everything
    qmd update 2>/dev/null || true
    qmd embed 2>/dev/null || true
    touch .qmd-last-refresh

    echo "  qmd: 3 collections registered, wiki-typed, and indexed"
  else
    echo "  qmd: SKIPPED (qmd not found — install with: pip install qmd)"
  fi
else
  echo "  qmd: skipped (--no-qmd)"
fi

# ═══════════════════════════════════════════════════════════════
# Phase 8: Validation
# ═══════════════════════════════════════════════════════════════
echo ""
echo "[Phase 8] Running validation..."

PASS=0
FAIL=0

check() {
  local label="$1"
  if eval "$2"; then
    echo "  [PASS] $label"
    PASS=$((PASS + 1))
  else
    echo "  [FAIL] $label"
    FAIL=$((FAIL + 1))
  fi
}

# Directory structure
check "16+ wiki directories present" \
  '[ $(find "$VAULT_PATH/wiki" -type d | wc -l) -ge 17 ]'

# Schema count and validity
check "Schemas installed (>0)" \
  '[ "$SCHEMA_COUNT" -ge 1 ]'

SCHEMA_VALID=true
for f in "$VAULT_PATH/templates/schemas"/*.yaml; do
  [ -f "$f" ] || continue
  python3 -c "import yaml; yaml.safe_load(open('$f'))" 2>/dev/null || SCHEMA_VALID=false
done
check "All schemas parse as valid YAML" '[ "$SCHEMA_VALID" = true ]'

# hooks.json
check "hooks.json is valid JSON" \
  "python3 -c \"import json; json.load(open('$VAULT_PATH/.claude/hooks/hooks.json'))\" 2>/dev/null"

check "hooks.json: no hardcoded ~/deep-tech-wiki" \
  "! grep -q '~/deep-tech-wiki' '$VAULT_PATH/.claude/hooks/hooks.json' 2>/dev/null"

# Agents
AGENT_COUNT=$(ls "$VAULT_PATH/.claude/agents"/*.md 2>/dev/null | wc -l | tr -d ' ')
check "3 agent definitions present" '[ "$AGENT_COUNT" -eq 3 ]'

# Skills (7 flat second-brain skills)
for skill_name in capture query lint reconcile investigate synthesize status; do
  check "second-brain-$skill_name SKILL.md present" \
    "[ -f \"$VAULT_PATH/.claude/skills/second-brain-$skill_name/SKILL.md\" ]"
done

# CLAUDE.md
check "CLAUDE.md present" '[ -f "$VAULT_PATH/CLAUDE.md" ]'

# wiki stubs
check "wiki/index.md present" '[ -f "$VAULT_PATH/wiki/index.md" ]'
check "wiki/log.md present" '[ -f "$VAULT_PATH/wiki/log.md" ]'

# .gitignore and .claudeignore
check ".gitignore present" '[ -f "$VAULT_PATH/.gitignore" ]'
check ".claudeignore present" '[ -f "$VAULT_PATH/.claudeignore" ]'

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Validation: $PASS passed, $FAIL failed"
echo "  Vault:      $VAULT_PATH"
echo "  Domain:     $DOMAIN"
echo "  Schema:     v$(grep -oP 'Schema v\K[^ ]*' "$VAULT_PATH/CLAUDE.md" 2>/dev/null || echo '?')"
echo ""
echo "  Next steps:"
echo "    1. cd $VAULT_PATH"
echo "    2. Open in Obsidian: 'Open folder as vault'"
echo "    3. Set MINERU_TOKEN in .env for PDF extraction"
echo "    4. Run /second-brain-capture on your first source"
echo "    5. Run /brain-init:brain-init --validate to verify vault health"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
