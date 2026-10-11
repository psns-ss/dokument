# logic/inflection_db.py
# SQLite-backed inflection dictionary with per-thread connections, background
# save queue, nested LIKE + fuzzy ranking, and append-only merge semantics.

import sqlite3
import logging
import json
import atexit
import threading
from collections import deque
from contextlib import contextmanager
from difflib import SequenceMatcher
from pathlib import Path

logger = logging.getLogger('inflection_db')

DB_PATH = Path(__file__).parent.parent / "inflection_data" / "inflections.db"
_lock = threading.Lock()
_schema_initialized = False
_thread_state = threading.local()

# Fuzzy thresholds
ANCHOR_FUZZY_THRESHOLD = 0.85
LIKE_FUZZY_THRESHOLD = 0.7
LIKE_LIMIT = 50

# Conflict types (stored in inflection_conflicts.conflict_type, shown on the admin card)
CONFLICT_ANCHOR = "anchor"      # LIKE candidate, anchor form too dissimilar (<= 0.85)
CONFLICT_SPLIT = "split"        # submitted cases exact-match two different words
CONFLICT_COLLISION = "collision"  # a form is already claimed by another word (UNIQUE hit)

# Canonical case order for display. Also used to pick a word's "headword"
# (its browse/display name) when it has no 'no' form.
CASE_ORDER = ["no", "ge", "da", "ac", "in", "pre"]
_CASE_RANK = {cc: i for i, cc in enumerate(CASE_ORDER)}


def _order_forms(forms: dict[str, str]) -> dict[str, str]:
    """Reorder {case_code: value} by canonical case order; unknown cases last (alphabetical).

    The DB stores forms in insertion order, so a 'no' case added later would
    otherwise render last in the admin table. Rendering always reads by case
    key, so this only affects display order."""
    return dict(sorted(forms.items(), key=lambda kv: (_CASE_RANK.get(kv[0], len(CASE_ORDER)), kv[0])))


def _display_key(s: str) -> str:
    """Strip leading non-alphanumeric chars (quotes, guillemets, parens, spaces).

    Bureaucratic wordphrases like '"ООО Ромашка"' or '«Альфа»' keep their leading
    symbols in the stored value (they are part of the phrase for lookup/save), but
    browsing/searching keys off the first real letter so they sort and are findable
    under О / А instead of a stray symbol tile."""
    i = 0
    while i < len(s) and not s[i].isalnum():
        i += 1
    return s[i:]


# One headword row per word: the 'no' form if present, else the first form in
# canonical case order (ties broken by rowid for determinism). Lets browse /
# count / filter key off a stable name so entries without a nominative get a
# real letter instead of a blank, NULL-sorted-to-top row.
_HEADWORD_SQL = """
    SELECT word_id, form_value AS headword, display_key AS headword_display_key
    FROM (
        SELECT word_id, form_value, display_key,
               ROW_NUMBER() OVER (
                   PARTITION BY word_id
                   ORDER BY CASE case_code
                        WHEN 'no' THEN 0 WHEN 'ge' THEN 1 WHEN 'da' THEN 2
                        WHEN 'ac' THEN 3 WHEN 'in' THEN 4 WHEN 'pre' THEN 5
                        ELSE 6 END,
                        id
               ) AS rn
        FROM inflection_forms
    )
    WHERE rn = 1
"""


# ── Connection & Schema (lazy init) ──────────────────────────────

def _connect() -> sqlite3.Connection:
    """This thread's connection — created (PRAGMAs + schema) on first use.

    Cached per thread: the AJAX lookup path fires on field blur, and
    re-opening + re-PRAGMA-ing per call was pure overhead. Under Gunicorn
    thread workers the connection lives for the thread's lifetime; anything
    that swaps DB_PATH (tests) must call close_connection() first."""
    global _schema_initialized
    conn = getattr(_thread_state, "conn", None)
    if conn is not None:
        return conn
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    if not _schema_initialized:
        with _lock:
            if not _schema_initialized:
                _create_schema(conn)
                _schema_initialized = True
    _thread_state.conn = conn
    return conn


def close_connection() -> None:
    """Close and forget this thread's connection (test isolation, DB-path swap)."""
    conn = getattr(_thread_state, "conn", None)
    if conn is not None:
        _thread_state.conn = None
        conn.close()


@contextmanager
def _write(conn: sqlite3.Connection):
    """Commit on success, rollback on error.

    The per-thread connection is long-lived: an exception mid-write must not
    leave an open transaction that the thread's next call would silently join."""
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _create_schema(conn: sqlite3.Connection):
    """Create tables and indexes. Idempotent (IF NOT EXISTS)."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS inflection_forms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word_id INTEGER NOT NULL,
            form_value TEXT NOT NULL,
            form_value_lower TEXT NOT NULL,
            display_key TEXT NOT NULL DEFAULT '',
            case_code TEXT NOT NULL,
            UNIQUE(case_code, form_value_lower)
        );
        CREATE INDEX IF NOT EXISTS idx_lookup
            ON inflection_forms(case_code, form_value_lower);
        CREATE INDEX IF NOT EXISTS idx_word_id
            ON inflection_forms(word_id);
        CREATE TABLE IF NOT EXISTS inflection_conflicts (
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
        -- Dedicated word_id sequence. Kept SEPARATE from inflection_forms.id
        -- (a global autoincrement spanning every case row of every word):
        -- allocating word_id as a form row's id could land on an id an existing
        -- word already owns once the two counters diverge (varying case counts,
        -- deletes, or a DB seeded by an older layout), silently merging a new
        -- word into an existing one. words.id is its own counter, so it can't.
        CREATE TABLE IF NOT EXISTS words (
            id INTEGER PRIMARY KEY AUTOINCREMENT
        );
    """)
    _migrate_display_key(conn)
    _migrate_words_table(conn)


def _migrate_display_key(conn: sqlite3.Connection) -> None:
    """Add + backfill display_key on DBs created before the column existed.

    display_key = casefolded _display_key(form_value) (leading non-alphanumerics
    stripped) — the browse/search key, stored so the letter filter, sort and
    prefix match run in SQL instead of materializing the whole table.
    One-time: fresh DBs get the column from CREATE TABLE above."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(inflection_forms)")}
    if "display_key" in cols:
        return
    conn.execute("ALTER TABLE inflection_forms ADD COLUMN display_key TEXT NOT NULL DEFAULT ''")
    rows = conn.execute("SELECT id, form_value_lower FROM inflection_forms").fetchall()
    conn.executemany(
        "UPDATE inflection_forms SET display_key = ? WHERE id = ?",
        [(_display_key(fvl), row_id) for row_id, fvl in rows]
    )
    conn.commit()


def _migrate_words_table(conn: sqlite3.Connection) -> None:
    """Backfill the words sequence on DBs created before it existed.

    words.id is the authoritative word_id sequence. Seed it with every existing
    word_id (so a fresh word can never reuse one) and bump the AUTOINCREMENT
    high-water mark past MAX(word_id) so the next allocation is collision-free.
    Idempotent: INSERT OR IGNORE + a monotonic seq bump, so re-running is a no-op."""
    rows = conn.execute(
        "SELECT DISTINCT word_id FROM inflection_forms WHERE word_id > 0"
    ).fetchall()
    for (wid,) in rows:
        conn.execute("INSERT OR IGNORE INTO words (id) VALUES (?)", (wid,))
    max_wid = conn.execute(
        "SELECT COALESCE(MAX(word_id), 0) FROM inflection_forms"
    ).fetchone()[0]
    seq_row = conn.execute(
        "SELECT seq FROM sqlite_sequence WHERE name = 'words'"
    ).fetchone()
    if seq_row is None:
        conn.execute(
            "INSERT INTO sqlite_sequence (name, seq) VALUES ('words', ?)", (max_wid,)
        )
    elif seq_row[0] < max_wid:
        conn.execute(
            "UPDATE sqlite_sequence SET seq = ? WHERE name = 'words'", (max_wid,)
        )
    conn.commit()


# ── Public API ───────────────────────────────────────────────────

def lookup_by_form(case_code: str, form_value: str) -> dict | None:
    """Exact match on form_value_lower -> return all forms for that word_id."""
    lowered = form_value.casefold()
    conn = _connect()
    row = conn.execute(
        "SELECT word_id FROM inflection_forms "
        "WHERE case_code = ? AND form_value_lower = ?",
        (case_code, lowered)
    ).fetchone()
    if row is None:
        return None
    word_id = row[0]
    rows = conn.execute(
        "SELECT case_code, form_value FROM inflection_forms WHERE word_id = ?",
        (word_id,)
    ).fetchall()
    return _order_forms({r[0]: r[1] for r in rows})


def save_word(forms: dict[str, str]) -> int | None:
    """Synchronous save with append-only merge. Returns word_id."""
    if not forms or len(forms) <= 1:
        return None  # abbreviation, nothing to learn

    conn = _connect()
    try:
        with _write(conn):
            return _save_word_transaction(conn, forms)
    except Exception:
        logger.exception(f"Inflection save failed: {forms}")
        return None


def delete_word(word_id: int) -> None:
    """Remove all forms for a word."""
    conn = _connect()
    with _write(conn):
        conn.execute("DELETE FROM inflection_forms WHERE word_id = ?", (word_id,))


def delete_conflict(conflict_id: int) -> None:
    """Remove a conflict log entry (admin dismiss / post-merge cleanup)."""
    conn = _connect()
    with _write(conn):
        conn.execute("DELETE FROM inflection_conflicts WHERE id = ?", (conflict_id,))


def replace_word(word_id: int, forms: dict[str, str]) -> int:
    """Replace all forms of a word (admin edit / conflict merge).

    Delete the word's existing rows, then insert the submitted forms under the
    same word_id. If a submitted form collides with a form claimed by another
    word (UNIQUE(case_code, form_value_lower)), the colliding case is skipped
    and logged to inflection_conflicts — it is not allowed to overwrite data
    that belongs to a different word.
    """
    conn = _connect()
    with _write(conn):
        conn.execute("DELETE FROM inflection_forms WHERE word_id = ?", (word_id,))
        for case_code, form_value in forms.items():
            lowered = form_value.casefold()
            cursor = conn.execute(
                "INSERT OR IGNORE INTO inflection_forms "
                "(word_id, form_value, form_value_lower, display_key, case_code) "
                "VALUES (?, ?, ?, ?, ?)",
                (word_id, form_value, lowered, _display_key(lowered), case_code)
            )
            if cursor.rowcount == 0:
                conflict_row = conn.execute(
                    "SELECT word_id, form_value FROM inflection_forms "
                    "WHERE case_code = ? AND form_value_lower = ?",
                    (case_code, lowered)
                ).fetchone()
                if conflict_row and conflict_row[0] != word_id:
                    conn.execute(
                        "INSERT INTO inflection_conflicts "
                        "(existing_word_id, new_word_id, case_code, existing_value, new_value, new_forms_json, conflict_type) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (conflict_row[0], word_id, case_code, conflict_row[1], form_value, json.dumps(forms), CONFLICT_COLLISION)
                    )
        return word_id


def _word_with_forms(conn: sqlite3.Connection, word_id: int, nominative: str) -> dict:
    """One browse/search result row: word_id + case-ordered forms."""
    form_rows = conn.execute(
        "SELECT case_code, form_value FROM inflection_forms WHERE word_id = ?",
        (word_id,)
    ).fetchall()
    return {
        "word_id": word_id,
        "forms": _order_forms({r[0]: r[1] for r in form_rows}),
        "nominative": nominative
    }


def get_letter_counts() -> dict[str, int]:
    """Return counts of words per first letter of their headword.

    Headword = nominative ('no') form, else first case-ordered form — so words
    without a 'no' case still get a letter. The letter is taken from the display
    key (leading symbols like quotes/guillemets stripped), so '"ООО Ромашка"'
    files under О, not a stray '"' tile. Used by the admin browse page to render
    a compact filter bar that only shows letters which actually have words —
    the same key list_words() filters on, so every tile shows its words."""
    conn = _connect()
    rows = conn.execute("SELECT headword_display_key FROM (" + _HEADWORD_SQL + ")").fetchall()
    counts = {}
    for (key,) in rows:
        if key:
            letter = key[0]
            counts[letter] = counts.get(letter, 0) + 1
    return counts


def list_words(letter: str = "", page: int = 1, page_size: int = 50) -> list[dict]:
    """Paginated listing filtered by first letter of the word's headword.

    Headword = nominative ('no') form, else first case-ordered form, so words
    without a 'no' case are browsable under a real letter instead of floating to
    the top as blank rows. Letter + sort key off the display key (leading symbols
    stripped), so '"ООО Ромашка"' sorts/files under О; the stored value is shown
    unchanged. Filter, sort and pagination run in SQL — only the requested page
    is materialized."""
    conn = _connect()
    sql = "SELECT word_id, headword FROM (" + _HEADWORD_SQL + ")"
    params: list = []
    if letter:
        # display_key is stored casefolded; SQLite LIKE is case-sensitive for
        # non-ASCII, so the bound pattern is casefolded too.
        sql += " WHERE headword_display_key LIKE ? ESCAPE '\\'"
        params.append(_escape_like(letter.casefold()) + "%")
    sql += " ORDER BY headword_display_key, word_id LIMIT ? OFFSET ?"
    params.extend([page_size, (page - 1) * page_size])
    rows = conn.execute(sql, params).fetchall()

    return [_word_with_forms(conn, word_id, headword or "")
            for word_id, headword in rows]


def count_words(letter: str = "") -> int:
    """Total words matching the browse letter filter (0/empty = all).

    Mirrors list_words()'s WHERE clause so the browse subtitle shows the real
    total for the current filter, not just the page's count."""
    conn = _connect()
    sql = "SELECT COUNT(*) FROM (" + _HEADWORD_SQL + ")"
    params: list = []
    if letter:
        # display_key is stored casefolded; casefold the pattern too (LIKE is
        # case-sensitive for non-ASCII) — same rule as list_words.
        sql += " WHERE headword_display_key LIKE ? ESCAPE '\\'"
        params.append(_escape_like(letter.casefold()) + "%")
    return conn.execute(sql, params).fetchone()[0]


def search_words(query: str) -> list[dict]:
    """Prefix search on form values (match + sort in SQL, capped at LIKE_LIMIT).

    A letter-leading query (e.g. 'ООО') matches the display key, so it finds
    '"ООО Ромашка"' (leading symbol ignored). A symbol-leading query (e.g. '"ООО')
    matches the raw value, so it narrows to only the symbol-prefixed words — the
    user is deliberately including the symbol to scope the search. Results are
    ordered by the headword's display key (no-form else first case-ordered form)."""
    q = query.casefold()
    if not q:
        return []
    dq = _display_key(q)
    conn = _connect()
    # Letter-leading (q == dq): match the display key. Symbol-leading (q != dq):
    # raw prefix — the leading symbol deliberately narrows the scope.
    if q == dq:
        match_sql, match_param = "display_key LIKE ? ESCAPE '\\'", _escape_like(dq) + "%"
    else:
        match_sql, match_param = "form_value_lower LIKE ? ESCAPE '\\'", _escape_like(q) + "%"

    rows = conn.execute(
        "SELECT h.word_id, h.headword FROM (" + _HEADWORD_SQL + ") h "
        "WHERE h.word_id IN (SELECT word_id FROM inflection_forms WHERE " + match_sql + ") "
        "ORDER BY h.headword_display_key, h.word_id LIMIT ?",
        (match_param, LIKE_LIMIT)
    ).fetchall()

    return [_word_with_forms(conn, word_id, headword or "")
            for word_id, headword in rows]


def get_word(word_id: int) -> dict | None:
    """Get a single word with all its forms (case-ordered)."""
    conn = _connect()
    rows = conn.execute(
        "SELECT case_code, form_value FROM inflection_forms WHERE word_id = ?",
        (word_id,)
    ).fetchall()
    if not rows:
        return None
    forms = _order_forms({r[0]: r[1] for r in rows})
    # Headword: nominative if present, else first case-ordered form.
    nominative = forms.get('no') or next(iter(forms.values()), "")
    return {"word_id": word_id, "forms": forms, "nominative": nominative}


def _conflict_row_to_dict(row) -> dict:
    """Map a conflict table row to its admin-UI dict (shared by list + detail)."""
    return {
        "id": row[0],
        "ts": row[1],
        "existing_word_id": row[2],
        "new_word_id": row[3],
        "case_code": row[4],
        "existing_value": row[5],
        "new_value": row[6],
        "new_forms_json": json.loads(row[7]) if row[7] else {},
        "conflict_type": row[8]
    }


def get_conflict_with_words(conflict_id: int) -> dict | None:
    """Get a conflict with full word data for both sides."""
    conn = _connect()
    row = conn.execute(
        "SELECT id, ts, existing_word_id, new_word_id, case_code, "
        "existing_value, new_value, new_forms_json, conflict_type "
        "FROM inflection_conflicts WHERE id = ?",
        (conflict_id,)
    ).fetchone()
    if row is None:
        return None

    conflict = _conflict_row_to_dict(row)

    # Load full word data for existing_word_id (always real)
    conflict["existing_word"] = get_word(conflict["existing_word_id"])

    # new_word_id is a real word_id at insert time (all three conflict types log
    # it once the word exists). Fall back to new_forms_json only if that word was
    # later deleted by an admin, so get_word() returns None.
    new_word = get_word(conflict["new_word_id"])
    if new_word is None and conflict["new_forms_json"]:
        new_word = {
            "word_id": conflict["new_word_id"],
            "forms": conflict["new_forms_json"],
            "nominative": conflict["new_forms_json"].get("no") or next(iter(conflict["new_forms_json"].values()), "")
        }
    conflict["new_word"] = new_word

    return conflict


def get_conflicts(page: int = 1, page_size: int = 50) -> list[dict]:
    """Retrieve recent conflicts for admin UI."""
    conn = _connect()
    rows = conn.execute(
        "SELECT id, ts, existing_word_id, new_word_id, case_code, "
        "existing_value, new_value, new_forms_json, conflict_type "
        "FROM inflection_conflicts ORDER BY id DESC LIMIT ? OFFSET ?",
        (page_size, (page - 1) * page_size)
    ).fetchall()
    return [_conflict_row_to_dict(row) for row in rows]


# ── Background Save Queue ────────────────────────────────────────

_save_queue = deque()
_bg_lock = threading.Lock()
_bg_worker = None


def enqueue_save(forms: dict) -> None:
    """Thread-safe enqueue. Starts background worker if idle.

    Fast path: skip words the dictionary already knows fully — /generate fires
    this on every run, and re-saving a known word is a no-op merge. The check
    is advisory only (a first-save race just double-merges, which is harmless:
    append-only + INSERT OR IGNORE), and a DB hiccup falls back to the old
    always-enqueue behavior — enqueue must never raise into /generate."""
    global _bg_worker
    try:
        if _is_known_word(_connect(), forms):
            return
    except Exception:
        pass
    with _bg_lock:
        _save_queue.append(forms)
        if _bg_worker is None or not _bg_worker.is_alive():
            _bg_worker = threading.Thread(target=_drain_queue, daemon=True)
            _bg_worker.start()


def _is_known_word(conn: sqlite3.Connection, forms: dict[str, str]) -> bool:
    """True when every submitted form already belongs to a single word.

    One indexed query (idx_lookup) instead of a full save round-trip in the
    background worker."""
    clauses = " OR ".join(["case_code = ? AND form_value_lower = ?"] * len(forms))
    rows = conn.execute(
        f"SELECT word_id, COUNT(*) FROM inflection_forms WHERE ({clauses}) GROUP BY word_id",
        [v for cc, fv in forms.items() for v in (cc, fv.casefold())]
    ).fetchall()
    return len(rows) == 1 and rows[0][1] == len(forms)


def _drain_queue():
    global _bg_worker
    while True:
        with _bg_lock:
            if not _save_queue:
                _bg_worker = None   # signal: worker exited, allow restart
                return
            forms = _save_queue.popleft()
        try:
            word_id = save_word(forms)
            logger.info(f"Inflection saved: {forms} -> word_id={word_id}")
        except Exception:
            logger.exception(f"Inflection save failed: {forms}")


def _flush_queue() -> None:
    """Drain the save queue on shutdown (atexit hook).

    The background worker is a daemon thread — it's killed at process exit, so
    words still queued would be lost. This hook lets a running worker finish,
    then drains whatever is left, so nothing is dropped. Best-effort: a failure
    is logged, never raised (atexit must not crash shutdown)."""
    global _bg_worker
    if _bg_worker is not None and _bg_worker.is_alive():
        _bg_worker.join(timeout=5)
    while True:
        with _bg_lock:
            if not _save_queue:
                return
            forms = _save_queue.popleft()
        try:
            word_id = save_word(forms)
            logger.info(f"Inflection saved (flush): {forms} -> word_id={word_id}")
        except Exception:
            logger.exception(f"Inflection save failed (flush): {forms}")


atexit.register(_flush_queue)


# ── Internal helpers ─────────────────────────────────────────────

def _strip_word(word: str) -> str:
    """Strip min(3, floor(len/2)) chars from end. Skip if too short."""
    n = len(word)
    if n <= 2:
        return word  # too short to stem
    strip_count = min(3, n // 2)
    return word[:n - strip_count]


def _escape_like(s: str) -> str:
    """Escape '%' and '_' for LIKE patterns."""
    return s.replace('%', '\\%').replace('_', '\\_')


def _build_like_pattern(form_value: str) -> str:
    """Split by spaces, strip each word, escape LIKE wildcards, join with %-suffixes.

    Casefolded so the pattern matches the casefolded form_value_lower column.
    SQLite LIKE is case-sensitive for non-ASCII, so a capitalized Cyrillic input
    would otherwise never match a lowercased stored value (killing the fuzzy path)."""
    words = form_value.casefold().split()
    stems = []
    for w in words:
        # Strip FIRST, then escape: _strip_word removes trailing chars to make a
        # prefix, so it must run on the raw word. Escaping after means any '%'/'_'
        # in the surviving prefix is protected, and the escape backslashes are
        # never eaten by the strip. (Escaping first let _strip_word consume the
        # backslashes, turning an escaped '_' into a wildcard.)
        stem = _strip_word(w)
        stems.append(_escape_like(stem) + '%')
    return ' '.join(stems)


def _similarity_ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _save_word_transaction(conn: sqlite3.Connection, forms: dict[str, str]) -> int:
    """Execute save logic within a transaction. Returns word_id."""

    # Step 1: Exact match on form_value_lower
    matched_word_ids = {}
    for case_code, form_value in forms.items():
        lowered = form_value.casefold()
        row = conn.execute(
            "SELECT word_id FROM inflection_forms "
            "WHERE case_code = ? AND form_value_lower = ?",
            (case_code, lowered)
        ).fetchone()
        if row:
            matched_word_ids.setdefault(row[0], []).append((case_code, form_value))

    if matched_word_ids:
        # All forms map to same word_id?
        if len(matched_word_ids) == 1:
            word_id = list(matched_word_ids.keys())[0]
            return _merge_into_word_id(conn, word_id, forms)
        else:
            # Forms map to different word_ids -> conflict
            # Pick the first one (prefer 'no' case)
            preferred_case = 'no' if 'no' in forms else next(iter(forms.keys()))
            preferred_word_id = None
            for wid, cases_list in matched_word_ids.items():
                for cc, fv in cases_list:
                    if cc == preferred_case:
                        preferred_word_id = wid
                        break
            if preferred_word_id is None:
                preferred_word_id = list(matched_word_ids.keys())[0]

            # Log conflicts for mismatched cases
            for wid, cases_list in matched_word_ids.items():
                if wid != preferred_word_id:
                    for cc, fv in cases_list:
                        conn.execute(
                            "INSERT INTO inflection_conflicts "
                            "(existing_word_id, new_word_id, case_code, existing_value, new_value, new_forms_json, conflict_type) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (wid, preferred_word_id, cc, fv, forms.get(cc, ''), json.dumps(forms), CONFLICT_SPLIT)
                        )
            return _merge_into_word_id(conn, preferred_word_id, forms)

    # Step 2: Nested LIKE (per-word stem prefix search)
    # Prefer 'no' form first
    search_form = forms.get('no') or next(iter(forms.values()))
    pattern = _build_like_pattern(search_form)

    like_rows = conn.execute(
        "SELECT DISTINCT word_id FROM inflection_forms "
        "WHERE form_value_lower LIKE ? ESCAPE '\\' LIMIT ?",
        (pattern, LIKE_LIMIT)
    ).fetchall()

    if like_rows:
        if len(like_rows) == 1:
            candidate_word_id = like_rows[0][0]
            # Anchor fuzzy check
            conflict = _anchor_fuzzy_check(conn, candidate_word_id, forms)
            if conflict is None:
                return _merge_into_word_id(conn, candidate_word_id, forms)
            # Anchor mismatch — insert as a new word, then log the conflict with
            # the real new_word_id so the admin merge flow can find/delete it.
            new_word_id = _insert_new_word(conn, forms)
            _log_anchor_conflict(conn, candidate_word_id, new_word_id, conflict, forms)
            return new_word_id
        else:
            # 2+ matches -> fuzzy rank
            best_score = 0
            best_word_id = None
            for (word_id,) in like_rows:
                score = _like_fuzzy_score(conn, word_id, forms)
                if score > best_score:
                    best_score = score
                    best_word_id = word_id
            if best_word_id and best_score > LIKE_FUZZY_THRESHOLD:
                conflict = _anchor_fuzzy_check(conn, best_word_id, forms)
                if conflict is None:
                    return _merge_into_word_id(conn, best_word_id, forms)
                new_word_id = _insert_new_word(conn, forms)
                _log_anchor_conflict(conn, best_word_id, new_word_id, conflict, forms)
                return new_word_id

    # Step 3: INSERT as new word
    return _insert_new_word(conn, forms)


def _anchor_fuzzy_check(conn: sqlite3.Connection, word_id: int, forms: dict[str, str]):
    """Check anchor case (prefer 'no') with fuzzy comparison.

    Returns None when the submitted forms can be merged into the candidate
    word, or a conflict dict (case_code, existing_value, new_value) when the
    anchor mismatch means they should be inserted as a new word. The caller
    inserts the conflict row AFTER the new word gets its real word_id, so the
    admin merge flow can find and delete it."""
    # Find first declared filled case, preferring 'no'
    anchor_case = None
    for cc in ['no'] + [k for k in forms.keys() if k != 'no']:
        if cc in forms:
            anchor_case = cc
            break
    if anchor_case is None:
        return None

    existing_row = conn.execute(
        "SELECT form_value FROM inflection_forms "
        "WHERE word_id = ? AND case_code = ?",
        (word_id, anchor_case)
    ).fetchone()

    if existing_row is None:
        return None  # no anchor to compare

    existing_val = existing_row[0]
    new_val = forms[anchor_case]

    if existing_val.casefold() == new_val.casefold():
        return None  # exact match

    ratio = _similarity_ratio(existing_val, new_val)
    if ratio > ANCHOR_FUZZY_THRESHOLD:
        return None  # close enough

    return {
        "case_code": anchor_case,
        "existing_value": existing_val,
        "new_value": new_val,
    }


def _log_anchor_conflict(conn: sqlite3.Connection, existing_word_id: int,
                         new_word_id: int, conflict: dict,
                         forms: dict[str, str]) -> None:
    """Insert an anchor-mismatch conflict after the new word has a real word_id."""
    conn.execute(
        "INSERT INTO inflection_conflicts "
        "(existing_word_id, new_word_id, case_code, existing_value, new_value, new_forms_json, conflict_type) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (existing_word_id, new_word_id, conflict["case_code"],
         conflict["existing_value"], conflict["new_value"], json.dumps(forms), CONFLICT_ANCHOR)
    )


def _like_fuzzy_score(conn: sqlite3.Connection, word_id: int, forms: dict[str, str]) -> float:
    """Compute fuzzy score for LIKE candidate vs submitted forms."""
    # Compare nominative forms
    existing_no = conn.execute(
        "SELECT form_value FROM inflection_forms "
        "WHERE word_id = ? AND case_code = 'no'",
        (word_id,)
    ).fetchone()

    if existing_no and 'no' in forms:
        return _similarity_ratio(existing_no[0], forms['no'])

    # Fallback: compare first available form (ORDER BY id — deterministic pick)
    existing_forms = conn.execute(
        "SELECT form_value FROM inflection_forms WHERE word_id = ? ORDER BY id LIMIT 1",
        (word_id,)
    ).fetchone()

    if existing_forms:
        new_val = next(iter(forms.values()))
        return _similarity_ratio(existing_forms[0], new_val)

    return 0


def _merge_into_word_id(conn: sqlite3.Connection, word_id: int, forms: dict[str, str]) -> int:
    """Batch insert missing cases into found word_id (append-only)."""
    for case_code, form_value in forms.items():
        lowered = form_value.casefold()

        # Check if any form already exists for this (word_id, case_code)
        existing = conn.execute(
            "SELECT form_value_lower FROM inflection_forms "
            "WHERE word_id = ? AND case_code = ?",
            (word_id, case_code)
        ).fetchone()

        if existing:
            if existing[0] == lowered:
                continue  # exact match, already present
            else:
                continue  # different form already exists — append-only, skip

        # Insert (or handle UNIQUE constraint collision)
        cursor = conn.execute(
            "INSERT OR IGNORE INTO inflection_forms "
            "(word_id, form_value, form_value_lower, display_key, case_code) "
            "VALUES (?, ?, ?, ?, ?)",
            (word_id, form_value, lowered, _display_key(lowered), case_code)
        )

        if cursor.rowcount == 0:
            # UNIQUE constraint hit — check if different word claims this form
            conflict_row = conn.execute(
                "SELECT word_id, form_value FROM inflection_forms "
                "WHERE case_code = ? AND form_value_lower = ?",
                (case_code, lowered)
            ).fetchone()
            if conflict_row and conflict_row[0] != word_id:
                conn.execute(
                    "INSERT INTO inflection_conflicts "
                    "(existing_word_id, new_word_id, case_code, existing_value, new_value, new_forms_json, conflict_type) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (conflict_row[0], word_id, case_code, conflict_row[1], form_value, json.dumps(forms), CONFLICT_COLLISION)
                )

    return word_id


def _insert_new_word(conn: sqlite3.Connection, forms: dict[str, str]) -> int:
    """INSERT as new word, allocating word_id from the dedicated words sequence.

    word_id comes from words.id (its own autoincrement), NOT from the first form
    row's id: inflection_forms.id is a global counter across every case row of
    every word, so once it diverges from the word_id space (varying case counts,
    deletes, or an older seeded layout) reusing it as word_id could land on an id
    an existing word already owns — merging the new word into it."""
    items = list(forms.items())
    if not items:
        return 0

    word_id = conn.execute("INSERT INTO words DEFAULT VALUES").lastrowid

    # Insert first case row (plain INSERT — a UNIQUE hit here means the form is
    # already claimed by another word; let it raise and roll back the save).
    first_case, first_value = items[0]
    first_lower = first_value.casefold()
    conn.execute(
        "INSERT INTO inflection_forms (word_id, form_value, form_value_lower, display_key, case_code) "
        "VALUES (?, ?, ?, ?, ?)",
        (word_id, first_value, first_lower, _display_key(first_lower), first_case)
    )

    # Insert remaining cases (OR IGNORE — a form claimed by another word is
    # logged as a conflict, not fatal to the new word)
    for case_code, form_value in items[1:]:
        lowered = form_value.casefold()
        cursor = conn.execute(
            "INSERT OR IGNORE INTO inflection_forms "
            "(word_id, form_value, form_value_lower, display_key, case_code) "
            "VALUES (?, ?, ?, ?, ?)",
            (word_id, form_value, lowered, _display_key(lowered), case_code)
        )
        if cursor.rowcount == 0:
            # UNIQUE constraint hit
            conflict_row = conn.execute(
                "SELECT word_id, form_value FROM inflection_forms "
                "WHERE case_code = ? AND form_value_lower = ?",
                (case_code, lowered)
            ).fetchone()
            if conflict_row and conflict_row[0] != word_id:
                conn.execute(
                    "INSERT INTO inflection_conflicts "
                    "(existing_word_id, new_word_id, case_code, existing_value, new_value, new_forms_json, conflict_type) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (conflict_row[0], word_id, case_code, conflict_row[1], form_value, json.dumps(forms), CONFLICT_COLLISION)
                )

    return word_id
