# tests/CLAUDE.md

Test suite: unit, integration, end-to-end.

---

## Running

```bash
# All tests (skip E2E if no container)
python -m pytest -v

# E2E only (requires container at localhost:5555)
python -m pytest tests/test_e2e.py -v --e2e
```

---

## Test Structure

**Route tests** (`routes/`):
- `test_init.py` — GET/POST /init
- `test_generate.py` — POST /generate
- `test_debug.py` — GET /debug-vars
- `test_select.py` — GET/POST /select (pack selection)
- `test_onlyoffice.py` — OnlyOffice integration
- `test_inflection_route.py` — `/inflection/lookup` AJAX + blueprint registration
- `test_inflection_form.py` — per-case form inputs + scatter-key collection (POST /init)
- `test_inflection_admin.py` — `/debug/inflections` browse/search/delete/conflicts
- `test_inflection_edit_page.py` — edit page GET/POST, `get_word`, conflict merge
- `test_generate_inflection.py` — `InflectedWord` wrapping + `enqueue_save` (POST /generate)

**Core module tests**:
- `test_context.py` — DataContext dataclass
- `test_context_manager.py` — Thread-local DataContext
- `test_pack_manager.py` — Pack discovery/validation
- `test_computation.py` — Variable computation
- `test_parser.py` — descr.docx parsing
- `test_renderer.py` — Template rendering
- `test_renderer_subdoc_errors.py` — Subdoc error handling (graceful degradation)
- `test_nested_subdocs.py` — Nested subdoc rendering (bookmark-within-bookmark + table preservation)
- `test_matching.py` — Matching orchestration (hints-based)
- `test_dynamic_ui.py` — the init-form dynamic-UI block: `generate_dynamic_ui_block` / `dynamic_ui_hash` / `render_dynamic_ui_block` (Option E: empty-safe, session placeholders, static HTML/JS round-trip, autoescape-off) / `build_dynamic_ui_block` + `DynamicUIBlock`
- `test_matcher.py` — YAML loading and fuzzy matching functions from match_helpers.py
- `test_hints_builder.py` — HintsCollections building from variable metadata
- `test_session_manager.py` — Session operations
- `test_extractor.py` — variables_from_docx() (normalizes docxtpl forms to base var, scans all header/footer parts)
- `test_form_handler.py` — analyze_template_variables()
- `test_subdocuments.py` — create_subdoc_from_bookmark() (subdoc framework function)
- `test_thread_isolation.py` — Concurrent thread isolation
- `test_config.py` — Config class dynamic properties, active pack management
- `test_inflection.py` — `InflectedWord` (single/multi form, case access, `__str__`)
- `test_inflection_db.py` — SQLite dictionary (save/lookup/merge/search/conflicts, bg queue)

**User logic tests** (`test_user_logic/`):
- `test_birth_year.py` — Compute module
- `test_appeal.py` — Compute module
- `test_university.py` — Match/compute
- `test_signature.py` — Bool variable
- `test_cv.py` — init_cv() file upload hook
- `test_university_subdoc.py` — university_historical() subdoc generation

**E2E**:
- `test_e2e.py` — Container health, log verification
- `test_e2e_multipack.py` — Multi-pack E2E tests against running container

**Legacy**:
- `test_generator_*.py` — Old generator tests (test_generator_errors.py, test_generator_integration.py, test_generator_utils.py)

---

## Fixtures (conftest.py)

| Fixture | Purpose |
|---------|---------|
| `isolate_document_store` (autouse) | Redirect `cfg.document_store` to a per-test `tmp_path` dir. The `/document_store` default is a Docker volume path: on a host run it either wrote to the Windows drive root or died with `PermissionError` on Linux CI. Tests that need to assert output paths request this fixture and use its return value — never the literal `/document_store` |
| `client` | Flask test client |
| `fresh_inflection_db` | Point `logic.inflection_db` at a fresh temp DB (module globals + cached thread connection reset) — shared by all inflection tests |
| `test_dir` | Path to `tests/` |
| `fixtures_dir` | Path to `tests/fixtures/` |
| `project_root` | Path to project root |
| `temp_dir` | Temporary directory (auto-cleanup) |
| `sample_yaml_dict` | Sample YAML dictionary for matching functions |
| `user_logic_dir` | Host path to user plugins (`templates/logic`) |

---

## Fixtures Data (`fixtures/`)

Test DOCX files and YAML configs. See `fixtures/create_fixtures.py` to regenerate.

**Core fixtures:**
- `descr.docx` — Variable metadata for tests
- `template_simple.docx` — Simple template for extraction/rendering tests
- `template_with_header.docx` — Template with header variables
- `template_with_table.docx` — Template with table variables
- `template_inflection.docx` — Every docxtpl form (`{{var.case}}`, `{{p var}}`, `{{! var}}`, `{{p var[0]}}`, single-letter `{{f}}`) for extractor tests
- `template_many_headers.docx` — ≥10 header parts (13 sections); sentinel var only in the highest-numbered header
- `sample_config.yaml` — Sample YAML for matching tests

**Nested subdoc fixtures:**
- `nested_base.docx` — Template with `{{p level1}}`, `{{user_name}}`
- `nested_library.docx` — Bookmark `level1_content` with table column + `{{p table_3}}`
- `nested_source.docx` — Table 0 with `{{user_name}}`, `{{user_age}}`, `{{sex}}`
