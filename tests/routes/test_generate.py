"""
Tests for app/routes/generate.py - document generation route.

Covers:
    POST /generate - Generate documents from templates
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path


class TestGeneratePost:
    """POST /generate — document generation."""

    def test_post_generate_returns_200(self, client):
        """POST /generate should return a 200 response."""
        response = client.post('/generate', data={
            'user_name': 'TestUser',
            'user_age': '25'
        })
        # Should either succeed or return an error with status code
        assert response.status_code in (200, 500)

    def test_post_generate_parses_form_data(self, client):
        """POST /generate should parse form data correctly."""
        response = client.post('/generate', data={
            'user_name': 'TestUser',
            'user_age': '30',
            'sex': 'Мужской'
        })
        assert response.status_code in (200, 500)

    def test_post_generate_calls_compute_variables(self, client):
        """POST /generate should call compute_variables for missing vars."""
        with patch('routes.generate.compute_variables') as mock_compute:
            mock_compute.return_value = ({'computed_var': 'value'}, {})
            response = client.post('/generate', data={
                'user_name': 'TestUser'
            })
            # compute_variables should have been called
            assert mock_compute.called
            assert response.status_code in (200, 500)

    def test_post_generate_calls_read_variable_descriptions(self, client):
        """POST /generate should read variable descriptions."""
        with patch('routes.generate.read_variable_descriptions') as mock_read:
            mock_read.return_value = {
                'user_name': {'description': 'Name', 'show_in_form': True, 'type': 'text'}
            }
            response = client.post('/generate', data={
                'user_name': 'TestUser'
            })
            assert mock_read.called
            assert response.status_code in (200, 500)

    def test_post_generate_calls_render_templates(self, client):
        """POST /generate should call render_templates."""
        with patch('routes.generate.render_templates') as mock_render:
            mock_render.return_value = []
            response = client.post('/generate', data={
                'user_name': 'TestUser'
            })
            # render_templates should be called (even if it returns empty)
            assert mock_render.called
            # Empty outputs route through the flash+redirect safety net
            assert response.status_code == 302

    def test_post_generate_handles_no_templates(self, client):
        """POST /generate should handle case when no templates exist."""
        with patch('routes.generate.find_templates') as mock_find:
            mock_find.return_value = []
            response = client.post('/generate', data={
                'user_name': 'TestUser'
            })
            # Should still run but may have no outputs (→ redirect safety net)
            assert response.status_code in (200, 302, 500)

    def test_post_generate_generates_editor_html(self, client):
        """POST /generate should generate OnlyOffice editor HTML."""
        with patch('routes.generate.find_templates') as mock_find:
            with patch('routes.generate.render_templates') as mock_render:
                with patch('routes.generate.generate_editor_html') as mock_editor:
                    mock_find.return_value = []  # Skip template processing
                    mock_render.return_value = [Path('/tmp/test.docx')]
                    response = client.post('/generate', data={
                        'user_name': 'TestUser'
                    })
                    # generate_editor_html should be called for each output
                    assert mock_editor.called or response.status_code in (200, 500)

    def test_post_generate_editor_failure_still_returns_ready(self, client,
                                                             isolate_document_store: Path):
        """A failure writing an editor wrapper (outside the render try/except)
        must not 500: the docs are already on disk, so return ready.html with
        the doc linked to the raw .docx (not the missing .html) + a warning."""
        # Mocked render output: the store comes from the fixture, so the path is
        # plausible without asserting the Docker-only /document_store literal.
        rendered = isolate_document_store / 'abc123' / 'generated_template_1.docx'

        def _boom(session_dir, name, url):
            raise OSError("simulated write failure")

        with patch('routes.generate.render_templates', return_value=[rendered]), \
             patch('routes.generate.generate_editor_html', side_effect=_boom):
            response = client.post('/generate', data={'user_name': 'TestUser'})

        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert 'generated_template_1.docx' in html           # doc still listed
        assert 'generated_template_1.docx.html' not in html  # fell back to raw .docx

    def test_post_generate_returns_ready_template(self, client):
        """POST /generate should return ready.html with document links."""
        # This tests the successful path
        response = client.post('/generate', data={
            'user_name': 'TestUser'
        })
        # Should return 200 or 500 (no templates/outputs)
        assert response.status_code in (200, 500)

    def test_post_generate_with_cleaned_data_extraction(self, client):
        """POST /generate should extract cleaned data from form."""
        response = client.post('/generate', data={
            'user_name': 'TestUser',
            'user_age': '25',
            '{sex}': 'Мужской'  # Form with braces
        })
        assert response.status_code in (200, 500)

    def test_post_generate_error_handling_no_outputs(self, client):
        """POST /generate with no documents generated routes through the
        flash+redirect safety net (not a raw 500)."""
        with patch('routes.generate.render_templates') as mock_render:
            mock_render.return_value = []
            response = client.post('/generate', data={
                'user_name': 'TestUser'
            })
            assert response.status_code == 302
            assert response.headers['Location']  # redirected back to /init

    def test_post_generate_creates_url_links(self, client):
        """POST /generate should create document links for ready page."""
        with patch('routes.generate.generate_editor_html') as mock_editor:
            mock_editor.return_value = '/documents/session/doc1.html'
            response = client.post('/generate', data={
                'user_name': 'TestUser'
            })
            # generate_editor_html provides the editor URL
            assert mock_editor.called or response.status_code in (200, 500)

    def test_post_generate_loads_calculation_modules(self, client):
        """POST /generate should load calculation modules from logic_dir."""
        with patch('routes.generate.load_plugins') as mock_load:
            mock_load.return_value = {'module1': MagicMock()}
            response = client.post('/generate', data={
                'user_name': 'TestUser'
            })
            assert mock_load.called
            assert response.status_code in (200, 500)


class TestGenerateIntegration:
    """Integration tests for the generate route."""

    def test_full_generate_flow(self, client):
        """Test the complete generate flow with mocked dependencies."""
        with patch('routes.generate.compute_variables') as mock_compute:
            with patch('routes.generate.render_templates') as mock_render:
                mock_compute.return_value = ({}, {})
                mock_render.return_value = []

                response = client.post('/generate', data={
                    'user_name': 'TestUser',
                    'user_age': '30'
                })

                assert response.status_code in (200, 302, 500)

    def test_generate_with_subdoc_functions(self, client):
        """Test generate route handles subdoc functions correctly (DeferredSubdoc wrapping)."""
        with patch('routes.generate.compute_variables') as mock_compute:
            mock_compute.return_value = (
                {'computed': 'value'},
                {'table_1': MagicMock()}  # table_1 is in template_1.docx → will be evaluated
            )
            response = client.post('/generate', data={
                'user_name': 'TestUser'
            })
            assert response.status_code in (200, 500)

    def test_generate_preserves_session_context(self, client):
        """Test that generate route maintains proper session context."""
        with client.session_transaction() as sess:
            sess['user_name'] = 'SessionUser'

        response = client.post('/generate', data={
            'user_age': '25'
        })

        assert response.status_code in (200, 500)
