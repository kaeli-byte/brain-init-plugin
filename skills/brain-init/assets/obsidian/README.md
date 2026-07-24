# Obsidian Plugin Installation

This directory contains Obsidian vault configuration only (JSON files).
Community plugins (dataview, templater, obsidian-git) are NOT bundled.

During `brain-init`, the script automatically downloads plugins declared in
`community-plugins.json` from their GitHub releases. Requires: python3, curl.

If the download fails (offline, rate-limited), open the vault in Obsidian
and install them manually from Settings → Community plugins.
