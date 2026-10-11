"""
Matching orchestration for match-type variables.

Coordinates plugin loading, execution, and result aggregation.
"""
import logging
from pathlib import Path
from typing import Any, Dict, List

from logic.loader import load_plugins
from logic.hints_builder import HintsCollections

logger = logging.getLogger(__name__)


def run_matching(
    session: Dict[str, Any],
    hints: HintsCollections,
    logic_dir: Path
) -> Dict[str, List[str]]:
    """
    Execute matching for all match-type variables.

    Plugins read session['uploaded_files'] directly via get_file()
    (not an uploaded_path argument). The second plugin argument is
    yaml_key — the descr.docx column-4 value (or the var name); the
    plugin interprets it (typically: the YAML filename to search).

    Args:
        session: Flask session (passed to match functions)
        hints: Pre-computed hints from build_hints_collections()
        logic_dir: Directory to load match plugins from

    Returns:
        Dict[var_name, List[matched_keys]]
    """
    # Use pre-computed dict - no type checking, no variable_desc needed
    match_vars = hints.vars_to_match

    if not match_vars:
        logger.debug("No match-type variables found")
        return {}

    # Load match plugins
    match_plugins = load_plugins(logic_dir, 'match')
    logger.debug(f"Loaded match plugins: {list(match_plugins.keys())}")

    # Execute matching for each variable
    matched_entities = {}
    for var_name, yaml_key in match_vars.items():
        # yaml_key is None -> skip (no YAML data available)
        # yaml_key is explicit value from descr.docx, or var_name as default
        if not yaml_key:
            logger.warning(f"Match variable {var_name} has no YAML key — skipping")
            continue

        for plugin_name, plugin in match_plugins.items():
            func_name = f"match_{var_name}"
            if hasattr(plugin, func_name):
                try:
                    logger.debug(f"Calling {func_name} from plugin {plugin_name}")
                    matched = getattr(plugin, func_name)(session, yaml_key)
                    if matched and not isinstance(matched, list):
                        logger.warning(
                            f"match_{var_name} returned {type(matched).__name__}, "
                            f"expected List[str] — ignoring"
                        )
                    elif matched:
                        matched_entities[var_name] = matched
                        logger.debug(f"Matched {len(matched)} entities for {var_name}")
                except Exception as e:
                    logger.error(f"Error in match_{var_name}: {e}")
                # First plugin owning match_{var} wins (consistent with
                # compute_variables) — a later plugin must not override it.
                break

    return matched_entities
