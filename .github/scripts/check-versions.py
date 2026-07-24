#!/usr/bin/env python3
"""Version gate: fail CI if versioned files changed without a version bump.

Compares changed files between HEAD and the base branch (default: origin/master).
Every file that declares a version must have its version incremented vs. the base.

Detected version locations:
  - SKILL.md frontmatter: `version: X.Y.Z` (top-level or metadata.version)
  - plugin.json: `"version": "X.Y.Z"`
  - marketplace.json: `plugins[0].version`
"""

import json
import os
import subprocess
import sys


import yaml


def run(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, text=True).strip()


def changed_files(base: str = "origin/master") -> list[str]:
    """Return list of files changed between base and HEAD."""
    try:
        return run(["git", "diff", "--name-only", f"{base}...HEAD"]).split("\n")
    except subprocess.CalledProcessError:
        return []


def file_at_ref(path: str, ref: str) -> str | None:
    """Get file content at a git ref. Returns None if file doesn't exist there."""
    try:
        return run(["git", "show", f"{ref}:{path}"])
    except subprocess.CalledProcessError:
        return None


def parse_version(path: str, content: str) -> str | None:
    """Extract version from a file. Returns version string or None."""
    if not content:
        return None

    if path.endswith("plugin.json"):
        try:
            return json.loads(content).get("version")
        except json.JSONDecodeError:
            return None

    if path.endswith("marketplace.json"):
        try:
            plugins = json.loads(content).get("plugins", [])
            return plugins[0].get("version") if plugins else None
        except json.JSONDecodeError:
            return None

    if path.endswith("SKILL.md"):
        try:
            parts = content.split("---", 2)
            if len(parts) < 3:
                return None
            fm = yaml.safe_load(parts[1])
            if not isinstance(fm, dict):
                return None
            if "version" in fm:
                return str(fm["version"])
            if "metadata" in fm and isinstance(fm["metadata"], dict):
                return str(fm["metadata"].get("version", ""))
        except Exception:
            return None

    return None


def parse_semver(v: str) -> tuple[int, int, int]:
    """Parse semver string. Handles '1.0.0', 'v1.0.0', and quoted '"1.0.0"'."""
    v = v.strip().strip('"').strip("'").lstrip("v")
    parts = v.split(".")
    return (int(parts[0]), int(parts[1]), int(parts[2]))


def version_bumped(old: str | None, new: str | None) -> bool:
    """Check if version was bumped (new > old). New files (old=None) auto-pass."""
    if old is None:
        return True
    if new is None:
        return False
    try:
        return parse_semver(new) > parse_semver(old)
    except (ValueError, IndexError):
        return False


def main() -> int:
    is_pr = os.environ.get("GITHUB_EVENT_NAME") == "pull_request"

    if is_pr:
        base = os.environ.get("GITHUB_BASE_REF", "origin/master")
        target = f"origin/{base}"
        try:
            run(["git", "fetch", "origin", base, "--depth=1"])
        except subprocess.CalledProcessError:
            pass
    else:
        # Push: compare against previous commit on the same branch
        target = "HEAD~1"
        try:
            # Verify HEAD~1 exists
            run(["git", "rev-parse", target])
        except subprocess.CalledProcessError:
            print("Push event with no previous commit — skipping version check.")
            return 0

    files = changed_files(target)
    if not files:
        print("No changed files detected. Nothing to check.")
        return 0

    versioned = {
        f for f in files
        if f.endswith("SKILL.md")
        or f.endswith("plugin.json")
        or f.endswith("marketplace.json")
    }

    if not versioned:
        print(f"No versioned files among {len(files)} changed file(s).")
        return 0

    label = f"PR base ({base})" if is_pr else "previous commit"
    print(f"Checking {len(versioned)} versioned file(s) changed vs {label}:\n")

    failed: list[tuple[str, str, str]] = []
    passed: list[tuple[str, str | None, str, str]] = []
    no_version: list[tuple[str, str]] = []

    for path in sorted(versioned):
        head_content = file_at_ref(path, "HEAD")
        base_content = file_at_ref(path, target)

        head_ver = parse_version(path, head_content or "")
        base_ver = parse_version(path, base_content or "") if base_content else None

        rel = os.path.relpath(path)

        if head_ver is None:
            no_version.append((rel, "no version field found"))
            print(f"  !  {rel}: no version field - can't enforce bump")
            continue

        if base_ver is None:
            passed.append((rel, None, head_ver, "new"))
            print(f"  OK {rel}: {head_ver} (new file)")
            continue

        if version_bumped(base_ver, head_ver):
            passed.append((rel, base_ver, head_ver, "bumped"))
            print(f"  OK {rel}: {base_ver} -> {head_ver}")
        else:
            failed.append((rel, base_ver, head_ver))
            print(f"  FAIL {rel}: {base_ver} (no bump)")

    if no_version:
        print(f"\n  ! {len(no_version)} file(s) without version fields (advisory)")

    if failed:
        print(f"\nFAIL: {len(failed)} versioned file(s) changed without a version bump:")
        for rel, old, new in failed:
            print(f"   - {rel}: still {new} (was {old})")
        print("\nAction: increment the version field in each listed file.")
        return 1

    if passed:
        print(f"\nOK: {len(passed)} versioned file(s) correctly bumped or new.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
