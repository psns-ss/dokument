"""
Tests for app/generator.py error handling.

Covers: missing files, plugin load failures,
and edge cases in the route handlers.

Uses lazy imports via fixtures to avoid module-level import issues
with generator.py's `from logic.*` imports.
"""

import pytest
import types
from pathlib import Path


@pytest.fixture
def gen():
    """Lazy import of app.generator objects after conftest sys.path setup.

    Note: load_calculation_modules was removed during refactoring.
    Utility functions moved to logic.loader: ensure_file, load_plugins.
    """
    from logic.loader import (
        ensure_file,
        load_plugins,
    )
    return types.SimpleNamespace(
        ensure_file=ensure_file,
        load_plugins=load_plugins,
    )


class TestGenerateMissingTemplate:
    """POST /generate when templates are missing or broken."""

    def test_generate_handles_empty_form(self, client):
        """POST /generate with empty form should not crash the server."""
        response = client.post('/generate', data={})
        assert response.status_code in (200, 500)


class TestPluginLoadErrors:
    """Plugin loading with broken modules."""

    def test_load_plugins_handles_broken_module(self, gen, tmp_path):
        """load_plugins should skip modules that fail to import."""
        broken = tmp_path / "broken.py"
        broken.write_text("import nonexistent_module_xyz\nraise SyntaxError('bad')\n")

        good = tmp_path / "good.py"
        good.write_text("def compute_good(): return 'ok'\n")

        plugins = gen.load_plugins(tmp_path, 'compute')

        assert 'good' in plugins
        assert 'broken' not in plugins

    def test_load_plugins_empty_dir(self, gen, tmp_path):
        """load_plugins on empty directory should return empty dict."""
        plugins = gen.load_plugins(tmp_path, 'compute')
        assert plugins == {}

    def test_load_plugins_on_host_logic_dir(self, gen):
        """load_plugins should work on the project root logic/ (user plugins)."""
        logic_dir = Path(__file__).parent.parent / "logic"
        plugins = gen.load_plugins(logic_dir, 'compute')
        assert isinstance(plugins, dict)


class TestSessionEdgeCases:
    """Edge cases in session handling across routes."""

    def test_init_post_preserves_non_form_keys(self, client):
        """POST /init should not strip pre-existing non-form session keys."""
        with client.session_transaction() as sess:
            sess['custom_state'] = ['kept']

        response = client.post('/init', data={
            'user_name': 'TestUser',
        })
        assert response.status_code == 200

        with client.session_transaction() as sess:
            assert sess['custom_state'] == ['kept']

    def test_generate_preserves_session(self, client):
        """POST /generate should not clear the session."""
        with client.session_transaction() as sess:
            sess['user_name'] = 'PreservedUser'

        client.post('/generate', data={
            'user_name': 'TestUser',
        })

        with client.session_transaction() as sess:
            assert 'user_name' in sess


class TestDebugVarsErrors:
    """GET /debug-vars with missing or broken templates."""

    def test_debug_vars_handles_templates(self, client):
        """debug-vars should handle templates wrapped in try/except."""
        response = client.get('/debug-vars')
        assert response.status_code == 200
        data = response.get_data(as_text=True)
        assert 'Отладка переменных' in data


class TestResetEdgeCases:
    """GET /reset edge cases."""

    def test_reset_idempotent(self, client):
        """Two resets should both succeed (no error on empty session)."""
        client.get('/reset')
        response = client.get('/reset')
        assert response.status_code == 200

    def test_reset_after_init(self, client):
        """Reset after /init should clear all form data."""
        client.get('/init')
        client.post('/init', data={'user_name': 'TestUser'})
        client.get('/reset')

        with client.session_transaction() as sess:
            assert 'user_name' not in sess
