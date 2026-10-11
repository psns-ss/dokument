"""
OnlyOffice editor HTML generation utilities.

Provides functionality to generate HTML wrappers for documents
that will be edited in OnlyOffice.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from config import jinja_env


def generate_editor_html(session_dir: str,
                         docx_filename: str,
                         docx_public_url: str) -> str:
    """
    Render editor_template.html to session_dir/<docx_filename>.html
    and return the public URL to this .html file.

    Args:
        session_dir: Directory where the HTML file will be written
        docx_filename: Name of the document (used to name the HTML file)
        docx_public_url: Public URL path to the document

    Returns:
        Public URL path to the generated HTML editor wrapper
    """
    html_filename = f"{docx_filename}.html"
    html_path = Path(session_dir) / html_filename

    # Title: the template name without the renderer's "generated_" prefix and
    # the "template_" naming prefix (generated_template_1.docx -> "1").
    title = Path(docx_filename).stem
    for _prefix in ("generated_", "template_"):
        if title.startswith(_prefix):
            title = title[len(_prefix):]

    template = jinja_env.get_template("editor_template.html")
    rendered = template.render(
        title=title,
        key=str(uuid.uuid4()),
        url=docx_public_url
    )

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(rendered)

    session_id = Path(session_dir).name
    return f"/documents/{session_id}/{html_filename}"
