# Word Inflection (grammatical cases)

`text` variables can declare grammatical cases in `descr.docx` column 4 (e.g. `no,ge,da,ac,in,pre`; the typed form `text:no,ge,da` for multi-type vars). The form renders one input per case; templates reference a case with `{{var.ge}}`, `{{var.da}}`, etc.

## Case codes

| Code | Case | Russian |
|------|------|---------|
| `no` | Nominative | именительный |
| `ge` | Genitive | родительный |
| `da` | Dative | дательный |
| `ac` | Accusative | винительный |
| `in` | Instrumental | творительный |
| `pre` | Prepositional | предложный |

## End-to-end flow

1. **Config** — `descr.docx` column 4 lists the cases for a `text` var → parser stores `var_meta["options"]["text"]` (see [templates/CLAUDE.md](../../templates/CLAUDE.md)).
2. **Form** (`routes/html_helpers/init.html`) — one input per case (`name="var__case"`). Blur auto-fill calls AJAX `/inflection/lookup` to fill empty siblings from the DB; submit is intercepted to await in-flight lookups (2s cap).
3. **POST /init** (`routes/init.py`) — `var__case` scatter keys are collected into `session[var] = {case: value}` and the scatter keys are popped (replace, not merge).
4. **POST /generate** (`routes/generate.py`) — each inflected dict in `final_data` is wrapped as `InflectedWord` before `DataContext`. Single form → expanded to all declared cases (no DB save); multiple forms → `enqueue_save()` (background).
5. **Rendering** — `{{var.ge}}` → that case's form; bare `{{var}}` → `[INFLECTED: specify case]` + warning log; `{{var.<unknown>}}` → Jinja `Undefined`.

## Components

| Piece | Where |
|-------|-------|
| `InflectedWord` (rendering wrapper) | [inflection.py](inflection.py) — detail in [CLAUDE.md](CLAUDE.md) |
| SQLite dictionary (lookup/save/search/conflicts) | [inflection_db.py](inflection_db.py) — detail in [CLAUDE.md](CLAUDE.md) |
| AJAX lookup route | [routes/inflection.py](../routes/inflection.py) |
| Admin UI (browse/search/edit/delete/conflicts) | [routes/debug.py](../routes/debug.py) → `/debug/inflections` |
| Storage | `app/inflection_data/inflections.db` (lazy init, WAL) |

## Known limitations / gotchas

- **Jinja method shadowing:** `InflectedWord` subclasses `dict`, so `{{var.keys}}`/`{{var.items}}` render as `<built-in method …>`. Use declared case codes (`no`, `ge`, …) only.
- **Column 4 is per-type:** each consumer type carries its own value in the options cell (`enum:…;text:…`), so a var can now be both `enum` and inflected `text`.
- **Computed inflected vars:** a `compute_*` plugin for an inflected var must return an `InflectedWord` or `{case: form}` dict — a plain string breaks `{{var.case}}`.
- **Concurrent same-word save** can silently drop a form (append-only; fails safe, logged, no orphan rows).
- **Security:** `/debug/inflections*` and `/inflection/lookup` are reachable unauthenticated via nginx — fine locally, add auth before non-local exposure.