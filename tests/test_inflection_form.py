"""
Tests for inflection form handling:
- init.html renders inflection fields for variables with case options (`options["text"]`)
- POST /init collects scatter keys into dicts
- Scatter keys are cleaned from session
"""

import pytest


class TestInflectionFormRendering:
    """Test that inflection fields are rendered in init.html (using real app)."""

    def test_inflection_fields_rendered(self, client):
        """GET /init renders inflection-row for org_name (from real descr.docx)."""
        response = client.get('/init')
        data = response.get_data(as_text=True)

        assert response.status_code == 200
        assert 'inflection-row' in data
        # org_name in real descr.docx has cases no, ge, pre
        assert 'org_name__no' in data
        assert 'org_name__ge' in data
        assert 'org_name__pre' in data
        assert 'inflection-field' in data
        assert 'data-var="org_name"' in data

    def test_blur_js_present(self, client):
        """init.html includes blur auto-fill JS."""
        response = client.get('/init')
        data = response.get_data(as_text=True)

        assert '_pendingLookups' in data
        assert '/inflection/lookup' in data
        assert 'inflection-field' in data


class TestInflectionScatterKeys:
    """Test that POST /init properly handles inflection scatter keys."""

    def test_scatter_keys_collected_into_dict(self, client):
        """POST /init with inflection fields -> session has consolidated dict."""
        # org_name in real descr.docx has cases: no, ge, pre
        response = client.post('/init', data={
            'user_name': 'Test',
            'org_name__no': 'Ромашка',
            'org_name__ge': 'Ромашки',
            'org_name__pre': 'Ромашке',
        }, follow_redirects=True)

        assert response.status_code == 200

        with client.session_transaction() as sess:
            # Scatter keys should be removed
            assert 'org_name__no' not in sess, f"org_name__no still in session: {sess.keys()}"
            assert 'org_name__ge' not in sess
            assert 'org_name__pre' not in sess

            # Consolidated dict should exist
            assert 'org_name' in sess
            org = sess['org_name']
            assert isinstance(org, dict)
            assert org.get('no') == 'Ромашка'
            assert org.get('ge') == 'Ромашки'
            assert org.get('pre') == 'Ромашке'

    def test_scatter_keys_partial_fill(self, client):
        """POST /init with only some inflection fields filled."""
        response = client.post('/init', data={
            'org_name__no': 'Дек-1',
            # ge and pre left empty
        }, follow_redirects=True)

        assert response.status_code == 200

        with client.session_transaction() as sess:
            org = sess.get('org_name', {})
            assert org.get('no') == 'Дек-1'
            assert 'ge' not in org
            assert 'pre' not in org

    def test_non_inflection_vars_unaffected(self, client):
        """Regular text variables are not affected by inflection processing."""
        response = client.post('/init', data={
            'user_name': 'Alice',
            'org_name__no': 'TestOrg',
            'org_name__ge': 'TestOrg-ge',
        }, follow_redirects=True)

        assert response.status_code == 200

        with client.session_transaction() as sess:
            assert sess.get('user_name') == 'Alice'
            assert sess.get('org_name', {}).get('no') == 'TestOrg'

    def test_multi_post_replace_not_merge(self, client):
        """Second POST replaces the dict (not merges)."""
        # First POST
        client.post('/init', data={
            'org_name__no': 'First',
            'org_name__ge': 'First-ge',
        }, follow_redirects=True)

        # Second POST — only nominative
        client.post('/init', data={
            'org_name__no': 'Second',
        }, follow_redirects=True)

        with client.session_transaction() as sess:
            org = sess.get('org_name', {})
            assert org.get('no') == 'Second'
            # ge should be gone (replaced, not merged)
            assert 'ge' not in org
