# app/CLAUDE.md

Flask application: HTTP routing and session coordination. Heavy lifting delegated to `logic/` modules.

---

## Module Tree

```
app/
├── generator.py        # WSGI entry point (gunicorn), route registration
├── config.py           # Config dataclass (cfg), pack resolution
├── session_manager.py  # Session operations (clear, save, restore, get_file)
├── pack_manager.py     # Pack discovery, validation
├── logic/              # Core framework (see logic/CLAUDE.md)
│   ├── extractor.py    # Variable extraction from DOCX
│   ├── parser.py       # Parse descr.docx
│   ├── renderer.py     # Template rendering
│   ├── context.py      # DataContext factory
│   ├── context_manager.py  # Thread-local DataContext
│   ├── match_helpers.py    # YAML loading, fuzzy matching
│   ├── form_handler.py     # Form analysis
│   ├── subdoc_helper.py    # Subdocument extraction
│   ├── loader.py           # Plugin discovery
│   ├── computation.py      # Variable computation
│   ├── matching.py         # Matching orchestration
│   ├── dynamic_ui.py       # Init-form dynamic-UI block (generate/checksum/render)
│   ├── hints_builder.py    # Pre-computed hints from variable metadata
│   ├── inflection.py       # InflectedWord (grammatical-case rendering)
│   └── inflection_db.py    # SQLite inflection dictionary
└── routes/             # Route blueprints
    ├── init.py         # GET/POST /init (form)
    ├── generate.py     # POST /generate (render)
    ├── select.py       # GET/POST /select (pack choice)
    ├── debug.py        # GET /debug-vars, /reset, /debug/inflections (admin)
    ├── inflection.py   # GET /inflection/lookup (AJAX auto-fill)
    ├── onlyoffice.py   # Editor HTML generation
    └── html_helpers/   # HTML templates
        ├── init.html       # Form template
        ├── select.html     # Pack selection
        ├── ready.html      # Document links
        ├── auto_submit.html# Auto-submit helper
        ├── editor_template.html  # OnlyOffice wrapper
        ├── debug-vars.html       # Debug view
        ├── reset.html            # Reset confirmation
        ├── debug_inflections.html  # Inflection admin (browse)
        ├── debug_conflicts.html    # Inflection admin (conflict log)
        └── edit_inflection.html    # Inflection admin (edit)
```

---

## Routes

| Route | Method | Purpose |
|-------|--------|---------|
| `/` | Blocked | OnlyOffice reserved. Entry = `/init`. |
| `/select` | GET | Show pack selection UI (if multiple packs) |
| `/select` | POST | Select pack, load DataContext, clear session, redirect `/init` |
| `/init` | GET | Show form (step 1), clear session |
| `/init` | POST | Save form, handle upload, run matching → step 2 or auto-submit |
| `/generate` | POST | Render docs, launch OnlyOffice editors |
| `/debug-vars` | GET | Variable extraction analysis |
| `/reset` | GET | Clear session |
| `/documents/*` | GET | nginx serves static files |

---

## Configuration

`Config` dataclass → `cfg`. Paths Docker-mounted.

**Multi-pack:** `cfg` resolves paths dynamically via `active_pack` (session-set).

| Field | Default | Docker | Resolves to |
|-------|---------|--------|-------------|
| `templates_dir` | `templates` | `/app/templates` | Root of all packs |
| `active_pack` | `'root'` | — | Session-set pack name |
| `pack_dir` | dynamic | — | `{templates_dir}/{active_pack}` (pack base directory) |
| `descr_file` | dynamic | — | `{pack_dir}/descr.docx` |
| `lang_rules` | dynamic | — | Pack YAML, fallback root |
| `logic_dir` | dynamic | — | Pack `logic/`, or `None` |
| `document_store` | `/document_store` (env `DOCUMENT_STORE`) | `/usr/share/nginx/documents` | Shared |

**Env vars:** `FLASK_LOG_LEVEL` — root log level (default INFO; E2E log-content tests need DEBUG). `COMPUTE_ON_ERROR` — compute-failure behavior: `lenient` (default) renders a sentinel string into the document, `strict` aborts generation (see the computation section in [logic/CLAUDE.md](logic/CLAUDE.md)). `DATA_TTL_DAYS` — age in days past which `/reset` sweeps document-store entries (default 14). `DOCUMENT_STORE` — document-store directory; the `/document_store` default is a Docker volume path, so set it to run outside Docker (CI sets it; the suite redirects it per test — see [tests/CLAUDE.md](../tests/CLAUDE.md)).

**Thread note:** `cfg._active_pack` has narrow race window. Routes call `ensure_active_pack()` at entry; use explicit path resolution in routes for full safety.

---

## Session Keys

| Key | Purpose | Cleared on pack switch? | Cleared on GET /init? |
|-----|---------|------------------------|----------------------|
| `active_pack` | Pack name ('root' or subdir) | No | No |
| `session_id` | Session folder ID (file naming) | Yes | No |
| `<var_name>` | User form values | Yes | Yes |
| `uploaded_files` | Dict of type=file upload paths | Yes | Yes |

**Nuke pattern:** `clear_for_init()` (GET /init) preserves only `active_pack` and `session_id`. `clear_for_pack_switch()` preserves only `active_pack`. Both methods unlink old uploaded files from disk before clearing references.

**`uploaded_files` structure:**
```python
session['uploaded_files'] = {
    'cv': ['/document_store/<session_id>/cv_<session_id>_0.docx'],
    'portfolio': ['/document_store/<session_id>/portfolio_<session_id>_0.docx']
}
```
Access via `get_file(session, var_name)`. Files are saved as `<var_name>_<session_id>_<n>.ext` in `cfg.document_store / session_id`.

**POST /init flow:** Build `HintsCollections` → process `type=file` uploads into `uploaded_files` → run `match_*` plugins unconditionally (hints-based, plugins read `uploaded_files` via `get_file()`) → enrich the local `matched_entities` dict with `vars_need_init_form` → `init_*` plugins generate UI (results are not persisted — the user's selection arrives as ordinary form fields) → hash guard decides step 2 or auto-submit.

---

## Plugin Loading

- `load_plugins(logic_dir, category, extra_stems=None)` - Finds `{category}_{module}` in `{pack}/logic/*.py`; a module is kept if it exports `{category}_{module_name}()` or any of `extra_stems` (the compute load passes the subdoc var names so subdoc-only modules aren't dropped)
- Categories: `match`, `compute`, `init`
- **Cache:** Thread-local per `(logic_dir, category, extra_stems)`
- **Fallback:** Pack `logic/` → root `logic/` if missing
- **Loading:** explicit file path (`spec_from_file_location`), not `sys.path` — a plugin can't `import` a sibling (raises `ImportError`)

## Hints Collections

`HintsCollections` (from `hints_builder.py`) is the single source of truth for which hooks fire:
- `vars_to_match` → `match_<var>()` plugins (matching phase)
- `vars_to_compute` → `compute_<var>()` plugins (computation phase)
- `vars_as_subdocs` → `<var>()` plugins (render phase, deferred)
- `vars_need_init_form` → `init_<var>()` plugins (init phase, UI generation)

Built from the `types` list in `descr.docx` variable metadata. Supports multi-type variables (e.g., `match,computed,subdoc`).

**sys.modules:** Top-level plugins don't register (loaded by explicit path, not via `sys.path`). Intra-plugin imports (`from helper import X`) raise `ImportError` — the logic dir isn't on `sys.path`, so a plugin can't `import` a sibling (do them package-scoped if ever needed). No cross-pack same-named-helper collision is possible.

---

## Logging

All logs → `/app/flask_app.log`. Root level defaults to **INFO**; override with
`FLASK_LOG_LEVEL` (e.g. `DEBUG` — required for the E2E log-content tests).
Third-party pins (independent of root): `docxtpl`/`jinja2` = DEBUG (render
diagnostics), `docx` = WARNING.

---

## Docs

| Location | Content |
|----------|---------|
| [logic/CLAUDE.md](logic/CLAUDE.md) | Core modules |
| [logic/FLOW.md](logic/FLOW.md) | Flow diagram |
| [logic/INFLECTION.md](logic/INFLECTION.md) | Word inflection feature (flow + limitations) |
| [../templates/CLAUDE.md](../templates/CLAUDE.md) | Templates |
| [../logic/CLAUDE.md](../logic/CLAUDE.md) | User plugins |