"""
Generate route for document generation.

Routes:
    POST /generate - Generate documents from templates
"""
from __future__ import annotations

import uuid
import logging
import shutil
import io

from flask import (Blueprint, request, render_template, redirect, url_for,
                   flash, session, send_file, jsonify)

from config import cfg, get_data_context, ensure_active_pack
from pack_manager import validate_pack, resolve_pack_paths, resolve_pack_dirs
from session_manager import SessionManager
from logic.context_manager import load_data_context_for_pack
from logic.computation import compute_variables
from logic.parser import read_variable_descriptions
from logic.hints_builder import build_hints_collections
from logic.renderer import render_templates
from logic.loader import find_templates, load_plugins
from logic.inflection import InflectedWord
from logic.inflection_db import enqueue_save
from logic.download import zip_generated_docs
from routes.onlyoffice import generate_editor_html
from routes.init import process_init_form

logger = logging.getLogger(__name__)

generate_bp = Blueprint('generate', __name__, template_folder='html_helpers')


def run_generation(session, variable_desc, hints, logic_dir, template_paths,
                   enqueue_inflection=True):
    """Compute missing vars + render the pack's templates.

    Extracted from POST /generate so the headless POST /download can reuse the
    exact compute+render pipeline. Reads form data from the session (populated by
    process_init_form) and renders into the session folder.

    enqueue_inflection gates the background inflection save: True for /generate
    (a human's word is worth learning), False for POST /download (a remote caller
    must not pollute the shared dictionary).

    Returns (outputs, render_errors). Raises on compute/render failure — the
    caller decides how to surface it (flash+redirect vs JSON error).
    """
    session_mgr = SessionManager(session)
    cleaned_data = session_mgr.get_form_data()
    logger.debug("SESSION FORM DATA KEYS = %s", list(cleaned_data.keys()))
    expected_vars = set(variable_desc.keys())

    modules = load_plugins(logic_dir, "compute", extra_stems=set(hints.vars_as_subdocs))
    computed_values, subdoc_functions = compute_variables(
        cleaned_data, expected_vars, hints, modules, session=session)

    final_data = {**cleaned_data, **computed_values}

    # Wrap inflected variable dicts as InflectedWord + (optionally) enqueue DB save
    for var_name, meta in variable_desc.items():
        cases = (meta.get("options") or {}).get("text")
        if not cases:
            continue
        value = final_data.get(var_name)
        if isinstance(value, InflectedWord):
            continue  # already wrapped by a compute plugin
        if not isinstance(value, dict) or len(value) == 0:
            continue
        final_data[var_name] = InflectedWord(value, cases=cases)
        if enqueue_inflection and len(value) > 1:
            enqueue_save(value)  # background queue, fire-and-forget

    # Separate plain values (everything that is not callable)
    plain_context_dict = {
        k: v for k, v in final_data.items()
        if k in expected_vars and not callable(v)
    }
    DataContext = get_data_context()
    plain_context = DataContext.from_dict(plain_context_dict)
    logger.debug(f"Final data keys: {list(final_data.keys())}")

    # Render into the session folder
    session_path = cfg.document_store / session['session_id']
    session_path.mkdir(parents=True, exist_ok=True)
    render_errors: list = []
    outputs = render_templates(
        templates=template_paths,
        context=plain_context,
        store_dir=session_path,
        subdoc_funcs=subdoc_functions,
        errors_out=render_errors,
    )
    return outputs, render_errors


# .docx MIME — sent explicitly because the single-file download is served from an
# in-memory buffer (send_file can't infer the type from a filename there).
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def build_download_response(session_dir, pack):
    """Download response for a session folder's generated docs.

    One doc → serve that .docx directly (no archive needed); more than one → a
    single ZIP. Both are read fully into memory, so the caller may delete the
    on-disk folder before the response is sent (POST /download does).
    """
    docs = sorted(session_dir.glob("generated_*.docx"))
    if len(docs) == 1:
        doc = docs[0]
        return send_file(io.BytesIO(doc.read_bytes()), mimetype=DOCX_MIME,
                         as_attachment=True, download_name=doc.name)
    return send_file(zip_generated_docs(session_dir), mimetype="application/zip",
                     as_attachment=True, download_name=f"generated_{pack}.zip")


@generate_bp.route('/generate', methods=['POST'])
def generate_documents():
    """
    Generate documents from templates.

    Process:
    1. Load form data from session (cleaned data)
    2. Read variable descriptions
    3. Compute missing variables via compute_variables()
    4. Build final context (DataContext)
    5. Render templates via render_templates() with subdoc_funcs
    6. Generate OnlyOffice editor HTML for each output
    7. Return ready.html with document links
    """
    # Sanity check: sessions are filesystem-backed, so the cookie only carries
    # the session ID — log its size to catch accidental bloat (4 KB browser limit).
    session_cookie = request.cookies.get('session', '')
    cookie_bytes = len(session_cookie.encode('latin-1'))
    logger.debug(f"Session cookie: {cookie_bytes} / 4096 bytes ({cookie_bytes / 4096 * 100:.1f}%)")

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

    # Ensure session_id is set
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())

    # Resolve all pack paths from the identifier (thread-safe) — reading
    # cfg.descr_file/pack_dir/logic_dir would race under gthread (they derive
    # from the process-global cfg.active_pack). Same pattern as select.py.
    descr_path, lang_path = resolve_pack_paths(cfg.templates_dir, active_identifier)
    pack_dir, logic_dir = resolve_pack_dirs(cfg.templates_dir, active_identifier)

    # Parse descr.docx ONCE and share the result (DataContext + hints both
    # consume it) — avoids re-opening the docx per request.
    variable_descriptions = read_variable_descriptions(descr_path, lang_path)
    hints = build_hints_collections(variable_descriptions)

    # Load DataContext for this pack (reuses the parsed variable_descriptions)
    load_data_context_for_pack(descr_path, lang_path, variable_descriptions)

    # Use pack-specific template directory (keep as Path objects for renderer)
    template_paths = find_templates(pack_dir)

    # Compute + render (extracted — shared with POST /download). The safety net
    # catches compute/render failures (bad descr, context build, ...) — flash+
    # redirect like /init and /select, not a raw Werkzeug 500.
    try:
        outputs, render_errors = run_generation(
            session, variable_descriptions, hints, logic_dir, template_paths)
    except Exception as e:
        logger.error(f"Generation failed: {e}", exc_info=True)
        flash(f"Ошибка генерации документов: {e}", "error")
        return redirect(url_for('init.show_form'))
    if not outputs:
        flash("Не удалось сгенерировать документы", "error")
        return redirect(url_for('init.show_form'))

    # Partial failure: some templates rendered, others didn't. Surface the
    # failures — they'd otherwise be silently missing from ready.html.
    if render_errors:
        failed = "; ".join(f"{name}: {reason}" for name, reason in render_errors)
        flash(f"Сгенерировано {len(outputs)} из {len(template_paths)}; не удалось: {failed}", "warning")

    # 5. OnlyOffice editors — outside the render try/except above, so guard
    # separately: a wrapper-write failure must not 500 after the docs are
    # already on disk. Per-doc, fall back to the raw .docx (still served by
    # nginx) and warn.
    session_id = session['session_id']
    failed_docs = set()
    editor_urls = {}
    for docx_path in outputs:
        docx_public_url = f"/documents/{session_id}/{docx_path.name}"
        try:
            # generate_editor_html returns the editor URL — the single source
            # of the /documents/... .html link (no separate make_public_urls pass).
            editor_urls[docx_path.name] = generate_editor_html(
                docx_path.parent, docx_path.name, docx_public_url)
        except Exception as e:
            failed_docs.add(docx_path.name)
            logger.error(f"Editor HTML failed for {docx_path.name}: {e}", exc_info=True)

    doc_links = []
    for i, docx_path in enumerate(outputs):
        name = docx_path.name
        # raw .docx fallback for docs whose editor wrapper failed to write
        editor = editor_urls.get(name, f"/documents/{session_id}/{name}")
        doc_links.append({"name": name, "editor": editor, "index": i + 1})

    if failed_docs:
        flash(f"Документы сгенерированы, но редактор не открыт для {len(failed_docs)} "
              f"из {len(outputs)} — для них ссылка ведёт на исходный .docx.", "warning")

    return render_template("ready.html", doc_links=doc_links)


@generate_bp.route('/download', methods=['GET'])
def download_get():
    """Download the current session's generated docs (interactive — after /generate).

    One doc → that .docx; more → a ZIP. Assembled on each hit (never cached) so
    post-OnlyOffice edits are reflected. The on-disk files are kept (OnlyOffice
    needs them). Logs at DEBUG.
    """
    session_dir = cfg.document_store / session.get('session_id', '')
    docs = sorted(session_dir.glob("generated_*.docx")) if session_dir.is_dir() else []
    if not docs:
        flash("Нет сгенерированных документов", "error")
        return redirect(url_for('init.show_form'))
    pack = session.get('active_pack', 'root')
    logger.debug("GET /download: session=%s pack=%s docs=%d",
                 session.get('session_id'), pack, len(docs))
    return build_download_response(session_dir, pack)


@generate_bp.route('/download', methods=['POST'])
def download_post():
    """Headless /init + /generate: POST the form fields (+ files), get the ZIP.

    A remote site's one-shot call — no session round-trip, no OnlyOffice, no init
    step-2, no matching (the caller supplies static picks). Runs on a throwaway
    session dict (the caller's cookie is never touched) in a fresh session folder,
    which is deleted right after zipping (the archive is fully in memory). Logs at
    INFO.

    TODO(auth): gate this POST (shared-secret / API-key header) — no in-app auth
    for now; expected to live outside the app (nginx or a separate entity).
    """
    # Active pack: explicit field, else the session's, else root. Resolved
    # read-only (no ensure_active_pack) so the caller's session is never mutated.
    # The run is built under that pack's constraints (required vars, compute).
    active_identifier = (request.form.get('active_pack')
                         or session.get('active_pack')
                         or 'root')
    if not validate_pack(cfg.templates_dir, active_identifier)[0]:
        return jsonify(error="pack unavailable"), 400

    # Isolated run: throwaway session dict, fresh folder.
    s = {'active_pack': active_identifier, 'session_id': str(uuid.uuid4())}

    descr_path, lang_path = resolve_pack_paths(cfg.templates_dir, active_identifier)
    pack_dir, logic_dir = resolve_pack_dirs(cfg.templates_dir, active_identifier)
    variable_desc = read_variable_descriptions(descr_path, lang_path)
    hints = build_hints_collections(variable_desc)
    load_data_context_for_pack(descr_path, lang_path, variable_desc)
    template_paths = find_templates(pack_dir)

    # Form + uploads (same code as POST /init). Matching is skipped — the caller
    # supplies static picks, so match_* output would be unused.
    process_init_form(s, variable_desc, hints, logic_dir, matching_needed=False)

    # Compute + render (same code as POST /generate). enqueue_inflection=False:
    # a remote caller must not train the shared inflection dictionary.
    try:
        outputs, _ = run_generation(s, variable_desc, hints, logic_dir, template_paths,
                                    enqueue_inflection=False)
    except Exception as e:
        logger.error(f"POST /download generation failed: {e}", exc_info=True)
        return jsonify(error="generation failed"), 500
    if not outputs:
        logger.info("POST /download: pack=%s session=%s -> no outputs",
                    active_identifier, s['session_id'])
        return jsonify(error="generation failed"), 500

    logger.info("POST /download: pack=%s session=%s outputs=%d",
                active_identifier, s['session_id'], len(outputs))
    session_dir = cfg.document_store / s['session_id']
    response = build_download_response(session_dir, active_identifier)
    shutil.rmtree(session_dir, ignore_errors=True)  # response is in memory; drop the on-disk run
    return response
