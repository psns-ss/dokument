"""
Build pre-computed hints from variable metadata.

Hints tell the engine which vars need which hooks; actual hook functions
(init_<var>(), match_<var>(), compute_<var>() or <var>() for subdocs) are resolved separately
from plugins.
"""
import importlib.util
import logging
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Any
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class HintsCollections:
    """Pre-computed hints telling the engine which vars need which hooks.

    vars_to_match is a Dict[var_name, yaml_key] so the matching engine has
    the YAML filename without needing to re-read variable_desc.
    """
    vars_to_match: Dict[str, str] = field(default_factory=dict)
    vars_to_compute: List[str] = field(default_factory=list)
    vars_as_subdocs: List[str] = field(default_factory=list)
    vars_need_init_form: List[str] = field(default_factory=list)


def build_hints_collections(variable_desc: Dict[str, Dict[str, Any]]) -> HintsCollections:
    """
    Build pre-computed hints from variable metadata.

    Args:
        variable_desc: Variable descriptions from parser (includes 'types' list)

    Returns:
        HintsCollections with pre-categorized variable names

    Type hints:
        - 'match' -> vars_to_match (dict: var_name -> yaml_key)
        - 'computed' -> vars_to_compute
        - 'subdoc' -> vars_as_subdocs
        - 'form' or 'file' -> vars_need_init_form
    """
    hints = HintsCollections()

    for var, meta in variable_desc.items():
        types = meta.get('types') or [t.strip() for t in meta.get('type', 'text').split(',')]

        if 'match' in types:
            # yaml_key: explicit options from descr.docx column 4, or var_name as default
            options = meta.get('options') or {}
            yaml_key = options.get('match')
            hints.vars_to_match[var] = yaml_key if yaml_key else var
        if 'computed' in types:
            hints.vars_to_compute.append(var)
        if 'subdoc' in types:
            hints.vars_as_subdocs.append(var)
        # 'form' meta-type OR 'file' type both need init hooks
        if 'form' in types or 'file' in types:
            hints.vars_need_init_form.append(var)

    return hints


def verify_hooks_exist(
    hints: HintsCollections,
    logic_dir: Path | None
) -> Dict[str, Any]:
    """
    Scan the plugin modules in logic_dir and record which hinted hooks have
    implementations.

    Unlike load_plugins() (which drops a module unless it exports
    {category}_{module_name}()), this imports every *.py file once and matches
    function names against the hinted variables — so a hook is reported even
    when the engine's loader would drop its module. Such modules are listed
    separately in 'dropped': the function exists in the file, but the engine
    never loads the module, so the hook never fires.

    Hook → function name (mirrors the engine's lookups):
        match   -> match_<var>
        compute -> compute_<var>
        init    -> init_<var>    (expected for form/file vars AND match vars —
                                  generate_dynamic_ui_block fires init_<var> for every
                                  matched_entities key, match results included)
        subdoc  -> <var>          (bare name)

    Args:
        hints: Pre-computed hints from build_hints_collections()
        logic_dir: Directory with plugin modules (None → empty report)

    Returns:
        {
          'found':   {var: {hook: module_stem}},   # only hooks expected for that var
          'dropped': {category: [stem, ...]},      # modules the engine's loader drops
          'errors':  {filename: error_str},        # modules that failed to import
        }
    """
    report: Dict[str, Any] = {
        'found': {},
        'dropped': {'match': [], 'compute': [], 'init': []},
        'errors': {},
    }
    if logic_dir is None or not Path(logic_dir).exists():
        return report

    # Same sys.path setup as load_plugins (for intra-plugin imports)
    logic_dir = Path(logic_dir)
    if str(logic_dir) not in sys.path:
        sys.path.insert(0, str(logic_dir))

    modules: Dict[str, Any] = {}
    for py_file in sorted(logic_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        try:
            # Not registered in sys.modules — same as load_plugins
            spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            modules[py_file.stem] = module
        except Exception as e:
            logger.error(f"verify_hooks_exist: error loading {py_file.name}: {e}")
            report['errors'][py_file.name] = str(e)

    # Expected hooks per hinted var
    expected: Dict[str, set] = {}
    for var in hints.vars_to_match:
        expected.setdefault(var, set()).add('match')
    for var in hints.vars_to_compute:
        expected.setdefault(var, set()).add('compute')
    for var in hints.vars_as_subdocs:
        expected.setdefault(var, set()).add('subdoc')
    for var in hints.vars_need_init_form:
        expected.setdefault(var, set()).add('init')
    for var in hints.vars_to_match:
        # Match vars also get init_<var>: generate_dynamic_ui_block fires init hooks
        # for every matched_entities key, and run_matching populates match vars
        expected.setdefault(var, set()).add('init')

    # Name-match scan across ALL modules (loader filter does not apply here)
    for var, hooks in expected.items():
        found: Dict[str, str] = {}
        for hook in sorted(hooks):
            target = var if hook == 'subdoc' else f"{hook}_{var}"
            for stem, mod in modules.items():
                fn = getattr(mod, target, None)
                # __module__ check: only count a hook DEFINED in this module,
                # not an imported name that happens to match.
                if callable(fn) and getattr(fn, '__module__', None) == mod.__name__:
                    found[hook] = stem
                    break
        report['found'][var] = found

    # Modules the engine's loader would drop: no {category}_{stem} function,
    # yet the file contains hooks the engine would want.
    for stem, mod in modules.items():
        fns = [n for n in dir(mod)
               if not n.startswith('_') and callable(getattr(mod, n))]
        for cat in ('match', 'init'):
            if not hasattr(mod, f"{cat}_{stem}") and any(f.startswith(cat + '_') for f in fns):
                report['dropped'][cat].append(stem)
        if not hasattr(mod, f"compute_{stem}") and (
            any(f.startswith('compute_') for f in fns)
            or any(v in fns for v in hints.vars_as_subdocs)
        ):
            report['dropped']['compute'].append(stem)

    return report
