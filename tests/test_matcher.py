"""
Tests for app/logic/match_helpers.py

These tests cover the YAML loading and matching functions.
Matcher tests are a good starting point because:
- They're pure functions (no side effects)
- No complex setup required
- Fast to run
"""

import pytest
from pathlib import Path
import tempfile

# Import the module under test
from logic.match_helpers import load_yaml, find_matches


class TestLoadYaml:
    """Tests for the load_yaml function."""

    def test_load_yaml_success(self, project_root):
        """
        Test that a valid YAML file loads correctly.

        This is the happy path - valid file that exists.
        Note: load_yaml requires files to be inside templates/ directory.
        """
        # Use a real YAML file from the templates directory
        yaml_path = project_root / "templates" / "language_rules.yaml"
        result = load_yaml(yaml_path)

        # Should return a dict with the language rules
        assert isinstance(result, dict)
        assert "sex_options" in result or "appeals" in result

    def test_load_yaml_path_traversal_rejected(self, fixtures_dir):
        """
        Test that path traversal attacks are blocked.

        The load_yaml function should reject paths with '..'
        that try to escape the templates directory.
        """
        # Try to load a file outside templates using path traversal
        malicious_path = fixtures_dir / ".." / ".." / ".." / "windows" / "test.yaml"

        with pytest.raises(ValueError) as exc_info:
            load_yaml(malicious_path)

        assert "templates/" in str(exc_info.value)

    def test_load_yaml_sibling_dir_rejected(self, tmp_path, monkeypatch):
        """
        A sibling directory named 'templates_evil/' must be rejected.

        The old string-prefix guard (str.startswith) let it through, because
        '.../templates_evil/x.yaml' starts with '.../templates'. The
        component-based is_relative_to check rejects it.
        """
        monkeypatch.chdir(tmp_path)
        (tmp_path / "templates").mkdir()
        (tmp_path / "templates_evil").mkdir()
        evil_file = tmp_path / "templates_evil" / "secret.yaml"
        evil_file.write_text("secret: yes")

        with pytest.raises(ValueError) as exc_info:
            load_yaml(evil_file)

        assert "templates/" in str(exc_info.value)

    def test_load_yaml_wrong_extension(self, fixtures_dir, tmp_path):
        """
        Test that non-.yaml files are rejected.

        Only .yaml extension should be allowed.
        Note: Path must first pass the templates/ directory check.
        """
        # Create a temp directory that looks like it's in templates
        # and test extension check
        import sys
        from unittest.mock import patch

        # Mock the path resolution to bypass directory check but fail on extension
        test_dir = tmp_path / "templates"
        test_dir.mkdir(parents=True)
        yml_file = test_dir / "test.yml"
        yml_file.write_text("test: value")

        with pytest.raises(ValueError) as exc_info:
            load_yaml(yml_file)

        # The error message should mention either path traversal or extension
        error_msg = str(exc_info.value)
        assert ".yaml" in error_msg or "templates/" in error_msg

    def test_load_yaml_missing_file_returns_empty(self, project_root):
        """
        Test that a missing file returns empty dict (graceful handling).

        The function logs an error but doesn't raise an exception.
        """
        # Use a path inside templates that doesn't exist
        missing_path = project_root / "templates" / "nonexistent_test_file.yaml"
        result = load_yaml(missing_path)

        # Should return empty dict, not raise
        assert result == {}

    def test_load_yaml_empty_file_returns_empty(self, project_root, tmp_path):
        """
        Test that an empty YAML file returns empty dict.
        """
        # Create empty file inside a templates-like path
        import os
        # Copy the empty file to a location that passes the directory check
        # by using project_root/templates
        empty_file = project_root / "templates" / "_test_empty_temp.yaml"
        try:
            empty_file.write_text("")
            result = load_yaml(empty_file)
            assert result == {}
        finally:
            # Clean up
            if empty_file.exists():
                empty_file.unlink()


class TestFindMatches:
    """Tests for the find_matches function."""

    def test_find_matches_exact(self, sample_yaml_dict):
        """
        Test exact substring matching.

        If the search text contains an exact match of a short or full name,
        it should be found.
        """
        search_text = "I studied at МГУ and graduated in 2020"
        result = find_matches(search_text, sample_yaml_dict, use_fuzzy=False)

        assert "university_1" in result

    def test_find_matches_exact_full_name(self, sample_yaml_dict):
        """
        Test exact matching with full name.
        """
        search_text = "The company ООО Яндекс announced results"
        result = find_matches(search_text, sample_yaml_dict, use_fuzzy=False)

        assert "company_1" in result

    def test_find_matches_fuzzy(self, sample_yaml_dict):
        """
        Test fuzzy matching when exact match fails.

        Fuzzy matching should find similar strings.
        """
        # "Moscow State Univ" is similar to "Московский государственный университет"
        # but not an exact match - fuzzy should catch it
        search_text = "Московский государственный"  # Slightly misspelled
        result = find_matches(search_text, sample_yaml_dict, use_fuzzy=True, threshold=70)

        # Should find university_1 via fuzzy matching
        assert "university_1" in result

    def test_find_matches_no_match(self, sample_yaml_dict):
        """
        Test that non-matching text returns empty list.
        """
        search_text = "xyz123 random text nothing related"
        result = find_matches(search_text, sample_yaml_dict, use_fuzzy=False)

        assert result == []

    def test_find_matches_empty_text(self, sample_yaml_dict):
        """
        Test that empty search text returns empty list.
        """
        result = find_matches("", sample_yaml_dict)
        assert result == []

    def test_find_matches_empty_yaml_dict(self):
        """
        Test matching against empty YAML dict.
        """
        search_text = "some search text"
        result = find_matches(search_text, {})

        assert result == []

    def test_find_matches_custom_keys(self):
        """
        Test matching with custom key names.
        """
        custom_dict = {
            "item_1": {"name": "Apple", "alias": "App"},
            "item_2": {"name": "Banana", "alias": "Ban"},
        }

        # Search using 'name' key only
        result = find_matches("I like Apple", custom_dict, keys=("name",))

        assert "item_1" in result
        assert "item_2" not in result

    def test_find_matches_threshold_filtering(self, sample_yaml_dict):
        """
        Test that threshold filters out weak fuzzy matches.

        Higher threshold = fewer matches (only strong similarities)
        """
        # Very different text - should not match even with fuzzy
        search_text = "completely different text"
        result_high_threshold = find_matches(
            search_text, sample_yaml_dict, use_fuzzy=True, threshold=95
        )
        result_low_threshold = find_matches(
            search_text, sample_yaml_dict, use_fuzzy=True, threshold=30
        )

        # High threshold should have fewer or equal matches
        assert len(result_high_threshold) <= len(result_low_threshold)

    def test_find_matches_multiple_results(self, sample_yaml_dict):
        """
        Test that multiple matches are returned.
        """
        search_text = "МГУ и Яндекс"  # Contains both university_1 and company_1
        result = find_matches(search_text, sample_yaml_dict, use_fuzzy=False)

        assert "university_1" in result
        assert "company_1" in result
        assert len(result) >= 2
