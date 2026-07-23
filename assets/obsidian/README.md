# Obsidian Plugin Installation

This directory contains Obsidian vault configuration only (JSON files).
Community plugins (dataview, templater, obsidian-git) are NOT bundled.

After brain-init creates your vault, open it in Obsidian with "Safe Mode" off.
Obsidian will automatically download the declared plugins on first open.

If you need the plugins built during initialization:
```
/brain-init:brain-init --install-obsidian-plugins ~/my-brain
```
(Requires git, node, and npm. Coming in v1.1.)
