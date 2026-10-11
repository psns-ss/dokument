# logic/context_manager.py
"""
Dynamic DataContext class management for multi-pack support.

Each thread gets its own DataContext class for its pack.
threading.local() keeps them separate.

Separate from context.py because this one tracks state (which pack is
active in this thread). context.py is just a factory—no state.

NOTE: Plugins can't import from each other — the loader loads them by
explicit file path (spec_from_file_location), not via sys.path, so a
`from helper import X` inside a plugin raises ImportError. (If it did
resolve, the import would land in process-global sys.modules and could
collide across packs shipping same-named helpers; the missing sys.path
entry is what prevents that.) Do intra-plugin imports package-scoped if
ever needed.
"""
import threading
from pathlib import Path
from logic.context import make_context_class

_thread = threading.local()


def load_data_context_for_pack(descr_path: Path, lang_path: Path,
                               variable_desc=None) -> type:
    """
    Create or reload DataContext class for the given pack (thread-local).

    Args:
        descr_path: Path to pack's descr.docx
        lang_path: Path to language_rules.yaml
        variable_desc: Pre-parsed variable descriptions, forwarded to
            make_context_class so the route's single descr.docx parse isn't
            repeated here. Ignored on the fast path (class already cached).

    Returns:
        The DataContext class (reuses cached class if same pack in this thread)
    """
    # Fast path: reuse if already loaded for this pack in this thread
    if getattr(_thread, 'data_context_class', None) is not None:
        if getattr(_thread, 'current_pack', None) == descr_path:
            return _thread.data_context_class

    # Create new class (reusing the caller's parse when provided)
    _thread.data_context_class = make_context_class(descr_path, lang_path, variable_desc)
    _thread.current_pack = descr_path
    return _thread.data_context_class


def get_data_context_class() -> type:
    """Get the currently loaded DataContext class for this thread."""
    cls = getattr(_thread, 'data_context_class', None)
    if cls is None:
        raise RuntimeError(
            "DataContext not initialized for this thread. "
            "Call load_data_context_for_pack() first."
        )
    return cls


def invalidate_data_context():
    """Clear cached DataContext class for this thread.

    Use in test fixtures (conftest.py teardown) to avoid test contamination.
    Not needed in request flow — thread-local state is fresh per thread.
    """
    _thread.data_context_class = None
    _thread.current_pack = None
