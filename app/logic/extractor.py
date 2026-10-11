# logic/extractor.py
# Extracts variable names from a DOCX file
# (word/document.xml, headers, footers, footnotes, endnotes)
#
# A diagnostic tool (its consumer is /debug-vars), so the goal is to
# miss no docxtpl form and reduce it to the base variable:
#   {{var}}                        -> var
#   {{var.case}}                   -> var   (inflection / attribute access)
#   {{p var}} / {{l var}} / {{t var}} -> var (docxtpl rich-tags)
#   {{! var}}                      -> var   (safe mode)
#   {{p var[0]}}                   -> var   (index / subscript)
#   {{# var}} / {{/ var}}          -> var   (loop tags)
#   {{var[key]}}                   -> var + key  (identifier in a subscript —
#                                                 a context lookup:
#                                                 {{h[msu]}} looks up msu in the data)
#   {% if var ... %}               -> var   (condition)
#   {%p if var ... %}              -> var   (docxtpl paragraph block-tag:
#                                                 docxtpl strips the <w:p> wrapper
#                                                 and the "p " prefix before Jinja)
#   {% for x in var %}             -> var   (iterable; x is local)
#
# Loop-local names (for targets) are collected per XML part and subtracted at
# the end: {{u.full}} inside "for u in university" does not yield "u". Scope is
# approximated per part, not per block — good enough for diagnostics.

import re
import zipfile
import html
from pathlib import Path
from typing import Set

# DOCX parts we search for variables in: document + ANY headerN/footerN
# (no artificial cap at 10) + footnotes/endnotes.
_PART = re.compile(
    r"^word/(?:document|footnotes|endnotes)\.xml$"
    r"|^word/(?:header|footer)\d+\.xml$"
)

# Paragraph tag <w:p> (with attributes) or its close </w:p>.
# (?:\s[^>]*)? allows attributes but does not match <w:pPr>/<w:tab> etc.
# Self-closing <w:p .../> also matches — _paragraphs skips them
# (they have no body and no closing tag; counting them as an open would
# break the nesting counter for the rest of the document).
_P_TAG = re.compile(r"<w:p(?:\s[^>]*)?>|</w:p>")
_TEXT = re.compile(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>", re.DOTALL)

# One regex: an optional tag (p/l/t/#//! + space) and the base identifier.
# \s+ after a one-letter tag prevents reading a variable named, say, "p"
# as a tag. The identifier is taken up to "." / "[" / space.
VAR_NAME = re.compile(r"\{\{\s*(?:[plt#/]\s+|!\s+)?([A-Za-z_]\w*)")

# Full {{ ... }} expression (for scanning subscripts inside).
_EXPR = re.compile(r"\{\{.*?\}\}", re.DOTALL)

# Identifier in a subscript: [name] — a context lookup ({{h[msu]}}).
_SUBSCRIPT = re.compile(r"\[\s*([A-Za-z_]\w*)")

# Control block: {% ... %} and docxtpl paragraph forms {%p ... %} /
# {%tr ... %} / {%tc ... %} / {%r ... %} (docxtpl strips the prefix before Jinja).
_BLOCK = re.compile(r"\{%(?:(?:p|tr|tc|r)\s+)?(.*?)%\}", re.DOTALL)

# for TARGET[, TARGET...] in EXPR
_FOR = re.compile(r"^for\s+(.+?)\s+in\s+(.+)$", re.DOTALL)

# Identifier NOT preceded by "." (attribute names are not context
# lookups: u.year -> only u).
_IDENT = re.compile(r"(?<![\w.])([A-Za-z_]\w*)")

# String literals (after quote normalization, see _strip_strings). Escape-aware:
# 'it\'s' is one literal, not 'it\' + s.
_STRING = re.compile(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"")

# Filter chain: |name — that is a filter, not a variable (u.year|int -> u).
# Consumes optional (args) so named params don't leak (|int(base=16) -> int).
_FILTER = re.compile(r"\|\s*[A-Za-z_]\w*(?:\s*\([^)]*\))?")

# Jinja keywords / builtins that are not context variables.
_KEYWORDS = {
    "true", "false", "none", "and", "or", "not", "in", "is",
    "if", "else", "elif", "endif", "for", "endfor", "while", "endwhile",
    "set", "as", "with", "endwith", "cyclical",
    "loop", "varloop", "range", "dict", "cycler", "joiner", "namespace",
    "lipsum", "random",
    "block", "endblock", "extends", "include", "import", "from", "macro",
    "endmacro", "filter", "endfilter", "raw", "endraw", "autoescape",
    "endautoescape", "trans", "endtrans", "call", "endcall", "do",
}


def variables_from_docx(path: Path) -> Set[str]:
    """
    Return the set of variable names from a DOCX file; all docxtpl forms are
    normalized to the base variable (see the module header).
    Checks: document.xml, all headerN.xml / footerN.xml, footnotes.xml,
    endnotes.xml.
    """
    found: Set[str] = set()

    with zipfile.ZipFile(path) as z:
        for xml_file in z.namelist():
            if not _PART.match(xml_file):
                continue

            xml = z.read(xml_file).decode("utf-8", errors="ignore")
            found |= _variables_from_part(xml)
    return found


def _paragraphs(xml: str):
    """Bodies of outer <w:p> paragraphs, accounting for nesting: a textbox
    inserts a <w:p> inside a <w:p> (via <w:txbxContent>), and a non-greedy split
    up to the first </w:p> lost the text after it in the same outer paragraph."""
    depth = 0
    start = 0
    for m in _P_TAG.finditer(xml):
        tag = m.group(0)
        if tag.startswith("</"):
            if depth:
                depth -= 1
                if not depth:
                    yield xml[start:m.start()]
        elif tag.endswith("/>"):
            continue  # self-closing <w:p .../> — no body, no close
        else:
            if not depth:
                start = m.end()
            depth += 1


def _variables_from_part(xml: str) -> Set[str]:
    """One XML part. Text is gathered paragraph by paragraph (not the whole
    file as one string) so that a "{{" in one paragraph and a "}}" in another
    do not false-match. The split accounts for nesting (textboxes —
    see _paragraphs)."""
    found: Set[str] = set()
    loop_locals: Set[str] = set()

    for paragraph in _paragraphs(xml):
        text = "".join(html.unescape(t) for t in _TEXT.findall(paragraph))
        if not text:
            continue

        # {{ ... }}: base variable + identifiers in subscripts
        found.update(VAR_NAME.findall(text))
        for expr in _EXPR.findall(text):
            found.update(_SUBSCRIPT.findall(_strip_strings(expr)))

        # {% ... %} / {%p ... %}: conditions, iterables for, etc.
        for block in _BLOCK.findall(text):
            found.update(_vars_from_block(block, loop_locals))

    # Loop targets (for u in university) — not context variables.
    return found - loop_locals


def _strip_strings(text: str) -> str:
    """Strip string literals; curly "quotes" are normalized first —
    as docxtpl's clean_tags does before Jinja."""
    text = (text.replace("‘", "'").replace("’", "'")
                .replace("“", '"').replace("”", '"')
                .replace("«", '"').replace("»", '"'))
    return _STRING.sub("", text)


def _vars_from_block(body: str, loop_locals: Set[str]) -> Set[str]:
    """Variables referenced by the body of a {% ... %} block."""
    m = _FOR.match(body.strip())
    if m:
        # for TARGET[, TARGET...] in EXPR — targets are local,
        # the expression is a context reference
        for target in m.group(1).split(","):
            if re.fullmatch(r"[A-Za-z_]\w*", target.strip()):
                loop_locals.add(target.strip())
        body = m.group(2)

    body = _strip_strings(body)
    body = _FILTER.sub("", body)
    return {n for n in _IDENT.findall(body) if n not in _KEYWORDS}
