# Document Processing Flow

## Overview

Three phases, in this order:

1. **Init** (`GET /init`, `POST /init`) — form, uploads, matching, dynamic UI redraw.
2. **Generation** (`POST /generate`) — computation, rendering.
3. **Post-generation** — editing in OnlyOffice and/or downloading the result.

Pack selection is not a phase: it runs before them and only sets the roots the
phases below read (descr file, template glob, logic directory).

Numbers below mark **steps**, and the diagram and the step-by-step section use the
same ones: (1.5) is the same step in both.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          DOCX TEMPLATE PROCESSING                           │
└─────────────────────────────────────────────────────────────────────────────┘

════════════════════════════ PHASE 0 · PACK SELECTION (setter) ════════════════

┌───────────────────────────────────────┐
│  routes/select.py                     │  ──▶  active_pack (session + cfg),
│  GET /select · POST /select           │      which resolves: descr_file,
│  - single pack: auto-selected         │      template glob, logic_dir
└───────────────────────────────────────┘


════════════════════════════ PHASE 1 · INIT ═══════════════════════════════════

┌──────────────────┐
│  descr.docx      │
│  language_rules.yaml ───┐
└──────────────────┘      │
                          ▼
┌───────────────────────────────────────┐
│  parser.py                            │  ──(1.1)─▶  {var: {description, type,
│  read_variable_descriptions()         │              types, show_in_form, options}}
│  - Parse DOCX table                   │
│  - Split comma-separated types        │
│  - Parse options cell (typed/bare)    │
│  - Validate values per type           │
└───────────────────────────────────────┘
                          │
                          ▼
┌───────────────────────────────────────┐
│  hints_builder.py                     │  ──(1.2)─▶  HintsCollections
│  build_hints_collections()            │    (vars_to_match, vars_to_compute,
│  - match → vars_to_match              │     vars_as_subdocs, vars_need_init_form)
│  - computed → vars_to_compute         │
│  - subdoc → vars_as_subdocs           │
│  - form/file → vars_need_init_form    │
└───────────────────────────────────────┘
                          │
          ┌───────────────┴────────────────┐
          │                                │
    (1.3) GET /init                  (1.4) POST /init
          ▼                                ▼
┌───────────────────────────────────────┐
│  init.html                            │  Native fields for text / enum / bool
│  native form fields           (1.3)   │  with show_in_form set. The dynamic
└───────────────────────────────────────┘  block below is rendered into it.
                          │
                          │  (1.4) uploads on POST: saved to
                          │  document_store/<session_id>/<var>_<session_id>_<n>.ext
                          │  and recorded in session['uploaded_files']
                          ▼
┌───────────────────────────────────────┐
│  matching.py                          │  ──(1.5)─▶  matched_entities (local dict,
│  run_matching()               (1.5)   │  not persisted). Reads uploads through
│  - match_<var>(session, yaml_key)     │  get_file(session, var_name)
└───────────────────────────────────────┘
                          │
                          ▼
┌───────────────────────────────────────┐
│  dynamic_ui.py                        │  ──(1.6)─▶  unrendered Jinja fragment +
│  build_dynamic_ui_block()     (1.6)   │  its sha256. init_<var>() fires for every
│  - match results + form/file vars     │  matched key, so a match var gets its
│  - output stays a template, not HTML  │  init hook without declaring form
└───────────────────────────────────────┘
                          │
                          ▼
┌───────────────────────────────────────┐
│  HASH GUARD                           │  ──(1.7)─▶  same hash or empty block:
│  hash(unrendered) vs form's ui_hash   │  auto_submit.html → POST /generate
│                                       │  hash changed: init.html redraws with
│                                       │  the new hash (stays in phase 1)
└───────────────────────────────────────┘


════════════════════════════ PHASE 2 · GENERATION ═════════════════════════════

                          │  auto-submit (the only phase 1 → 2 transition)
                          │  descr.docx parsed again for this request
                          ▼
┌───────────────────────────────────────┐
│  context.py                           │  ──(2.1)─▶  DataContext dataclass
│  make_context_class()         (2.1)   │  (fields from descr.docx, Any, default "")
│  - Create dynamic dataclass           │
│  - Auto-convert values via            │
│    _smart_convert()                   │
└───────────────────────────────────────┘
                          │
                          ▼
┌───────────────────────────────────────┐
│  computation.py                       │  ──(2.2)─▶  computed values +
│  compute_variables()          (2.2)   │  subdoc function map
│  - hints-based, descr order first     │  two lookups per var:
│  - two lookups: compute_ / <var>()    │  compute_<var>() and bare <var>()
│  - merge_result() flattens dicts      │
│  - COMPUTE_ON_ERROR lenient/strict    │
└───────────────────────────────────────┘
                          │
                          ▼
┌───────────────────────────────────────┐
│  renderer.py                          │  ──(2.3)─▶  Rendered DOCX files in
│  render_templates()           (2.3)   │  document_store/<session_id>/
│  - Direct DocxTemplate load           │
│  - DeferredSubdoc for subdoc_funcs    │
│  - tpl.render() triggers lazy eval    │
│  - Sandwich + nested subdoc support   │
└───────────────────────────────────────┘


════════════════════════════ PHASE 3 · POST-GENERATION ════════════════════════

                          │
                          ▼
┌───────────────────────────────────────┐
│  routes/onlyoffice.py                 │  ──(3.1)─▶  <doc>.html wrapper per output,
│  generate_editor_html()       (3.1)   │  written next to the DOCX in the session dir
│  - key: fresh uuid per generation     │
│  - no callbackUrl                     │
└───────────────────────────────────────┘
                          │
                          ▼
┌───────────────────────────────────────┐
│  ready.html                           │  ──(3.2)─▶  editor link · /download link
│  two ways out                 (3.2)   │  GET /download: last generated file
│                                       │  POST /download: re-generate, then download
└───────────────────────────────────────┘
                          │
                          ▼
┌───────────────────────────────────────┐
│  OnlyOffice (editor)                  │  Edits are not written back: the config
│  fetches the DOCX over /documents/*   │  carries no callbackUrl, so keeping a
│  (nginx), edits in the browser        │  revision means saving it out of the editor
└───────────────────────────────────────┘

Support modules (used by the steps above, not steps themselves)

┌───────────────────────────────────────┐
│  match_helpers.py             → 1.5   │  Path-traversal protected YAML loading,
│  load_yaml() · find_matches()         │  exact substring then fuzzy fallback
└───────────────────────────────────────┘
┌───────────────────────────────────────┐
│  subdoc_helper.py             → 2.3   │  Lazy-evaluated subdoc wrapper; bookmark and
│  DeferredSubdoc()                     │  table extraction: theme copy → numbering and
│  create_subdoc_sandwich()             │  styles → append elements → render placeholders
│  create_subdoc_from_bookmark()        │  → Subdoc. Sandwich + nested support
│  extract_table_as_subdoc()            │
└───────────────────────────────────────┘
┌───────────────────────────────────────┐
│  loader.py                  → 1.5,    │  Loads *.py from the active pack's logic dir
│  load_plugins()             1.6, 2.2  │  (fallback: root logic/), keeps a module only
│  - Discover *.py in the pack's logic/ │  if it exports {category}_{file_stem}()
│  - Expect {category}_{module}()       │
└───────────────────────────────────────┘

Outside the flow: extractor.py, form_handler.py and the debug/admin pages are
described at the end of this file.
```

## Step-by-Step Flow

### 0. Pack selection (setter, not a phase)

`GET /select` lists packs and is skipped when there is only one. `POST /select`
stores `active_pack` in the session and resolves the roots every later step reads:
`descr_file`, the `template_*.docx` glob, and `logic_dir`. Resolution is explicit per
request (`_resolve_pack_paths()`) instead of mutating shared config state, which is
what keeps concurrent requests on different packs from crossing over.

### 1. Input Files
- `descr.docx` - Variable metadata table (single source of truth)
- `language_rules.yaml` - Enum options and matching data

### 1.1 Parser (parser.py)
Parses `descr.docx` table into variable metadata dictionary.

**Table columns:**
| Col | Name | Required | Description |
|-----|------|----------|-------------|
| 0 | Variable name | Yes | `user_name` or `{{user_name}}` |
| 1 | Description | Yes | Human-readable label |
| 2 | Show in form | Yes | `❌` = hide, else show |
| 3 | Type | Yes | `text`, `enum`, `bool`, `match`, `subdoc`, `computed`, `form`, `file`, `table` (comma-separated) |
| 4 | Options | Conditional | Typed `<type>:<value>` pairs or bare value (single-type); see below |

**Multi-type support:** Column 3 can contain multiple comma-separated types (e.g., `match,computed,subdoc`). Parser splits into a `types` list for membership checking.

**Column 4 — options:** typed form `<type>:<value>[;<type>:<value>]*` for any number of types, bare value for single-type vars (bare on multi-type → logged error, no options). Parsed into a per-type dict `var_meta["options"]` (`None` when empty). Value format per consumer type:
- `enum`: dot-path into `language_rules.yaml` resolving to a list
- `match`: YAML filename the `match_<var>` plugin searches (the plugin's second arg; defaults to the var name when empty)
- `text`: comma-separated inflection case codes (e.g. `no,ge,da`)
- `file`: max upload count (parsed only, enforced by the plugin — see logic/CLAUDE.md)
- other types (`bool`, `computed`, `subdoc`, `form`, `table`): no options — a pair for one is ignored

### 1.2 Hints Builder (hints_builder.py)
Builds `HintsCollections` from parsed variable metadata. Each type in the `types` list maps to a specific hints collection:
- `match` → `vars_to_match` (var_name → yaml_key, defaults to var_name)
- `computed` → `vars_to_compute`
- `subdoc` → `vars_as_subdocs`
- `form` or `file` → `vars_need_init_form`

Hints are consumed by `run_matching()`, `compute_variables()`, and the init route to determine which hooks to fire.

### 1.3 Form generation (init.html + init_* hooks)

Native fields (text, enum, bool) are rendered by `init.html` itself, for variables with `show_in_form` set. Everything custom comes from `init_*` hooks through `dynamic_ui.build_dynamic_ui_block()` — on GET with an empty match list per `vars_need_init_form` var, on POST with match results plus enriched empty lists. See 1.6.

### 1.4 Uploads (POST /init)

Uploaded files are written to `document_store/<session_id>/<var>_<session_id>_<n>.<ext>`
and recorded in `session['uploaded_files']` as `{var_name: [paths]}`. Plugins reach
them only through `get_file(session, var_name)`; no file path is passed as a hook
argument. Pack switch and `GET /init` unlink the stored files before clearing the
references.

### 1.5 Matching (matching.py)
Executed on POST /init (unconditionally — short-circuits when no match vars).

- **Signature:** `run_matching(session, hints, logic_dir)` — no `uploaded_path` argument
- Uses `hints.vars_to_match` (pre-computed dict of var_name → yaml_key)
- For each match variable, discovers and runs `match_<var>(session, yaml_key)` plugin — `yaml_key` is the column-4 value (the var name when the cell is empty)
- Plugins read uploaded files via `get_file(session, var_name)` from `session['uploaded_files']`
- Returns `matched_entities` dict (local — not persisted; the user's selection
  arrives as ordinary form fields)

### 1.6 Dynamic UI redraw (dynamic_ui.py)

`build_dynamic_ui_block(matched_entities, session, logic_dir, variable_desc=None)`
calls `init_<var>()` for every key in `matched_entities`: match results plus the
empty-list entries added for `vars_need_init_form`. A `match` variable therefore gets
its `init_` hook without declaring `form` — that hook is what draws the checkboxes for
what was found. `variable_desc` is passed through for metadata access (e.g., table
slot discovery).

Hook output is treated as a **Jinja template**, not as finished HTML: session values
stay as `{{ session.get(...) }}` placeholders and are filled later, after the hash
check. That is what allows a redraw to keep the values already picked.

### 1.7 Hash guard — the transition to generation

The joined hook output is hashed **before** rendering, so the hash depends on the
structure of the form and not on what the user typed:

| Condition | Result |
|-----------|--------|
| hash equals the `ui_hash` submitted with the form, or the block is empty | `auto_submit.html` posts to `/generate` — the only way out of phase 1 |
| hash differs | `init.html` is re-rendered with the new hash and the user confirms the redrawn selection step |

The block is rendered strictly after this check (`DynamicUIBlock.render()`), never
before. Consequence for plugin authors: hook output must be deterministic — a
timestamp or a random id moves the hash on every request and the form never settles.

### 2.1 Context (context.py)
Creates dynamic `DataContext` dataclass. `descr.docx` is parsed once per
`/generate` request and the result is shared by the context and the hints.

- Fields derived from `descr.docx` variable names
- Default value: `""` for all fields
- Auto-conversion via `_smart_convert()`:
  - Pass-through: `RichText`, `Subdoc`, `InlineImage`, `BytesIO`, `list`, `dict`
  - Convert to string: everything else

### 2.2 Computation (computation.py)
Executed on POST /generate for missing variables.

- Uses `hints.vars_to_compute` and `hints.vars_as_subdocs`
- Compute order: missing `compute_*` vars run first, in descr order (`hints.vars_to_compute`), so a `compute_<b>` reading `compute_<a>`'s output sees it when `a` is declared before `b`; the rest (subdoc / no-rule) follow in arbitrary order
- Two independent lookups per variable:
  - `compute_<var>()` — immediate execution (if `computed` in types)
  - `<var>()` — deferred subdoc (if `subdoc` in types)
- A variable with both types gets both lookups fired independently
- `session` dict passed to compute plugins (for file access via `get_file()`)
- `merge_result()` flattens dict returns from compute plugins: callable values → subdoc functions, non-callables → computed scalars
- Subdoc plugins receive `tpl` and `**kwargs` (full context). They may pass `render_context=kwargs` to `create_subdoc_from_bookmark()` to enable sandwich rendering — Jinja placeholders inside bookmark content are rendered before Subdoc creation
- Error behavior (`config.COMPUTE_ON_ERROR`, env `COMPUTE_ON_ERROR`, default `lenient`): no rule / compute exception → `lenient` renders a sentinel string into the document (`"NO RULE for <var>"` / `"ERROR: ..."`); `strict` logs and raises — the /generate safety net flashes and redirects to /init
- Returns `(computed_values, subdoc_functions)` tuple

### 2.3 Renderer (renderer.py)
Single-phase rendering via docxtpl with lazy subdoc evaluation:

- Load each template directly as `DocxTemplate` (no intermediate files)
- Wrap `subdoc_funcs` as `DeferredSubdoc` — lazy evaluation on first Jinja2 access
- `tpl.render(data_dict)` — triggers `DeferredSubdoc.__str__()` for placeholders
- Subdoc functions may use sandwich rendering: bookmark content with Jinja placeholders is rendered before Subdoc creation (via `create_subdoc_from_bookmark(render_context=...)`)
- Nested subdocs: a subdoc's bookmark content can contain its own subdoc placeholders (e.g., `{{p table_3}}`), resolved inner-first during sandwich rendering

### 3.1 Editor wrapper (routes/onlyoffice.py)

`generate_editor_html(session_dir, docx_filename, docx_public_url)` renders
`editor_template.html` and writes `<docx_filename>.html` next to the generated DOCX
in the session directory, then returns its public URL.

The config carries a `key` that is a fresh uuid per generation, so OnlyOffice never
reuses a cached revision, and **no `callbackUrl`**: the editor does not save back to
the document store.

`document.url` is prefixed with `http://nginx` (the compose service name) in
`editor_template.html` — this stands in for a download callback. Document Server
fetches the DOCX itself, server-side, and resolves `nginx` on `app_network`; the
browser is never given that URL and never needs to. It is why no CORS headers are
required on `/documents/*`. Renaming the nginx service, or running Document Server
outside this network, breaks editing.

### 3.2 Two ways out (ready.html)

- **Edit** — the editor link opens OnlyOffice, which fetches the DOCX through
  `/documents/*` (served by nginx). Since there is no save callback, a revision is
  kept by saving it out of the editor (download permissions are on), not by closing
  the tab.
- **Download** — `GET /download` returns the file the last `/generate` produced;
  `POST /download` re-runs generation and returns the result.

### Support Modules

| Module | Purpose |
|--------|---------|
| `hints_builder.py` | Build HintsCollections from variable metadata |
| `match_helpers.py` | Safe YAML loading + fuzzy string matching |
| `subdoc_helper.py` | Bookmark/table subdoc extraction, sandwich + nested rendering |
| `loader.py` | Plugin discovery from the active pack's `logic/`, fallback to root |

## Notes

- Variables not in `descr.docx` are ignored (not rendered)
- Empty variable names in `descr.docx` are skipped
- Options-cell errors degrade-and-log (missing/invalid enum path → `{"enum": []}`; unknown case codes dropped) — the parser never raises
- Multi-type variables (e.g., `match,computed,subdoc`) are parsed into a `types` list; hints builder categorizes each type independently
- Hints are the single source of truth for which hooks to fire — framework modules don't check types directly
- Init hooks (`init_<var>()`) are stateless from the framework's perspective — they inspect session state to decide output, but must return deterministic templates (see 1.7)
- **Editor edits are not persisted.** Without a `callbackUrl` (3.1) the document store keeps exactly what `/generate` wrote; anything typed in OnlyOffice is lost when the tab closes. The only way to keep an edited revision is the editor's own download. A user gets no warning about this today
- **Inflection** is a convenience along this flow, not a branch of it: a `text` variable with case codes carries an `InflectedWord` through 2.1/2.3, and `/generate` hands the entered forms to the dictionary in the background. See [INFLECTION.md](INFLECTION.md)

## Outside the flow

Debug and admin pages read the same modules but are not part of document
processing: `/debug-vars` (variable and hook wiring; its data sources are
`extractor.py::variables_from_docx()` and `form_handler.py::analyze_template_variables()`,
neither of which runs on a request path), `/debug/inflections` with its sub-pages
(dictionary browse, edit, conflicts), and `/reset` (clears the session, sweeps stale
`data/` entries).
