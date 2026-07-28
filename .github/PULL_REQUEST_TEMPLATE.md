## Summary

<!-- One sentence: what does this change and why -->

## Type

- [ ] Bug fix
- [ ] New feature
- [ ] Domain preset (new or updated template)
- [ ] Bundle update (skill, script, or reference doc)
- [ ] CI / tooling

## Checklist

- [ ] Shell scripts pass `bash -n`
- [ ] YAML files pass `python3 -c "import yaml; yaml.safe_load(...)"`
- [ ] JSON files pass `python3 -c "import json; json.load(...)"`
- [ ] Version bumped in `SKILL.md` / `plugin.json` / `marketplace.json` if any of them changed (CI version-gate enforces this)
- [ ] All 5 domain presets still scaffold (no regressions in untested templates)
- [ ] `brain-init.sh` still works: `./skills/brain-init/scripts/brain-init.sh /tmp/test --domain semiconductor --no-git --no-qmd --no-obsidian --no-supporting-skills`

## Screenshots / Output

<!-- If applicable, paste relevant CLI output or screenshots -->

```

```
