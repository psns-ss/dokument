# logic/inflection.py
# InflectedWord — dict subclass for grammatical case inflection in template rendering.
#
# Template syntax: {{var.ge}}, {{var.da}}, etc.
# Bare {{var}} renders "[INFLECTED: specify case, e.g. {{var.no}}]" via __str__.
# Single form expands to all declared cases (works for abbreviations like "Дек-1").

import logging

logger = logging.getLogger(__name__)

# Recognized grammatical case codes — shared with the parser, which validates
# the case lists declared in descr.docx against this set.
RECOGNIZED_CASES = frozenset({"no", "ge", "da", "ac", "in", "pre"})


class InflectedWord(dict):
    """Dict subclass for inflected variables. Used in template rendering.

    - {{var.ge}} -> Jinja dot access -> __getattr__ (recognized cases) or dict __getitem__ fallback (other keys)
    - {{var}}     -> __str__ -> "[INFLECTED: specify case, e.g. {{var.no}}]" + warning log
    - _single expansion: all case keys map to the same value
    - __getattr__ raises AttributeError for non-case attributes (preserves hasattr semantics,
      prevents poisoning _smart_convert's file-like check or any other hasattr-based probe)
    """

    def __init__(self, forms: dict, cases: list[str] | None = None):
        if len(forms) == 1 and cases:
            # Single form -> expand to all declared cases.
            # Works for abbreviations ("Дек-1") and vars without nominative
            # (e.g. only ge,da declared). Expands to whatever the variable
            # declares, regardless of which case key was filled. With no cases
            # declared, keep the original form (don't drop the value).
            single_val = next(v for k, v in forms.items())
            expanded = {c: single_val for c in cases}
            super().__init__(expanded)
        else:
            super().__init__(forms)

    def __getattr__(self, key: str) -> str:
        if key in RECOGNIZED_CASES:
            if key not in self:
                logger.warning(f"InflectedWord missing case '{key}' for forms: {dict(self)}")
                return ""
            return self[key]
        raise AttributeError(f"'InflectedWord' has no attribute '{key}'")

    def __str__(self) -> str:
        logger.warning(f"InflectedWord rendered bare (no case specified): {dict(self)}")
        return "[INFLECTED: specify case, e.g. {{var.no}}]"
