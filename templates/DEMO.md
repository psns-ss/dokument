# Demo Plugins

Sample implementations in `../logic/` demonstrating the plugin system. These are mounted to `/app/templates/logic/` in Docker.

**Note:** Replace with your own business logic. Structure and naming conventions should be preserved.

---

## Compute Modules

### `birth_year.py` - Age to Birth Year

**Variable:** `birth_year` (type: `text`, hidden from form)

```python
def compute_birth_year(user_age, **kwargs) -> str:
```

Computes birth year from user's age: `current_year - age`.

**Dependencies:** None

---

### `appeal.py` - Gendered Formal Address

**Variable:** `appeal` (type: `text`, hidden from form)

```python
def compute_appeal(sex, language='ru', **kwargs) -> str:
```

Generates formal address suffix based on gender (`sex` field).

**Dependencies:**
- `language_rules.yaml` - Contains `sex_options` and `appeals` mappings

**Data structure:**
```yaml
sex_options: ["Мужской", "Женский"]
appeals:
  ru:
    formal:
      male: "ый"
      female: "ая"
```

---

## Match + Init + Compute + Subdoc: University Example

### `university.py` - Full Workflow Demo

Demonstrates all plugin types in one module.

#### 1. Matching (`match_university`)

**Variable:** `university` (type: `match`)

```python
def match_university(session, yaml_key) -> List[str]:
```

Scans uploaded DOCX tables for university names, matches against `university.yaml`.

**Returns:** List of matched keys (e.g., `['msu', 'spbu']`)

**Dependencies:**
- `university.yaml` - University database
- `match_helpers.find_matches()` - Fuzzy matching utility

---

#### 2. UI Generation (`init_university`)

```python
def init_university(session, matched_list, variable_desc=None) -> str:
```

Generates HTML form for user to order matched universities and add graduation years.

**Returns:** HTML fragment injected into form

---

#### 3. Computation (`compute_university`)

```python
def compute_university(**kwargs) -> List[Dict[str, Any]]:
```

Assembles final university data from form inputs (ordering + years).

**Returns:** List of dicts with full university data

---

#### 4. Subdocument (`university_historical`)

**Variable:** `university_historical` (type: `subdoc`)

```python
def university_historical(tpl, **kwargs) -> Dict[str, Subdoc]:
```

Extracts bookmarked sections from `university.docx` for each selected university.

**Returns:** `{university_key: Subdoc_object}` for docxtpl rendering

**Dependencies:**
- `university.yaml` - Bookmark names per university
- `university.docx` - Source document with bookmarked sections
- `subdoc_helper.create_subdoc_from_bookmark()` - Extraction utility

---

## File Upload + File-Count Limit: Sticker Example

### `sticker.py` — Capped multi-file upload + SVG insertion

Demonstrates the **file-count limit**: a `file` var declares a max upload count in the
descr options column (`file:<N>`), and the `init` hook enforces it client-side. The sticker
is the showcase — it also converts the accepted SVGs to PNG and splices them side-by-side
into the document after the signature.

**Variable:** `sticker` (type: `file,computed`, hidden from form)

#### 1. Init — the upload-count cap (the feature)

```python
def init_sticker(session, matched_list, variable_desc=None) -> str:
```

Reads `variable_desc['sticker']['options']['file']` (the `file:<N>` value) and renders a
`multiple` file input plus a JS `change` check: an over-limit batch is cleared with a
re-select alert. No cap declared → the input is uncapped. No `accept` — rogue files are
allowed in; the render hook sorts them out. This half needs no extra dependencies.

#### 2. Compute — SVG → PNG → subdoc (demo flourish)

```python
def compute_sticker(**kwargs) -> dict:
```

Content-sniffs the uploads for real SVGs (drops the rest), converts up to two to PNG at
natural size, and returns `{'sticker': <deferred assembler>}` that splices them side-by-side
into the `{{p sticker}}` slot (inside the `{%p if signature %}` block). No renderable SVGs
→ `{}` → the slot renders empty.

**Dependencies (demo half only — NOT in `requirements.txt`):**
- `cairosvg` — SVG→PNG conversion.
- `libcairo2` — cairosvg's native backend.

Both are installed **in the running container via `exec`** only (kept out of the published
requirements/Dockerfile). A container **rebuild wipes them** — re-run after any `up -d --build`:

```bash
docker compose exec webserver sh -c "apt-get update && apt-get install -y --no-install-recommends libcairo2 && rm -rf /var/lib/apt/lists/*"
docker compose exec webserver pip install --no-cache-dir cairosvg
```

Without them the init cap still works; only the SVG insertion degrades (logged, slot renders empty).

**Sample uploads:** `tests/fixtures/sticker_pelican_bike.svg`, `sticker_pelican_coffee.svg`.

**Test:** the init cap is covered by `tests/test_user_logic/test_sticker.py`. The compute
half (SVG→PNG + subdoc) is demo-only and untested by design.

---

## Table processing pipeline: Donor Tables Mapped Into Placeholders

### `table.py` — discovery, mapping UI, deferred extractors (three hooks)

| Piece | Role |
|-------|------|
| `table` in `descr.docx`, types `match, computed` | the only variable the engine reads: fires `match_table` on POST /init, `compute_table` on /generate, and `init_table` alongside the match result |
| `table_1`, `table_2`, `table_3`, types `table` | **slots** — found by name prefix (`[v for v in variable_desc if v.startswith('table_')]`); the type cell itself is inert |
| `source.docx` | the donor file the user uploads to `cv` — ФИО / Возраст / Пол, образование, опыт работы |
| `{{p table_2}}` in a template | where the chosen donor table lands |

#### 1. Discovery (`match_table`)

Walks the uploads of every file variable named in `TABLE_SOURCE_FILES` (`['cv']` — the
list to extend for another donor source), takes up to 3 rows as a preview, and returns one
entry per table under a composite key `file_var:file_idx:table_idx` (e.g. `cv:0:2`).

#### 2. Mapping UI (`init_table`)

One block per discovered table with its preview and a `<select>` choosing the slot
("Не использовать" is allowed). Hidden inputs carry the composite keys back, and every
`table_*` slot gets a hidden empty default — so an unmapped slot arrives as an empty
value rather than a missing one, and the template renders blank instead of the `NO RULE`
sentinel.

#### 3. Extraction (`compute_table`)

Returns `{slot_name: extractor}`, flattened by `merge_result()` into the subdoc pipeline.
Each extractor is deferred: at render time it opens the donor and calls
`extract_table_as_subdoc(..., render_placeholders=True)`, so placeholders **inside the
donor table** (`{{user_name}}` in `source.docx`) resolve against the live context.

**Template rule:** keep `{{p table_N}}` alone in its paragraph. The tag paragraph is
consumed either way — an empty or undefined `{{p …}}` **deletes** it, where an inline
`{{ … }}` leaves a blank line — and a soft break inside the tag paragraph is dropped.

**The `table` type cell does nothing.** No hints collection is built from it; it exists in
`_KNOWN_TYPES` (will be refactored later) only so the options column can parse a `table:` prefix. The word is a
leftover of when tables were a framework feature (a pre-pass in `generator.py` spliced
donor tables in at markers before docxtpl ran); `264e7a3` moved the work into this plugin.
Full note: [templates/CLAUDE.md](CLAUDE.md), "The `table` type is inert".

---

## Demo Data Files

| File | Purpose |
|------|---------|
| `university.yaml` | University database (names, bookmarks, metadata) |
| `university.docx` | Source document with bookmarked university histories |
| `source.docx` | Donor document for table slots — 3 tables, uploaded to `cv` |

---

## YAML Structure Example

`university.yaml`:
```yaml
moscow_state_university:
  bookmark: moscow_state_university
  short: "МГУ"
  full: "Московский государственный университет"
  historical: "История МГУ..."
  location: "Москва"
  founded: 1755
  specialties:
    - "Прикладная математика"
    - "Физика"
```

**Field Reference:**

| Field | Required | Purpose |
|-------|----------|---------|
| `bookmark` | Yes | Bookmark name in `university.docx` for subdoc extraction |
| `short` | Yes | Short name used for matching against uploaded documents |
| `full` | Yes | Full name displayed in dropdown UI |
| `historical` | No | Historical description (demo data) |
| `location` | No | City/location (demo data) |
| `founded` | No | Founding year (demo data) |
| `specialties` | No | List of specialty areas (demo data) |

> **Note:** Fields marked "No" are demo-specific. Your custom YAML files can define any schema needed for your business logic. The matching system only requires identifiable fields (typically `short`/`full`).

---

## Bool Variables (No Plugin Required)

**Variable:** `type: bool` in `descr.docx`

Bool variables render as checkboxes in the form. No compute/match/init plugin needed.

**Template usage:**
```jinja2
{% if signature == 'true' %}
С уважением,
_________________ / Организация
{% endif %}
```

**Test:** See `tests/test_user_logic/test_signature.py`

---

## Adding Your Own Plugin

1. Create `../logic/myplugin.py`
2. Implement function(s) following naming conventions:
   - `compute_<var>(**kwargs)` for derived values
   - `match_<var>(session, yaml_key)` for entity matching
   - `init_<var>(session, matched_list, variable_desc=None)` for UI generation
   - `<varname>(tpl, **kwargs)` for subdocuments
3. Update `descr.docx` with variable definition

*See: [../logic/CLAUDE.md](../logic/CLAUDE.md) for full API reference*
