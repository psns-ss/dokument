"""
Template variable analysis — the data source for /debug-vars.

Compares the variables extracted from the templates against those declared in
descr.docx (present / missing / unexpected). No Flask code — pure
"data → analysis dict".
"""
from __future__ import annotations
from .extractor import variables_from_docx
from pathlib import Path
import logging

# Logger
logger = logging.getLogger(__name__)


def analyze_template_variables(template_paths: list, variable_desc: dict) -> dict:
    """
    Collects per-variable statistics across all templates.

    Takes the already-parsed variable_desc (the caller — /debug-vars — parses
    descr.docx once and shares it), so this doesn't re-open the docx.
    """
    all_variables = set()
    template_details = {}

    # Expected variables (the descr var names), from the caller's parse.
    expected_vars = set(variable_desc)

    for path in template_paths:
        try:
            vars_in_template = variables_from_docx(Path(path))
        except Exception as e:
            # A broken template must not kill the whole analysis — mark it and move on
            logger.error(f"analyze_template_variables: {path}: {e}")
            template_details[path] = {
                'error': str(e),
                'present_vars': [],
                'missing_expected': [],
                'extra_vars': []
            }
            continue
        all_variables.update(vars_in_template)
        template_details[path] = {
            'present_vars': sorted(vars_in_template),
            'missing_expected': sorted(expected_vars - vars_in_template),
            'extra_vars': sorted(vars_in_template - expected_vars)
        }

    result = {
        'all_template_vars': all_variables,
        'template_details': template_details
    }
    
    logger.debug(f"analyze_template_variables returning: {type(result)}")
    logger.debug(f"Keys in result: {result.keys()}")
    
    return result
