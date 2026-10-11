# app/config.py
# --------------
# Logging setup, configuration dataclass, and module-level constants.
# Imported by generator.py and test modules.

from __future__ import annotations

import logging
from pathlib import Path
from dataclasses import dataclass, field
import json
from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup

from pack_manager import resolve_pack_paths, resolve_pack_dirs

# ------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------
# Log path and level: defaults to /app/flask_app.log (Docker runs with CWD=/app).
# Override with FLASK_LOG_PATH (the test suite redirects /app/... to a host-writable
# file). If the default path isn't writable (e.g. running on a host without /app),
# fall back to a CWD-relative file so startup doesn't crash. Root level defaults to
# INFO; set FLASK_LOG_LEVEL=DEBUG for debug-level logs (the E2E log-content tests in
# tests/test_e2e.py require it)
import os
LOG_PATH = Path(os.environ.get('FLASK_LOG_PATH', '/app/flask_app.log'))
LOG_LEVEL = os.environ.get('FLASK_LOG_LEVEL', 'INFO').upper()

_LOG_FORMAT = '%(asctime)s %(levelname)s:%(message)s'
try:
    logging.basicConfig(
        filename=str(LOG_PATH),
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format=_LOG_FORMAT,
        encoding='utf-8'
    )
except OSError:
    # /app/... isn't writable here — fall back to a CWD-relative log file.
    logging.basicConfig(
        filename='flask_app.log',
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format=_LOG_FORMAT,
        encoding='utf-8'
    )
logger = logging.getLogger(__name__)

# Warn on an unrecognized level name — getattr above silently fell back to INFO.
if not hasattr(logging, LOG_LEVEL):
    logger.warning(f"Unknown FLASK_LOG_LEVEL={LOG_LEVEL!r} — using INFO")

# Third-party loggers follow FLASK_LOG_LEVEL (the earlier docxtpl/jinja2=DEBUG
# and docx=WARNING pins were a historical workaround, now removed).
_third_party_level = getattr(logging, LOG_LEVEL, logging.INFO)
for _name in ('docxtpl', 'jinja2', 'docx'):
    logging.getLogger(_name).setLevel(_third_party_level)

# ------------------------------------------------------------------
# Compute error behavior (consumed by logic/computation.py)
# ------------------------------------------------------------------
# What /generate does when a missing variable has no compute rule, or a
# compute_* plugin raises:
#   lenient (default) — a sentinel string is rendered into the document
#     ("NO RULE for <var>" / "ERROR: ...") — generation continues
#   strict — log and raise; generation aborts (the /generate safety net
#     flashes the message and redirects to /init)
def _compute_on_error() -> str:
    value = os.environ.get('COMPUTE_ON_ERROR', 'lenient').lower()
    if value not in ('lenient', 'strict'):
        logger.warning(f"Unknown COMPUTE_ON_ERROR={value!r} — using 'lenient'")
        return 'lenient'
    return value

COMPUTE_ON_ERROR = _compute_on_error()

# ------------------------------------------------------------------
# Document-store TTL (consumed by routes/debug.py reset cleanup)
# ------------------------------------------------------------------
# How old (days) a top-level entry in the document store (data/) must be
# before /reset sweeps it. The store is a shared volume (Flask /document_store,
# nginx, OnlyOffice cache) that accumulates session folders + stale artifacts
# and is otherwise never cleaned. Default 14 days.
def _data_ttl_days() -> int:
    raw = os.environ.get('DATA_TTL_DAYS', '14')
    try:
        n = int(raw)
    except ValueError:
        logger.warning(f"Unknown DATA_TTL_DAYS={raw!r} — using 14")
        return 14
    if n <= 0:
        logger.warning(f"DATA_TTL_DAYS={raw!r} must be positive — using 14")
        return 14
    return n

DATA_TTL_DAYS = _data_ttl_days()

# ------------------------------------------------------------------
# Document store location
# ------------------------------------------------------------------
# /document_store is the Docker volume (Flask writes, nginx serves). Outside
# Docker the literal path is wrong either way: on Windows it is drive-relative
# and writable, so anything run there silently writes to <drive>:\document_store;
# on a Linux runner it is a root-level path the user cannot create, and
# /generate aborts. DOCUMENT_STORE points the app at a real directory.
def _document_store() -> Path:
    raw = os.environ.get('DOCUMENT_STORE')
    return Path(raw) if raw else Path('/document_store')

# ------------------------------------------------------------------
# Jinja2 environment for HTML editor generation
# ------------------------------------------------------------------
jinja_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "routes" / "html_helpers"),
    autoescape=True
)
# tojson: JSON-encode a value for a JS string literal (the editor template
# interpolates key/title/url into JS). Returns Markup so autoescape doesn't
# re-escape the JSON quotes.
jinja_env.filters["tojson"] = lambda v: Markup(json.dumps(v))

# ------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------
@dataclass
class Config:
    templates_dir: Path = Path("templates")  # folder with .docx templates
    # Where generated docx go. default_factory (not a plain default) so
    # DOCUMENT_STORE is read per construction — a plain default would freeze the
    # value at class-creation time and make the env override untestable.
    document_store: Path = field(default_factory=_document_store)

    # Which pack is active. Set by ensure_active_pack() at route start.
    # WARNING: threaded workers have a tiny race window here.
    # For safety, use explicit path resolution (see select.py).
    _active_pack: str | None = None

    def __post_init__(self):
        # Initialize _active_pack to 'root' on first access
        if self._active_pack is None:
            self._active_pack = 'root'

    @property
    def active_pack(self) -> str:
        """Get the currently active pack identifier."""
        return self._active_pack

    @active_pack.setter
    def active_pack(self, value: str):
        """Setter marks that pack changed - actual reload happens in route handler."""
        self._active_pack = value

    # Pack-derived paths delegate to pack_manager.resolve_pack_* — the single
    # source of truth the routes already use for explicit (thread-safe)
    # resolution. Keeping the props as thin wrappers means they can't drift from
    # that logic, and the exists() fallback lives in one place. NOTE: they still
    # read _active_pack, so they carry the same narrow thread-race caveat as
    # active_pack — routes resolve explicitly instead of reading these.
    @property
    def descr_file(self) -> Path:
        """The active pack's descr.docx."""
        return resolve_pack_paths(self.templates_dir, self.active_pack)[0]

    @property
    def lang_rules(self) -> Path:
        """The active pack's language_rules.yaml, falling back to root."""
        return resolve_pack_paths(self.templates_dir, self.active_pack)[1]

    @property
    def logic_dir(self) -> Path:
        """The effective logic dir — the pack's logic/ if present, else root
        logic/ (matches what the routes load via resolve_pack_dirs)."""
        return resolve_pack_dirs(self.templates_dir, self.active_pack)[1]

    @property
    def pack_dir(self) -> Path:
        """The active pack's base directory (where templates live)."""
        return resolve_pack_dirs(self.templates_dir, self.active_pack)[0]


cfg = Config()


def ensure_active_pack(session) -> str | None:
    """Return the active pack identifier, defaulting to 'root' if not set.

    Sets cfg.active_pack and session['active_pack'] for the current request.
    Returns None if no pack is available (caller should redirect to /select).

    Use at the top of every route handler to establish pack context before
    reading any cfg property.
    """
    if session.get('active_pack'):
        cfg.active_pack = session['active_pack']
        return session['active_pack']  # local value — re-reading cfg.active_pack races

    # Default to root if descr.docx exists at root
    if (cfg.templates_dir / 'descr.docx').exists():
        cfg.active_pack = 'root'
        session['active_pack'] = 'root'
        return 'root'

    return None


def get_data_context():
    """Get the current DataContext class for the active pack.

    Lazy wrapper — tests and route handlers import this instead of
    importing DataContext directly from config. Prevents module-level
    import breakage when DataContext is not yet loaded for a pack.
    """
    from logic.context_manager import get_data_context_class
    return get_data_context_class()

