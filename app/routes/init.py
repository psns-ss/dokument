"""
Init route for document generation form.

Routes:
    GET  /init - Show initialization form, clear session,
                 call init hooks for vars_need_init_form
    POST /init - Save form data, handle file upload, run matching,
                 enrich matched_entities, generate dynamic UI,
                 return step 2 or auto-submit
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from pathlib import Path

from flask import Blueprint, request, session, render_template, url_for, redirect, flash
from werkzeug.utils import secure_filename

from config import cfg, ensure_active_pack
from pack_manager import validate_pack, resolve_pack_paths, resolve_pack_dirs
from session_manager import SessionManager
from logic.matching import run_matching
from logic.dynamic_ui import build_dynamic_ui_block, DynamicUIBlock, dynamic_ui_hash
from logic.parser import read_variable_descriptions
from logic.hints_builder import build_hints_collections
from logic.context_manager import load_data_context_for_pack

init_bp = Blueprint('init', __name__, template_folder='html_helpers')
logger = logging.getLogger(__name__)

# Prepositional-form case names for the inflection inputs ("в именительном падеже").
# Distinct from debug.py's nominative-form _INFLECTION_CASE_NAMES (a different
# grammatical form for the admin labels), so not a shared constant.
_CASE_NAMES = {
    "no": "именительном", "ge": "родительном", "da": "дательном",
    "ac": "винительном", "in": "творительном", "pre": "предложном"
}


def process_init_form(session, variable_desc, hints, logic_dir, matching_needed=True):
    """Save the POSTed form + files to the session, then run matching.

    Extracted from POST /init so the headless POST /download can reuse the exact
    pipeline (form-save, inflection consolidation, file uploads, matching) without
    the dynamic-UI / hash-guard tail. Reads the request context
    (request.form / request.files); mutates the passed session dict.

    matching_needed=False (headless) skips the matching pass + the init-form enrich —
    the caller supplies static picks, so match output would be unused.

    Returns matched_entities (dict) for the dynamic-UI tail; empty when
    matching_needed is False.
    """
    session_mgr = SessionManager(session)
    form_data = request.form.to_dict()

    # Save user variables to session
    session_mgr.save_form_data(form_data)

    # ui_hash is a convergence guard that travels in the form field, not the
    # session — drop the session copy so it doesn't linger between requests.
    session.pop('ui_hash', None)

    # Collect inflected form inputs into dicts + clean up scatter keys.
    # Runs between save_form_data() and get_form_data() so that consolidated
    # dicts are included in session_data passed to the template.
    for _var_name, _meta in variable_desc.items():
        _cases = (_meta.get("options") or {}).get("text")
        if not _cases:
            continue
        _forms = {}
        _present = False
        try:
            for _case in _cases:
                _key = f"{_var_name}__{_case}"
                if _key in form_data:
                    _present = True
                    _val = form_data[_key].strip()
                    if _val:
                        _forms[_case] = _val
        finally:
            # Always remove scatter keys, even if consolidation fails mid-way
            # (an exception must not orphan __{case} keys in the session).
            for _case in _cases:
                session.pop(f"{_var_name}__{_case}", None)
        # Only overwrite when the form actually carried the case inputs — an absent
        # set (embedded/automated POST) must not wipe a previously stored value.
        if _present:
            session[_var_name] = _forms

    # ---- Dynamic file upload handling (type=file variables) ----
    # Single pass over variable_desc: ensure each file var has a stored list, then
    # process its upload. Replace semantics: the submitted selection is the truth.
    # Browsers re-send selected files on every form submission (back/refresh
    # resubmit), so files are content-addressed (var + session_id + content hash)
    # and identical content reuses its existing path instead of accumulating copies.
    uploaded_files = session.setdefault('uploaded_files', {})
    session_id = session['session_id']
    for var_name, meta in variable_desc.items():
        types_list = meta.get('types', [meta.get('type', 'text')])
        if 'file' not in types_list:
            continue

        # Ensure the var has a key (keeps the stored list when no upload this round)
        uploaded_files.setdefault(var_name, [])

        # getlist() supports multiple files per variable (HTML input with "multiple")
        parts = request.files.getlist(var_name)
        if not parts:
            continue  # input absent from this form (e.g. step-2 page) — keep stored list

        session_path = cfg.document_store / session_id
        session_path.mkdir(parents=True, exist_ok=True)

        new_paths = []
        for file in parts:
            if not file or not file.filename:
                continue  # input present but empty/cleared

            # Content hash → stable, deduplicating filename
            file.seek(0)
            hasher = hashlib.sha256()
            for chunk in iter(lambda: file.read(65536), b''):
                hasher.update(chunk)
            digest = hasher.hexdigest()
            file.seek(0)

            # No extension → store without one (don't mislabel as .docx, which
            # OnlyOffice would then fail to open).
            ext = Path(secure_filename(file.filename)).suffix
            path = session_path / f"{var_name}_{session_id}_{digest[:16]}{ext}"
            if not path.exists():
                file.save(str(path))

            new_paths.append(str(path))

        # Submitted selection replaces the stored list (empty if the input was cleared)
        uploaded_files[var_name] = new_paths

    # Force Flask to mark session dirty — mutating the nested dict doesn't
    # trigger the session's modified flag, so reassign the top-level key.
    session['uploaded_files'] = uploaded_files

    # Run matching (skipped headless — the caller's static picks bypass it, so the
    # (unused) cv-scan is avoided). match_* plugins access session['uploaded_files']
    # directly; results stay local — the user's selection arrives as ordinary form
    # fields, so nothing is persisted for /generate.
    matched_entities = {}
    if matching_needed:
        try:
            matched_entities = run_matching(session, hints, logic_dir)
        except Exception as e:
            logger.warning(f"Matching failed (continuing without): {e}")
        # Always enrich vars_need_init_form so their init hooks fire on POST, even
        # if run_matching() returned empty (e.g. no match vars in this pack).
        for var in hints.vars_need_init_form:
            matched_entities.setdefault(var, [])
    return matched_entities


@init_bp.route('/init', methods=['GET', 'POST'])
def show_form():
    """Handle initialization form - GET shows form, POST processes submission."""
    # Ensure active pack is set; redirect to /select if not available
    active_identifier = ensure_active_pack(session)
    if active_identifier is None:
        return redirect(url_for('select.select_pack'))

    # Validate pack still exists
    valid, error = validate_pack(cfg.templates_dir, active_identifier)
    if not valid:
        session.pop('active_pack', None)
        flash(f"Выбранный набор шаблонов недоступен: {error}")
        return redirect(url_for('select.select_pack'))

    # Resolve all pack paths from the identifier (thread-safe) — reading
    # cfg.descr_file/logic_dir would race under gthread (they derive from the
    # process-global cfg.active_pack). Same pattern as select.py.
    descr_path, lang_path = resolve_pack_paths(cfg.templates_dir, active_identifier)
    _pack_dir, logic_dir = resolve_pack_dirs(cfg.templates_dir, active_identifier)

    # Parse descr.docx ONCE and share the result (DataContext + hints both
    # consume it) — avoids re-opening the docx per request.
    variable_desc = read_variable_descriptions(descr_path, lang_path)

    # Load DataContext for this pack (reuses the parsed variable_desc)
    load_data_context_for_pack(descr_path, lang_path, variable_desc)

    # Ensure session_id is set (persisted across GET → POST → /generate)
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())

    hints = build_hints_collections(variable_desc)

    # Use SessionManager for all session operations
    session_mgr = SessionManager(session)

    if request.method == 'GET':
        # First visit - clear old session data
        session_mgr.clear_for_init()

        # Fire ALL init_<var>() hooks for vars_need_init_form with an empty
        # matched_list — the same shared helper as POST (dict order = descr order).
        # The hash is on the UNRENDERED template (stable — no user input); render
        # strictly post-hash so a fresh pick can't move the hash.
        block = build_dynamic_ui_block(
            {var: [] for var in hints.vars_need_init_form},
            session, logic_dir, variable_desc,
        )

        return render_template(
            "init.html",
            variable_desc=variable_desc,
            session_data={},
            dynamic_ui=block.render(session),
            ui_hash=block.ui_hash,
            case_names=_CASE_NAMES,
        )

    # POST request - process form submission
    matched_entities = process_init_form(session, variable_desc, hints, logic_dir)
    session_data = session_mgr.get_form_data()

    # Build the dynamic-UI block (generate + checksum) if there's anything to
    # render (match results OR form hooks). Generation is optional — a failure
    # degrades to an empty block.
    if matched_entities:
        try:
            block = build_dynamic_ui_block(matched_entities, session, logic_dir, variable_desc)
        except Exception as e:
            # Log error but continue - the dynamic UI is optional
            logger.warning(f"build_dynamic_ui_block failed (continuing without): {e}")
            block = DynamicUIBlock.empty()
    else:
        block = DynamicUIBlock.empty()

    # Hash-based convergence guard:
    # block.ui_hash is over the UNRENDERED template — it carries no user input, so
    # a fresh pick doesn't move it (picks are session.get(...) tags filled in
    # post-hash by block.render()). The hash travels in a hidden form field (not
    # the session) so it stays tied to the page the user submitted.
    #
    # - Empty block (no dynamic UI) → auto-submit
    # - Hash matches the form's → stabilized → auto-submit
    # - Hash differs, or no hash in the form (embedded/automated POST) → show step 2
    form_hash = request.form.get('ui_hash')

    if block.is_empty():
        logger.info("Hash guard: no dynamic UI → auto-submit to /generate")
        return render_template(
            'auto_submit.html',
            action_url=url_for('generate.generate_documents')
        )

    if block.ui_hash == form_hash:
        # Hash stabilized — auto-submit
        logger.info("Hash guard: converged (hash matched) → auto-submit to /generate")
        return render_template(
            'auto_submit.html',
            action_url=url_for('generate.generate_documents')
        )

    # Structure changed (hash differs) or first render (no hash in form)
    # → show form with dynamic UI
    reason = "hash differs" if form_hash else "no hash in form (embedded POST)"
    logger.debug(f"Hash guard: {reason} → render form with dynamic UI")
    return render_template(
        "init.html",
        variable_desc=variable_desc,
        session_data=session_data,
        dynamic_ui=block.render(session),   # post-hash render (lazy)
        ui_hash=block.ui_hash,
        case_names=_CASE_NAMES,
    )
