"""
Tests for app/logic/inflection_db.py — SQLite inflection dictionary.

Per-test DB isolation comes from the shared `fresh_inflection_db` fixture
(conftest.py).
"""

import pytest
import sqlite3
import time

import logic.inflection_db as mod


class TestSchemaInit:
    def test_lazy_init_on_connect(self, fresh_inflection_db):
        conn = fresh_inflection_db._connect()
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {r[0] for r in rows}
        assert "inflection_forms" in table_names
        assert "inflection_conflicts" in table_names
        fresh_inflection_db.close_connection()

    def test_per_thread_connection_reused(self, fresh_inflection_db):
        c1 = fresh_inflection_db._connect()
        assert c1 is fresh_inflection_db._connect()

        fresh_inflection_db.close_connection()
        c3 = fresh_inflection_db._connect()
        assert c3 is not c1
        with pytest.raises(sqlite3.ProgrammingError):
            c1.execute("SELECT 1")


class TestSaveAndLookup:
    def test_save_and_lookup_exact(self, fresh_inflection_db):
        forms = {"no": "Ромашка", "ge": "Ромашки", "da": "Ромашке"}
        word_id = fresh_inflection_db.save_word(forms)
        assert word_id is not None
        assert isinstance(word_id, int)

        result = fresh_inflection_db.lookup_by_form("no", "Ромашка")
        assert result == forms

    def test_lookup_case_insensitive(self, fresh_inflection_db):
        forms = {"no": "Ромашка", "ge": "Ромашки"}
        fresh_inflection_db.save_word(forms)

        result = fresh_inflection_db.lookup_by_form("no", "РОМАШКА")
        assert result is not None
        assert result["no"] == "Ромашка"

    def test_lookup_not_found(self, fresh_inflection_db):
        result = fresh_inflection_db.lookup_by_form("no", "Неизвестная")
        assert result is None

    def test_save_single_form_skipped(self, fresh_inflection_db):
        result = fresh_inflection_db.save_word({"no": "Дек-1"})
        assert result is None

    def test_save_empty_skipped(self, fresh_inflection_db):
        result = fresh_inflection_db.save_word({})
        assert result is None

    def test_multiple_words_independent(self, fresh_inflection_db):
        fresh_inflection_db.save_word({"no": "Word1", "ge": "Word1-ge"})
        fresh_inflection_db.save_word({"no": "Word2", "ge": "Word2-ge"})

        r1 = fresh_inflection_db.lookup_by_form("no", "Word1")
        r2 = fresh_inflection_db.lookup_by_form("no", "Word2")

        assert r1["no"] == "Word1"
        assert r2["no"] == "Word2"
        assert r1 != r2


class TestAppendOnlyMerge:
    def test_merge_missing_cases(self, fresh_inflection_db):
        w1 = fresh_inflection_db.save_word({"no": "Тест", "ge": "Теста"})
        assert w1 is not None

        w2 = fresh_inflection_db.save_word({"no": "Тест", "da": "Тесту", "ac": "Тест"})
        assert w2 is not None
        assert w1 == w2

        result = fresh_inflection_db.lookup_by_form("no", "Тест")
        assert result["no"] == "Тест"
        assert result["ge"] == "Теста"
        assert result["da"] == "Тесту"
        assert result["ac"] == "Тест"

    def test_append_only_no_overwrite(self, fresh_inflection_db):
        fresh_inflection_db.save_word({"no": "Original", "ge": "Original-ge"})
        fresh_inflection_db.save_word({"no": "Original", "ge": "Different-ge"})

        result = fresh_inflection_db.lookup_by_form("no", "Original")
        assert result["ge"] == "Original-ge"


class TestDelete:
    def test_delete_word(self, fresh_inflection_db):
        forms = {"no": "DeleteMe", "ge": "DeleteMe-ge"}
        word_id = fresh_inflection_db.save_word(forms)

        fresh_inflection_db.delete_word(word_id)
        result = fresh_inflection_db.lookup_by_form("no", "DeleteMe")
        assert result is None


class TestListWords:
    def test_list_all_words(self, fresh_inflection_db):
        fresh_inflection_db.save_word({"no": "Apple", "ge": "Apple-ge"})
        fresh_inflection_db.save_word({"no": "Banana", "ge": "Banana-ge"})

        results = fresh_inflection_db.list_words()
        assert len(results) == 2

    def test_list_filtered_by_letter(self, fresh_inflection_db):
        fresh_inflection_db.save_word({"no": "Apple", "ge": "Apple-ge"})
        fresh_inflection_db.save_word({"no": "Apricot", "ge": "Apricot-ge"})
        fresh_inflection_db.save_word({"no": "Banana", "ge": "Banana-ge"})

        results = fresh_inflection_db.list_words(letter="A")
        nominatives = [r["nominative"] for r in results]
        assert "Banana" not in nominatives
        assert len(results) >= 1

    def test_list_pagination(self, fresh_inflection_db):
        fresh_inflection_db.save_word({"no": "A1", "ge": "A1-ge"})
        fresh_inflection_db.save_word({"no": "A2", "ge": "A2-ge"})
        fresh_inflection_db.save_word({"no": "A3", "ge": "A3-ge"})

        page1 = fresh_inflection_db.list_words(page=1, page_size=2)
        assert len(page1) == 2

        page2 = fresh_inflection_db.list_words(page=2, page_size=2)
        assert len(page2) == 1


class TestSearchWords:
    def test_prefix_search(self, fresh_inflection_db):
        fresh_inflection_db.save_word({"no": "Ромашка", "ge": "Ромашки"})
        fresh_inflection_db.save_word({"no": "Ромаш", "ge": "Ромаш-ge"})
        fresh_inflection_db.save_word({"no": "Яблоко", "ge": "Яблоко-ge"})

        results = fresh_inflection_db.search_words("Ром")
        nominatives = [r["nominative"] for r in results]
        assert "Яблоко" not in nominatives
        assert len(results) >= 1

    def test_letter_query_finds_symbol_prefixed_word(self, fresh_inflection_db):
        """'ООО' matches the display key, so the leading quote is ignored."""
        fresh_inflection_db.save_word({"no": '"ООО Ромашка"', "ge": '"ООО Ромашки"'})

        results = fresh_inflection_db.search_words("ООО")
        assert [r["nominative"] for r in results] == ['"ООО Ромашка"']

    def test_symbol_query_narrows_to_symbol_prefixed(self, fresh_inflection_db):
        """A symbol-leading query matches the raw value — it deliberately scopes."""
        fresh_inflection_db.save_word({"no": '"ООО Ромашка"', "ge": '"ООО Ромашки"'})
        fresh_inflection_db.save_word({"no": "ООО Вектор", "ge": "ООО Вектора"})

        results = fresh_inflection_db.search_words('"ООО')
        assert [r["nominative"] for r in results] == ['"ООО Ромашка"']


class TestDisplayKey:
    """display_key column: migration backfill + browse/search keying."""

    def test_migration_backfills_display_key(self, fresh_inflection_db):
        """A pre-display_key DB gets the column added + backfilled on first use."""
        path = fresh_inflection_db.DB_PATH
        raw = sqlite3.connect(str(path))
        raw.executescript("""
            CREATE TABLE inflection_forms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word_id INTEGER NOT NULL,
                form_value TEXT NOT NULL,
                form_value_lower TEXT NOT NULL,
                case_code TEXT NOT NULL,
                UNIQUE(case_code, form_value_lower)
            );
            CREATE TABLE inflection_conflicts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL DEFAULT (datetime('now')),
                existing_word_id INTEGER NOT NULL,
                new_word_id INTEGER NOT NULL,
                case_code TEXT NOT NULL,
                existing_value TEXT NOT NULL,
                new_value TEXT NOT NULL,
                new_forms_json TEXT,
                conflict_type TEXT
            );
        """)
        raw.execute(
            "INSERT INTO inflection_forms (word_id, form_value, form_value_lower, case_code) "
            "VALUES (1, '\"ООО Ромашка\"', '\"ооо ромашка\"', 'no')"
        )
        raw.commit()
        raw.close()

        # First module call triggers schema init + the one-time migration
        words = fresh_inflection_db.list_words()
        assert len(words) == 1
        assert words[0]["nominative"] == '"ООО Ромашка"'

        raw = sqlite3.connect(str(path))
        (dk,) = raw.execute("SELECT display_key FROM inflection_forms WHERE id = 1").fetchone()
        raw.close()
        assert dk == "ооо ромашка\""

    def test_symbol_prefixed_word_files_under_letter(self, fresh_inflection_db):
        fresh_inflection_db.save_word({"no": '"ООО Ромашка"', "ge": '"ООО Ромашки"'})
        fresh_inflection_db.save_word({"no": "Яблоко", "ge": "Яблоко-ge"})

        results = fresh_inflection_db.list_words(letter="о")
        nominatives = [r["nominative"] for r in results]
        assert '"ООО Ромашка"' in nominatives
        assert "Яблоко" not in nominatives

    def test_letter_counts_key_off_display_key(self, fresh_inflection_db):
        fresh_inflection_db.save_word({"no": '"ООО Ромашка"', "ge": '"ООО Ромашки"'})
        fresh_inflection_db.save_word({"no": "Яблоко", "ge": "Яблоко-ge"})

        counts = fresh_inflection_db.get_letter_counts()
        assert counts == {"о": 1, "я": 1}


class TestWordIdAllocation:
    """word_id comes from a dedicated `words` sequence, not from the first form
    row's global `id`. Regression: once the row-id and word_id counters diverge
    (varying case counts, deletes, or an older seeded layout), reusing the row id
    as word_id could land on an id an existing word already owns — silently
    merging a new word into it (a word ending up with two 'no' forms)."""

    def _seed_diverged_db(self, path):
        """Old layout: word_ids that don't equal the first-row id, no `words`
        table, and row ids filled (11..17) so the next insert lands on 18 — an
        id Ромашка already owns as its word_id."""
        raw = sqlite3.connect(str(path))
        raw.executescript("""
            CREATE TABLE inflection_forms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word_id INTEGER NOT NULL,
                form_value TEXT NOT NULL,
                form_value_lower TEXT NOT NULL,
                display_key TEXT NOT NULL DEFAULT '',
                case_code TEXT NOT NULL,
                UNIQUE(case_code, form_value_lower)
            );
            CREATE TABLE inflection_conflicts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL DEFAULT (datetime('now')),
                existing_word_id INTEGER NOT NULL,
                new_word_id INTEGER NOT NULL,
                case_code TEXT NOT NULL,
                existing_value TEXT NOT NULL,
                new_value TEXT NOT NULL,
                new_forms_json TEXT,
                conflict_type TEXT
            );
        """)
        rows = [
            (18, 'Ромашка', 'no'), (18, 'Ромашки', 'ge'),
            (18, 'Ромашке', 'da'), (18, 'Ромашке', 'pre'),
            (21, 'ООО "Тест"', 'no'), (21, 'ООО "Теста"', 'ge'),
            (21, 'ООО "Тесте"', 'pre'),
        ]
        for i, (wid, v, c) in enumerate(rows, start=11):
            lv = v.casefold()
            raw.execute(
                "INSERT INTO inflection_forms "
                "(id,word_id,form_value,form_value_lower,display_key,case_code) "
                "VALUES (?,?,?,?,?,?)", (i, wid, v, lv, lv, c))
        raw.commit()
        raw.close()

    def test_new_word_does_not_collide_with_diverged_word_id(self, fresh_inflection_db):
        self._seed_diverged_db(fresh_inflection_db.DB_PATH)

        new_id = fresh_inflection_db.save_word(
            {"no": "абырвалг", "ge": "абырвалгу", "pre": "абырвалге"})

        assert new_id is not None
        assert new_id != 18, "new word collided with Ромашка's word_id=18"

        raw = sqlite3.connect(str(fresh_inflection_db.DB_PATH))
        (no_count,) = raw.execute(
            "SELECT COUNT(*) FROM inflection_forms WHERE word_id=18 AND case_code='no'"
        ).fetchone()
        assert no_count == 1, "Ромашка gained a second 'no' form"
        new_cases = [r[0] for r in raw.execute(
            "SELECT case_code FROM inflection_forms WHERE word_id=? ORDER BY case_code",
            (new_id,))]
        assert new_cases == ['ge', 'no', 'pre']
        raw.close()

    def test_words_sequence_backfilled_past_max_word_id(self, fresh_inflection_db):
        self._seed_diverged_db(fresh_inflection_db.DB_PATH)
        fresh_inflection_db._connect()  # triggers schema init + migration

        raw = sqlite3.connect(str(fresh_inflection_db.DB_PATH))
        (seq,) = raw.execute(
            "SELECT seq FROM sqlite_sequence WHERE name='words'").fetchone()
        raw.close()
        assert seq >= 21, f"words sequence not bumped past MAX(word_id): {seq}"


class TestConflicts:
    def test_conflict_logged_on_split_word_ids(self, fresh_inflection_db):
        """When submitted forms map to different existing word_ids, conflict is logged."""
        fresh_inflection_db.save_word({"no": "A", "ge": "G1", "da": "D1"})  # WordA
        fresh_inflection_db.save_word({"no": "B", "ge": "G2", "da": "D2"})  # WordB

        # Save with nominative from WordA + dative from WordB -> split word_ids
        fresh_inflection_db.save_word({"no": "A", "da": "D2"})

        conflicts = fresh_inflection_db.get_conflicts()
        assert len(conflicts) >= 1

    def test_conflict_type_split(self, fresh_inflection_db):
        """Cross-case split (A's no + B's ge) records conflict_type='split'."""
        fresh_inflection_db.save_word({"no": "Ромашка", "ge": "Ромашки"})  # word A
        fresh_inflection_db.save_word({"no": "Тест", "ge": "Теста"})        # word B
        fresh_inflection_db.save_word({"no": "Ромашка", "ge": "Теста"})      # A's no + B's ge

        assert any(c["conflict_type"] == "split" for c in fresh_inflection_db.get_conflicts())

    def test_conflict_type_anchor(self, fresh_inflection_db):
        """Anchor mismatch (LIKE candidate, ratio <= 0.85) records 'anchor'."""
        fresh_inflection_db.save_word({"no": "колобок", "ge": "колобка"})    # word C
        fresh_inflection_db.save_word({"no": "колед", "ge": "колед-ге"})     # too dissimilar

        assert any(c["conflict_type"] == "anchor" for c in fresh_inflection_db.get_conflicts())

    def test_conflict_type_collision(self, fresh_inflection_db):
        """A form already claimed by another word records 'collision'."""
        fresh_inflection_db.save_word({"no": "Ромашка", "ge": "Ромашки"})    # word A owns ge=Ромашки
        d_id = fresh_inflection_db.save_word({"no": "Вишня", "ge": "Вишни"})  # word D
        fresh_inflection_db.replace_word(d_id, {"no": "Вишня", "ge": "Ромашки"})  # steal A's ge

        assert any(c["conflict_type"] == "collision" for c in fresh_inflection_db.get_conflicts())

    def test_get_conflicts_returns_conflict_type_key(self, fresh_inflection_db):
        """Every conflict dict carries a conflict_type key."""
        fresh_inflection_db.save_word({"no": "Ромашка", "ge": "Ромашки"})
        fresh_inflection_db.save_word({"no": "Тест", "ge": "Теста"})
        fresh_inflection_db.save_word({"no": "Ромашка", "ge": "Теста"})

        for c in fresh_inflection_db.get_conflicts():
            assert "conflict_type" in c


class TestLikeHelpers:
    def test_strip_word(self, fresh_inflection_db):
        assert fresh_inflection_db._strip_word("Hello") == "Hel"  # 5 chars -> strip 2
        assert fresh_inflection_db._strip_word("ab") == "ab"  # too short
        assert fresh_inflection_db._strip_word("abcdef") == "abc"  # 6 -> strip 3

    def test_escape_like(self, fresh_inflection_db):
        assert fresh_inflection_db._escape_like("100%") == "100\\%"
        assert fresh_inflection_db._escape_like("a_b") == "a\\_b"

    def test_build_like_pattern(self, fresh_inflection_db):
        pattern = fresh_inflection_db._build_like_pattern("ООО Ромашка")
        assert "%" in pattern

    def test_build_like_pattern_casefolds_cyrillic(self, fresh_inflection_db):
        """Pattern is casefolded to match the casefolded form_value_lower column.

        Regression: without casefolding, a capitalized Cyrillic input produced a
        pattern ('Рома%') that never matched the lowercased stored value, so the
        fuzzy LIKE path silently never fired for Russian words."""
        assert fresh_inflection_db._build_like_pattern("Ромашка") == "рома%"

    def test_similarity_ratio(self, fresh_inflection_db):
        assert fresh_inflection_db._similarity_ratio("abc", "abc") == 1.0
        assert fresh_inflection_db._similarity_ratio("abc", "xyz") == 0.0
        ratio = fresh_inflection_db._similarity_ratio("romashka", "romashki")
        assert 0.5 < ratio < 1.0


class TestThresholds:
    def test_anchor_threshold(self, fresh_inflection_db):
        assert fresh_inflection_db.ANCHOR_FUZZY_THRESHOLD == 0.85

    def test_like_threshold(self, fresh_inflection_db):
        assert fresh_inflection_db.LIKE_FUZZY_THRESHOLD == 0.7


class TestBackgroundQueue:
    def test_enqueue_and_drain(self, fresh_inflection_db):
        forms = {"no": "BgWord", "ge": "BgWord-ge"}
        fresh_inflection_db.enqueue_save(forms)

        for _ in range(30):
            time.sleep(0.1)
            result = fresh_inflection_db.lookup_by_form("no", "BgWord")
            if result is not None:
                break

        assert result is not None
        assert result["no"] == "BgWord"

    def test_enqueue_skips_fully_known_word(self, fresh_inflection_db):
        """Re-saving a word whose forms are all known doesn't touch the queue."""
        forms = {"no": "Known", "ge": "Known-ge"}
        fresh_inflection_db.save_word(forms)

        fresh_inflection_db.enqueue_save(forms)

        assert len(fresh_inflection_db._save_queue) == 0
        assert fresh_inflection_db._bg_worker is None

    def test_enqueue_partial_word_still_merges(self, fresh_inflection_db):
        """A submission with one unknown case still goes through the queue."""
        fresh_inflection_db.save_word({"no": "Partial", "ge": "Partial-ge"})

        fresh_inflection_db.enqueue_save({"no": "Partial", "da": "Partial-da"})

        result = None
        for _ in range(30):
            time.sleep(0.1)
            result = fresh_inflection_db.lookup_by_form("no", "Partial")
            if result and "da" in result:
                break

        assert result["da"] == "Partial-da"
