# app/routes/html_helpers/CLAUDE.md

HTML templates for Flask routes. All rendered via Jinja2 with autoescaping.

---

## Templates

### [init.html](init.html)

**Purpose:** Initialization form with dynamic UI fragments from init hooks.

**Context:**
- `variable_desc` - Variable metadata from descr.docx
- `session_data` - User form values
- `dynamic_ui` - HTML fragments from `init_<var>()` hooks (match results, file uploads, custom forms)
- `ui_hash` - Hash for convergence guard (step 2 → auto-submit)

**Key sections:**
- Form fields loop (text, enum, bool native types)
- Dynamic UI fragments — rendered from `init_<var>()` hook output
- Hash-based convergence guard for auto-submit (hidden `ui_hash` field)

---

### [select.html](select.html)

**Purpose:** Pack selection UI.

**Context:**
- `packs` - List of pack info dicts (`identifier`, `description`, `is_disabled`, `error`, `is_duplicate`, `template_count`)
- `error` - Error message (if any)

**Key sections:**
- Pack cards with radio buttons
- Disabled pack indicators
- Error display

---

### [ready.html](ready.html)

**Purpose:** Document links after generation.

**Context:**
- `doc_links` - List of `{name, editor, index}` dicts

**Key sections:**
- Document download links
- OnlyOffice editor links

---

### [auto_submit.html](auto_submit.html)

**Purpose:** Hidden-form POST to /generate (when dynamic UI is empty or hash has converged).

**Context:**
- `action_url` - URL for /generate

**Key sections:**
- Auto-submit JavaScript (body onload submits the empty form — data lives in the session)

---

### [editor_template.html](editor_template.html)

**Purpose:** OnlyOffice editor wrapper.

**Context:**
- `title` - Document title
- `key` - Unique revision key
- `url` - Public URL to document

**Key sections:**
- OnlyOffice JavaScript API integration
- Document loading configuration

---

### [debug-vars.html](debug-vars.html)

**Purpose:** Template author's checklist — vars found in templates vs descr.docx, hooks per var.

**Context:**
- `packs` / `active_pack` / `pack_description` - pack selector (disabled packs greyed with error)
- `var_rows` - per var: `name`, `description`, `types`, `hooks` (`[{name, fn, module}]` — module None = missing), `wiring` (`[{module, hooks [fn]}]`), `missing_hooks` (`[fn]`)
- `unexpected_vars` - found in templates, not in descr.docx
- `templates` - per template: `{name, found (set), error?}`
- `dropped` - `{category: [modules the engine's loader drops]}`
- `hook_errors` - `{filename: import error}`
- `stats` - `{templates, expected, found, unexpected, hooks_wired, hooks_total}`

**Key sections (UI in Russian):**
- Pack selector (auto-submit on change)
- Stat plaques are quick filters (vanilla JS): Ожидаемые = all rows (default), В шаблонах = rows found in ≥1 template, Неожиданные (rendered only when non-zero) = scroll to the unexpected table, Хуки = rows with ≥1 wired hook; the affected table glows cold-blue for ~0.5s on each switch
- Main matrix: var × templates + type; hover the var name → description + real hook function names (CSS tooltip, no JS)
- Column sorting (vanilla JS, main matrix + unexpected table): rows render in descr.docx order by default; clicking a header cycles that column's order — ascending (↑) → descending (↓) → back to descr order (no arrow). One column at a time, Cyrillic-aware (`localeCompare`), ties keep descr order; the hover tooltip is stripped from the sort key
- Unexpected-vars table
- Wiring graph container: var → module.py → hooks (missing in red)
- Loader-drop / import-error warnings

---

### [reset.html](reset.html)

**Purpose:** Session reset confirmation — auto-redirects to `url` after a 1 s beat.

**Context:**
- `url` - Redirect URL (e.g., `/init`)

---

### [debug_inflections.html](debug_inflections.html)

**Purpose:** Inflection admin — browse/search the dictionary.

**Context:**
- `words` - Page of words (or search results)
- `query` - Active search query
- `letter` - Active letter filter
- `page` - Current page
- `letter_counts` - `{letter: count}` for the filter bar (Cyrillic → Latin → digits order)

---

### [debug_conflicts.html](debug_conflicts.html)

**Purpose:** Inflection admin — save-conflict log.

**Context:**
- `conflicts` - Page of conflict entries
- `page` - Current page

---

### [edit_inflection.html](edit_inflection.html)

**Purpose:** Inflection admin — edit a word / add a new one; also the conflict-merge form.

**Context:**
- `word` - The word being edited (`word_id`, `forms`, `nominative`)
- `conflict` / `new_word` - Conflict-merge context (None when editing normally)
- `case_rows` - Per-case form rows (`kind`: `simple` or `conflict`)
- `case_names` - `{code: case name}` labels
- `is_new` - True on the "add word" page
