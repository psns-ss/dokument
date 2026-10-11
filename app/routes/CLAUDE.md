# app/routes/CLAUDE.md

Flask route blueprints: HTTP endpoints and request handling.

---

## Blueprints

| Blueprint | File | Registered At |
|-----------|------|---------------|
| `select` | [select.py](select.py) | `/select` (pack selection) |
| `init` | [init.py](init.py) | `/init` (form) |
| `generate` | [generate.py](generate.py) | `/generate` (render) |
| `debug` | [debug.py](debug.py) | `/debug-vars`, `/reset`, `/debug/inflections*` (admin UI) |
| `inflection` | [inflection.py](inflection.py) | `/inflection/lookup` (AJAX auto-fill) |
| `onlyoffice` | [onlyoffice.py](onlyoffice.py) | Utility (no routes) |

---

## Route Handlers

### [select.py](select.py)

**GET /select**: Show pack selection UI.
- Auto-select if single pack available
- Redirect to `/init` after selection

**POST /select**: Process pack selection.
- Validate pack exists
- Resolve paths explicitly (thread-safe)
- Load DataContext for thread
- Clear session data (preserve system keys)
- Set `active_pack` in config + session
- Redirect to `/init`

**Key function:** `_resolve_pack_paths(identifier)` - Returns `(descr_path, lang_path)` without mutating `cfg.active_pack`.

---

### [init.py](init.py)

**GET /init**: Show initialization form.
- Clear old session data
- Load DataContext for current pack (descr.docx parsed once, shared with hints)
- Build `HintsCollections` from variable descriptions
- Call `init_<var>()` hooks for `vars_need_init_form` via `build_dynamic_ui_block()` (empty `matched_list`)
- Render `init.html` with form fields + `dynamic_ui` fragments

**POST /init**: Process form submission.
- Save user variables to session
- Initialize `uploaded_files` for all `type=file` variables, handle uploads (save to `document_store/session_id/`, track in session)
- Run matching (`run_matching()`) unconditionally (short-circuits if no match vars)
- Enrich `matched_entities` in-place — add empty lists for `vars_need_init_form`
- Build the dynamic-UI block (`build_dynamic_ui_block()` — generate + checksum of the unrendered template)
- Hash guard: if the block is empty OR its hash matches the form's `ui_hash` → auto-submit; hash changed → render `init.html` with the new hash; the hash travels in a hidden form field

---

### [generate.py](generate.py)

**POST /generate**: Render documents and launch editors.
- Parse form data (cleaned data)
- Validate pack still available
- Load DataContext for thread (reuses the parsed descriptions — no re-open)
- Find template files in pack directory
- Read variable descriptions (descr.docx parsed **once** here, shared by DataContext + hints)
- Build `HintsCollections` from variable descriptions
- Compute missing variables (`compute_variables()` with hints) → returns computed values + subdoc_functions
- Build DataContext from cleaned + computed values
- Render templates (`render_templates()` with subdoc_funcs) — single-phase, no intermediate files
- Generate OnlyOffice editor HTML for each output
- Return `ready.html` with document links
- Compute/render failure → `logger.error` + flash + redirect to /init (safety net — the per-var internals already degrade; note /init GET clears the session)

---

### [debug.py](debug.py)

**GET /debug-vars?pack=<id>**: Template author's checklist.
- Pack selectable (`?pack=`, default: active pack); paths resolved via `pack_manager.resolve_pack_paths()` — no `cfg.active_pack` mutation
- Matrix: descr.docx vars × pack templates (found/missing) + type; rows in descr.docx order by default, any column sortable via header click (asc ↑ / desc ↓ / back to descr order); hover the var name → description + real hook function names
- Hooks: expected (from `types`) vs implemented (`verify_hooks_exist()` name-match scan); shown as a "var → module → hooks" wiring graph
- Flags: loader-dropped modules (hooks that never fire), plugin import errors, unexpected vars (in templates, not in descr)

**GET /reset**: Clear session, sweep stale data, auto-redirect.
- Wipes all session data
- Sweeps document-store entries older than `DATA_TTL_DAYS` via `_cleanup_stale_sessions()` (best-effort, never raises)
- Renders `reset.html`, which auto-redirects to `/init` after a 1 s beat

---

### [onlyoffice.py](onlyoffice.py)

**Utility module** (no routes).

**`generate_editor_html(session_dir, docx_filename, docx_public_url)`**:
- Render `editor_template.html` to session directory
- Write `<docx_filename>.html` with OnlyOffice config
- Return public URL path to HTML file

---

## HTML Helpers

Templates in [html_helpers/](html_helpers/):

| Template | Used By | Purpose |
|----------|---------|---------|
| `init.html` | init.py | Form with fields, tables, dynamic UI fragments |
| `select.html` | select.py | Pack selection radio buttons |
| `ready.html` | generate.py | Document links after generation |
| `auto_submit.html` | init.py | Hidden-form POST to /generate |
| `editor_template.html` | onlyoffice.py | OnlyOffice editor wrapper |
| `debug-vars.html` | debug.py | Variable analysis display |
| `reset.html` | debug.py | Reset confirmation |
| `debug_inflections.html` | debug.py | Inflection admin: browse/search |
| `debug_conflicts.html` | debug.py | Inflection admin: conflict log |
| `edit_inflection.html` | debug.py | Inflection admin: edit/add word |

---

## Thread Safety

**Pack switching:** Routes use explicit path resolution (`_resolve_pack_paths()`) to avoid `cfg._active_pack` race conditions.

**DataContext:** Each thread loads its own DataContext class via `load_data_context_for_pack()`.

**Plugins:** Thread-local cache keyed by `(logic_dir, category)`.