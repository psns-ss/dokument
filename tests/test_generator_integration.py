"""
Integration tests for app/generator.py.

Tests the full workflow: GET /init → POST /init → POST /generate.
Also tests multi-step flows with file uploads and matching.

These tests use real templates from templates/ directory and the Flask test client.
They verify end-to-end behavior without mocking internal modules.
"""

import pytest
from pathlib import Path
from unittest.mock import patch


class TestFullWorkflow:
    """Complete form → generate workflow."""

    def test_get_init_returns_form(self, client):
        """GET /init should return the form page."""
        response = client.get('/init')
        assert response.status_code == 200
        data = response.get_data(as_text=True)
        assert '<input' in data or '<select' in data

    def test_post_init_then_generate(self, client):
        """POST /init with data then POST /generate should complete."""
        # Step 1: Submit form
        response = client.post('/init', data={
            'user_name': 'IntegrationTestUser',
            'user_age': '28',
            'sex': 'Мужской',
        })
        assert response.status_code == 200

        # Step 2: Session should have data
        with client.session_transaction() as sess:
            assert sess.get('user_name') == 'IntegrationTestUser'

    def test_workflow_without_file_auto_submits(self, client):
        """POST /init without file should return auto-submit HTML."""
        response = client.post('/init', data={
            'user_name': 'AutoSubmitUser',
        })
        assert response.status_code == 200
        data = response.get_data(as_text=True)
        assert 'genform' in data
        assert '/generate' in data

    def test_session_data_preserved_across_requests(self, client):
        """active_pack and session_id should persist across GET /init (nuke pattern).

        GET /init clears all session data except active_pack and session_id.
        User-provided form data is cleared on GET /init (start fresh).
        """
        client.post('/init', data={'user_name': 'PersistentUser'})

        # Make another request — GET /init clears all except active_pack/session_id
        client.get('/init')

        with client.session_transaction() as sess:
            # GET /init nukes everything except active_pack and session_id
            assert 'active_pack' in sess
            assert 'session_id' in sess
            # User data is cleared on GET /init
            assert 'user_name' not in sess


class TestDebugEndpoint:
    """Debug endpoint integration tests."""

    def test_debug_vars_lists_all_templates(self, client):
        """GET /debug-vars should show all template files."""
        response = client.get('/debug-vars')
        assert response.status_code == 200
        data = response.get_data(as_text=True)

        # Should mention at least one template
        assert 'template' in data.lower()

    def test_debug_vars_shows_extracted_variables(self, client):
        """GET /debug-vars should show extracted variable names."""
        response = client.get('/debug-vars')
        data = response.get_data(as_text=True)

        # Should show variables like user_name, user_age, etc.
        has_variable = any(var in data for var in ['user_name', 'user_age', 'sex'])
        assert has_variable


class TestResetWorkflow:
    """Reset and re-init workflow."""

    def test_reset_then_init_fresh(self, client):
        """After reset, GET /init should show a clean form."""
        client.post('/init', data={'user_name': 'OldUser'})
        client.get('/reset')
        response = client.get('/init')

        assert response.status_code == 200
        with client.session_transaction() as sess:
            assert 'user_name' not in sess

    def test_multiple_cycles(self, client):
        """Multiple init → post → reset cycles should work."""
        for i in range(3):
            client.get('/init')
            client.post('/init', data={'user_name': f'Cycle{i}'})
            client.get('/reset')

        with client.session_transaction() as sess:
            user_keys = [k for k in sess if not k.startswith('_')]
            assert len(user_keys) == 0


class TestGenerateEndpointIntegration:
    """POST /generate with realistic data."""

    def test_generate_creates_output_files(self, client, isolate_document_store: Path):
        """POST /generate should create output files in document_store.

        The store comes from the autouse fixture, so a non-200 here is a real
        failure — not the Docker-only default path being unwritable.
        """
        response = client.post('/generate', data={
            'user_name': 'OutputTestUser',
            'user_age': '30',
            'sex': 'Мужской',
        })
        assert response.status_code == 200

        with client.session_transaction() as sess:
            session_id = sess.get('session_id')
        assert session_id, "session_id missing — nothing could have been written"
        session_dir = isolate_document_store / session_id
        assert list(session_dir.glob('generated_*.docx')), (
            f"No generated files found in {session_dir}"
        )


class TestGenerateFullRender:
    """Integration tests that exercise the full render pipeline (no mocks)."""

    def test_generate_with_real_render_creates_files(self, client, tmp_path):
        """POST /generate should render templates and create output files.

        Regression test: template_paths were converted to strings ([str(p) for p...]),
        but renderer.py accessed tmpl_path.name (Path-only attribute), causing
        AttributeError for every template and empty outputs → 500.
        """
        # Override document_store to a writable temp directory
        from config import cfg
        original_store = cfg.document_store
        cfg.document_store = tmp_path
        try:
            response = client.post('/generate', data={
                'user_name': 'RenderTestUser',
                'user_age': '30',
                'sex': 'Мужской',
            })
            assert response.status_code == 200, (
                f"Expected 200, got {response.status_code}. "
                f"This usually means render_templates failed silently."
            )

            # Verify output files were created
            session_id = None
            with client.session_transaction() as sess:
                session_id = sess.get('session_id')

            if session_id:
                session_dir = tmp_path / session_id
                output_files = list(session_dir.glob('generated_*.docx')) if session_dir.exists() else []
                assert len(output_files) > 0, (
                    f"No generated files found in {session_dir}. "
                    f"render_templates may have silently failed."
                )
        finally:
            cfg.document_store = original_store

    def test_generate_passes_path_objects_to_renderer(self, client, tmp_path):
        """Verify render_templates receives Path objects, not strings.

        The renderer accesses tmpl_path.name and tmpl_path.parent,
        which require Path objects. Strings would cause AttributeError.
        """
        from config import cfg
        original_store = cfg.document_store
        cfg.document_store = tmp_path
        try:
            received_types = []

            def capture_types(templates, *args, **kwargs):
                received_types.extend(type(t) for t in templates)
                # Return empty to avoid actual rendering in this test
                return []

            with patch('routes.generate.render_templates', side_effect=capture_types):
                client.post('/generate', data={'user_name': 'TypeTest'})

            # If render_templates was called, verify template types
            if received_types:
                for t in received_types:
                    assert issubclass(t, Path), (
                        f"render_templates received {t.__name__} instead of Path. "
                        f"renderer.py requires Path objects for .name/.parent access."
                    )
        finally:
            cfg.document_store = original_store


class TestSessionKeys:
    """Verify session keys match documented behavior."""

    def test_session_has_expected_keys_after_post(self, client):
        """After POST /init, session should have form data keys."""
        client.post('/init', data={
            'user_name': 'SessionTestUser',
            'user_age': '25',
        })

        with client.session_transaction() as sess:
            assert 'user_name' in sess
            assert 'user_age' in sess
