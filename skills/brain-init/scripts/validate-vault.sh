#!/usr/bin/env bash
# validate-vault.sh — Health check for an Industrial Intelligence Brain vault
# Usage: validate-vault.sh <vault-path>
# Called by: /brain-init --validate, or brain-init.sh Phase 8

set -euo pipefail

VAULT_PATH="${1:-}"
if [ -z "$VAULT_PATH" ]; then
  echo "Usage: validate-vault.sh <vault-path>" >&2
  exit 1
fi

# Resolve path
VAULT_PATH="${VAULT_PATH/#\~/$HOME}"
if [[ "$VAULT_PATH" != /* ]]; then
  VAULT_PATH="$PWD/$VAULT_PATH"
fi
VAULT_PATH="${VAULT_PATH//\\//}"
VAULT_PATH="${VAULT_PATH%/}"

if [ ! -d "$VAULT_PATH" ]; then
  echo "ERROR: Vault path does not exist: $VAULT_PATH" >&2
  exit 1
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Brain Vault Validation"
echo "  Vault: $VAULT_PATH"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

PASS=0
FAIL=0
WARN=0

pass() { echo "  [PASS] $1"; PASS=$((PASS + 1)); }
fail() { echo "  [FAIL] $1"; FAIL=$((FAIL + 1)); }
warn() { echo "  [WARN] $1"; WARN=$((WARN + 1)); }

# ═══════════════════════════════════════════════════════════════
# 1. Directory Structure
# ═══════════════════════════════════════════════════════════════
echo "── Directory Structure ──"

WIKI_DIRS=$(find "$VAULT_PATH/wiki" -type d 2>/dev/null | wc -l | tr -d ' ')
if [ "$WIKI_DIRS" -ge 17 ]; then
  pass "16+ wiki directories (found $WIKI_DIRS)"
else
  fail "16+ wiki directories (found $WIKI_DIRS)"
fi

for dir in analyses claims companies concepts industries investigations \
           markets patent-families people processes products queries \
           regulations sources standards syntheses technologies; do
  if [ -d "$VAULT_PATH/wiki/$dir" ]; then
    pass "  wiki/$dir/"
  else
    fail "  wiki/$dir/ — MISSING"
  fi
done

RAW_DIRS=$(find "$VAULT_PATH/raw" -type d 2>/dev/null | wc -l | tr -d ' ')
if [ "$RAW_DIRS" -ge 11 ]; then
  pass "11 raw directories (found $RAW_DIRS)"
else
  fail "11 raw directories (found $RAW_DIRS)"
fi

# ═══════════════════════════════════════════════════════════════
# 2. Schema YAML Validity
# ═══════════════════════════════════════════════════════════════
echo ""
echo "── Schema YAML Validity ──"

SCHEMA_DIR="$VAULT_PATH/templates/schemas"
if [ -d "$SCHEMA_DIR" ]; then
  SCHEMA_COUNT=$(ls "$SCHEMA_DIR"/*.yaml 2>/dev/null | wc -l | tr -d ' ')
  if [ "$SCHEMA_COUNT" -gt 0 ]; then
    pass "Schema directory exists ($SCHEMA_COUNT YAML files)"
  else
    fail "Schema directory empty"
  fi

  for f in "$SCHEMA_DIR"/*.yaml; do
    [ -f "$f" ] || continue
    SCHEMA_NAME=$(basename "$f")
    if python3 -c "import yaml; yaml.safe_load(open('$f'))" 2>/dev/null; then
      pass "  $SCHEMA_NAME"
    else
      fail "  $SCHEMA_NAME — INVALID YAML"
    fi
  done
else
  fail "Schema directory at templates/schemas/"
fi

# ═══════════════════════════════════════════════════════════════
# 3. types.json Coverage
# ═══════════════════════════════════════════════════════════════
echo ""
echo "── types.json Coverage ──"

TYPES_JSON="$VAULT_PATH/.obsidian/types.json"
if [ -f "$TYPES_JSON" ]; then
  # Extract property names from schemas
  SCHEMA_PROPS=$(mktemp)
  for f in "$SCHEMA_DIR"/*.yaml; do
    [ -f "$f" ] || continue
    grep -oP '^[a-z][a-z_0-9]*' "$f" 2>/dev/null | sort -u >> "$SCHEMA_PROPS" || true
  done

  # Extract keys from types.json
  TYPES_PROPS=$(mktemp)
  python3 -c "
import json
data = json.load(open('$TYPES_JSON'))
for k in data.get('types', {}):
    print(k)
" 2>/dev/null | sort > "$TYPES_PROPS" || true

  MISSING=0
  while IFS= read -r prop; do
    [ -z "$prop" ] && continue
    case "$prop" in
      \#*|Referenced|Load|Key|Body|Required|Every|When|Must|These|The|All|This|It|If|For|See|Full|One|In|No|Do|Check) continue ;;
    esac
    if ! grep -qxF "$prop" "$TYPES_PROPS" 2>/dev/null; then
      if [ "$MISSING" -eq 0 ]; then
        echo "  Properties in schemas but missing from types.json:"
      fi
      echo "    - $prop"
      MISSING=$((MISSING + 1))
    fi
  done < "$SCHEMA_PROPS"

  rm -f "$SCHEMA_PROPS" "$TYPES_PROPS"

  if [ "$MISSING" -eq 0 ]; then
    pass "All schema properties mapped in types.json"
  else
    warn "$MISSING properties missing from types.json"
  fi
else
  warn "types.json not found (Obsidian properties will be untyped)"
fi

# ═══════════════════════════════════════════════════════════════
# 4. Hook Integrity
# ═══════════════════════════════════════════════════════════════
echo ""
echo "── Hook Integrity ──"

HOOKS_JSON="$VAULT_PATH/.claude/hooks/hooks.json"
if [ -f "$HOOKS_JSON" ]; then
  if python3 -c "import json; json.load(open('$HOOKS_JSON'))" 2>/dev/null; then
    pass "hooks.json: valid JSON"
  else
    fail "hooks.json: INVALID JSON"
  fi

  if grep -q '~/deep-tech-wiki' "$HOOKS_JSON" 2>/dev/null; then
    fail "hooks.json: contains hardcoded ~/deep-tech-wiki"
  else
    pass "hooks.json: no hardcoded ~/deep-tech-wiki"
  fi

  if grep -q '{{VAULT' "$HOOKS_JSON" 2>/dev/null; then
    fail "hooks.json: contains unexpanded {{VAULT_*}} placeholders"
  else
    pass "hooks.json: no unexpanded placeholders"
  fi

  HOOK_COUNT=$(python3 -c "import json; h=json.load(open('$HOOKS_JSON')); print(len(h.get('hooks',[])))" 2>/dev/null || echo '0')
  if [ "$HOOK_COUNT" -gt 0 ]; then
    pass "hooks.json: $HOOK_COUNT hooks configured"
  else
    fail "hooks.json: no hooks configured"
  fi
else
  warn "hooks.json not found"
fi

# ═══════════════════════════════════════════════════════════════
# 5. Agent Definitions
# ═══════════════════════════════════════════════════════════════
echo ""
echo "── Agent Definitions ──"

AGENT_DIR="$VAULT_PATH/.claude/agents"
if [ -d "$AGENT_DIR" ]; then
  AGENT_COUNT=$(ls "$AGENT_DIR"/*.md 2>/dev/null | wc -l | tr -d ' ')
  if [ "$AGENT_COUNT" -eq 3 ]; then
    pass "3 agent definitions present"
  else
    fail "3 agent definitions (found $AGENT_COUNT)"
  fi

  for f in "$AGENT_DIR"/*.md; do
    [ -f "$f" ] || continue
    AGENT_NAME=$(basename "$f" .md)
    if python3 -c "
import yaml
content = open('$f').read()
if content.startswith('---'):
    yaml.safe_load(content.split('---')[1])
" 2>/dev/null; then
      pass "  $AGENT_NAME: valid frontmatter"
    else
      fail "  $AGENT_NAME: invalid frontmatter"
    fi
  done
else
  warn "Agent directory not found"
fi

# ═══════════════════════════════════════════════════════════════
# 6. Skill Health
# ═══════════════════════════════════════════════════════════════
echo ""
echo "── Skill Health ──"

SKILL_BASE="$VAULT_PATH/.claude/skills"
SKILL_DIRS="second-brain-capture second-brain-query second-brain-lint second-brain-reconcile second-brain-investigate second-brain-synthesize second-brain-status"
SKILL_OK=0
SKILL_FAIL=0
for d in $SKILL_DIRS; do
  SKILL_MD="$SKILL_BASE/$d/SKILL.md"
  if [ -f "$SKILL_MD" ]; then
    if python3 -c "
import yaml
content = open('$SKILL_MD').read()
if content.startswith('---'):
    yaml.safe_load(content.split('---')[1])
" 2>/dev/null; then
      pass "  $d/SKILL.md: valid frontmatter"
      SKILL_OK=$((SKILL_OK + 1))
    else
      fail "  $d/SKILL.md: invalid frontmatter"
      SKILL_FAIL=$((SKILL_FAIL + 1))
    fi
  else
    fail "  $d/SKILL.md: not found"
    SKILL_FAIL=$((SKILL_FAIL + 1))
  fi
done
echo "    $SKILL_OK passed, $SKILL_FAIL failed"

# ═══════════════════════════════════════════════════════════════
# 7. Brain Runtime
# ═══════════════════════════════════════════════════════════════
echo ""
echo "── Brain Runtime ──"

[ -d "$VAULT_PATH/.brain/runs" ] && pass ".brain/runs/" || warn ".brain/runs/ — MISSING"
[ -d "$VAULT_PATH/.brain/evals" ] && pass ".brain/evals/" || warn ".brain/evals/ — MISSING"
[ -f "$VAULT_PATH/.brain/runtime/brain_runtime/cli.py" ] && \
  pass "brain runtime code present" || warn "brain runtime code — MISSING"

if PYTHONPATH="$VAULT_PATH/.brain/runtime" python3 -c \
  'import sys; from pathlib import Path; import brain_runtime; import brain_runtime.cli; Path(brain_runtime.__file__).resolve().relative_to(Path(sys.argv[1]).resolve())' \
  "$VAULT_PATH/.brain/runtime" 2>/dev/null; then
  pass "brain runtime imports"
else
  warn "brain runtime import failed — capture will run without shadow instrumentation"
fi

# ═══════════════════════════════════════════════════════════════
# 8. qmd Health
# ═══════════════════════════════════════════════════════════════
echo ""
echo "── qmd Health ──"

if command -v qmd &>/dev/null; then
  cd "$VAULT_PATH"
  for col in brain-knowledge brain-sources brain-investigations; do
    if [ -L "$col" ] || [ -d "$col" ]; then
      if qmd wiki list -c "$col" >/dev/null 2>&1; then
        pass "qmd '$col': responding"
      else
        warn "qmd '$col': not initialized"
      fi
    else
      warn "qmd symlink '$col' not found"
    fi
  done
else
  echo "  qmd not installed — skipping collection checks"
fi

# ═══════════════════════════════════════════════════════════════
# 9. Wiki & Root Integrity
# ═══════════════════════════════════════════════════════════════
echo ""
echo "── Wiki & Root Integrity ──"

[ -f "$VAULT_PATH/wiki/index.md" ] && pass "wiki/index.md" || fail "wiki/index.md — MISSING"
[ -f "$VAULT_PATH/wiki/log.md" ] && pass "wiki/log.md" || fail "wiki/log.md — MISSING"
[ -f "$VAULT_PATH/CLAUDE.md" ] && pass "CLAUDE.md" || fail "CLAUDE.md — MISSING"
[ -f "$VAULT_PATH/.gitignore" ] && pass ".gitignore" || warn ".gitignore — MISSING"
[ -f "$VAULT_PATH/.claudeignore" ] && pass ".claudeignore" || warn ".claudeignore — MISSING"

PAGE_COUNT=$(find "$VAULT_PATH/wiki" -name '*.md' 2>/dev/null | wc -l | tr -d ' ')
echo "  Total wiki pages: $PAGE_COUNT"

# Index freshness
if [ -f "$VAULT_PATH/wiki/index.md" ]; then
  INDEX_COUNT=$(grep -oP '\*\*Total\*\* \| \*\*\K[0-9]+' "$VAULT_PATH/wiki/index.md" 2>/dev/null || echo '0')
  if [ "$INDEX_COUNT" != "$PAGE_COUNT" ]; then
    warn "Index freshness: index says $INDEX_COUNT, actual is $PAGE_COUNT"
  else
    pass "Index freshness: matches ($PAGE_COUNT pages)"
  fi
fi

# ═══════════════════════════════════════════════════════════════
# 10. External Dependencies
# ═══════════════════════════════════════════════════════════════
echo ""
echo "── External Dependencies ──"

# Python
if command -v python3 &>/dev/null; then
  PY_VER=$(python3 --version 2>&1)
  pass "python3: $PY_VER"
else
  fail "python3: NOT FOUND — required for all tooling"
fi

# Python packages
for pkg in yaml requests; do
  if python3 -c "import $pkg" 2>/dev/null; then
    pass "  Python $pkg: OK"
  else
    fail "  Python $pkg: NOT FOUND — pip install $pkg"
  fi
done

# qmd (semantic search)
if command -v qmd &>/dev/null; then
  QMD_VER=$(qmd --version 2>&1 || echo 'unknown')
  pass "qmd: $QMD_VER"
else
  warn "qmd: not installed — pip install qmd (semantic search disabled)"
fi

# pdftotext (PDF fallback converter)
if command -v pdftotext &>/dev/null; then
  pass "pdftotext: available (PDF fallback converter)"
else
  warn "pdftotext: not installed — brew install poppler (PDF fallback unavailable)"
fi

# agent_gw (SEC EDGAR + Tianyancha + other Kimi data sources)
if python3 -c "import agent_gw" 2>/dev/null; then
  AGW_VER=$(python3 -c "import agent_gw; print(agent_gw.__version__)" 2>/dev/null || echo 'unknown')
  pass "agent_gw: $AGW_VER"
else
  warn "agent_gw: not installed — sec-edgar + tianyancha skills won't work"
fi

# API keys
KIMI_KEY_OK=false
if [ -n "${KIMI_API_KEY:-}" ]; then
  pass "KIMI_API_KEY: set"
  KIMI_KEY_OK=true
else
  warn "KIMI_API_KEY: NOT SET — sec-edgar + tianyancha won't work"
fi

if [ -n "${KIMI_BASE_URL:-}" ]; then
  pass "KIMI_BASE_URL: set ($KIMI_BASE_URL)"
else
  warn "KIMI_BASE_URL: NOT SET — agent_gw defaults to unreachable dev endpoint"
fi

# KIMI connectivity check (only if key + base URL are set)
if [ "$KIMI_KEY_OK" = true ] && [ -n "${KIMI_BASE_URL:-}" ]; then
  # Extract host from base URL for a lightweight connectivity probe
  KIMI_HOST=$(echo "$KIMI_BASE_URL" | sed 's|.*://||' | cut -d/ -f1)
  if python3 -c "
import socket
try:
    socket.create_connection(('$KIMI_HOST', 443), timeout=5)
except Exception:
    exit(1)
" 2>/dev/null; then
    pass "  KIMI connectivity: $KIMI_HOST reachable"
  else
    warn "  KIMI connectivity: $KIMI_HOST UNREACHABLE — check network"
  fi
fi

if [ -n "${MINERU_TOKEN:-}" ]; then
  pass "MINERU_TOKEN: set"
else
  warn "MINERU_TOKEN: NOT SET — PDF extraction via mineru won't work"
fi

# ═══════════════════════════════════════════════════════════════
# 11. Git State
# ═══════════════════════════════════════════════════════════════
echo ""
echo "── Git State ──"

cd "$VAULT_PATH"
if git rev-parse --git-dir >/dev/null 2>&1; then
  pass "Git repository: initialized"
  if git diff --quiet 2>/dev/null && git diff --cached --quiet 2>/dev/null; then
    pass "Git: working tree clean"
  else
    UNSTAGED=$(git diff --name-only 2>/dev/null | wc -l | tr -d ' ')
    STAGED=$(git diff --cached --name-only 2>/dev/null | wc -l | tr -d ' ')
    warn "Git: $UNSTAGED unstaged, $STAGED staged changes"
  fi
  LAST_COMMIT=$(git log -1 --format='%s' 2>/dev/null || echo 'none')
  echo "  Last commit: $LAST_COMMIT"
else
  warn "Git: not initialized"
fi

# ═══════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Validation Complete"
echo "  Passed:   $PASS"
echo "  Failed:   $FAIL"
echo "  Warnings: $WARN"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ "$FAIL" -gt 0 ]; then
  echo ""
  echo "  Remediation hints:"
  echo "    - Missing schemas? Run /brain-init --upgrade-harness"
  echo "    - Broken YAML? Check templates/schemas/ for syntax errors"
  echo "    - Missing hooks? Re-init with --force to merge harness"
  exit 1
elif [ "$WARN" -gt 0 ]; then
  echo ""
  echo "  Vault is functional with $WARN warning(s)."
  exit 0
else
  echo ""
  echo "  Vault is healthy. All checks passed."
  exit 0
fi
