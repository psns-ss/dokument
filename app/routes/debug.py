"""
Debug endpoints: variable-extraction analysis + inflection-dictionary admin.

Routes:
    GET /debug-vars - Template author's checklist (pack-selectable)
    GET /reset      - Clear session and redirect to /init
    GET /debug/inflections - Browse/search the inflection dictionary
    GET /debug/inflections/search - JSON autocomplete search
    DELETE /debug/inflections/<word_id> - Delete a word
    GET/POST /debug/inflections/<word_id>/edit - Edit a word / merge a conflict
    GET/POST /debug/inflections/new - Add a new word
    GET /debug/inflections/conflicts - View save conflicts
    DELETE /debug/inflections/conflicts/<conflict_id> - Dismiss a conflict
"""
from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

from flask import Blueprint, session, render_template, request, jsonify, flash, redirect, url_for

from config import cfg, DATA_TTL_DAYS
from pack_manager import discover_packs, resolve_pack_paths
from logic.inflection_db import (
    CASE_ORDER, list_words, search_words, delete_word, delete_conflict, get_conflicts,
    save_word, get_word, get_conflict_with_words, replace_word, get_letter_counts,
    count_words
)
from logic.form_handler import analyze_template_variables
from logic.loader import find_templates
from logic.parser import read_variable_descriptions
from logic.hints_builder import build_hints_collections, verify_hooks_exist

logger = logging.getLogger(__name__)

debug_bp = Blueprint('debug', __name__, template_folder='html_helpers')


@debug_bp.route('/debug-vars')
def debug_variables():
    """Template author's checklist for the selected pack (?pack=<id>).

    Shows which variables are found in the pack's templates, how they line up
    with descr.docx, and which hooks (match/compute/init/subdoc) are
    implemented for each variable. Pack paths are resolved explicitly — no
    cfg.active_pack mutation (thread-safe).
    """
    packs = discover_packs(cfg.templates_dir)
    available = [p for p in packs if not p['is_disabled']]
    if not available:
        flash("Нет доступных наборов шаблонов", "error")
        return redirect(url_for('select.select_pack'))

    # ?pack=<id> — default: the active pack if still available, else root. If the
    # requested pack isn't available, flash a warning (the URL would otherwise
    # silently show a substituted pack).
    requested = request.args.get('pack') or session.get('active_pack') or 'root'
    pack = next((p for p in available if p['identifier'] == requested), None)
    if pack is None:
        pack = next((p for p in available if p['identifier'] == 'root'), available[0])
        flash(f"Набор '{requested}' недоступен — показан '{pack['identifier']}'.", "warning")

    descr_path, lang_path = resolve_pack_paths(cfg.templates_dir, pack['identifier'])
    variable_desc = read_variable_descriptions(descr_path, lang_path)
    hints = build_hints_collections(variable_desc)

    # Templates of the selected pack (pack dir — not the root, as before)
    analysis = analyze_template_variables(
        find_templates(pack['base_dir']), variable_desc
    )

    # Logic dir: pack logic/, fallback to root logic/ (same as the engine)
    logic_dir = pack['base_dir'] / 'logic'
    if not logic_dir.exists():
        root_logic = cfg.templates_dir / 'logic'
        logic_dir = root_logic if root_logic.exists() else None
    hook_report = verify_hooks_exist(hints, logic_dir)

    template_data = [
        {'name': Path(p).name, 'found': set(d['present_vars']), 'error': d.get('error')}
        for p, d in analysis['template_details'].items()
    ]

    # Per-var rows: metadata + expected hooks vs implemented.
    # Each hook carries its real function name (fn) and the wiring rows
    # group found hooks by module for the "var → module → hooks" graph.
    var_rows = []
    # descr.docx order (order of appearance), not alphabetical — the table's
    # default ordering; the client can sort any column, which cycles back here.
    for var in variable_desc:
        meta = variable_desc[var]
        types = meta.get('types', [meta.get('type', 'text')])
        hook_names = [h for h, present in (
            ('match', 'match' in types),
            ('compute', 'computed' in types),
            ('subdoc', 'subdoc' in types),
            # match vars also get init_<var>: generate_dynamic_ui_block fires init hooks
            # for every matched_entities key, match results included
            ('init', 'form' in types or 'file' in types or 'match' in types),
        ) if present]
        found = hook_report['found'].get(var, {})
        hooks = []
        for h in hook_names:
            hooks.append({
                'name': h,
                'fn': var if h == 'subdoc' else f"{h}_{var}",
                'module': found.get(h),
            })
        by_module = {}
        missing = []
        for h in hooks:
            if h['module']:
                by_module.setdefault(h['module'], []).append(h['fn'])
            else:
                missing.append(h['fn'])
        var_rows.append({
            'name': var,
            'description': meta.get('description', ''),
            'types': types,
            'hooks': hooks,
            'wiring': [{'module': m, 'hooks': fns} for m, fns in by_module.items()],
            'missing_hooks': missing,
            # plaque quick-filters (debug-vars.html)
            'found_any': any(var in t['found'] for t in template_data),
            'hooks_any': any(h['module'] for h in hooks),
        })

    hooks_total = sum(len(r['hooks']) for r in var_rows)
    hooks_wired = sum(1 for r in var_rows for h in r['hooks'] if h['module'])

    # Unexpected vars: found in templates but NOT in descr.docx
    unexpected_vars = sorted(analysis['all_template_vars'] - set(variable_desc))

    return render_template(
        'debug-vars.html',
        packs=packs,
        active_pack=pack['identifier'],
        pack_description=pack.get('description') or '',
        var_rows=var_rows,
        unexpected_vars=unexpected_vars,
        templates=template_data,
        dropped=hook_report['dropped'],
        hook_errors=hook_report['errors'],
        stats={
            'templates': len(template_data),
            'expected': len(var_rows),
            'found': len(analysis['all_template_vars'] & set(variable_desc)),
            'unexpected': len(unexpected_vars),
            'hooks_wired': hooks_wired,
            'hooks_total': hooks_total,
        },
    )


def _cleanup_stale_sessions(document_store: Path, max_age_days: int) -> int:
    """Remove top-level entries (files + dirs) in document_store older than
    max_age_days. The store is a shared volume (Flask /document_store, nginx,
    OnlyOffice cache) that accumulates session folders and stale artifacts and
    is otherwise never cleaned; this sweeps anything past the TTL. Best-effort:
    a failure on one entry is logged and skipped, never raised (the reset must
    complete). Returns the number of entries removed.
    """
    if not document_store.is_dir():
        return 0
    cutoff = time.time() - (max_age_days * 86400)
    removed = 0
    for entry in document_store.iterdir():
        try:
            if entry.stat().st_mtime >= cutoff:
                continue
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()
            removed += 1
        except OSError as e:
            logger.warning("cleanup: could not remove %s: %s", entry.name, e)
    if removed:
        logger.debug("cleanup: removed %d stale entr%s from %s",
                     removed, 'y' if removed == 1 else 'ies', document_store)
    return removed


@debug_bp.route('/reset')
def reset_session():
    """Clear session data, sweep stale document-store entries, show the
    auto-redirect reset page."""
    session.clear()
    _cleanup_stale_sessions(cfg.document_store, DATA_TTL_DAYS)
    return render_template('reset.html', url='/init')


# ------------------------------------------------------------------
# Inflection Admin UI
# ------------------------------------------------------------------

_INFLECTION_CASE_NAMES = {
    "no": "именительный", "ge": "родительный", "da": "дательный",
    "ac": "винительный", "in": "творительный", "pre": "предложный"
}


def _conflict_case_codes(existing_word: dict, new_word: dict | None) -> list[str]:
    """Case codes rendered as conflict rows: both words have a value and they
    differ. Must match the case_rows kind logic in edit_inflection_page."""
    codes = []
    for cc in CASE_ORDER:
        e = existing_word["forms"].get(cc)
        n = new_word["forms"].get(cc) if new_word else None
        if e is not None and n is not None and e != n:
            codes.append(cc)
    return codes


def _collect_forms(conflict_codes: list[str] | None = None) -> dict:
    """Collect case_code → value from the form.

    Simple cases submit parallel case[]/value[] lists; conflict cases submit a
    case_<code> radio (0/1) + value_<code>_<idx> text inputs, so the chosen
    option is resolved **server-side** — no JS dependency (the old rename-on-submit
    trick made the "new" value win when JS was off). Shared by the edit and
    new-word POST handlers (new-word has no conflict cases)."""
    forms = {}
    for c, v in zip(request.form.getlist('case'), request.form.getlist('value')):
        if c and v.strip():
            forms[c] = v.strip()
    for code in (conflict_codes or []):
        idx = request.form.get(f'case_{code}')
        if idx is None:
            continue
        val = request.form.get(f'value_{code}_{idx}', '').strip()
        if val:
            forms[code] = val
    return forms


@debug_bp.route('/debug/inflections')
def debug_inflections():
    """Admin UI: browse/search inflection dictionary."""
    letter = request.args.get('letter', '')
    query = request.args.get('q', '')
    page = max(1, request.args.get('page', 1, type=int))
    page_size = 50

    words = []
    if query:
        words = search_words(query)
    else:
        words = list_words(letter=letter, page=page, page_size=page_size)

    # Compact filter bar: only first letters that actually have words,
    # so the browse filter isn't a giant grid of mostly-empty links. Search
    # mode doesn't use the letter bar, so skip the (unused) count query there.
    letter_counts = get_letter_counts() if not query else {}

    # Order: Cyrillic first, then Latin, then digits — matches how a Russian
    # dictionary is usually browsed.
    def _letter_key(item):
        ch = item[0]
        if 'Ѐ' <= ch <= 'ӿ':
            return (0, ch)
        elif ch.isdigit():
            return (2, ch)
        else:
            return (1, ch)
    letter_counts = dict(sorted(letter_counts.items(), key=_letter_key))

    # Last-page detection for the "Next" link (browse mode only — search
    # results are a single capped list, not paginated).
    has_next = (not query) and len(words) >= page_size

    # Real total for the current filter (browse mode) — the subtitle shows this
    # instead of the page's count. Search is a capped list, so no total there.
    total_words = count_words(letter) if not query else None

    return render_template(
        'debug_inflections.html',
        words=words,
        query=query,
        letter=letter,
        page=page,
        letter_counts=letter_counts,
        has_next=has_next,
        total_words=total_words,
    )


@debug_bp.route('/debug/inflections/search', methods=['GET'])
def debug_inflections_search():
    """JSON search endpoint for autocomplete."""
    q = request.args.get('q', '')
    results = search_words(q) if q else []
    return jsonify([
        {"word_id": w["word_id"], "nominative": w["nominative"]}
        for w in results
    ])


@debug_bp.route('/debug/inflections/<int:word_id>', methods=['DELETE'])
def delete_inflection(word_id):
    """Delete a word from the dictionary."""
    delete_word(word_id)
    return jsonify({"ok": True})


@debug_bp.route('/debug/inflections/<int:word_id>/edit', methods=['GET', 'POST'])
def edit_inflection_page(word_id):
    """Edit word form, optionally resolving a conflict via merge."""
    word = get_word(word_id)

    # Conflict merge context — check query string (GET) and form body (POST).
    # Loaded before the missing-word check: a merge whose existing word was
    # deleted still needs the conflict to offer a recovery view (not orphan it).
    conflict_id = request.args.get('merge', type=int) or request.form.get('_merge', type=int)
    conflict = None
    new_word = None
    if conflict_id:
        conflict = get_conflict_with_words(conflict_id)
        if conflict is None:
            flash("Конфликт не найден", "error")
            return redirect("/debug/inflections")
        # The merge must target the conflict's existing word — a stale or
        # hand-edited URL must not fold forms into a different word_id.
        if word_id != conflict["existing_word_id"]:
            flash("Конфликт не относится к этому слову", "error")
            return redirect("/debug/inflections")
        new_word = conflict.get("new_word") if conflict else None

    if word is None:
        if conflict_id and conflict:
            # The existing word was deleted after the conflict was logged. Don't
            # orphan the conflict: offer to discard it, or to save the word that
            # triggered it (pre-populated from the conflict's forms) as new.
            return render_template(
                'edit_inflection.html',
                word=None,
                conflict=conflict,
                new_word=new_word,
                missing_existing=True,
                case_names=_INFLECTION_CASE_NAMES,
            )
        flash("Слово не найдено", "error")
        return redirect("/debug/inflections")

    if request.method == 'POST':
        # Collect case_code → value from form. Disputed cases (both words have a
        # differing value) are read via their radio + named value inputs, so the
        # admin's choice is honored server-side even with JS off.
        conflict_codes = _conflict_case_codes(word, new_word) if conflict_id else []
        forms = _collect_forms(conflict_codes)

        # If resolving a conflict: remove the "new" word first so its forms no
        # longer occupy UNIQUE slots, then write the chosen values into this
        # word. This makes the merge actually apply the admin's selection.
        if conflict_id and new_word and new_word.get("word_id") and new_word["word_id"] != word_id:
            nw_id = new_word["word_id"]
            # Only delete if it still exists (a stale conflict may point at a
            # word an admin already removed)
            if get_word(nw_id) is not None:
                delete_word(nw_id)

        # Replace (not append) — so the admin can actually change a form value
        # or drop a case by clearing it.
        if forms:
            replace_word(word_id, forms)
            msg = "Сохранено"
        else:
            delete_word(word_id)
            msg = "Все формы пусты — слово удалено"

        # If resolving a conflict, clean up — runs in both branches, so the
        # empty-forms path can't early-return and orphan the conflict.
        if conflict_id:
            delete_conflict(conflict_id)

        flash(msg, "success")
        return redirect("/debug/inflections")

    # GET — build case rows for the form
    case_names = _INFLECTION_CASE_NAMES

    # Always show all 6 standard cases so missing forms are visible and can be
    # filled in, instead of only the cases already stored.
    all_codes = list(CASE_ORDER)

    case_rows = []
    for cc in all_codes:
        existing_val = word["forms"].get(cc)
        new_val = new_word["forms"].get(cc) if new_word else None

        if new_val is not None and existing_val is not None:
            if existing_val == new_val:
                # Same form — single field
                case_rows.append({"code": cc, "kind": "simple", "value": existing_val})
            else:
                # Conflict — two options
                case_rows.append({
                    "code": cc, "kind": "conflict",
                    "options": [
                        {"idx": 0, "label": "Существующее", "value": existing_val},
                        {"idx": 1, "label": "Новое", "value": new_val},
                    ]
                })
        elif existing_val is not None:
            case_rows.append({"code": cc, "kind": "simple", "value": existing_val})
        else:
            case_rows.append({"code": cc, "kind": "simple", "value": new_val or ""})

    return render_template(
        'edit_inflection.html',
        word=word,
        conflict=conflict,
        new_word=new_word,
        case_rows=case_rows,
        case_names=case_names,
    )


@debug_bp.route('/debug/inflections/new', methods=['GET', 'POST'])
def new_inflection():
    """Add a new word to the dictionary (admin).

    GET accepts ?from_conflict=<id> to pre-populate the form from a conflict's
    submitted forms — used by the missing-word recovery view, where the word that
    triggered the conflict can be saved as new instead of lost."""
    if request.method == 'POST':
        forms = _collect_forms()
        from_conflict = request.form.get('_from_conflict', type=int)

        # save_word skips single-form words (abbreviations are not learned),
        # so only two or more filled cases produce a real dictionary entry.
        # save_word returns None on a failed insert — don't report success then.
        if len(forms) > 1:
            if save_word(forms) is not None:
                flash("Слово добавлено", "success")
                # Saving the word that triggered a conflict resolves it — dismiss
                # so the recovery flow doesn't leave an orphaned conflict behind.
                if from_conflict:
                    delete_conflict(from_conflict)
            else:
                flash("Не удалось добавить слово", "error")
        else:
            flash("Заполните хотя бы два падежа", "error")
        return redirect("/debug/inflections")

    # Pre-populate from a conflict's submitted forms (missing-word recovery).
    from_conflict = request.args.get('from_conflict', type=int)
    pre_forms = {}
    if from_conflict:
        conflict = get_conflict_with_words(from_conflict)
        if conflict and conflict.get("new_forms_json"):
            pre_forms = conflict["new_forms_json"]

    case_rows = [
        {"code": cc, "kind": "simple", "value": pre_forms.get(cc, "")}
        for cc in CASE_ORDER
    ]
    return render_template(
        'edit_inflection.html',
        word={"word_id": 0, "forms": {}, "nominative": ""},
        conflict=None,
        new_word=None,
        case_rows=case_rows,
        case_names=_INFLECTION_CASE_NAMES,
        is_new=True,
        # Only note it when the pre-population actually applied (a stale id
        # leaves the form blank — no need to claim a source then).
        from_conflict=from_conflict if pre_forms else None,
    )


@debug_bp.route('/debug/inflections/conflicts')
def debug_conflicts():
    """Admin UI: view conflicts."""
    page = max(1, request.args.get('page', 1, type=int))
    page_size = 50
    conflicts = get_conflicts(page=page, page_size=page_size)

    return render_template(
        'debug_conflicts.html',
        conflicts=conflicts,
        page=page,
        has_next=len(conflicts) >= page_size,
    )


@debug_bp.route('/debug/inflections/conflicts/<int:conflict_id>', methods=['DELETE'])
def dismiss_conflict(conflict_id):
    """Dismiss a conflict entry."""
    delete_conflict(conflict_id)
    return jsonify({"ok": True})


@debug_bp.route('/debug/inflections/conflicts/<int:conflict_id>/dismiss', methods=['POST'])
def dismiss_conflict_form(conflict_id):
    """No-JS dismiss (the missing-word recovery page): dismiss + redirect."""
    delete_conflict(conflict_id)
    flash("Конфликт отклонён", "success")
    return redirect("/debug/inflections/conflicts")
