# CLAUDE.md

## Project Overview

Flask-based document generation system with OnlyOffice integration. Users fill forms based on template variables and could upload files or proceed w/o it, and documents are generated with Jinja2 rendering then edited in OnlyOffice.

**Access:** `http://localhost:5555/init` (via Docker)

## Architecture Summary

```
┌─────────────────────────────────────────────────────────────┐
│  nginx (5555)  →  webserver:5000  →  OnlyOffice:80          │
│  (reverse      (Flask app +         (document editor        │
│   proxy)        gunicorn)           for generated docs)     │
└─────────────────────────────────────────────────────────────┘
```

### Volume Mounts

| Host Path | Container Path | Purpose |
|-----------|----------------|---------|
| `./app/` | `/app/` | Flask app + core framework |
| `./templates/` | `/app/templates/` | Templates, configs, YAML files |
| `./logic/` | `/app/templates/logic/` | User plugins (nested mount) |
| `./data/` | `/document_store` (webserver), `/usr/share/nginx/documents` (nginx) | Persistent document storage |
| `./inflection_data/` | `/app/inflection_data/` | SQLite inflection dictionary (created lazily) |

**Core framework modules** (`./app/logic/` → `/app/logic/`):
- `extractor.py` - Variable extraction from DOCX
- `parser.py` - Parse `descr.docx` content (metadata + pack description)
- `renderer.py` - Template rendering (docxtpl)
- `context.py` - DataContext dataclass factory (pure, stateless)
- `context_manager.py` - Thread-local DataContext class management (multi-pack)
- `match_helpers.py` - Safe YAML loading + fuzzy matching
- `form_handler.py` - HTML form generation
- `subdoc_helper.py` - Subdocument extraction
- `loader.py` - User plugin discovery (thread-local cache)
- `matching.py` - Matching orchestration (calls `match_*` plugins)
- `computation.py` - Variable computation (calls `compute_*` plugins)
- `hints_builder.py` - Pre-computed hints from variable metadata
- `inflection.py` - InflectedWord (grammatical-case dict subclass for rendering)
- `inflection_db.py` - SQLite inflection dictionary (lookup/save/search, conflict log, bg save queue)

**Note:** The `./templates/logic/` directory must exist on host as a mount target for podman's nested volume mount (`./logic:/app/templates/logic`).

## Single Source of Truth

**`templates/descr.docx`** defines all variables: name, type, visibility, options.

*See: [templates/CLAUDE.md](templates/CLAUDE.md) for table structure and parsing details.*

## Directory Structure

| Path | Purpose |
|------|---------|
| `app/` | Flask app + core framework (NOT a Python package) |
| `app/generator.py` | Main entry point, route orchestration |
| `app/config.py` | Configuration dataclass (dynamic pack resolution) |
| `app/session_manager.py` | Flask session wrapper |
| `app/pack_manager.py` | Pack discovery and validation (multi-pack) |
| `app/routes/` | Route handlers (`init.py`, `generate.py`, `select.py`, etc.) |
| `app/routes/html_helpers/` | HTML templates (`init.html`, `select.html`, `ready.html`, etc.) |
| `app/logic/` | Core modules (see above) |
| `app/inflection_data/` | SQLite inflection dictionary (created lazily at runtime) |
| `logic/` | User plugins (Docker: `/app/templates/logic/`) |
| `templates/` | Templates/config (Docker: `/app/templates/`) |
| `templates/descr.docx` | Variable definitions (single source of truth, root pack) |
| `templates/<pack>/` | Additional template packs (multi-pack) |
| `templates/<pack>/descr.docx` | Pack-specific variable definitions |
| `templates/<pack>/logic/` | Pack-specific user plugins (optional) |
| `nginx/` | Nginx reverse proxy configuration |
| `tests/` | Test suite (unit, integration, E2E) |
| `PLAN/` | Planning documents, investigation notes (ignored by git) |

## Import Paths

**`app/` is NOT a Python package.** Docker mount `./app:/app` + `CMD ["python", "generator.py"]` means:

```
/app/  ← sys.path[0] (working directory)
├── generator.py
├── config.py
├── logic/
└── routes/
```

**Correct imports (host + Docker):** `from config import cfg`, `from logic.parser import ...`, `from routes.generate import ...`

## Services (docker-compose.yml)

| Service   | Port  | Purpose                              |
|-----------|-------|--------------------------------------|
| nginx     | 5555  | Reverse proxy, serves documents      |
| webserver | 5000  | Flask app on gunicorn + OnlyOffice   |
| onlyoffice| 80    | Document editor (internal)           |

## Variable Processing Flow

1. **Pack Selection:** User selects pack (or auto-selected if single pack) → `/select` loads DataContext
2. **Extraction:** Variables extracted from Word templates (`document.xml`, headers, footers)
3. **Description:** Metadata loaded from pack's `descr.docx` (table format)
4. **Form Generation:** Only `show_in_form=true` variables appear. `init_*` hooks inject custom UI for `form`/`file`-type variables (file uploads, match selectors, table mapping).
5. **Matching:** `match_*` plugins extract entities from uploaded files (runs unconditionally on POST /init).
6. **Computation:** Missing variables computed via `compute_*` plugins. Returns may be scalars or dict-of-callables (flattened by `merge_result()`).
7. **Rendering:** docxtpl renders variables into output documents. `Subdoc` objects wrapped in `DeferredSubdoc` for lazy evaluation. Inflected text vars render via `{{var.case}}` (`InflectedWord`).
8. **Editing:** Generated docs opened in OnlyOffice for final edits.

## Documentation

| Component | Location |
|-----------|----------|
| Project overview | [CLAUDE.md](CLAUDE.md) |
| Flask routes | [app/CLAUDE.md](app/CLAUDE.md) |
| Core modules | [app/logic/CLAUDE.md](app/logic/CLAUDE.md) |
| Processing flow | [app/logic/FLOW.md](app/logic/FLOW.md) |
| Inflection feature | [app/logic/INFLECTION.md](app/logic/INFLECTION.md) |
| Templates & config | [templates/CLAUDE.md](templates/CLAUDE.md) |
| User plugins | [logic/CLAUDE.md](logic/CLAUDE.md) |
| Demo plugins | [templates/DEMO.md](templates/DEMO.md) |
| Tests | [tests/CLAUDE.md](tests/CLAUDE.md) |