"""
Pack selection route for multi-template-pack support.
"""
from flask import Blueprint, request, session, redirect, url_for, render_template, flash
from config import cfg
from pack_manager import discover_packs, validate_pack, resolve_pack_paths
from logic.context_manager import load_data_context_for_pack
from session_manager import SessionManager

select_bp = Blueprint('select', __name__, template_folder='html_helpers')


@select_bp.route('/select', methods=['GET', 'POST'])
def select_pack():
    """Show pack selection or auto-select if only one pack exists."""
    if request.method == 'POST':
        selected_identifier = request.form.get('selected_pack')
        if selected_identifier:
            # Validate pack exists and is valid
            valid, error = validate_pack(cfg.templates_dir, selected_identifier)
            if not valid:
                flash(f"Набор шаблонов '{selected_identifier}' недоступен: {error}")
                packs = discover_packs(cfg.templates_dir)
                return render_template("select.html", packs=packs, error=None)

            # Validate pack is not disabled
            packs = discover_packs(cfg.templates_dir)
            selected_pack = next((p for p in packs if p['identifier'] == selected_identifier), None)
            if selected_pack and selected_pack['is_disabled']:
                flash(f"Набор шаблонов '{selected_identifier}' недоступен: {selected_pack['error']}")
                return render_template("select.html", packs=packs, error=None)

            # Resolve paths explicitly — avoids cfg.active_pack race condition
            descr_path, lang_path = resolve_pack_paths(cfg.templates_dir, selected_identifier)

            # Load DataContext class for this thread
            load_data_context_for_pack(descr_path, lang_path)

            # Clear session data from the previous pack — but only if the pack
            # actually changed (re-selecting the current pack must not wipe progress).
            if session.get('active_pack') != selected_identifier:
                SessionManager(session).clear_for_pack_switch()

            # Set active pack in config (for property lookups in subsequent routes)
            cfg.active_pack = selected_identifier
            session['active_pack'] = selected_identifier

            return redirect(url_for('init.show_form'))

    # TODO: Cache discover_packs() result (60s TTL or file-watch).
    # Currently scans all descr.docx files on every request.
    packs = discover_packs(cfg.templates_dir)

    if not packs:
        return render_template("select.html", packs=[], error="No template packs found.")

    available = [p for p in packs if not p['is_disabled']]
    if not available:
        return render_template("select.html", packs=packs,
            error="Нет доступных наборов шаблонов")

    if len(available) == 1:
        pack = available[0]
        descr_path, lang_path = resolve_pack_paths(cfg.templates_dir, pack['identifier'])
        load_data_context_for_pack(descr_path, lang_path)
        cfg.active_pack = pack['identifier']
        session['active_pack'] = pack['identifier']
        return redirect(url_for('init.show_form'))

    return render_template("select.html", packs=packs, error=None)
