"""
Tests for bool variable: signature

Covers: checkbox form rendering, session data handling
"""

import pytest


class TestSignatureBool:
    """Tests for signature bool variable."""

    def test_signature_checkbox_in_form(self, client):
        """GET /init should render checkbox for signature field."""
        resp = client.get('/init')
        assert resp.status_code == 200
        assert b'type="checkbox"' in resp.data
        assert b'name="signature"' in resp.data

    def test_signature_checked_saves_to_session(self, client):
        """POST /init with signature=true should save 'true' to session."""
        resp = client.post('/init', data={
            'user_name': 'Test User',
            'signature': 'true'
        })
        assert resp.status_code == 200
        # Check session data has signature=true
        with client.session_transaction() as sess:
            assert sess.get('signature') == 'true'

    def test_signature_unchecked_absent_from_session(self, client):
        """POST /init without signature should NOT have signature in session."""
        resp = client.post('/init', data={
            'user_name': 'Test User'
            # signature not sent = unchecked
        })
        assert resp.status_code == 200
        # Check session data does NOT have signature
        with client.session_transaction() as sess:
            assert 'signature' not in sess or sess.get('signature') == ''

    def test_signature_checkbox_auto_submit_includes_data(self, client):
        """POST /init with signature should store it in session for auto-submit."""
        resp = client.post('/init', data={
            'user_name': 'Test User',
            'signature': 'true'
        })
        assert resp.status_code == 200
        # Data is in session, not in auto-submit form. Verify session has it.
        with client.session_transaction() as sess:
            assert sess.get('signature') == 'true'
