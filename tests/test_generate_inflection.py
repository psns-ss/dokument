"""
Tests for app/routes/generate.py — InflectedWord wrapping + enqueue_save.
"""

import pytest
from unittest.mock import patch, MagicMock


class TestInflectedWordWrapping:
    """Test that generate.py wraps inflection dicts as InflectedWord."""

    def test_inflected_dict_wrapped_as_inflected_word(self, client):
        """Inflection dict in session -> wrapped as InflectedWord in context."""
        from logic.inflection import InflectedWord

        # Set up session with inflection dict for org_name
        with client.session_transaction() as sess:
            sess['org_name'] = {"no": "Ромашка", "ge": "Ромашки", "da": "Ромашке"}

        with patch('routes.generate.compute_variables') as mock_compute:
            with patch('routes.generate.render_templates') as mock_render:
                with patch('routes.generate.enqueue_save'):
                    mock_compute.return_value = ({}, {})
                    mock_render.return_value = []  # No templates -> 500, but we check the call

                    client.post('/generate')

                    # Check that render_templates was called with InflectedWord in context
                    assert mock_render.called
                call_args = mock_render.call_args
                context = call_args.kwargs.get('context') or call_args.args[1]

                # The context should have org_name as InflectedWord (via DataContext)
                # DataContext wraps it, so check the attribute
                org_name = getattr(context, 'org_name', None)
                assert org_name is not None
                assert isinstance(org_name, InflectedWord)

    def test_single_form_expands_to_all_cases(self, client):
        """Single form inflection -> InflectedWord with _single expansion."""
        from logic.inflection import InflectedWord

        with client.session_transaction() as sess:
            sess['org_name'] = {"no": "Дек-1"}  # single form

        with patch('routes.generate.compute_variables') as mock_compute:
            with patch('routes.generate.render_templates') as mock_render:
                mock_compute.return_value = ({}, {})
                mock_render.return_value = []

                client.post('/generate')

                assert mock_render.called
                call_args = mock_render.call_args
                context = call_args.kwargs.get('context') or call_args.args[1]

                org_name = getattr(context, 'org_name', None)
                assert org_name is not None
                assert isinstance(org_name, InflectedWord)
                # Single form should expand to all declared cases
                # org_name in descr.docx declares: no, ge, pre
                assert org_name.ge == "Дек-1"
                assert org_name.pre == "Дек-1"

    def test_empty_dict_not_wrapped(self, client):
        """Empty inflection dict -> not wrapped as InflectedWord."""
        from logic.inflection import InflectedWord

        with client.session_transaction() as sess:
            sess['org_name'] = {}  # empty dict

        with patch('routes.generate.compute_variables') as mock_compute:
            with patch('routes.generate.render_templates') as mock_render:
                mock_compute.return_value = ({}, {})
                mock_render.return_value = []

                client.post('/generate')

                assert mock_render.called
                call_args = mock_render.call_args
                context = call_args.kwargs.get('context') or call_args.args[1]

                org_name = getattr(context, 'org_name', None)
                # Empty dict should not be wrapped -> remains as empty dict or ""
                assert not isinstance(org_name, InflectedWord)

    def test_non_dict_not_wrapped(self, client):
        """Non-dict inflection value -> not wrapped."""
        with client.session_transaction() as sess:
            sess['org_name'] = "plain string"

        with patch('routes.generate.compute_variables') as mock_compute:
            with patch('routes.generate.render_templates') as mock_render:
                mock_compute.return_value = ({}, {})
                mock_render.return_value = []

                client.post('/generate')

                assert mock_render.called

    def test_already_inflected_word_not_double_wrapped(self, client):
        """InflectedWord from compute plugin -> not double-wrapped."""
        from logic.inflection import InflectedWord

        with client.session_transaction() as sess:
            sess['org_name'] = {"no": "A", "ge": "B"}

        # Simulate compute plugin returning InflectedWord
        with patch('routes.generate.compute_variables') as mock_compute:
            with patch('routes.generate.render_templates') as mock_render:
                # compute_variables returns InflectedWord in computed_values
                mock_compute.return_value = (
                    {"org_name": InflectedWord({"no": "Computed", "ge": "Computed-ge"})},
                    {}
                )
                mock_render.return_value = []

                client.post('/generate')

                assert mock_render.called
                call_args = mock_render.call_args
                context = call_args.kwargs.get('context') or call_args.args[1]

                org_name = getattr(context, 'org_name', None)
                assert org_name is not None
                assert isinstance(org_name, InflectedWord)
                assert org_name.no == "Computed"


class TestEnqueueSave:
    """Test that enqueue_save is called for multi-form inflections."""

    def test_enqueue_save_called_multi_form(self, client):
        """Multi-form inflection dict -> enqueue_save called."""
        with client.session_transaction() as sess:
            sess['org_name'] = {"no": "Ромашка", "ge": "Ромашки"}

        with patch('routes.generate.compute_variables') as mock_compute:
            with patch('routes.generate.render_templates') as mock_render:
                with patch('routes.generate.enqueue_save') as mock_enqueue:
                    mock_compute.return_value = ({}, {})
                    mock_render.return_value = []

                    client.post('/generate')

                    assert mock_enqueue.called
                    # Check the forms dict passed to enqueue_save
                    call_args = mock_enqueue.call_args
                    forms = call_args.args[0]
                    assert forms["no"] == "Ромашка"
                    assert forms["ge"] == "Ромашки"

    def test_enqueue_save_not_called_single_form(self, client):
        """Single-form inflection -> enqueue_save NOT called."""
        with client.session_transaction() as sess:
            sess['org_name'] = {"no": "Дек-1"}

        with patch('routes.generate.compute_variables') as mock_compute:
            with patch('routes.generate.render_templates') as mock_render:
                with patch('routes.generate.enqueue_save') as mock_enqueue:
                    mock_compute.return_value = ({}, {})
                    mock_render.return_value = []

                    client.post('/generate')

                    assert not mock_enqueue.called

    def test_enqueue_save_not_called_empty(self, client):
        """Empty inflection dict -> enqueue_save NOT called."""
        with client.session_transaction() as sess:
            sess['org_name'] = {}

        with patch('routes.generate.compute_variables') as mock_compute:
            with patch('routes.generate.render_templates') as mock_render:
                with patch('routes.generate.enqueue_save') as mock_enqueue:
                    mock_compute.return_value = ({}, {})
                    mock_render.return_value = []

                    client.post('/generate')

                    assert not mock_enqueue.called

    def test_enqueue_save_skipped_non_inflection_var(self, client):
        """Non-inflection variable -> enqueue_save NOT called."""
        with client.session_transaction() as sess:
            sess['user_name'] = "TestUser"

        with patch('routes.generate.compute_variables') as mock_compute:
            with patch('routes.generate.render_templates') as mock_render:
                with patch('routes.generate.enqueue_save') as mock_enqueue:
                    mock_compute.return_value = ({}, {})
                    mock_render.return_value = []

                    client.post('/generate')

                    assert not mock_enqueue.called
