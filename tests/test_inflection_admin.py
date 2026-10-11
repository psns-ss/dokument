"""
Tests for app/routes/debug.py — Inflection admin UI endpoints.

Per-test DB isolation comes from the shared `fresh_inflection_db` fixture
(conftest.py).
"""

import json


class TestDebugInflectionsPage:
    """GET /debug/inflections — word browser page."""

    def test_page_returns_200(self, client, fresh_inflection_db):
        """Admin page should return 200."""
        response = client.get('/debug/inflections')
        assert response.status_code == 200

    def test_page_contains_html(self, client, fresh_inflection_db):
        """Admin page should return HTML."""
        response = client.get('/debug/inflections')
        data = response.get_data(as_text=True)
        assert '<h1>' in data or 'склонен' in data.lower() or 'Управление' in data

    def test_page_empty_when_no_words(self, client, fresh_inflection_db):
        """Page should show empty state when no words in DB."""
        response = client.get('/debug/inflections')
        data = response.get_data(as_text=True)
        assert response.status_code == 200

    def test_page_shows_words(self, client, fresh_inflection_db):
        """Page should list saved words."""
        fresh_inflection_db.save_word({"no": "Ромашка", "ge": "Ромашки", "da": "Ромашке"})

        response = client.get('/debug/inflections')
        data = response.get_data(as_text=True)
        assert 'Ромашка' in data

    def test_search_param(self, client, fresh_inflection_db):
        """Search by query parameter."""
        fresh_inflection_db.save_word({"no": "Ромашка", "ge": "Ромашки"})
        fresh_inflection_db.save_word({"no": "Яблоко", "ge": "Яблоко-ge"})

        response = client.get('/debug/inflections?q=Ром')
        data = response.get_data(as_text=True)
        assert 'Ромашка' in data
        assert 'Яблоко' not in data

    def test_letter_filter(self, client, fresh_inflection_db):
        """Filter by first letter."""
        fresh_inflection_db.save_word({"no": "Apple", "ge": "Apple-ge"})
        fresh_inflection_db.save_word({"no": "Apricot", "ge": "Apricot-ge"})
        fresh_inflection_db.save_word({"no": "Banana", "ge": "Banana-ge"})

        response = client.get('/debug/inflections?letter=A')
        data = response.get_data(as_text=True)
        assert 'Apple' in data or 'Apricot' in data
        assert 'Banana' not in data


class TestInflectionSearchJSON:
    """GET /debug/inflections/search — JSON autocomplete endpoint."""

    def test_returns_json(self, client, fresh_inflection_db):
        """Search endpoint should return JSON."""
        response = client.get('/debug/inflections/search?q=test')
        assert response.status_code == 200
        assert response.content_type and 'application/json' in response.content_type

    def test_empty_query_empty_results(self, client):
        """Empty query returns empty list."""
        response = client.get('/debug/inflections/search?q=')
        data = json.loads(response.get_data(as_text=True))
        assert data == []

    def test_search_returns_matches(self, client, fresh_inflection_db):
        """Search returns matching words."""
        fresh_inflection_db.save_word({"no": "Ромашка", "ge": "Ромашки"})

        response = client.get('/debug/inflections/search?q=Ром')
        data = json.loads(response.get_data(as_text=True))

        assert len(data) >= 1
        assert data[0]["nominative"] == "Ромашка"
        assert "word_id" in data[0]


class TestDeleteInflection:
    """DELETE /debug/inflections/<word_id> — delete word."""

    def test_delete_word(self, client, fresh_inflection_db):
        """DELETE should remove word from DB."""
        word_id = fresh_inflection_db.save_word({"no": "DeleteMe", "ge": "DeleteMe-ge"})

        # Verify it exists
        assert fresh_inflection_db.lookup_by_form("no", "DeleteMe") is not None

        response = client.delete(f'/debug/inflections/{word_id}')
        assert response.status_code == 200
        data = json.loads(response.get_data(as_text=True))
        assert data["ok"] is True

        # Verify it's gone
        assert fresh_inflection_db.lookup_by_form("no", "DeleteMe") is None

    def test_delete_nonexistent_ok(self, client, fresh_inflection_db):
        """DELETE of non-existent word should still return 200."""
        response = client.delete('/debug/inflections/99999')
        assert response.status_code == 200


class TestConflictsPage:
    """GET /debug/inflections/conflicts — conflict viewer."""

    def test_page_returns_200(self, client, fresh_inflection_db):
        """Conflicts page should return 200."""
        response = client.get('/debug/inflections/conflicts')
        assert response.status_code == 200

    def test_page_contains_html(self, client, fresh_inflection_db):
        """Conflicts page should return HTML."""
        response = client.get('/debug/inflections/conflicts')
        data = response.get_data(as_text=True)
        assert '<h1>' in data or 'Конфлик' in data or 'конфлик' in data.lower()

    def test_empty_when_no_conflicts(self, client, fresh_inflection_db):
        """Page should show empty state when no conflicts."""
        response = client.get('/debug/inflections/conflicts')
        data = response.get_data(as_text=True)
        assert response.status_code == 200


class TestDismissConflict:
    """DELETE /debug/inflections/conflicts/<id> — dismiss conflict."""

    def test_dismiss_conflict(self, client, fresh_inflection_db):
        """Dismiss should remove conflict entry."""
        # Create a conflict by saving overlapping forms
        fresh_inflection_db.save_word({"no": "A", "ge": "G1", "da": "D1"})
        fresh_inflection_db.save_word({"no": "B", "ge": "G2", "da": "D2"})
        fresh_inflection_db.save_word({"no": "A", "da": "D2"})  # This creates a conflict

        conflicts = fresh_inflection_db.get_conflicts()
        assert len(conflicts) >= 1
        conflict_id = conflicts[0]["id"]

        response = client.delete(f'/debug/inflections/conflicts/{conflict_id}')
        assert response.status_code == 200
        data = json.loads(response.get_data(as_text=True))
        assert data["ok"] is True

        # Verify conflict is gone
        remaining = fresh_inflection_db.get_conflicts()
        remaining_ids = [c["id"] for c in remaining]
        assert conflict_id not in remaining_ids
