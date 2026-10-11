# logic/CLAUDE.md

User plugins directory. Mounted at runtime via Docker: `./logic:/app/templates/logic`.

**Per-pack plugins:** Each pack can have its own `templates/<pack>/logic/` that overrides/fallbacks to root `logic/`.

---

## Plugin Categories

Plugins are discovered by `load_plugins(logic_dir, category)` and expected to export a function named `{category}_{module_name}`.

Which hooks fire for each variable is determined by `HintsCollections` (built from the `types` list in `descr.docx`).

### `match_*` — Fuzzy Matching

**Purpose:** Extract entities from uploaded files.

**Signature:** `match_<var_name>(session, yaml_key) → List[str]`

**Example:** `match_university(session, yaml_key)` → `["mgu"]`

**Data source:** the `yaml_key` argument — the column-4 value (the YAML filename to search, e.g. `universities`; defaults to the var name when the cell is empty).

**File access:** Read uploaded files via `get_file(session, var_name)` from `session_manager`:
```python
from session_manager import get_file

def match_university(session, yaml_key):
    cv_paths = get_file(session, 'cv')
    if not cv_paths:
        return []  # no file uploaded
    doc = Document(cv_paths[0])
    # ... extract and match ...
```

**Hints:** Variable must have `match` in its `types` list.

---

### `compute_*` — Derived Variables

**Purpose:** Compute variables not provided by the user.

**Signature:** `compute_<var_name>(**kwargs, session) → Any`

**Parameters:**
- `**kwargs` — form data + already-computed variables passed as keyword args. Plugins typically declare needed vars as positional params (e.g., `def compute_appeal(sex, language='ru', **kwargs)`) or use `kwargs.get('var_name')`.
- `session` — Flask session dict, always passed as a kwarg. Use `kwargs.get('session')` to access uploaded files, session_id, etc.

**Return values:**
- **Scalar** (str, int, list, etc.) → stored as computed value for the variable
- **Dict** → flattened by `merge_result()`: keys with callable values become deferred subdoc functions; keys with non-callable values become computed scalars. This allows a single `compute_*` to return multiple variables at once (see `table.py`).

**Example:** `compute_birth_year(user_age=30)` → `"1996"`

**Called:** During generation, for missing/empty variables.

**Hints:** Variable must have `computed` in its `types` list.

---

### `init_*` — UI Generation

**Purpose:** Generate custom UI elements (file uploads, match result selectors, wizards).

**Signature:** `init_<var_name>(session, matched_list, variable_desc=None) → str`

**Parameters:**
- `session` — Flask session dict (access uploaded files via `get_file(session, var_name)`)
- `matched_list` — results from `match_*` (for match+form vars) or empty list `[]` (for file-only vars, enriched in POST /init)
- `variable_desc` — dict of all variable metadata from `descr.docx`. Use to discover related variables (e.g., `table_*` slots). Optional — default `None`.

**Returns:** A Jinja **template** string to inject into the form. The framework joins all hooks' output, hashes it (unrendered — stable), then renders it post-hash via `render_dynamic_ui_block()` before embedding in `init.html`. See "Pre-populate from session" below.

**Called:** GET /init (with empty `matched_list`) and POST /init (with match results or empty list).

**Pre-populate from session (Jinja snippets):** an `init_*` hook that renders user-editable fields (text inputs, selects) emits them with the value/`selected` as a **Jinja placeholder over the session** — not read in Python and baked into the HTML. The framework hashes the *unrendered* joined template (it carries no user input, so a fresh pick doesn't move `ui_hash` — no extra init-page click) and renders it post-hash via `render_dynamic_ui_block()`, which fills `{{ session.get('field') }}` / `{% if session.get('field') %}selected{% endif %}` from the session. A structure-change re-render (e.g. a file hook silencing once its upload lands) refills the picks from the session — no value-loss.

Emit each Jinja tag as a **plain (non-f) string** and interpolate the Python values by concatenation (plain strings keep `{% %}`/`{{ }}` literal; the outer f-string drops the tag into the HTML). Escape user-typed values with `| e` (the snippet env autoescapes off, so the HTML structure passes through). Only `session` is exposed to the template — a derived value not in the session must be stashed there during matching (like `cv_years`).

**All hook output is Jinja-parsed:** the joined output of every hook goes through one `from_string()`, so static HTML/JS (the file-upload hooks) must not contain literal `{{`/`{%`/`{#}`. Hooks with no session fields (e.g. `init_cv`, `init_sticker`) return plain HTML and pass through unchanged. See `init_university` (`year_{i}`, `university_order[{i}]`) and `init_table` (`table_map[{idx}]`).

**Hints:** Variable must have `form` or `file` in its `types` list.

**File-count limit (user-side):** To cap how many files a `file` var accepts, declare `file:<N>` in the descr options column (column 4). The parser yields `options['file'] = N`, and the `init_<var>` hook reads it to render a `multiple` input plus a JS `change` check — an over-limit batch is cleared (the FileList can't be trimmed) with a re-select message. The core engine parses `file:<N>` but does **not** enforce it; the whole limit is user-side. There is no content filtering at the picker (rogue files are allowed in) — any content check belongs in the render hook. See `sticker.py` (demo) and [templates/DEMO.md](../templates/DEMO.md).

---

### `<var_name>()` — Subdocument Extraction

**Purpose:** Extract bookmarked sections as `Subdoc` / `DeferredSubdoc` objects for deferred rendering.

**Signature:** `<var_name>(tpl, **kwargs) → Dict[str, Subdoc]`

**Parameters:**
- `tpl` — `DocxTemplate` instance (used to create subdocs via `tpl.new_subdoc()` or `create_subdoc_from_bookmark()`)
- `**kwargs` — full rendering context (all variables, computed values, etc.)

**Called:** During rendering. The returned `Subdoc` objects are wrapped in `DeferredSubdoc` for lazy evaluation — they render on first `str()` call (Jinja2 template rendering) and cache the result. Nested subdocs are supported (a bookmark can contain another subdoc placeholder).

**Hints:** Variable must have `subdoc` in its `types` list.

**Note:** No `subdoc_` prefix — the function is named after the variable itself (e.g., `university_historical()`).

**Sandwich rendering:** Bookmarks in source DOCX can contain Jinja placeholders (e.g., `{{sex_text}}`). Pass `render_context` to `create_subdoc_from_bookmark()` to render them before Subdoc creation:

```python
from logic.subdoc_helper import create_subdoc_from_bookmark

def university_historical(tpl, **kwargs):
    render_ctx = kwargs  # full context — placeholder keys determined by bookmark content
    return {
        'mgu': create_subdoc_from_bookmark(tpl, 'mgu_exercise', src_path, render_context=render_ctx)
    }
```

---

## Variable Types and Hook Mapping

| `types` in `descr.docx` | Hook fired | When |
|-------------------------|------------|------|
| `match` | `match_<var>()` | POST /init (matching phase) |
| `computed` | `compute_<var>()` | /generate (missing variables) |
| `form` | `init_<var>()` | GET/POST /init (UI generation) |
| `file` | `init_<var>()` | GET/POST /init (file upload UI). Files handled by framework: saved to `document_store/session_id/`, tracked in `session['uploaded_files']`. Access via `get_file(session, var_name)`. |
| `subdoc` | `<var>()` | /generate (rendering phase, deferred) |

A variable can have **multiple types** (comma-separated in column 3), e.g., `match,form` fires both `match_*` and `init_*`.

**`table` is a marker, not a switch.** The engine assigns it no meaning — it is listed in `_KNOWN_TYPES` (`parser.py`) purely so the options column can parse a `table:` prefix. Table handling lives entirely in this plugin (`table.py`: `match_table` + `init_table` + `compute_table`), and it is gated by **name, not type**: `init_table` reads `variable_desc` for variables starting with `table_` to build the slots, and the hooks themselves are fired by the `table` variable's own `match, computed` types. So the `table` cells on `table_1/2/3` in the demo `descr.docx` change nothing; the prefix does. Not deprecated — this type was never removed, it was moved out of the framework (pre-pass table splicing in `generator.py` → subdoc-based plugin in `264e7a3`). New packs may prefer the generic `match,form,computed` combo; the name-prefix convention is what `table.py` requires either way.

---

## Plugin Structure

**Single file:** Each plugin is one `.py` file exporting one or more functions.

**Multi-hook modules:** A single file can export any combination of hook types — they're discovered independently by the framework per category (`load_plugins(logic_dir, 'match')`, `load_plugins(logic_dir, 'compute')`, etc.). Common patterns:

| Pattern | Example | Hooks exported |
|---------|---------|----------------|
| Compute only | `birth_year.py` | `compute_birth_year()` |
| Compute + subdoc | `university.py` | `compute_university()` + `university_historical()` |
| Match + init + compute | `table.py` | `match_table()` + `init_table()` + `compute_table()` |
| Init only | `cv.py` | `init_cv()` |

**Dict-of-callables return pattern:** `compute_*` plugins can return a dict whose values are callables. `merge_result()` in `computation.py` detects this and routes callables to the subdoc pipeline, while non-callable values become computed scalars. See `compute_table()` in `table.py` for the reference implementation.

**Example:** `compute_birth_year.py`:
```python
from datetime import datetime

def compute_birth_year(user_age, **kwargs):
    try:
        current_year = datetime.now().year
        age = int(user_age)
        return str(current_year - age)
    except (ValueError, TypeError):
        return "Invalid age"
```

**Note on positional params:** Plugins may declare required inputs as positional params (e.g., `compute_appeal(sex, language='ru', **kwargs)`). The framework passes all form data + computed values as kwargs, so positional params are matched by name.

**Cross-plugin imports:** Avoid `from other_plugin import X` — can cause `sys.modules` collisions across packs. Use unique module names if needed.

---

## Demo Plugins

See [templates/DEMO.md](../templates/DEMO.md) for examples:
- `birth_year.py` — Compute birth year from age
- `appeal.py` — Generate appeal letter (positional params pattern)
- `university.py` — Match universities, generate UI, subdoc extraction
- `cv.py` — File upload init hook (init-only plugin)
- `table.py` — Table discovery, mapping UI, deferred extractors (three-hook module)

---

## Pack-Specific Plugin Notes

**`templates/pack1/logic/`:** Pack1 has its own `university.py` with a **different `match_university()` signature** (`match_university(session, uploaded_path, lang_rules)` with an extra `uploaded_path` param). This is **incompatible** with the framework's call convention (`match_{var}(session, yaml_key)`) and will fail at runtime. Use the root `logic/university.py` as the reference implementation.

Pack1's `university_historical()` also **omits `render_context`** when calling `create_subdoc_from_bookmark()`, so it does not support sandwich rendering. Update to pass `render_context=kwargs` for consistency.