# logic/loader.py
"""
Load user plugins (compute, match, init, subdoc).
Thread-local cache keeps concurrent requests from different packs separate.
"""
import threading
from pathlib import Path
from typing import Dict, Any
import logging

from config import cfg

logger = logging.getLogger(__name__)

# Per-thread cache for plugin modules
_thread = threading.local()


def find_templates(
    templates_dir: Path | None = None,
    pattern: str = "template*.docx"
) -> list[Path]:
    """Find all template files matching the pattern in the given directory.

    Args:
        templates_dir: Directory to search. Defaults to cfg.templates_dir.
        pattern: Glob pattern for template files.
    """
    tdir = Path(templates_dir if templates_dir else cfg.templates_dir).expanduser().resolve()
    if not tdir.is_dir():
        return []
    return sorted(tdir.glob(pattern))


def ensure_file(path: str | Path, what: str = "file") -> Path:
    """Return absolute Path if file exists."""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"{what} not found: {p}")
    return p


def load_plugins(logic_dir: Path, category: str, extra_stems: set[str] | None = None) -> Dict[str, Any]:
    """
    Load all plugins of a specific category from the logic directory.

    Uses thread-local cache keyed by (logic_dir, category) to isolate plugin modules
    per thread. The category parameter is critical — without it, calling
    load_plugins(logic_dir, "compute") then load_plugins(logic_dir, "init") in the
    same thread would return the wrong plugins from cache.

    Note: top-level plugins are loaded by explicit file path (spec_from_file_location),
    not via sys.path, so a plugin cannot `import` a sibling in its own logic dir —
    that would raise ImportError (do intra-plugin imports properly, package-scoped, if
    ever needed). This also means no process-global sys.path entry accumulates and no
    cross-pack same-named-helper collision is possible.

    Args:
        logic_dir: Directory to load plugins from
        category: Plugin category (match, compute, init, etc.)
        extra_stems: Optional set of module stems to keep even without the
            {category}_<stem> hook (e.g. subdoc var names for the compute load,
            so subdoc-only modules aren't dropped).

    Returns:
        Dictionary of loaded modules. A module is included if it exports
        {category}_{module_name}() or any of extra_stems; other modules are
        silently dropped.
    """
    import importlib.util

    # Initialize per-thread cache
    if not hasattr(_thread, 'plugin_cache'):
        _thread.plugin_cache = {}

    # Canonicalize so relative/absolute forms of the same dir share a cache entry.
    logic_dir = Path(logic_dir).resolve()

    # Cache key MUST include category to avoid cross-category collisions, and
    # extra_stems — a shared logic_dir can back several packs with different
    # subdoc sets, so the same (dir, category) must not cross-contaminate.
    cache_key = (str(logic_dir), category, frozenset(extra_stems or ()))
    if cache_key in _thread.plugin_cache:
        return _thread.plugin_cache[cache_key]

    plugins = {}

    # Ensure directory exists
    if not logic_dir.exists():
        _thread.plugin_cache[cache_key] = plugins
        return plugins

    # Load all *.py files
    for py_file in logic_dir.glob("*.py"):
        if py_file.name.startswith("_"):
            continue

        try:
            # Load module using spec_from_file_location
            # These modules do NOT register in sys.modules
            spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Keep if it has the category hook, or (for a category that also
            # resolves other hooks — compute also resolves <var>() subdocs) one of
            # the extra stems. This is what keeps subdoc-only modules from being
            # dropped when the compute load passes the subdoc var names.
            if hasattr(module, f"{category}_{py_file.stem}") or (
                extra_stems and any(hasattr(module, s) for s in extra_stems)
            ):
                plugins[py_file.stem] = module

        except Exception as e:
            logger.error(f"Error loading plugin {py_file.name}: {e}")

    # Cache by (logic_dir, category)
    _thread.plugin_cache[cache_key] = plugins
    return plugins
