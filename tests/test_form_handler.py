"""
Tests for app/logic/form_handler.py::analyze_template_variables.

analyze_template_variables gathers per-template variable statistics
(present / missing-expected / extra) for the debug endpoint.
"""

import pytest
from pathlib import Path

# Import the module under test
from logic.form_handler import analyze_template_variables
from logic.parser import read_variable_descriptions


class TestAnalyzeTemplateVariables:
    """Tests for the analyze_template_variables function."""

    def test_analyze_with_fixtures(self, fixtures_dir, tmp_path):
        """Test analyzing template variables using fixture files."""
        template_path = fixtures_dir / "template_simple.docx"
        descr_path = fixtures_dir / "descr.docx"
        lang_rules_path = fixtures_dir / "nonexistent.yaml"

        variable_desc = read_variable_descriptions(descr_path, lang_rules_path)
        result = analyze_template_variables(
            [str(template_path)], variable_desc
        )

        # Check result structure
        assert "all_template_vars" in result
        assert "template_details" in result

        # Template should have some variables
        assert len(result["all_template_vars"]) > 0

    def test_analyze_with_multiple_templates(self, fixtures_dir, tmp_path):
        """Test analyzing multiple templates."""
        template1 = fixtures_dir / "template_simple.docx"
        template2 = fixtures_dir / "template_with_header.docx"
        descr_path = fixtures_dir / "descr.docx"
        lang_rules_path = fixtures_dir / "nonexistent.yaml"

        variable_desc = read_variable_descriptions(descr_path, lang_rules_path)
        result = analyze_template_variables(
            [str(template1), str(template2)], variable_desc
        )

        # Should have details for both templates
        assert str(template1) in result["template_details"]
        assert str(template2) in result["template_details"]

        # All variables should be combined
        assert len(result["all_template_vars"]) > 0

    def test_analyze_empty_template_list(self, fixtures_dir):
        """Test analyzing with no templates."""
        descr_path = fixtures_dir / "descr.docx"
        lang_rules_path = fixtures_dir / "nonexistent.yaml"

        variable_desc = read_variable_descriptions(descr_path, lang_rules_path)
        result = analyze_template_variables([], variable_desc)

        assert result["all_template_vars"] == set()
        assert result["template_details"] == {}
