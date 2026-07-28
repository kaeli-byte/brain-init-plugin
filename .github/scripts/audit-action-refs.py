#!/usr/bin/env python3
"""Audit helper: report which workflow action refs are floating (tags or short SHAs).

Intended for CI hygiene checks alongside .github/workflows pinning policy.
"""

import os
import re
import sys


def find_workflows(root: str) -> list[str]:
    """Collect workflow YAML files under root."""
    matches = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for name in filenames:
            if name.endswith((".yml", ".yaml")) and "workflow" in dirpath:
                matches.append(os.path.join(dirpath, name))
    return matches


FULL_SHA = re.compile(r"^[0-9a-fA-F]{40}$")


def action_refs(content: str) -> list[str]:
    """Extract `uses:` values from workflow YAML text (coarse but dependency-free)."""
    refs = []
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("uses:") or line.startswith("- uses:"):
            value = line.split("uses:", 1)[1].strip().strip('"').strip("'")
            # Drop trailing YAML inline comments (e.g. "@<sha> # v7").
            value = value.split("#", 1)[0].strip()
            if "@" in value and not value.startswith("./"):
                refs.append(value)
    return refs


def is_pinned(ref: str) -> bool:
    """A ref counts as pinned only when it ends in a full 40-char SHA."""
    return FULL_SHA.match(ref.rsplit("@", 1)[1]) is not None


def audit(paths: list[str]) -> dict[str, list[str]]:
    """Map each workflow file to its floating (unpinned) action refs."""
    findings = {}
    for path in paths:
        try:
            with open(path) as handle:
                content = handle.read()
        except OSError as exc:
            print(f"WARN: cannot read {path}: {exc}", file=sys.stderr)
            continue
        floating = [ref for ref in action_refs(content) if not is_pinned(ref)]
        if floating:
            findings[path] = floating
    return findings


def main() -> int:
    root = sys.argv[1] if len(sys.argv) > 1 else ".github"
    findings = audit(find_workflows(root))

    # Report every floating ref so maintainers can pin them.
    for path, refs in findings.items():
        for ref in refs:
            print(f"FLOATING {path}: {ref}")

    total = sum(len(refs) for refs in findings.values())
    print(f"\n{total} floating action ref(s) found")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
