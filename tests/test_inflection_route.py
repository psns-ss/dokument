"""
Tests for app/routes/inflection.py — AJAX lookup endpoint.
Tests for inflection_bp registration in generator.py.

Per-test DB isolation comes from the shared `fresh_inflection_db` fixture
(conftest.py).
"""


class TestInflectionBlueprintRegistered:
    """Test that inflection_bp is registered in the Flask app."""

    def test_inflection_lookup_route_exists(self, client, fresh_inflection_db):
        """The /inflection/lookup route should be accessible."""
        response = client.get('/inflection/lookup')
        # Should return JSON (empty dict if no params)
        assert response.status_code == 200
        assert response.content_type and 'application/json' in response.content_type

    def test_inflection_lookup_returns_json(self, client, fresh_inflection_db):
        """GET /inflection/lookup should return valid JSON."""
        import json
        response = client.get('/inflection/lookup?word=test&field=no')
        assert response.status_code == 200
        data = json.loads(response.get_data(as_text=True))
        assert isinstance(data, dict)


class TestInflectionLookupRoute:
    """Test /inflection/lookup AJAX endpoint with a temp DB."""

    def test_lookup_empty_when_no_params(self, client, fresh_inflection_db):
        """No params -> empty JSON response."""
        response = client.get('/inflection/lookup')
        import json
        data = json.loads(response.get_data(as_text=True))
        assert data == {}

    def test_lookup_returns_word(self, client, fresh_inflection_db):
        """Save a word, then lookup by form."""
        fresh_inflection_db.save_word({"no": "Ромашка", "ge": "Ромашки", "da": "Ромашке"})

        response = client.get('/inflection/lookup?word=Ромашка&field=no&var=company')
        import json
        data = json.loads(response.get_data(as_text=True))

        assert data["no"] == "Ромашка"
        assert data["ge"] == "Ромашки"
        assert data["da"] == "Ромашке"

    def test_lookup_case_insensitive(self, client, fresh_inflection_db):
        """Lookup should be case-insensitive."""
        fresh_inflection_db.save_word({"no": "Ромашка", "ge": "Ромашки"})

        response = client.get('/inflection/lookup?word=РОМАШКА&field=no')
        import json
        data = json.loads(response.get_data(as_text=True))

        assert data["no"] == "Ромашка"

    def test_lookup_not_found_empty(self, client, fresh_inflection_db):
        """Non-existent word returns empty dict."""
        fresh_inflection_db.save_word({"no": "Word1", "ge": "Word1-ge"})

        response = client.get('/inflection/lookup?word=NonExistent&field=no')
        import json
        data = json.loads(response.get_data(as_text=True))

        assert data == {}

    def test_lookup_by_genitive_form(self, client, fresh_inflection_db):
        """Lookup by genitive form should also find the word."""
        fresh_inflection_db.save_word({"no": "Ромашка", "ge": "Ромашки", "da": "Ромашке"})

        response = client.get('/inflection/lookup?word=Ромашки&field=ge')
        import json
        data = json.loads(response.get_data(as_text=True))

        assert data["no"] == "Ромашка"
        assert data["ge"] == "Ромашки"

    def test_lookup_url_encoding(self, client, fresh_inflection_db):
        """Lookup with URL-encoded Cyrillic should work."""
        fresh_inflection_db.save_word({"no": "ООО Ромашка", "ge": "ООО Ромашки"})

        response = client.get('/inflection/lookup?word=%D0%9E%D0%9E%D0%9E+%D0%A0%D0%BE%D0%BC%D0%B0%D1%88%D0%BA%D0%B0&field=no')
        import json
        data = json.loads(response.get_data(as_text=True))

        assert data["no"] == "ООО Ромашка"
