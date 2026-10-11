"""
Variable computation module.
Handles computing missing variables from logic plugins.
"""
import logging
from typing import Any, Callable, Dict, Set, Tuple

import config
from logic.hints_builder import HintsCollections

logger = logging.getLogger(__name__)


def merge_result(
    var: str,
    result: Any,
    computed_values: Dict[str, Any],
    subdoc_functions: Dict[str, Callable],
) -> None:
    """Merge a compute function's return value into the appropriate bucket.

    No type knowledge. callable() check determines deferral.

    Dict flattening rule: only flatten dicts containing at least one callable.
    Plain dicts (e.g., {'key': 'value'}) are stored as single values — no silent
    expansion. This preserves backward compatibility for any plugin returning
    a plain dict-of-values.
    """
    if isinstance(result, dict) and any(callable(v) for v in result.values()):
        # Dict with callables — flatten, dispatch each value individually
        for k, v in result.items():
            if callable(v):
                subdoc_functions[k] = v
            else:
                computed_values[k] = v
    elif isinstance(result, dict):
        # Plain dict — store as single value (backward compatible)
        computed_values[var] = result
    elif callable(result):
        subdoc_functions[var] = result
    else:
        computed_values[var] = result


def compute_variables(
    cleaned_data: Dict[str, Any],
    expected_vars: Set[str],
    hints: HintsCollections,
    modules: Dict[str, Any],
    session: Dict[str, Any] = None,
) -> Tuple[Dict[str, Any], Dict[str, Callable]]:
    """
    Compute missing variables using loaded logic modules.

    Hints tell the engine which lookups to fire for each variable.
    Actual hook functions are resolved independently from plugins.

    Two independent lookups per variable:
      - compute_<var>()  — gated by hints.vars_to_compute
        Signature: (**kwargs) -> value
        Called: immediately, result stored in computed_values
      - <var>()          — gated by hints.vars_as_subdocs
        Signature: (tpl, **data_dict) -> Dict[str, Subdoc]
        Called: deferred to render time, stored in subdoc_functions

    A variable with both type=computed AND type=subdoc gets both lookups
    fired independently — they discover different functions with different
    signatures and serve different purposes.

    Compute order: missing compute_* vars run first, in descr order
    (hints.vars_to_compute order), so a compute_<b> that reads a value produced
    by compute_<a> sees it when <a> is declared before <b>. The remaining vars
    (subdoc / no-rule) follow in arbitrary order — they never feed a later
    compute_*.

    Args:
        cleaned_data: User-provided data (form values)
        expected_vars: Set of all expected variable names
        hints: Pre-computed hints from build_hints_collections()
        modules: Dictionary of loaded logic modules
        session: Flask session dict — for get_file() access in plugins

    Returns:
        Tuple of (computed_values, subdoc_functions) where:
        - computed_values: Dict[str, Any] - computed values for regular variables
        - subdoc_functions: Dict[str, Callable] - callable subdoc functions to be
          executed later during rendering
    """
    computed_values: Dict[str, Any] = {}
    subdoc_functions: Dict[str, Callable] = {}

    # Determine which variables need computation
    missing_set = expected_vars - set(cleaned_data.keys())

    # Pre-computed sets from hints (no per-variable string comparison)
    compute_vars = set(hints.vars_to_compute)
    subdoc_vars = set(hints.vars_as_subdocs)

    # Order matters only among compute_* vars: they're the only lookups that
    # read computed_values, so compute_<b> that depends on compute_<a>'s output
    # must run after it. Run the missing compute vars first, in descr order
    # (hints.vars_to_compute is built in descr order — a list or a dict, both
    # iterate their keys in that order); the rest (subdoc / no-rule) never feed
    # a later compute_*, so their order is irrelevant and they follow in whatever
    # order the set yields.
    missing_vars = (
        [v for v in hints.vars_to_compute if v in missing_set]
        + [v for v in missing_set if v not in compute_vars]
    )

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(f"Modules loaded: {list(modules.keys())}")
        for mod_name, mod in modules.items():
            compute_hooks = [f for f in dir(mod) if f.startswith('compute_')]
            logger.debug(f"Module {mod_name} compute hooks: {compute_hooks}")

    for var in missing_vars:
        compute_rule = None
        subdoc_rule = None

        # Lookup 1: compute_<var>() — gated by hints
        if var in compute_vars:
            for m in modules.values():
                if hasattr(m, f"compute_{var}"):
                    compute_rule = getattr(m, f"compute_{var}")
                    break

        # Lookup 2: <var>() — gated by hints, independent of lookup 1
        if var in subdoc_vars:
            for m in modules.values():
                if hasattr(m, var):
                    subdoc_rule = getattr(m, var)
                    break

        # Execute compute rule immediately
        if compute_rule:
            try:
                # Merge context into one kwargs dict so a user variable literally
                # named `session` can't collide with the framework `session` kwarg
                # (a duplicate kwarg would raise TypeError, be swallowed below, and
                # render as a silent "ERROR:" string). Framework session wins.
                rule_kwargs = {**cleaned_data, **computed_values}
                rule_kwargs['session'] = session
                result = compute_rule(**rule_kwargs)
                merge_result(var, result, computed_values, subdoc_functions)
            except Exception as e:
                logger.error(f"Error in compute_{var}: {e}")
                if config.COMPUTE_ON_ERROR == 'strict':
                    raise RuntimeError(f"compute_{var} failed: {e}") from e
                computed_values[var] = f"ERROR: {e}"

        # Defer subdoc rule for renderer
        if subdoc_rule:
            subdoc_functions[var] = subdoc_rule

        # Neither found — no rule message
        if not compute_rule and not subdoc_rule:
            if config.COMPUTE_ON_ERROR == 'strict':
                logger.error(f"No compute rule for '{var}' — aborting (COMPUTE_ON_ERROR=strict)")
                raise RuntimeError(f"No compute rule for variable '{var}'")
            computed_values[var] = f"NO RULE for {var}"

    logger.debug(f"Computed values: {list(computed_values.keys())}")
    logger.debug(f"Subdoc functions to call: {list(subdoc_functions.keys())}")

    return computed_values, subdoc_functions
