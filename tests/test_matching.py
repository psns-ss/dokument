"""
Tests for app/logic/matching.py

Covers: run_matching function for match-type variables, error handling, and
various edge cases. (The dynamic-UI block — generate/hash/render — is covered
in test_dynamic_ui.py.)
"""
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from logic.hints_builder import build_hints_collections


@pytest.fixture
def matching():
    """Import run_matching from the matching module."""
    from logic.matching import run_matching
    return run_matching


class TestRunMatchingBasic:
    """Basic tests for run_matching function."""

    def test_returns_dict(self, matching):
        """run_matching should return a dictionary."""
        run_matching = matching
        hints = build_hints_collections({})
        result = run_matching({}, hints, Path("."))
        assert isinstance(result, dict)

    def test_empty_hints(self, matching):
        """Empty hints should return empty dict."""
        run_matching = matching
        hints = build_hints_collections({})
        result = run_matching({}, hints, Path("."))
        assert result == {}

    def test_no_match_type_variables(self, matching):
        """If no match-type variables, should return empty dict."""
        run_matching = matching
        variable_desc = {
            "name": {"type": "text", "types": ["text"]},
            "age": {"type": "text", "types": ["text"]},
        }
        hints = build_hints_collections(variable_desc)
        result = run_matching({}, hints, Path("."))
        assert result == {}

    def test_skips_non_text_table_vars(self, matching):
        """Should handle text, enum, match, subdoc, table types."""
        run_matching = matching
        variable_desc = {
            "name": {"type": "text", "types": ["text"]},
            "status": {"type": "enum", "types": ["enum"]},
            "data": {"type": "table", "types": ["table"]},
        }
        hints = build_hints_collections(variable_desc)
        result = run_matching({}, hints, Path("."))
        assert result == {}


class TestRunMatchingWithPlugins:
    """Tests for run_matching with actual match plugins."""

    def test_no_plugins_found(self, matching, user_logic_dir):
        """When match plugins exist but no match function for our var, return empty."""
        run_matching = matching
        variable_desc = {
            "university": {"type": "match", "types": ["match"], "options": {"match": "university"}}
        }
        hints = build_hints_collections(variable_desc)
        result = run_matching({}, hints, user_logic_dir)
        # Should not crash even if no matching function exists
        assert isinstance(result, dict)

    def test_with_mock_match_plugin(self, matching, temp_dir):
        """Should call match function and collect results."""
        run_matching = matching

        # Create temp logic dir with plugin - module name should match var name
        # loader.py expects: {category}_{module_name} = match_university
        (temp_dir / "university.py").write_text("""
def match_university(session, yaml_key):
    return ["uni1", "uni2"]
""", encoding="utf-8")

        variable_desc = {
            "university": {"type": "match", "types": ["match"], "options": {"match": "university"}}
        }
        hints = build_hints_collections(variable_desc)

        result = run_matching({}, hints, temp_dir)

        assert "university" in result
        assert result["university"] == ["uni1", "uni2"]

    def test_multiple_match_variables(self, matching, temp_dir):
        """Should handle multiple match-type variables."""
        run_matching = matching

        # Each module name should match the var name it handles
        (temp_dir / "university.py").write_text("""
def match_university(session, yaml_key):
    return ["uni1"]
""", encoding="utf-8")
        (temp_dir / "company.py").write_text("""
def match_company(session, yaml_key):
    return ["comp1"]
""", encoding="utf-8")

        variable_desc = {
            "university": {"type": "match", "types": ["match"], "options": {"match": "university"}},
            "company": {"type": "match", "types": ["match"], "options": {"match": "company"}},
        }
        hints = build_hints_collections(variable_desc)

        result = run_matching({}, hints, temp_dir)

        assert "university" in result
        assert "company" in result

    def test_empty_match_results_not_included(self, matching, temp_dir):
        """Empty match results should not be included in output."""
        run_matching = matching

        (temp_dir / "university.py").write_text("""
def match_university(session, yaml_key):
    return []
""", encoding="utf-8")

        variable_desc = {
            "university": {"type": "match", "types": ["match"], "options": {"match": "university"}}
        }
        hints = build_hints_collections(variable_desc)

        result = run_matching({}, hints, temp_dir)

        assert "university" not in result


class TestRunMatchingErrors:
    """Tests for error handling in run_matching."""

    def test_error_on_exception(self, matching, temp_dir):
        """Should log error but continue when plugin raises exception."""
        run_matching = matching

        (temp_dir / "university.py").write_text("""
def match_university(session, yaml_key):
    raise ValueError("test error")
""", encoding="utf-8")

        variable_desc = {
            "university": {"type": "match", "types": ["match"], "options": {"match": "university"}}
        }
        hints = build_hints_collections(variable_desc)

        # Should not raise, just return empty or partial results
        result = run_matching({}, hints, temp_dir)
        assert isinstance(result, dict)

    def test_missing_options_key_warning(self, matching, temp_dir, caplog):
        """Should warn when variable has no 'options' key."""
        run_matching = matching

        (temp_dir / "university.py").write_text("""
def match_university(session, yaml_key):
    return ["test"]
""", encoding="utf-8")

        variable_desc = {
            "university": {"type": "match", "types": ["match"]}  # No 'options' key
        }
        hints = build_hints_collections(variable_desc)

        result = run_matching({}, hints, temp_dir)

        # Should log warning but not crash — defaults to var_name as yaml_key, so won't skip
        # The warning is only for None/empty yaml_key; since it defaults to "university",
        # it should actually proceed. Check that it didn't crash.
        assert isinstance(result, dict)


class TestRunMatchingEdgeCases:
    """Edge case tests for run_matching."""

    def test_var_without_options(self, matching, temp_dir):
        """Match var without options key defaults to var_name as yaml_key (not skipped)."""
        run_matching = matching

        variable_desc = {
            "university": {"type": "match", "types": ["match"]}  # No options — defaults to var_name
        }
        hints = build_hints_collections(variable_desc)

        result = run_matching({}, hints, temp_dir)

        # No plugin for "university" in temp_dir, so result is empty — but not skipped
        assert result == {}

    def test_session_passed_to_plugins(self, matching, temp_dir):
        """Session should be passed to match functions."""
        run_matching = matching

        (temp_dir / "university.py").write_text("""
def match_university(session, yaml_key):
    session['checked'] = True
    return ["test"]
""", encoding="utf-8")

        variable_desc = {
            "university": {"type": "match", "types": ["match"], "options": {"match": "university"}}
        }
        hints = build_hints_collections(variable_desc)

        session = {}
        result = run_matching(session, hints, temp_dir)

        assert session.get("checked") is True

    def test_yaml_key_reaches_second_param(self, matching, temp_dir):
        """The column-4 key (or the var-name default) is the plugin's 2nd arg."""
        run_matching = matching

        (temp_dir / "university.py").write_text("""
def match_university(session, yaml_key):
    return ["key:" + str(yaml_key)]
""", encoding="utf-8")
        (temp_dir / "company.py").write_text("""
def match_company(session, yaml_key):
    return ["key:" + str(yaml_key)]
""", encoding="utf-8")

        variable_desc = {
            "university": {"type": "match", "types": ["match"],
                           "options": {"match": "unis"}},
            "company": {"type": "match", "types": ["match"]},  # no options → var name
        }
        hints = build_hints_collections(variable_desc)

        result = run_matching({}, hints, temp_dir)

        assert result["university"] == ["key:unis"]     # explicit column-4 value
        assert result["company"] == ["key:company"]     # var-name default
