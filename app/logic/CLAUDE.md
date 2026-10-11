# app/logic/CLAUDE.md

Core framework modules for DOCX template processing. Imported by `generator.py`.

**Flow:** See [FLOW.md](FLOW.md) for visual diagram.
**Inflection:** See [INFLECTION.md](INFLECTION.md) for the word-inflection feature overview.

---

## Modules

### [extractor.py](extractor.py)

**Purpose:** Extract `{{variable}}` names from DOCX (diagnostic — consumer is `/debug-vars`).

**`variables_from_docx(path)`**: Scans `document.xml`, **all** `headerN.xml`/`footerN.xml` (no 10-part cap), `footnotes.xml`, `endnotes.xml`. Returns a set of base variable names, normalizing every docxtpl form to its base: `{{var}}`, dotted `{{var.case}}` → `var`, tagged `{{p var}}`/`{{l var}}`/`{{t var}}` → `var`, safe `{{! var}}` → `var`, subscript `{{p var[0]}}` → `var`. Also reads control blocks: `{% if var ... %}` / `{%p if ... %}` (docxtpl paragraph block tag — the `p` prefix is stripped by docxtpl before Jinja) → the condition's variables, and `{% for x in var %}` → the iterable `var`; loop targets (`x`) are collected per XML part and subtracted, so `{{x.attr}}` inside the loop doesn't report `x` (scope is approximated per part, not per block). Identifier subscripts `{{var[key]}}` report `key` too (Jinja resolves it in the context); numeric indices and string keys don't. String literals are stripped after normalizing curly quotes — mirroring docxtpl's `clean_tags`. Text is joined per `<w:p>` (not per file) so a `{{` in one paragraph and `}}` in another can't false-match; the split is depth-aware — textboxes nest `<w:p>` inside `<w:p>` via `<w:txbxContent>`, and a var after a textbox in the same outer paragraph is still found.

---

### [parser.py](parser.py)

**Purpose:** Parse `descr.docx` table → variable metadata.

**`read_variable_descriptions(descr_path, lang_file)`**: Returns `{var: {description, show_in_form, type, types, options}}`. The `type` field is the raw string (e.g., `"match,computed"`). The `types` field is a parsed list (`["match", "computed"]`).

**Options cell (column 4):** typed form `<type>:<value>[;<type>:<value>]*` for any number of types, or a bare value — single-type vars only (bare on a multi-type var → logged error, no options; a bare cell's meaning must not silently change the day one of its types starts reading the column). Consumer types and their value formats: `enum` — dot-path to a list in `language_rules.yaml`; `match` — YAML filename for the `match_<var>` plugin; `text` — CSV of case codes (validated against `RECOGNIZED_CASES`); `file` — max upload count (`file:<N>`, positive int; `0` = no cap). Parsed result: `options` is a per-type dict (`{"enum": [...]}`, `{"match": "key"}`, `{"text": [...]}`, `{"file": N}`; `None` when there are no options). Note the core only *parses* `file:<N>` into `options['file']` — it does **not** enforce the limit; enforcement is user-side (an `init_<var>` hook reads `options['file']` and caps the upload batch in JS — see [logic/CLAUDE.md](../../logic/CLAUDE.md)). Errors are degrade-and-log, never raise — the parser is on the per-request path, a descr typo must not 500 the form.

**`extract_pack_description(descr_path)`**: First paragraph before table → pack description for `/select` UI.

**Types:** `text`, `enum`, `bool`, `match`, `subdoc`, `table`, `computed`, `form`, `file`. Types can be comma-separated (e.g., `match,computed,subdoc`).

---

### [hints_builder.py](hints_builder.py)

**Purpose:** Build pre-computed hints from variable metadata. Hints tell the engine which vars need which hooks.

**`HintsCollections`** (dataclass):
- `vars_to_match` — `Dict[str, str]` (var_name → yaml_key)
- `vars_to_compute` — `List[str]`
- `vars_as_subdocs` — `List[str]`
- `vars_need_init_form` — `List[str]`

**`build_hints_collections(variable_desc)`**: Scans `types` list per variable → populates HintsCollections. Type mapping: `match` → vars_to_match, `computed` → vars_to_compute, `subdoc` → vars_as_subdocs, `form`/`file` → vars_need_init_form (triggers `init_*` hooks).

**`verify_hooks_exist(hints, logic_dir)`**: Scans plugin modules for hook implementations (debug route). Imports every `*.py` in `logic_dir` once — the loader's `{category}_{stem}` filter does **not** apply, so a hook is reported even when the engine would drop its module. Returns `{'found': {var: {hook: module}}, 'dropped': {category: [module]}, 'errors': {file: err}}`: `dropped` = modules lacking `{category}_{stem}()` (their hooks never fire — e.g. subdoc-only modules), `errors` = import failures.

---

### [context.py](context.py)

**Purpose:** Dynamically create `DataContext` dataclass from `descr.docx`.

**`make_context_class(descr_path, lang_path, variable_desc=None)`**: Creates class with fields from descr (only the field *names* are used). Accepts a pre-parsed `variable_desc` so the route's single descr.docx parse isn't repeated; parses here only when `variable_desc` is `None`. Values auto-converted via `_smart_convert()`.

**`DataContext.from_dict(data)`**: Classmethod to create instance from dictionary.

**Lifecycle:**
1. `make_context_class()` → DataContext class with fields
2. Instance creation → `__post_init__` fires → `_normalize_fields()` converts all fields
3. `_smart_convert()` passes through `RichText`, `Subdoc`, `InlineImage`, `BytesIO`, `list`, `dict`; converts rest to string

---

### [context_manager.py](context_manager.py)

**Purpose:** Thread-local DataContext class management (multi-pack).

**`load_data_context_for_pack(descr_path, lang_path, variable_desc=None)`**: Creates/reuses DataContext class per thread. Forwards `variable_desc` to `make_context_class` so the route's single descr.docx parse isn't re-opened here (ignored on the cached fast path).

**`get_data_context_class()`**: Get current DataContext class for thread.

**`invalidate_data_context()`**: Clear thread-local cache (test isolation).

**Thread safety:** `threading.local()` isolates DataContext classes across concurrent requests with different packs.

**Warning:** If intra-plugin imports occur (`from helper import X`), a `sys.modules` collision can happen across packs that ship same-named helpers. It's a per-process collision — thread count doesn't help. Avoid intra-plugin imports, or give helpers unique per-pack names.

---

### [renderer.py](renderer.py)

**Purpose:** Single-phase template rendering via docxtpl with deferred subdoc support.

**`render_templates(templates, context, store_dir, subdoc_funcs?)`**:
- Load each template directly as `DocxTemplate`
- Wrap `subdoc_funcs` as `DeferredSubdoc` (lazy evaluation at render time)
- `tpl.render(data_dict)` — Jinja2 triggers `DeferredSubdoc.__str__()` for placeholders
- Subdoc functions may use sandwich rendering (insert content with Jinja placeholders)
- Nested subdocs: a subdoc's content can contain its own subdoc placeholders, resolved inner-first

(The editor `.html` URL is produced by `routes/onlyoffice.py::generate_editor_html`, not here.)

---

### [match_helpers.py](match_helpers.py)

**Purpose:** Safe YAML loading + fuzzy matching.

**`load_yaml(path)`**: Path traversal guard; `.yaml` only; must be under `templates/`.

**`find_matches(text, yaml_dict, keys, use_fuzzy?, threshold?)`**: Exact substring first, then fuzzy (`partial_ratio >= threshold`).

---

### [form_handler.py](form_handler.py)

**Purpose:** Template variable analysis — the `/debug-vars` data source (form generation lives in `init.html` + hooks; no framework module runs on the /init request path).

**`analyze_template_variables(template_paths, variable_desc)`**: Compare template vars vs. `descr.docx` → the `/debug-vars` matrix. Takes the already-parsed `variable_desc` (the route parses descr.docx once and shares it — no re-open here).

---

### [subdoc_helper.py](subdoc_helper.py)

**Purpose:** Subdoc extraction with sandwich rendering (Jinja placeholders inside inserted content). Supports nested subdocs — bookmark content can contain subdoc placeholders that resolve inner-first.

**`DeferredSubdoc(func, tpl, data_dict, name)`**: Lazy-evaluated wrapper. Holds a subdoc function + rendering context. Only calls the function when Jinja2 stringifies the object during `tpl.render()`, or when attribute access is used (dict-of-Subdocs case). Cached after first evaluation. Exceptions caught and logged — returns empty string on failure.

**`create_subdoc_sandwich(tpl, elements, context_data, source_doc?, render_placeholders?)`**: Unified subdoc creation pipeline:
1. Create fresh `Document()`
2. Copy theme from `tpl` (prevent font mismatch)
3. Copy numbering + styles from `source_doc` (if provided)
4. Append elements to body
5. Optionally render Jinja placeholders via `DocxTemplate`
6. Return `Subdoc` via `tpl.new_subdoc()`

**`create_subdoc_from_bookmark(tpl, bookmark_name, source_path, render_context?)`**: Extract bookmarked content, then delegate to `create_subdoc_sandwich()`. The bookmark **start** is located in top-level paragraphs only — wrap the section from a paragraph (a `bookmarkStart` inside a table cell isn't found → empty subdoc). Stops extraction on EOF or another bookmark's start/end. If `render_context` is provided, placeholders in the bookmark content are rendered before creating the Subdoc — supports nested subdocs when context contains `DeferredSubdoc` values. An empty `render_context` skips the render pass, leaving `{{placeholder}}` literals in the result.

**`extract_table_as_subdoc(tpl, doc, table_idx, context_data, render_placeholders?)`**: Extract a table from a donor document as a Subdoc. Thin wrapper around `create_subdoc_sandwich()`. Returns empty Subdoc if index out of range.

**`_copy_theme_from_tpl(tpl, target_doc)`**: Copy raw theme XML from tpl to target — prevents font mismatch for theme-based font references.

**`_copy_numbering_and_styles(source_doc, target_doc)`**: Copy numbering part and styles — preserves list definitions and style references.

---

### [loader.py](loader.py)

**Purpose:** Dynamic plugin loading + template discovery.

**`load_plugins(logic_dir, category, extra_stems=None)`**: Finds `{category}_{module}` in `*.py`. Returns `{module_name: module}`. A module is kept if it exports `{category}_{module_name}()` or any of `extra_stems` — the compute load passes the subdoc var names, so a subdoc-only module (e.g. `report_annual.py` with only `report_annual()`) is no longer dropped; other modules are silently dropped.

**`find_templates(templates_dir, pattern)`**: Find template files matching glob pattern.

**`ensure_file(path, what)`**: Validate file exists.

**Cache:** Thread-local per `(logic_dir, category)`.

**Note:** Top-level plugins load by explicit file path (`spec_from_file_location`), not via `sys.path`, so a plugin can't `import` a sibling in its own logic dir — that raises `ImportError` (do intra-plugin imports package-scoped if ever needed). No process-global `sys.path` entry accumulates, so no cross-pack same-named-helper collision is possible.

---

### [computation.py](computation.py)

**Purpose:** Compute missing variables from DataContext.

**`merge_result(var, result, computed_values, subdoc_functions)`**: Flattens a `compute_*` return value. When it's a dict with callable values, keys with callables route to `subdoc_functions` and non-callables to `computed_values`; plain dicts / scalars / callables are stored as-is. Allows a single `compute_*` to return multiple variables at once.

**`compute_variables(cleaned_data, expected_vars, hints, modules, session=None)`**:
- Iterate missing variables — **compute vars first, in descr order** (`hints.vars_to_compute` order), so a `compute_<b>` reading `compute_<a>`'s output sees it when `a` is declared before `b`; the rest (subdoc / no-rule) follow in arbitrary order (they never feed a later `compute_*`)
- Two independent lookups gated by hints: `compute_<var>()` (immediate, if `computed` in types) and `<var>()` (deferred subdoc, if `subdoc` in types)
- A variable with both `computed` and `subdoc` types gets both lookups fired independently
- `session` dict passed through to compute plugins as kwarg (for file access via `get_file()`)
- Subdoc plugins receive `tpl` and `**kwargs` (full context); may pass `render_context` to `create_subdoc_from_bookmark()` for sandwich rendering
- **Error behavior** (`config.COMPUTE_ON_ERROR`, env `COMPUTE_ON_ERROR`, default `lenient`): no rule / compute exception → `lenient` stores a sentinel string (`"NO RULE for <var>"` / `"ERROR: ..."`) that renders verbatim into the document; `strict` logs and raises `RuntimeError` — the /generate safety net aborts (flash + redirect)
- Return `{var: value}` + `{var_name: func}` (for subdocs)

---

### [matching.py](matching.py)

**Purpose:** Matching orchestration for `match`-type variables.

**`run_matching(session, hints, logic_dir)`**:
- Uses `hints.vars_to_match` (pre-computed `Dict[var_name, yaml_key]`)
- For each, run `match_<var>(session, yaml_key)` plugin — the second arg is the column-4 key (the var name when the cell is empty)
- Plugins read uploaded files via `get_file(session, var_name)` from `session['uploaded_files']`
- Aggregate results into `matched_entities`
- Called unconditionally on POST /init (short-circuits when no match vars)

---

### [dynamic_ui.py](dynamic_ui.py)

**Purpose:** The init form's dynamic-UI block — generation, checksumming, and post-hash rendering of `init_*` hook output. This is the part of the init form built from init hooks (not the whole form).

**`generate_dynamic_ui_block(matched_entities, session, logic_dir, variable_desc=None)`**: Fire `init_<var>()` hooks for every `matched_entities` key (match results + empty-list `vars_need_init_form` entries), join their unrendered Jinja fragments. Returns the block's unrendered template ("" if nothing to render).

**`dynamic_ui_hash(template)`**: sha256 of the *unrendered* template (stable — carries no user input).

**`render_dynamic_ui_block(template, session)`**: Render the joined template with `session` in the context — fills the `{{ session.get(...) }}` / `{% if session.get(...) %}` placeholders the hooks emit. Called strictly after the hash guard. Empty-safe. Uses the app's Jinja env; `from_string` autoescape off, so the HTML structure passes through and hooks escape user-typed values with `| e`. Only `session` is exposed.

**`build_dynamic_ui_block(matched_entities, session, logic_dir, variable_desc=None)`** → `DynamicUIBlock`: generate + checksum in one step (render is lazy).

**`DynamicUIBlock`** (dataclass): `{template, ui_hash, rendered}` + `is_empty()` / `render(session)` (lazy) / `empty()`. The invariant that makes pre-population work lives here: hash the *unrendered* template, render strictly post-hash — a fresh pick can't move the hash (kills the extra init click), and a structure-change re-render refills picks (no value-loss). The route carries the hash in a hidden form field so it travels with the page.

**Hook contract — deterministic output:** `init_*` hooks must emit **deterministic** output — no timestamps, nonces, or other per-render randomness in the template they return. The convergence guard auto-submits only when the unrendered-template hash matches the form's; a non-deterministic hook would move the hash every render and the form would never settle (a UX wedge, not a server loop — each POST is a separate request).

### [inflection.py](inflection.py)

**Purpose:** `InflectedWord` — dict subclass for grammatical-case rendering.

**`InflectedWord(forms, cases=None)`**: Wraps a `{case: value}` dict so templates use `{{var.ge}}` (Jinja dot access → `__getitem__`, with `__getattr__` fallback for the six recognized cases `no/ge/da/ac/in/pre`).
- **Single-form expansion:** `len(forms) == 1` → all declared `cases` map to that value (abbreviations like "Дек-1", or vars with no nominative).
- **Bare `{{var}}`** → `__str__` → `[INFLECTED: specify case, e.g. {{var.no}}]` + warning log.
- **`{{var.<recognized-but-empty>}}`** → `""` + warning log.
- **`{{var.<non-case>}}`** → `__getattr__` raises `AttributeError` (preserves `hasattr` semantics; won't poison `_smart_convert`'s file-like probes).
- **Caveat:** subclasses `dict`, so `{{var.keys}}`/`{{var.items}}` resolve to dict methods. Use declared case codes only.

Stateless, no DB access.

---

### [inflection_db.py](inflection_db.py)

**Purpose:** SQLite-backed inflection dictionary (per-thread connection, WAL, background save queue).

**Storage:** `app/inflection_data/inflections.db`. Three tables:
- `inflection_forms` — one row per (word, case). `word_id` groups a word's forms (not the PK; surrogate `id` is). `UNIQUE(case_code, form_value_lower)` stops two words claiming the same form; `form_value_lower` = `casefold()` for indexable case-insensitive lookups (`idx_lookup`); `display_key` = casefolded `_display_key(form_value)` (leading non-alphanumerics stripped) — the browse/search key, stored so the letter filter, sort and prefix match run in SQL (one-time migration backfills it on pre-existing DBs).
- `inflection_conflicts` — logged save conflicts for admin review (`conflict_type`: `anchor` / `split` / `collision`).
- `words` — the `word_id` sequence (`id INTEGER PRIMARY KEY AUTOINCREMENT`). Kept **separate** from `inflection_forms.id` (a global counter across every case row): allocating `word_id` as a form row's `id` could land on an id an existing word already owns once the two counters diverge (varying case counts, deletes, or an older seeded layout), silently merging a new word into it. A one-time migration backfills `words` with every existing `word_id` and bumps the counter past `MAX(word_id)`.

**Connections:** one per thread, cached in `threading.local` (PRAGMAs + schema on first use) — the AJAX lookup fires per keystroke. `close_connection()` closes the thread's conn (test isolation / DB-path swap). Writes run under `_write()` — commit on success, rollback on error, so a long-lived conn never carries an open transaction into the next call.

**Public API:**
- `lookup_by_form(case_code, form)` — exact match → all forms for that word (AJAX auto-fill).
- `save_word(forms)` — append-only merge; returns `word_id` (or `None` if `len(forms) <= 1`).
- `replace_word(word_id, forms)` — admin edit / conflict merge (delete + reinsert; colliding forms logged, never overwrites another word).
- `delete_word(word_id)`, `delete_conflict(conflict_id)`, `get_word(word_id)`, `list_words(letter, page)`, `search_words(query)`, `get_conflicts(page)`, `get_conflict_with_words(id)`.
- `enqueue_save(forms)` — thread-safe background save (fire-and-forget from `/generate`); skips words the dictionary already knows fully (one indexed check — `/generate` fires this on every run).
- `list_words` / `search_words` push filter + sort + pagination into SQL (headword subquery + `display_key` / `form_value_lower` LIKE) — only the requested page is materialized.

**Save logic (3-step, append-only):** (1) exact match on `form_value_lower` → merge missing cases; (2) nested LIKE (per-word stem prefix, escaped, `LIMIT 50`) + fuzzy rank (thresholds `0.85` anchor / `0.7` LIKE) → merge; (3) INSERT as new word (`word_id` from the `words` sequence — see Storage). Existing values are never overwritten by user submissions — corrections go through the admin UI.

**Headword / display key:** a word's browse/sort name is its `no` form, else first case-ordered form; leading non-alphanumerics (quotes/guillemets) are stripped for letter grouping and search (`"ООО Ромашка"` files under О, not a symbol tile). The letter bar and the letter filter key off the same stored `display_key`, so every tile shows its words.
