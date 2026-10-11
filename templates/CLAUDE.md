# templates/CLAUDE.md

Template files and configuration for the document generation system.

---

## Single Source of Truth: `descr.docx`

Authoritative configuration defining all variables, their types, and behavior.
**One `descr.docx` per pack, one active per workflow cycle.**

### Table Structure

| Col | Required | Description |
|-----|----------|-------------|
| 0 | Yes | Variable name (`user_name` or `{{user_name}}`) |
| 1 | Yes | Human-readable description |
| 2 | Yes | Show in form (`❌` = hide, else show) |
| 3 | Yes | Type: `text`, `enum`, `bool`, `match`, `computed`, `subdoc`, `form`, `file`, `table` (comma-separated) |
| 4 | Conditional | Type-specific (see below) |

**Multi-type support:** Column 3 can contain multiple comma-separated types (e.g., `match,computed,subdoc`). Parser splits into a `types` list; hints builder categorizes each type independently.

**Column 4 — options:**
- **Typed form** (any number of types): `<type>:<value>[;<type>:<value>]*` — e.g. `enum:sex_options`, `match:universities`, `text:no,ge,da`, or `enum:sex_options;text:no,ge` for an `enum,text` var.
- **Bare form** (single-type vars only): the cell is the value for that type — e.g. `sex_options` on `enum`, `no,ge,da` on `text`. A bare cell on a multi-type var is an authoring error (logged, no options set).
- **Value format per type:**
  - `enum`: dot-path into `language_rules.yaml` resolving to a list
  - `match`: YAML filename the `match_<var>` plugin searches (passed as the plugin's second arg; defaults to the var name when empty)
  - `text`: comma-separated inflection case codes (e.g. `no,ge,da,ac,in,pre`) — enables grammatical-case rendering `{{var.case}}`
- Other types (`bool`, `computed`, `subdoc`, `form`, `file`, `table`) have no options — a pair for one is ignored.
- Parsed result: `var_meta["options"]` = per-type dict (`{"enum": [...]}`, `{"match": "key"}`, `{"text": [...]}`); `None` when the cell is empty.

**Parser behavior:**
- Rows with < 4 columns are skipped
- Empty variable names are skipped (braces stripped)
- Cell errors degrade-and-log, never raise (missing/invalid enum path → `{"enum": []}`; unknown case codes dropped)
- Comma-separated types split into a `types` list for membership checking

*Parser: [app/logic/parser.py](../app/logic/parser.py) | Hints: [app/logic/hints_builder.py](../app/logic/hints_builder.py)*

---

## Pack Structure

**Root pack:** `templates/` with `descr.docx`, `language_rules.yaml`, `template_*.docx`, optional `logic/`

**Subdirectory pack:** `templates/<name>/` with own `descr.docx` (overrides root vars), optional `language_rules.yaml`, `logic/`

**Pack description:** First paragraph in `descr.docx` before table → shown in `/select` UI. See `extract_pack_description()` in [parser.py](../app/logic/parser.py).

---

## Variable Types

| Type | Purpose | Form Field | Logic Hook | Hints Collection |
|------|---------|------------|------------|-----------------|
| `text` | Free text / computed string | Text input | `compute_<var>()` | None |
| `enum` | Predefined options from YAML | Dropdown select | None | None |
| `bool` | Yes/no toggle | Checkbox | None | None |
| `match` | Auto-match entities from upload | Checkbox group | `match_<var>()` | `vars_to_match` |
| `computed` | Derived from other variables | Hidden | `compute_<var>()` | `vars_to_compute` |
| `subdoc` | Subdocument from bookmark (via YAML config) | Hidden | `<varname>()` | `vars_as_subdocs` |
| `form` | Custom UI via init hook | Custom | `init_<var>()` | `vars_need_init_form` |
| `file` | File upload + custom UI | Custom | `init_<var>()` | `vars_need_init_form` |
| `table` | **Not read by the framework** — user-side marker, see the note below | Selector drawn by `init_table` | None | None |

**The `table` type is inert — nothing dispatches on it.** It appears in `_KNOWN_TYPES` ([parser.py](../app/logic/parser.py)) only so the options column can recognise a `table:` prefix; no hints collection is built from it. All table behaviour lives in the user plugin [logic/table.py](../logic/table.py): the hooks fire from the plain `table` variable's own `match, computed` types, and the slots are found by **name** — `init_table` scans `descr.docx` for variables starting with `table_`. Add a `table_4` row and a fourth slot appears in the mapping UI; rename `table_1` to `personal_1` and it disappears, whatever its type cell says. Donor tables are discovered only in uploads to the file variables listed in `TABLE_SOURCE_FILES` (`['cv']`).

Not deprecated — relocated. Tables started as a framework feature: a pre-pass in `generator.py` (`prepare_tables_for_generation()` + `insert_tables_into_document()`) spliced donor tables in at markers *before* docxtpl ran. Commit `264e7a3` ("Tables processing refactor: subdoc-based tables, `merge_result()`") moved them onto the `Subdoc` path inside the plugin, so the word stayed in the vocabulary and lost the behaviour. See [templates/DEMO.md](DEMO.md).

**Multi-type:** A variable can have multiple types (e.g., `match,computed,subdoc`). Each type fires its own hook independently.

**Inflection (text only):** A `text` variable lists case codes in column 4 (e.g. `no,ge,da`); the form then renders one input per case and templates use `{{var.case}}`. See [app/logic/INFLECTION.md](../app/logic/INFLECTION.md).

---

## Word Templates (`template_*.docx`)

Document templates with `{{variable}}` placeholders. Variables are extracted from:
- `word/document.xml`
- `word/header*.xml`, `word/footer*.xml`
- `word/footnotes.xml`, `word/endnotes.xml`

*Extractor: [app/logic/extractor.py](../app/logic/extractor.py)*

---

## YAML Configuration

### `language_rules.yaml`

Language-specific data for `enum` types and computation logic.

### Custom YAML Files

`match` type variables reference YAML files for entity data. Structure:
```yaml
entity_key:
  short: "Short name"
  full: "Full name"
  # Additional fields as needed
```

> **Note:** The `university.yaml` file is demo-specific example data. Replace with your own business entity YAML files. The matching system is schema-agnostic - it only requires identifiable fields (typically `short`/`full` for matching). Additional fields are passthrough to your compute plugins.

*Matcher: [app/logic/match_helpers.py](../app/logic/match_helpers.py)*

---

## Adding New Variables

1. **Add to `descr.docx`:** New row with variable name, description, visibility, type (comma-separated for multi-type)
2. **Add to template:** Insert `{{varname}}` in `template_*.docx`
3. **Optional computation:** Create logic module with `compute_<var>()` (requires `computed` in type)
4. **Optional YAML data:** Add to `language_rules.yaml` or custom YAML
5. **Optional init hook:** Create `init_<var>()` for custom UI (requires `form` or `file` in type)

---

## File Summary

| File | Purpose |
|------|---------|
| `descr.docx` | Variable definitions (SINGLE SOURCE OF TRUTH) |
| `template_*.docx` | Document templates |
| `university.docx` | Source document for subdoc via bookmark extraction |
| `language_rules.yaml` | Enum options, matching data |
| `logic/*.py` | User plugins (compute, match, init) |

---

## Demo Examples

See [DEMO.md](DEMO.md) for demo plugin documentation (university matching, appeal generation, etc.).

---

## Known Limitations

- **Intra-plugin imports:** Plugins importing from each other within a pack can cause `sys.modules` collisions across packs. Current demo plugins don't use this pattern. Issue disappears with Gunicorn `--threads 1`.

---

## Note on `logic/` Subdirectory

This directory is a podman mount target for `./logic:/app/templates/logic`. User plugins live in `../logic/` and mount over it at runtime.