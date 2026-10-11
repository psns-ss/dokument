"""
Shared pytest fixtures for the document generation project.

Fixtures are reusable test components that setup/teardown test environment.
They're automatically discovered by pytest and can be used in any test file.
"""

import pytest
from pathlib import Path
import sys
import os
import logging

# ------------------------------------------------------------------
# sys.path setup for host testing (Docker vs Host path mapping)
# ------------------------------------------------------------------
# In Docker, CWD is /app/ (host ./app/), so `from logic.extractor ...`
# resolves to /app/logic/ (core modules). On host, we must put app/
# first in sys.path so `logic` resolves to ./app/logic/ (core),
# not ./logic/ (user plugins).

_root = Path(__file__).parent.parent
_app_dir = _root / "app"

# 1. app/ first — so `import logic.*` finds core modules (app/logic/)
if str(_app_dir) not in sys.path:
    sys.path.insert(0, str(_app_dir))

# 2. project root — for `import app.generator` style imports
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

# ------------------------------------------------------------------
# Logging: generator.py does logging.basicConfig(filename='/app/flask_app.log')
# which fails on host. Intercept it before the import.
# ------------------------------------------------------------------
_original_basicConfig = logging.basicConfig


def _safe_basicConfig(**kwargs):
    """Redirect Docker-only log paths to a host-writable location."""
    if kwargs.get('filename', '').startswith('/app/'):
        kwargs['filename'] = str(_root / 'test_flask_app.log')
    return _original_basicConfig(**kwargs)


logging.basicConfig = _safe_basicConfig


def pytest_addoption(parser):
    """Register the --e2e flag documented in tests/CLAUDE.md and README.md.

    E2E tests self-skip when the container at localhost:5555 is unreachable;
    the flag exists so the documented command doesn't fail with
    'unrecognized arguments: --e2e'.
    """
    parser.addoption(
        "--e2e",
        action="store_true",
        default=False,
        help="Run E2E tests (requires the Docker container at localhost:5555)",
    )


# ------------------------------------------------------------------
# Document store isolation (autouse)
# ------------------------------------------------------------------
# cfg.document_store defaults to /document_store — a Docker-only volume path.
# Left alone, a host test run writes to <drive>:\document_store (Windows: quiet
# pollution at the drive root) or dies with PermissionError/FileNotFoundError
# (Linux CI: 28 failures in the first CI run). Routes read cfg.document_store at
# call time, so patching the instance is enough — no import-site rewiring.
@pytest.fixture(autouse=True)
def isolate_document_store(monkeypatch, tmp_path):
    """Give every test a private document store directory."""
    from config import cfg
    store = tmp_path / "document_store"
    store.mkdir()
    monkeypatch.setattr(cfg, "document_store", store)
    return store


@pytest.fixture
def test_dir():
    """
    Return the tests directory path.

    Use this to locate fixtures or other test resources.
    """
    return Path(__file__).parent


@pytest.fixture
def fixtures_dir(test_dir):
    """
    Return the fixtures directory path.

    Example usage:
        def test_something(fixtures_dir):
            sample_file = fixtures_dir / "sample.yaml"
    """
    return test_dir / "fixtures"


@pytest.fixture
def project_root(test_dir):
    """
    Return the project root directory path.
    """
    return test_dir.parent


@pytest.fixture
def sample_yaml_dict():
    """
    Return a sample YAML dictionary for testing matching functions.

    This fixture provides test data without needing actual files.
    """
    return {
        "university_1": {
            "short": "МГУ",
            "full": "Московский государственный университет",
        },
        "university_2": {
            "short": "СПбГУ",
            "full": "Санкт-Петербургский государственный университет",
        },
        "company_1": {
            "short": "Яндекс",
            "full": "ООО Яндекс",
        },
    }


@pytest.fixture
def client(project_root):
    """
    Flask test client for integration testing routes.

    Usage:
        def test_index(client):
            response = client.get('/init')
            assert response.status_code == 200
    """
    from generator import app

    app.config["TESTING"] = True
    # On host, templates are at project_root/templates/ (not app/templates/)
    app.template_folder = str(project_root / "templates")
    with app.test_client() as client:
        yield client


@pytest.fixture
def fresh_inflection_db(tmp_path):
    """Point logic.inflection_db at a fresh temp DB (per-test isolation).

    Patches the module globals (DB_PATH, schema flag, queue state) and drops
    the thread's cached connection — with per-thread connections, a stale
    conn would keep pointing at the previous test's DB file. The connection
    is closed before tmp_path teardown so Windows can delete the DB files.
    """
    import threading
    from collections import deque
    import logic.inflection_db as mod

    orig = (mod.DB_PATH, mod._schema_initialized, mod._lock,
            mod._save_queue, mod._bg_lock, mod._bg_worker)
    mod.close_connection()
    mod.DB_PATH = tmp_path / "inflections.db"
    mod._schema_initialized = False
    mod._lock = threading.Lock()
    mod._save_queue = deque()
    mod._bg_lock = threading.Lock()
    mod._bg_worker = None
    try:
        yield mod
    finally:
        mod.close_connection()
        (mod.DB_PATH, mod._schema_initialized, mod._lock,
         mod._save_queue, mod._bg_lock, mod._bg_worker) = orig


@pytest.fixture
def temp_dir(tmp_path):
    """
    Create a temporary directory for test files.

    pytest's tmp_path fixture provides a unique temp dir per test.
    Files are automatically cleaned up after the test.

    Usage:
        def test_file_io(temp_dir):
            test_file = temp_dir / "test.txt"
            test_file.write_text("hello")
            assert test_file.read_text() == "hello"
    """
    return tmp_path


@pytest.fixture
def user_logic_dir(project_root):
    """
    Host path to user plugins (templates/logic).

    In Docker this is mounted to /app/templates/logic.
    On host, the actual user plugins are in project_root/logic/.
    """
    return project_root / "logic"
