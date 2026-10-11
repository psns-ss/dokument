"""
Inflection AJAX endpoints.
"""
import logging

from flask import Blueprint, request, jsonify
from logic.inflection_db import lookup_by_form

inflection_bp = Blueprint('inflection', __name__)
logger = logging.getLogger(__name__)


@inflection_bp.route('/inflection/lookup')
def lookup():
    """AJAX endpoint: lookup inflected forms by word and case.

    A DB hiccup must not 500 the per-keystroke auto-fill — degrade to an
    empty result (the field simply gets no suggestions).
    """
    word = request.args.get('word', '')
    case_code = request.args.get('field', '')
    try:
        forms = lookup_by_form(case_code, word)
    except Exception as e:
        logger.warning(f"inflection lookup failed ({case_code!r}, {word!r}): {e}")
        return jsonify({})
    return jsonify(forms or {})
