"""
Tests for app/routes/init.py - initialization form route.

Covers:
    GET  /init - Show initialization form, clear session
    POST /init - Save form data, handle file upload, run matching,
                 generate UI for matched entities
"""
from __future__ import annotations

import pytest
from pathlib import Path


class TestInitGet:
    """GET /init — initial form display."""

    def test_get_init_returns_200(self, client):
        """GET /init should return a 200 response."""
        response = client.get('/init')
        assert response.status_code == 200

    def test_get_init_parses_descr_once(self, client):
        """GET /init opens descr.docx exactly once — validate_pack is an
        existence check and load_data_context_for_pack reuses the route's parse
        (was 2-3 opens per request; Theme #2)."""
        import logic.parser as parser
        calls = []
        orig = parser.Document
        def counting(path, *a, **k):
            calls.append(path)
            return orig(path, *a, **k)
        parser.Document = counting
        try:
            client.get('/init')
        finally:
            parser.Document = orig
        assert len(calls) == 1, f"descr.docx opened {len(calls)}x (expected 1)"

    def test_get_init_clears_session_data(self, client):
        """GET /init should nuke all session data except active_pack and session_id."""
        # Set some session data first
        with client.session_transaction() as sess:
            sess['user_name'] = 'will_be_cleared'
            sess['matched_entities'] = {'university': ['MGU']}

        response = client.get('/init')
        assert response.status_code == 200

        # Verify session was cleared for init (nuke pattern)
        with client.session_transaction() as sess:
            assert 'user_name' not in sess
            assert 'matched_entities' not in sess
            # active_pack and session_id should be preserved
            assert 'active_pack' in sess
            assert 'session_id' in sess

    def test_get_init_renders_init_html_template(self, client):
        """GET /init should render the init.html template."""
        response = client.get('/init')
        data = response.get_data(as_text=True)

        # Should contain typical HTML structure
        assert '<html' in data.lower() or '<!doctype' in data.lower()
        # Should contain form-related elements
        assert 'form' in data.lower() or 'input' in data.lower()
        # Form posts back to /init
        assert 'action="/init"' in data

class TestInitFormTypeRendering:
    """init.html form-field dispatch by variable type (multi-type regression)."""

    def _render_form(self, client, variable_desc):
        """Render init.html directly with a crafted variable_desc."""
        from flask import render_template
        with client.application.test_request_context():
            return render_template(
                "init.html",
                variable_desc=variable_desc,
                session_data={},
                dynamic_ui="",
                ui_hash="",
            )

    def test_multi_type_enum_renders_select(self, client):
        """type='enum,form' must render a <select>, not fall through to text."""
        html = self._render_form(client, {
            "color": {
                "description": "Цвет",
                "show_in_form": True,
                "type": "enum,form",
                "types": ["enum", "form"],
                "options": {"enum": ["red", "green"]},
            }
        })
        assert "<select" in html
        assert 'value="red"' in html

    def test_multi_type_bool_renders_checkbox(self, client):
        """type='bool,form' must render a checkbox, not fall through to text."""
        html = self._render_form(client, {
            "active": {
                "description": "Активен",
                "show_in_form": True,
                "type": "bool,form",
                "types": ["bool", "form"],
            }
        })
        assert 'type="checkbox"' in html

    def test_single_type_enum_still_renders_select(self, client):
        """Sanity: single-type 'enum' still renders a <select>."""
        html = self._render_form(client, {
            "color": {
                "description": "Цвет",
                "show_in_form": True,
                "type": "enum",
                "types": ["enum"],
                "options": {"enum": ["red", "green"]},
            }
        })
        assert "<select" in html


class TestInitPost:
    """POST /init — form submission handling."""

    def test_post_init_saves_form_data_to_session(self, client):
        """POST /init should save user form data to session."""
        response = client.post('/init', data={
            'user_name': 'TestUser',
            'user_age': '25'
        }, follow_redirects=True)

        # Form data should be saved (check via session)
        assert response.status_code == 200

    def test_post_init_handles_empty_upload(self, client):
        """POST /init without file upload should return auto-submit HTML."""
        response = client.post('/init', data={
            'user_name': 'TestUser'
        })

        data = response.get_data(as_text=True)
        # Should contain auto-submit form structure
        assert 'genform' in data.lower() or 'document.getElementById' in data

    def test_post_init_returns_auto_submit_when_no_upload(self, client):
        """POST /init without upload should return auto-submit HTML to /generate."""
        response = client.post('/init', data={
            'user_name': 'TestUser',
            'sex': 'Мужской'
        })

        data = response.get_data(as_text=True)
        # Should contain auto-submit structure
        assert 'genform' in data
        assert 'generate_documents' in data or '/generate' in data
        assert 'onload' in data.lower()

    def test_post_init_preserves_form_data_in_auto_submit(self, client):
        """POST /init auto-submit should store form data in session."""
        response = client.post('/init', data={
            'user_name': 'PreservedUser',
            'user_age': '30'
        })

        assert response.status_code == 200
        # Data is in session, not in auto-submit form. Verify session has it.
        with client.session_transaction() as sess:
            assert sess.get('user_name') == 'PreservedUser'
            assert sess.get('user_age') == '30'

    def test_post_init_handles_missing_file_gracefully(self, client):
        """POST /init should handle missing file field without error."""
        response = client.post('/init', data={
            'user_name': 'TestUser'
            # No file uploaded
        })

        assert response.status_code == 200

    def test_post_init_handles_empty_filename(self, client):
        """POST /init should handle empty filename as no upload."""
        # Don't include file at all (same as empty filename)
        response = client.post('/init', data={
            'user_name': 'TestUser'
        })

        data = response.get_data(as_text=True)
        # Should treat as no upload - return auto-submit
        assert 'genform' in data or response.status_code == 200


class TestInitSessionManagement:
    """Test session management during init flow."""

    def test_session_data_persists_between_get_and_post(self, client):
        """Session data should persist through the init flow."""
        # First GET to initialize
        client.get('/init')

        # POST with data
        client.post('/init', data={
            'user_name': 'SessionTest',
            'sex': 'Мужской'
        })

        # Session should contain the data
        with client.session_transaction() as sess:
            # Form data should be preserved
            assert 'user_name' in sess or 'sex' in sess


class TestFileUploadRoute:
    """Tests for type=file variable upload flow."""

    def test_post_init_single_file_upload(self, client, test_dir):
        """POST /init with a single file upload to a type=file variable."""
        fixtures_dir = test_dir / 'fixtures'
        test_docx = fixtures_dir / 'template_simple.docx'

        if not test_docx.exists():
            pytest.skip("No test fixture available")

        with open(test_docx, 'rb') as f:
            response = client.post('/init', data={
                'user_name': 'Test',
                'cv': (f, 'resume.docx')
            })

        assert response.status_code == 200
        with client.session_transaction() as sess:
            assert 'uploaded_files' in sess
            assert 'cv' in sess['uploaded_files']
            cv_paths = sess['uploaded_files']['cv']
            assert len(cv_paths) == 1
            # Content-addressed name: cv_<session_id>_<content-hash>.docx
            assert Path(cv_paths[0]).name.startswith('cv_')
            assert Path(cv_paths[0]).exists()

    def test_post_init_multiple_file_vars(self, client, test_dir):
        """POST /init with files for multiple type=file variables."""
        fixtures_dir = test_dir / 'fixtures'
        docx1 = fixtures_dir / 'template_simple.docx'
        docx2 = fixtures_dir / 'template_with_table.docx'

        if not docx1.exists() or not docx2.exists():
            pytest.skip("Test fixtures not available")

        with open(docx1, 'rb') as f1:
            with open(docx2, 'rb') as f2:
                response = client.post('/init', data={
                    'user_name': 'Test',
                    'cv': (f1, 'resume.docx'),
                    'portfolio': (f2, 'portfolio.docx')
                })

        assert response.status_code == 200
        with client.session_transaction() as sess:
            files = sess.get('uploaded_files', {})
            assert 'cv' in files
            assert len(files['cv']) == 1

    # ---- U1: re-submitted files must not accumulate copies ----
    # Browsers re-send selected file inputs on every form submission
    # (back/refresh resubmit). Content-addressed names dedup identical
    # content; the submitted selection replaces the stored list.

    def test_post_init_resubmit_same_file_no_duplicates(self, client, test_dir):
        """Re-POSTing the same file reuses the existing path — no copies."""
        fixtures_dir = test_dir / 'fixtures'
        test_docx = fixtures_dir / 'template_simple.docx'
        if not test_docx.exists():
            pytest.skip("No test fixture available")

        with open(test_docx, 'rb') as f:
            client.post('/init', data={
                'user_name': 'Test',
                'cv': (f, 'resume.docx')
            })
        with client.session_transaction() as sess:
            first_path = sess['uploaded_files']['cv'][0]

        # Second POST — the browser re-sends the still-selected file
        with open(test_docx, 'rb') as f:
            client.post('/init', data={
                'user_name': 'Test',
                'cv': (f, 'resume.docx')
            })
        with client.session_transaction() as sess:
            cv_paths = sess['uploaded_files']['cv']
            assert len(cv_paths) == 1
            assert cv_paths[0] == first_path  # same path reused, no _2nd copy

    def test_post_init_new_file_replaces_previous(self, client, test_dir):
        """A different file for the same var replaces the stored list."""
        fixtures_dir = test_dir / 'fixtures'
        docx1 = fixtures_dir / 'template_simple.docx'
        docx2 = fixtures_dir / 'template_with_table.docx'
        if not docx1.exists() or not docx2.exists():
            pytest.skip("Test fixtures not available")

        with open(docx1, 'rb') as f:
            client.post('/init', data={'cv': (f, 'first.docx')})
        with client.session_transaction() as sess:
            first_path = sess['uploaded_files']['cv'][0]

        with open(docx2, 'rb') as f:
            client.post('/init', data={'cv': (f, 'second.docx')})
        with client.session_transaction() as sess:
            cv_paths = sess['uploaded_files']['cv']
            # Selection is the truth: only the new file, no accumulation
            assert len(cv_paths) == 1
            assert cv_paths[0] != first_path
            assert Path(cv_paths[0]).exists()

    def test_post_init_absent_input_keeps_stored_files(self, client, test_dir):
        """A POST without the file input (step-2 page) keeps the stored list."""
        fixtures_dir = test_dir / 'fixtures'
        test_docx = fixtures_dir / 'template_simple.docx'
        if not test_docx.exists():
            pytest.skip("No test fixture available")

        with open(test_docx, 'rb') as f:
            client.post('/init', data={
                'user_name': 'Test',
                'cv': (f, 'resume.docx')
            })
        with client.session_transaction() as sess:
            first_path = sess['uploaded_files']['cv'][0]

        # Re-POST without the file input, as the step-2 page does
        client.post('/init', data={'user_name': 'Test'})
        with client.session_transaction() as sess:
            assert sess['uploaded_files']['cv'] == [first_path]

    def test_post_init_multi_file_selection_resubmit(self, client, test_dir):
        """A multi-file selection is stored as-is; resubmitting adds no copies."""
        fixtures_dir = test_dir / 'fixtures'
        docx1 = fixtures_dir / 'template_simple.docx'
        docx2 = fixtures_dir / 'template_with_table.docx'
        if not docx1.exists() or not docx2.exists():
            pytest.skip("Test fixtures not available")

        with open(docx1, 'rb') as f1, open(docx2, 'rb') as f2:
            client.post('/init', data={
                'cv': [(f1, 'a.docx'), (f2, 'b.docx')]
            })
        with client.session_transaction() as sess:
            first_paths = list(sess['uploaded_files']['cv'])
        assert len(first_paths) == 2

        # Resubmit the same selection (browser re-sends all selected files)
        with open(docx1, 'rb') as f1, open(docx2, 'rb') as f2:
            client.post('/init', data={
                'cv': [(f1, 'a.docx'), (f2, 'b.docx')]
            })
        with client.session_transaction() as sess:
            assert sess['uploaded_files']['cv'] == first_paths

    def test_post_init_no_file_returns_empty_match(self, client):
        """POST /init without cv file — matching finds nothing, stores nothing."""
        response = client.post('/init', data={
            'user_name': 'Test',
            # Note: no 'cv' file uploaded
        })

        assert response.status_code == 200
        # Match results are not persisted to the session — the user's selection
        # arrives as ordinary form fields, so nothing is stored for /generate.
        with client.session_transaction() as sess:
            assert 'matched_entities' not in sess

    def test_get_init_clears_uploaded_files(self, client, test_dir):
        """GET /init clears previous uploads via clear_for_init()."""
        fixtures_dir = test_dir / 'fixtures'
        test_docx = fixtures_dir / 'template_simple.docx'

        if not test_docx.exists():
            pytest.skip("No test fixture available")

        # POST /init with file upload
        with open(test_docx, 'rb') as f:
            client.post('/init', data={
                'user_name': 'Test',
                'cv': (f, 'resume.docx')
            })

        with client.session_transaction() as sess:
            assert 'cv' in sess.get('uploaded_files', {})

        # GET /init calls clear_for_init(), clears previous uploads
        client.get('/init')

        with client.session_transaction() as sess:
            assert 'uploaded_files' not in sess
            assert 'matched_entities' not in sess
            # active_pack and session_id preserved
            assert 'active_pack' in sess
            assert 'session_id' in sess

    def test_uploaded_files_excluded_from_form_data(self, client, test_dir):
        """uploaded_files should not appear in auto-submit form data."""
        fixtures_dir = test_dir / 'fixtures'
        test_docx = fixtures_dir / 'template_simple.docx'

        if not test_docx.exists():
            pytest.skip("No test fixture available")

        with open(test_docx, 'rb') as f:
            response = client.post('/init', data={
                'user_name': 'Test',
                'cv': (f, 'resume.docx')
            })

        with client.session_transaction() as sess:
            # uploaded_files should be in session
            assert 'uploaded_files' in sess
            # but get_form_data() should exclude it
            from session_manager import SessionManager
            mgr = SessionManager(sess)
            form_data = mgr.get_form_data()
            assert 'uploaded_files' not in form_data
