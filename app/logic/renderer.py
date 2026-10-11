# logic/renderer.py
from __future__ import annotations

import logging
logger = logging.getLogger(__name__)

from pathlib import Path
from typing import List, Dict, Any
from docxtpl import DocxTemplate

from logic.subdoc_helper import DeferredSubdoc


def render_templates(
    templates: List[Path],
    context: "DataContext",
    store_dir: Path,
    subdoc_funcs: Dict[str, Any] | None = None,
    errors_out: List[tuple[str, str]] | None = None,
) -> List[Path]:
    """
    Render DOCX templates with variables and subdoc functions.

    Loads each template directly as DocxTemplate, executes deferred subdoc
    functions, renders variables, and saves output files.

    Args:
        templates: List of template file paths.
        context: DataContext with computed variable values.
        store_dir: Directory to save generated documents.
        subdoc_funcs: Deferred subdoc functions (table extractors, bookmark
            subdocs, etc.) called at render time.
        errors_out: Optional list; when provided, each template that fails to
            render appends a (template_name, reason) tuple here so the caller
            can warn the user. When omitted, failures are only logged.

    Returns:
        List of successfully rendered output file paths (failed templates are
        skipped, so a shorter list than `templates` means partial failure).
    """
    session_path = store_dir
    outputs: List[Path] = []

    if subdoc_funcs is None:
        subdoc_funcs = {}

    for tmpl_path in templates:
        try:
            # Load template directly as DocxTemplate
            tpl = DocxTemplate(tmpl_path)

            logger.debug(f"Renderer received context fields: {list(context.__dataclass_fields__)}")

            data_dict = {field: context.__dict__[field] for field in context.__dataclass_fields__}

            logger.debug(f"Wrapping subdoc functions: {list(subdoc_funcs.keys())}")
            for var_name, func in subdoc_funcs.items():
                if callable(func):
                    logger.debug(f'Wrapping subdoc function for {var_name}')
                    data_dict[var_name] = DeferredSubdoc(func, tpl, data_dict, name=var_name)

            logger.debug("Context: %s", data_dict)

            tpl.render(data_dict)
            out_name = f"generated_{tmpl_path.name}"
            out_path = session_path / out_name
            tpl.save(out_path)
            logger.debug(f"Generated file saved: {out_path}")

            outputs.append(out_path)

        except Exception as e:
            logger.error(f"Error processing template {tmpl_path}: {e}")
            if errors_out is not None:
                errors_out.append((tmpl_path.name, str(e)))
            continue

    return outputs
