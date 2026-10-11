"""
Shared helpers for domain-agnostic matching.
- Safe YAML loader (path traversal & extension guard)
- Exact + optional fuzzy matching
"""

from pathlib import Path
from typing import Dict, List, Any
import logging
import yaml

logger = logging.getLogger(__name__)

# Set once when thefuzz is missing, so the fallback warning fires a single time
# instead of on every find_matches() call.
_fuzzy_missing_warned = False


def load_yaml(path: Path) -> Dict[str, Any]:
    """
    Load a YAML file from the templates/ directory only.

    Raises
    ------
    ValueError
        If the path points outside templates or is not .yaml
    """
    root = Path("templates").resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"YAML path must stay inside 'templates/': {path}")

    if resolved.suffix != ".yaml":
        raise ValueError(f"Only .yaml files allowed: {path}")

    try:
        with resolved.open(encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.error("Cannot load %s: %s", path, e)
        return {}


def find_matches(raw_text: str,
                 yaml_dict: Dict[str, Any],
                 keys=("short", "full"),
                 *,
                 use_fuzzy: bool = True,
                 threshold: int = 80) -> List[str]:
    """
    Ordered list of keys that match raw_text.
    1. exact substring (fast)
    2. fuzzy only if exact failed
    """
    if use_fuzzy:
        try:
            # thefuzz = maintained MIT fork of fuzzywuzzy (which is unmaintained and
            # GPL-2.0); it delegates to rapidfuzz. Scores differ from fuzzywuzzy by up
            # to ~17 points on Cyrillic, match/no-match decisions at 70 and 80 did not.
            from thefuzz import fuzz  # type: ignore
        except ImportError:
            global _fuzzy_missing_warned
            use_fuzzy = False
            if not _fuzzy_missing_warned:
                _fuzzy_missing_warned = True
                logger.warning(
                    "thefuzz is not installed: fuzzy matching disabled, falling back to "
                    "exact-substring only. pip install thefuzz to restore it."
                )

    matched = []
    for key, record in yaml_dict.items():
        if not isinstance(record, dict):
            continue  # non-dict record (bad YAML) — can't match by key
        for k in keys:
            candidate = str(record.get(k, "") or "").strip()
            if candidate and candidate in raw_text:          # 1. exact
                matched.append(key)
                break
        else:                                  # 2. fuzzy fallback
            if use_fuzzy:
                for k in keys:
                    candidate = str(record.get(k, "") or "").strip()
                    if candidate and fuzz.partial_ratio(candidate, raw_text) >= threshold:
                        matched.append(key)
                        break
    return matched
