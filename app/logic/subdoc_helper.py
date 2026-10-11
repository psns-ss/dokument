# logic/subdoc_helper.py
"""
Subdocument helper utilities.

Provides unified subdoc creation with optional sandwich rendering
(rendering Jinja placeholders inside inserted content before Subdoc creation).
"""
import io
import logging
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docxtpl import DocxTemplate, Subdoc

logger = logging.getLogger(__name__)


class DeferredSubdoc:
    """Lazy-evaluated subdoc wrapper.

    Holds a subdoc function + rendering context. Only calls the function
    when Jinja2 stringifies the object during tpl.render(), or when
    attribute access is used (dict-of-Subdocs case).

    Not callable — ensures Jinja2 treats it as a value (invokes __str__)
    rather than trying to call it as a zero-arg function.
    """

    __slots__ = ('_func', '_name', '_tpl', '_data', '_result')

    def __init__(
        self,
        func: Any,
        tpl: "DocxTemplate",
        data_dict: Dict[str, Any],
        name: str = "",
    ):
        self._func = func
        self._name = name or getattr(func, '__name__', '')
        self._tpl = tpl
        self._data = data_dict
        self._result = None  # cached after first evaluation

    def _eval(self) -> Any:
        """Execute the subdoc function (lazy, cached).

        Catches exceptions and logs them — returns None on failure
        so rendering can continue gracefully.
        """
        if self._result is None:
            try:
                self._result = self._func(self._tpl, **self._data)
            except Exception as e:
                logger.error(f"Error executing subdoc function {self._name}: {e}")
                self._result = None
        return self._result

    def __str__(self) -> str:
        """Called by Jinja2 when the variable appears in template.

        Single Subdoc → return its XML.
        Dict of Subdocs → empty string (accessed via __getattr__ instead).
        """
        result = self._eval()
        if result is None:
            return ""
        if isinstance(result, dict):
            return ""
        return str(result)

    def __getattr__(self, name: str) -> Any:
        """Support dict-style attribute access: {{p var.key}}.

        Evaluates the function, looks up the key in the result dict.
        For single Subdoc results, forwards attribute access.
        """
        # Dunder/private lookups (copy/pickle probe __copy__, __getstate__, …)
        # must not trigger _eval() early or leak dict methods — treat as missing.
        if name.startswith('_'):
            raise AttributeError(name)
        result = self._eval()
        if isinstance(result, dict):
            if name in result:
                return result[name]
        if result is not None:
            return getattr(result, name)
        raise AttributeError(name)


# ---------- private helpers: theme + numbering/styles ----------

THEME_REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme'
NUMBERING_REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering'


def _copy_theme_from_tpl(tpl: DocxTemplate, target_doc: Document) -> None:
    """Copy raw theme XML from tpl (base template) to target doc.

    Prevents font mismatch when subdoc content carries theme-based font
    references (<w:rFonts w:asciiTheme="minorHAnsi"/>) that would resolve
    against the default theme (Cambria/Calibri) of a fresh Document().

    Uses tpl.get_docx() to access the lazily-loaded Document part —
    no redundant file read.
    """
    src_doc = tpl.get_docx()
    src_theme_blob = None
    for rel in src_doc.part.rels.values():
        if rel.reltype == THEME_REL:
            src_theme_blob = rel.target_part.blob
            break
    if src_theme_blob:
        for rel in target_doc.part.rels.values():
            if rel.reltype == THEME_REL:
                # Private API (python-docx): swap the theme part's blob in place.
                # Fragile across versions — logged so a breakage is visible.
                logger.debug("Swapping theme blob via private _blob")
                rel.target_part._blob = src_theme_blob
                break


def _copy_numbering_and_styles(source_doc: Document, target_doc: Document) -> None:
    """Copy numbering part and styles from source to target document.

    Preserves list definitions and style references when copying content
    from a donor document into a fresh Document().

    Errors are silently ignored — not all documents have numbering/styles
    parts, and missing parts are non-fatal.
    """
    try:
        # Probe rels first — accessing .numbering_part auto-creates an empty
        # part, which would mutate the donor document.
        if any(rel.reltype == NUMBERING_REL for rel in source_doc.part.rels.values()):
            target_doc.part.numbering_part._element = deepcopy(
                source_doc.part.numbering_part._element
            )
    except Exception as e:
        logger.debug("Copying numbering part failed: %s", e)
    try:
        if hasattr(source_doc.part, '_styles_part') and source_doc.part._styles_part:
            target_doc.part._styles_part._element = deepcopy(
                source_doc.part._styles_part._element
            )
    except Exception as e:
        logger.debug("Copying styles part failed: %s", e)


# ---------- unified subdoc creation ----------

def create_subdoc_sandwich(
    tpl: DocxTemplate,
    elements: list,
    context_data: dict,
    source_doc: Optional[Document] = None,
    render_placeholders: bool = True,
) -> Subdoc:
    """Unified subdoc creation with optional sandwich rendering.

    1. Create fresh Document()
    2. Copy theme from tpl (prevent font mismatch)
    3. Copy numbering + styles from source (if provided)
    4. Append elements to body
    5. Optionally render Jinja placeholders via DocxTemplate
    6. Return Subdoc via tpl.new_subdoc()

    Args:
        tpl: Target DocxTemplate (theme source + new_subdoc namespace).
        elements: XML elements to insert (tables, paragraphs, etc.).
        context_data: Data dict for placeholder rendering.
        source_doc: Source document for numbering + styles (optional).
        render_placeholders: If True, render Jinja placeholders in the
            subdoc content before creating the Subdoc.

    Returns:
        Subdoc ready for tpl.render() insertion.
    """
    # 1. Create fresh document
    sub_doc = Document()

    # 2. Copy theme from tpl (base template)
    _copy_theme_from_tpl(tpl, sub_doc)

    # 3. Copy numbering + styles from source (if provided)
    if source_doc is not None:
        _copy_numbering_and_styles(source_doc, sub_doc)

    # 4. Append elements (deepcopy to detach from source). Insert before the
    # body's sectPr (which must stay last) — appending after it yields invalid
    # intermediate OOXML.
    body = sub_doc._element.body
    sectPr = body.find(qn('w:sectPr'))
    for elem in elements:
        if sectPr is not None:
            sectPr.addprevious(deepcopy(elem))
        else:
            body.append(deepcopy(elem))

    # 5. Save to buffer
    buffer = io.BytesIO()
    sub_doc.save(buffer)
    buffer.seek(0)

    # 6. Optionally render Jinja placeholders
    if render_placeholders and context_data:
        rendered_tpl = DocxTemplate(buffer)
        rendered_tpl.render(context_data)
        rendered_buffer = io.BytesIO()
        rendered_tpl.save(rendered_buffer)
        rendered_buffer.seek(0)
        buffer = rendered_buffer

    return tpl.new_subdoc(buffer)


# ---------- table extraction ----------

def extract_table_as_subdoc(
    tpl: DocxTemplate,
    doc: Document,
    table_idx: int,
    context_data: Dict[str, Any],
    render_placeholders: bool = True,
) -> Subdoc:
    """Extract a table from a donor document as a Subdoc.

    Delegates to create_subdoc_sandwich() for theme copy,
    numbering/styles copy, placeholder rendering, and Subdoc creation.

    Args:
        tpl: Target DocxTemplate for Subdoc creation.
        doc: Source document containing the table.
        table_idx: Index of the table to extract.
        context_data: Data dict for placeholder rendering.
        render_placeholders: If True, render Jinja placeholders in the
            extracted table before creating the Subdoc.

    Returns:
        Subdoc with the table content (empty on error or out-of-range index).
    """
    if not 0 <= table_idx < len(doc.tables):
        return tpl.new_subdoc()  # empty fallback (also guards negative indices)
    return create_subdoc_sandwich(
        tpl, [doc.tables[table_idx]._tbl], context_data,
        source_doc=doc, render_placeholders=render_placeholders,
    )


# ---------- bookmark extraction ----------

def create_subdoc_from_bookmark(
    tpl: DocxTemplate,
    bookmark_name: str,
    source_path: Path,
    render_context: Optional[Dict[str, Any]] = None,
) -> Subdoc:
    """Extract bookmarked content from a source document as a Subdoc.

    If render_context is provided, Jinja placeholders in the extracted
    content are rendered before creating the Subdoc (sandwich rendering).

    Args:
        tpl: Target DocxTemplate for Subdoc creation.
        bookmark_name: Name of the bookmark to extract.
        source_path: Path to the source DOCX containing the bookmark.
        render_context: Optional data dict for rendering placeholders
            in the extracted content.

    Returns:
        Subdoc with the bookmarked content (empty on error).
    """
    if not source_path.exists():
        # A missing source file is an authoring mistake that would otherwise
        # degrade to an empty subdoc with no signal — log it clearly, distinct
        # from a render error (the generic handler below).
        logger.error(
            'Subdoc source file missing: %s (bookmark %s) — rendering an empty subdoc',
            source_path, bookmark_name,
        )
        return tpl.new_subdoc()
    try:
        src_doc = Document(source_path)
        body = src_doc._element.body

        # --- Bookmark extraction (preserved from current implementation) ---
        start_found = False
        paras_to_extract = []

        for i, elem in enumerate(body):
            if elem.tag.endswith('}p'):
                bookmark_starts = elem.findall(
                    './/w:bookmarkStart',
                    namespaces={'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
                )
                for bm_start in bookmark_starts:
                    bm_name = bm_start.get(qn('w:name'))
                    if bm_name == bookmark_name:
                        start_found = True
                        logger.debug(
                            'Found start of bookmark %s at position %d',
                            bookmark_name, i,
                        )
                        j = i + 1
                        while j < len(body):
                            elem2 = body[j]

                            # Check all body elements for bookmark boundaries
                            # (not just paragraphs — tables, images, etc. can carry bookmarks too)
                            bookmark_ends = elem2.findall(
                                './/w:bookmarkEnd',
                                namespaces={'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
                            )
                            found_end = False
                            for bm_end in bookmark_ends:
                                end_bm_name = bm_end.get(qn('w:name'))
                                if end_bm_name and end_bm_name != bookmark_name:
                                    logger.debug(
                                        'Stopping at position %d (end bookmark: %s)',
                                        j, end_bm_name,
                                    )
                                    found_end = True
                                    break
                            if found_end:
                                break

                            # Stop at start bookmark for a different bookmark
                            other_starts = elem2.findall(
                                './/w:bookmarkStart',
                                namespaces={'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
                            )
                            found_start = False
                            for other_bm in other_starts:
                                start_bm_name = other_bm.get(qn('w:name'))
                                if start_bm_name and start_bm_name != bookmark_name:
                                    logger.debug(
                                        'Stopping at position %d (start bookmark: %s)',
                                        j, start_bm_name,
                                    )
                                    found_start = True
                                    break
                            if found_start:
                                break

                            # Skip body-level structural elements (the last
                            # section's sectPr, a stray bookmarkEnd) — they
                            # would leak into the subdoc.
                            if not elem2.tag.endswith(('sectPr', 'bookmarkEnd')):
                                paras_to_extract.append(elem2)
                            j += 1
                        break
            if start_found:
                break

        logger.debug(
            'Found %d elements for bookmark %s',
            len(paras_to_extract), bookmark_name,
        )

        # --- Delegate subdoc creation to unified helper ---
        elements = paras_to_extract if paras_to_extract else [OxmlElement('w:p')]

        return create_subdoc_sandwich(
            tpl,
            elements,
            render_context or {},
            source_doc=src_doc,
            render_placeholders=(render_context is not None),
        )

    except Exception as e:
        logger.error('Error creating subdoc from bookmark %s: %s', bookmark_name, e)
        return tpl.new_subdoc()
