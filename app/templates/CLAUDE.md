# app/templates/CLAUDE.md

## Templates Directory (Docker Mount)

This directory is a **Docker mount** from the project root:

```yaml
# docker-compose.yml
volumes:
  - "./templates:/app/templates"        # Word templates, YAML configs
  - "./logic:/app/templates/logic"      # Pluggable computation modules
```

**Local paths (project root):**
- `./templates/` - Word templates, `descr.docx`, YAML configs
- `./logic/` - Pluggable Python computation modules

---

## Contents Reference

See detailed documentation:

| Resource | Location |
|----------|----------|
| Word templates (`template_*.docx`) | `../../templates/` |
| Variable definitions (`descr.docx`) | `../../templates/` |
| YAML configs (`language_rules.yaml`, `university.yaml`) | `../../templates/` |
| Pluggable modules (`*.py`) | `../../logic/` |
| Template docs | `../../templates/CLAUDE.md` |
| Logic module docs | `../../logic/CLAUDE.md` |