"""
Tests for app/routes/debug.py debug endpoints.

Covers:
    GET /debug-vars - variable extraction analysis
    GET /reset      - session clearing
"""
import pytest


class TestDebugVars:
    """GET /debug-vars — variable extraction debug endpoint."""

    def test_debug_vars_returns_200(self, client):
        """GET /debug-vars should return a 200 response."""
        response = client.get('/debug-vars')
        assert response.status_code == 200

    def test_debug_vars_shows_html_content(self, client):
        """GET /debug-vars should return HTML content."""
        response = client.get('/debug-vars')
        data = response.get_data(as_text=True)
        assert '<h1>' in data or 'Variable' in data or 'template' in data.lower()

    def test_debug_vars_lists_templates(self, client):
        """GET /debug-vars should list template paths."""
        response = client.get('/debug-vars')
        data = response.get_data(as_text=True)
        # Should contain some indication of templates being processed
        assert 'шаблонов' in data or 'descr.docx' in data or '<h2>' in data


class TestReset:
    """GET /reset — session clearing endpoint."""

    def test_reset_clears_session(self, client):
        """GET /reset should clear all session data."""
        # Set some session data
        with client.session_transaction() as sess:
            sess['user_name'] = 'TestUser'
            sess['tables_info'] = {'0': {}}

        # Call reset
        response = client.get('/reset')
        assert response.status_code == 200

        # Verify session is cleared (flask-session keeps _permanent)
        with client.session_transaction() as sess:
            user_keys = [k for k in sess if not k.startswith('_')]
            assert len(user_keys) == 0

    def test_reset_returns_html_with_link(self, client):
        """GET /reset should return HTML with a link back to /init."""
        response = client.get('/reset')
        data = response.get_data(as_text=True)
        assert '<a' in data or 'link' in data.lower() or 'href' in data
        # Link points back to /init
        assert '/init' in data

    def test_reset_clears_user_variable(self, client):
        """GET /reset should remove user variables from session."""
        with client.session_transaction() as sess:
            sess['user_name'] = 'ToDelete'

        client.get('/reset')

        with client.session_transaction() as sess:
            assert 'user_name' not in sess

    def test_reset_clears_uploaded_doc_path(self, client):
        """GET /reset should remove uploaded_doc_path from session."""
        with client.session_transaction() as sess:
            sess['uploaded_doc_path'] = '/some/path.docx'

        client.get('/reset')

        with client.session_transaction() as sess:
            assert 'uploaded_doc_path' not in sess


class TestCleanupStaleSessions:
    """_cleanup_stale_sessions() — TTL sweep of the document store."""

    def test_removes_old_keeps_recent(self, tmp_path):
        import os
        import time
        from routes.debug import _cleanup_stale_sessions

        recent = tmp_path / 'recent'
        recent.mkdir()

        old = tmp_path / 'old'
        old.mkdir()
        (old / 'f.docx').write_text('x')
        old_file = tmp_path / 'oldfile.txt'
        old_file.write_text('x')

        # Age the two "old" entries to 20 days (past the 14-day TTL).
        t = time.time() - 20 * 86400
        for p in (old, old / 'f.docx', old_file):
            os.utime(p, (t, t))

        removed = _cleanup_stale_sessions(tmp_path, 14)

        assert not old.exists()
        assert not old_file.exists()
        assert recent.exists()
        assert removed == 2

    def test_missing_dir_is_noop(self, tmp_path):
        from routes.debug import _cleanup_stale_sessions
        assert _cleanup_stale_sessions(tmp_path / 'nope', 14) == 0
