# logic/context.py
"""
Module for dynamically creating the DataContext dataclass based on the variable
descriptions in descr.docx.

Why is DataContext needed?
Originally docxtpl required a flat dict whose values could be:
- strings/numbers (for simple {{placeholder}} tags),
- special objects (RichText, Subdoc, InlineImage, etc.).

The keys had to match the template's variable names exactly, and the whole
structure had to support serialization (pickle).

DataContext solves three problems:
1. Automatic creation of a flat namespace.
   DataContext(user_name="Ann", contract_sum=1000) is clearer than building a
   dict by hand.
2. Zero-cost validation.
   Assigning a nonexistent field raises TypeError, which helps catch typos early.
3. Easy default values.
   Every field can have a default ("", 0, RichText(""), etc.), so templates can
   render even when computed values are absent.

docxtpl does not require a dataclass specifically — it works with any object
supporting __getitem__. DataContext is just a convenient wrapper to keep things
clean and type-safe.
"""
from __future__ import annotations
import dataclasses
import keyword
import logging
from pathlib import Path
from typing import Any, Dict
import io
from docxtpl import RichText, Subdoc, InlineImage
from .parser import read_variable_descriptions

logger = logging.getLogger(__name__)


def _smart_convert(value: Any) -> Any:
    """
    Convert a value to a docxtpl-compatible form.
    Returns the value unchanged if it is:
    - a docxtpl object (RichText, Subdoc, InlineImage),
    - a file-like object (BytesIO or with read/seek methods),
    - a container (list/dict).
    Otherwise converts it to a string.

    Args:
        value: The value to convert.

    Returns:
        The converted value.
    """
    if isinstance(value, (RichText, Subdoc, InlineImage)):
        return value
    if isinstance(value, io.BytesIO):
        return value
    if isinstance(value, (list, dict)):
        return value
    return str(value)

def _valid_field_name(name: str) -> bool:
    """A descr var name is usable as a dataclass field only if it's a valid
    identifier, not a Python keyword, not a dunder (collides with the methods
    make_dataclass generates), and not an injected method. Anything else would
    crash make_dataclass or silently shadow from_dict/__post_init__ → raw 500."""
    return (
        name.isidentifier()
        and not keyword.iskeyword(name)
        and not (name.startswith("__") and name.endswith("__"))
        and name != "from_dict"
    )

def make_context_class(descr_path: Path, lang_path: Path,
                       variable_desc: Dict[str, Any] | None = None) -> type[Any]:
    """
    Create and return the DataContext dataclass, whose fields correspond to the
    variables in descr.docx.
    Every field is typed Any with a default of "", so any object can be stored.
    Values are automatically normalized via _smart_convert.

    Args:
        descr_path: Path to the descr.docx file with the variable descriptions.
        lang_path: Path to the language_rules.yaml file.
        variable_desc: Pre-parsed variable descriptions (from
            read_variable_descriptions). When provided, descr.docx is NOT
            re-opened — the route parses it once and shares the result. Only
            the field names are needed. Parsed here only when None.

    Returns:
        The created DataContext dataclass.
    """
    # Reuse the caller's parse when available (single descr.docx open per
    # request); parse here only as a backward-compatible fallback.
    if variable_desc is None:
        variable_desc = read_variable_descriptions(descr_path, lang_path)
    # (field_name, type, dataclass_field) type=Any allows storing any object; default is an empty string.
    # Skip names that can't be a field (keyword/dunder/injected method) — degrade-and-log,
    # consistent with the parser, instead of crashing make_dataclass or shadowing a method.
    fields = []
    for name in variable_desc:
        if not _valid_field_name(name):
            logger.warning(f"descr var {name!r} is not a valid field name — skipping")
            continue
        fields.append((name, Any, dataclasses.field(default="")))

    # Additional methods injected into the class
    namespace = {
        "__post_init__": lambda self: _normalize_fields(self),
        "from_dict": classmethod(_from_dict),
    }

    cls = dataclasses.make_dataclass("DataContext", fields, namespace=namespace)
    return cls

def _normalize_fields(self) -> None:
    """
    Apply _smart_convert to all dataclass fields right after initialization.
    """
    for field in dataclasses.fields(self):
        raw = getattr(self, field.name)
        setattr(self, field.name, _smart_convert(raw))

def _from_dict(cls, data: Dict[str, Any]) -> Any:
    """
    Class method: create a dataclass instance from a dict, converting values
    automatically.

    Args:
        cls: The DataContext class.
        data: The dict of data to initialize from.

    Returns:
        A DataContext instance.
    """
    # Values are normalized once by __post_init__ (the single normalization
    # point) — don't pre-convert here or each value would be converted twice.
    return cls(**data)
