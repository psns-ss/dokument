"""
Tests for app/session_manager.py.

Covers SessionManager class: state transitions, data access, upload handling,
and form data management.
"""

import pytest
from pathlib import Path
from session_manager import SessionManager, get_file


class TestGetFile:
    """Tests for get_file() - standalone and method."""

    def test_get_file_empty_session(self):
        """get_file should return empty list when session has no uploaded_files."""
        paths = get_file({}, 'cv')
        assert paths == []

    def test_get_file_no_key(self):
        """get_file should return empty list when variable not in uploaded_files."""
        session = {'uploaded_files': {'portfolio': ['/path/p.docx']}}
        paths = get_file(session, 'cv')
        assert paths == []

    def test_get_file_with_data(self):
        """get_file should return file paths for the variable."""
        session = {
            'uploaded_files': {
                'cv': ['/path/to/cv_0.docx'],
                'portfolio': ['/path/to/p_0.docx']
            }
        }
        assert get_file(session, 'cv') == ['/path/to/cv_0.docx']
        assert get_file(session, 'portfolio') == ['/path/to/p_0.docx']
        assert get_file(session, 'missing') == []

class TestClearForInit:
    """Tests for clear_for_init() - nuke pattern (preserve active_pack + session_id)."""

    def test_clears_all_except_active_pack_and_session_id(self):
        """clear_for_init should nuke everything except active_pack and session_id."""
        session = {
            'active_pack': 'root',
            'session_id': 'abc-123',
            'uploaded_files': {'cv': ['/path/to/cv_0.docx']},
            'matched_entities': {'university': ['mgu']},
            'matched_university': ['mgu'],
            'user_name': 'Test'
        }
        mgr = SessionManager(session)
        mgr.clear_for_init()

        assert session['active_pack'] == 'root'
        assert session['session_id'] == 'abc-123'
        assert 'uploaded_files' not in session
        assert 'matched_entities' not in session
        assert 'matched_university' not in session
        assert 'user_name' not in session

    def test_clears_noop_when_empty(self):
        """clear_for_init should work with empty session."""
        session = {}
        mgr = SessionManager(session)
        mgr.clear_for_init()
        assert session == {}

    def test_unlinks_old_uploaded_files(self, temp_dir):
        """clear_for_init should delete old uploaded files from disk."""
        old_file = temp_dir / 'cv_old.docx'
        old_file.write_text('old content')
        session = {
            'active_pack': 'root',
            'session_id': 'abc-123',
            'uploaded_files': {'cv': [str(old_file)]}
        }
        mgr = SessionManager(session)
        mgr.clear_for_init()

        assert not old_file.exists()
        assert 'uploaded_files' not in session

    def test_preserves_active_pack_and_session_id_only(self):
        """clear_for_init should only preserve active_pack and session_id."""
        session = {
            'active_pack': 'my_pack',
            'session_id': 'xyz-789',
            'form_data': 'value',
            'matched_entities': {'key': ['val']}
        }
        mgr = SessionManager(session)
        mgr.clear_for_init()

        assert session == {'active_pack': 'my_pack', 'session_id': 'xyz-789'}


class TestClearForPackSwitch:
    """Tests for clear_for_pack_switch() - nuke pattern (preserve only active_pack)."""

    def test_clears_all_except_active_pack(self):
        """clear_for_pack_switch should nuke everything except active_pack."""
        session = {
            'active_pack': 'old_pack',
            'session_id': 'abc-123',
            'uploaded_files': {'cv': ['/path/cv.docx']},
            'matched_entities': {'university': ['MGU']},
            'matched_university': ['MGU'],
            'user_name': 'John',
            'user_age': '25'
        }
        mgr = SessionManager(session)
        mgr.clear_for_pack_switch()

        assert session['active_pack'] == 'old_pack'
        assert 'session_id' not in session
        assert 'uploaded_files' not in session
        assert 'matched_entities' not in session
        assert 'matched_university' not in session
        assert 'user_name' not in session
        assert 'user_age' not in session

    def test_preserves_active_pack_key(self):
        """clear_for_pack_switch should preserve active_pack key."""
        session = {'active_pack': 'my_pack', 'user_data': 'value'}
        mgr = SessionManager(session)
        mgr.clear_for_pack_switch()

        assert session['active_pack'] == 'my_pack'
        assert 'user_data' not in session

    def test_clears_noop_when_empty(self):
        """clear_for_pack_switch should work with empty session."""
        session = {}
        mgr = SessionManager(session)
        mgr.clear_for_pack_switch()
        assert session == {}

    def test_unlinks_old_uploaded_files(self, temp_dir):
        """clear_for_pack_switch should delete old uploaded files from disk."""
        old_file = temp_dir / 'cv_old.docx'
        old_file.write_text('old content')
        session = {
            'active_pack': 'root',
            'session_id': 'abc-123',
            'uploaded_files': {'cv': [str(old_file)]}
        }
        mgr = SessionManager(session)
        mgr.clear_for_pack_switch()

        assert not old_file.exists()
        assert 'uploaded_files' not in session
        assert 'session_id' not in session


class TestSessionManagerInit:
    """Tests for SessionManager initialization."""

    def test_init_with_empty_session(self):
        """SessionManager should wrap an empty session dict."""
        session = {}
        mgr = SessionManager(session)
        assert mgr.session is session
        assert len(mgr.session) == 0

    def test_init_with_populated_session(self):
        """SessionManager should wrap a populated session dict."""
        session = {'key1': 'value1', 'key2': 'value2'}
        mgr = SessionManager(session)
        assert mgr.session is session
        assert mgr.session['key1'] == 'value1'


class TestSaveFormData:
    """Tests for save_form_data() - saves user form values."""

    def test_saves_regular_form_fields(self):
        """save_form_data should save regular form fields."""
        session = {}
        mgr = SessionManager(session)
        form_data = {'user_name': 'John', 'user_age': '25'}
        mgr.save_form_data(form_data)
        assert session['user_name'] == 'John'
        assert session['user_age'] == '25'

    def test_handles_empty_form_data(self):
        """save_form_data should handle empty form data."""
        session = {'existing': 'value'}
        mgr = SessionManager(session)
        mgr.save_form_data({})
        assert session == {'existing': 'value'}

    def test_overwrites_existing_values(self):
        """save_form_data should overwrite existing session values."""
        session = {'user_name': 'OldName'}
        mgr = SessionManager(session)
        mgr.save_form_data({'user_name': 'NewName'})
        assert session['user_name'] == 'NewName'

    def test_saves_all_keys_including_table_fields(self):
        """save_form_data should save all form fields without filtering."""
        session = {}
        mgr = SessionManager(session)
        form_data = {
            'user_name': 'John',
            'table_map[0]': 'table_1',
            'table_key[0]': 'cv:0:2',
        }
        mgr.save_form_data(form_data)
        assert session['user_name'] == 'John'
        assert session['table_map[0]'] == 'table_1'
        assert session['table_key[0]'] == 'cv:0:2'


class TestGetFormData:
    """Tests for get_form_data() - retrieves user form values."""

    def test_excludes_uploaded_files(self):
        """get_form_data should exclude uploaded_files key."""
        session = {
            'user_name': 'John',
            'uploaded_files': {'cv': ['/path/cv.docx']}
        }
        mgr = SessionManager(session)
        result = mgr.get_form_data()
        assert 'user_name' in result
        assert 'uploaded_files' not in result

    def test_returns_empty_dict_for_system_keys_only(self):
        """get_form_data should return empty dict when only system keys exist."""
        session = {
            'uploaded_files': {'cv': ['/path/cv.docx']}
        }
        mgr = SessionManager(session)
        result = mgr.get_form_data()
        assert result == {}

    def test_returns_copy_not_reference(self):
        """get_form_data should return a copy, not the original dict."""
        session = {'user_name': 'John'}
        mgr = SessionManager(session)
        result = mgr.get_form_data()
        result['user_name'] = 'Modified'
        assert session['user_name'] == 'John'  # Original unchanged


class TestSessionManagerIntegration:
    """Integration tests for SessionManager with Flask test client."""

    def test_session_workflow_via_client(self, client):
        """Test a complete session workflow using Flask test client."""
        # Start fresh - GET /init should clear session
        response = client.get('/init')
        assert response.status_code == 200

        # Simulate POST with form data
        response = client.post('/init', data={
            'user_name': 'John',
            'user_age': '30'
        }, follow_redirects=False)
        assert response.status_code in [200, 302]
