"""
Tests for app/logic/parser.py

These tests cover the variable description parsing from descr.docx.
The parser reads a Word document table and converts it to a dictionary
of variable metadata.
"""

import pytest
from pathlib import Path
from docx import Document

# Import the module under test
from logic.parser import read_variable_descriptions, _load_lang_rules, extract_pack_description


class TestLoadLangRules:
    """Tests for the _load_lang_rules helper function."""

    def test_load_lang_rules_exists(self, fixtures_dir, tmp_path):
        """
        Test loading an existing YAML file.
        """
        # Create a test YAML file
        yaml_file = tmp_path / "test_rules.yaml"
        yaml_file.write_text("key1: value1\nkey2: [a, b, c]\n")

        result = _load_lang_rules(yaml_file)

        assert result == {"key1": "value1", "key2": ["a", "b", "c"]}

    def test_load_lang_rules_missing(self, tmp_path):
        """
        Test that a missing file returns empty dict.
        """
        missing_file = tmp_path / "nonexistent.yaml"
        result = _load_lang_rules(missing_file)

        assert result == {}

    def test_load_lang_rules_empty(self, tmp_path):
        """
        Test that an empty YAML file returns empty dict.
        """
        empty_file = tmp_path / "empty.yaml"
        empty_file.write_text("")

        result = _load_lang_rules(empty_file)

        assert result == {}

    def test_load_lang_rules_bad_yaml_degrades(self, tmp_path):
        """
        A malformed YAML file degrades to {} (never raise) — the parser is on
        the request path and a bad language_rules.yaml must not 500 the form.
        """
        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text("a: [1, 2\n   b: : :]\n", encoding="utf-8")

        result = _load_lang_rules(bad_file)

        assert result == {}


class TestReadVariableDescriptions:
    """Tests for the read_variable_descriptions function."""

    def test_read_variable_descriptions(self, fixtures_dir):
        """
        Test parsing a valid descr.docx file.

        This uses the fixture descr.docx created by create_fixtures.py.
        """
        descr_path = fixtures_dir / "descr.docx"
        lang_file = fixtures_dir / "nonexistent.yaml"  # Use non-existent to test fallback

        result = read_variable_descriptions(descr_path, lang_file)

        # Should have parsed the variables
        assert isinstance(result, dict)
        assert "user_name" in result
        assert "user_sex" in result

    def test_parser_skips_incomplete_rows(self, tmp_path):
        """
        Test that rows with fewer than 4 cells are skipped.
        """
        # Create a DOCX with incomplete rows - need at least 4 columns
        doc = Document()
        table = doc.add_table(rows=3, cols=4)  # 4 columns required

        # Row 1: Complete
        table.rows[0].cells[0].text = "var1"
        table.rows[0].cells[1].text = "Description 1"
        table.rows[0].cells[2].text = "✓"
        table.rows[0].cells[3].text = "text"

        # Row 2: Missing cells (should be skipped)
        table.rows[1].cells[0].text = "var2"
        # Other cells empty - this row has < 4 non-empty cells

        # Row 3: Complete
        table.rows[2].cells[0].text = "var3"
        table.rows[2].cells[1].text = "Description 3"
        table.rows[2].cells[2].text = "✓"
        table.rows[2].cells[3].text = "text"

        descr_path = tmp_path / "incomplete_descr.docx"
        doc.save(descr_path)

        lang_file = tmp_path / "lang.yaml"
        lang_file.write_text("")

        result = read_variable_descriptions(descr_path, lang_file)

        # The parser checks len(cells) < 4, not empty cells
        # All rows have 4 cells, so all will be parsed
        # But var2 will have empty description/type
        assert "var1" in result
        assert "var2" in result  # Will be parsed but with empty values
        assert "var3" in result

    def test_parser_skips_empty_var_name(self, tmp_path):
        """
        Test that rows with empty variable names are skipped.
        """
        doc = Document()
        table = doc.add_table(rows=2, cols=4)

        # Row 1: Empty variable name
        table.rows[0].cells[0].text = ""
        table.rows[0].cells[1].text = "Empty var"
        table.rows[0].cells[2].text = "✓"
        table.rows[0].cells[3].text = "text"

        # Row 2: Valid variable
        table.rows[1].cells[0].text = "valid_var"
        table.rows[1].cells[1].text = "Valid description"
        table.rows[1].cells[2].text = "✓"
        table.rows[1].cells[3].text = "text"

        descr_path = tmp_path / "empty_var_descr.docx"
        doc.save(descr_path)

        lang_file = tmp_path / "lang.yaml"
        lang_file.write_text("")

        result = read_variable_descriptions(descr_path, lang_file)

        assert "valid_var" in result
        assert "" not in result

    def test_parser_enum_options(self, tmp_path):
        """
        Test that enum type loads options from YAML.
        """
        # Create YAML with options
        lang_yaml = tmp_path / "lang.yaml"
        lang_yaml.write_text("sex_options:\n  - Male\n  - Female\n")

        # Create descr.docx with enum variable
        doc = Document()
        table = doc.add_table(rows=1, cols=5)

        table.rows[0].cells[0].text = "user_sex"
        table.rows[0].cells[1].text = "User's sex"
        table.rows[0].cells[2].text = "✓"
        table.rows[0].cells[3].text = "enum"
        table.rows[0].cells[4].text = "sex_options"

        descr_path = tmp_path / "enum_descr.docx"
        doc.save(descr_path)

        result = read_variable_descriptions(descr_path, lang_yaml)

        assert result["user_sex"]["type"] == "enum"
        assert result["user_sex"]["options"] == {"enum": ["Male", "Female"]}

    def test_parser_enum_missing_yaml_path(self, tmp_path):
        """
        Test that missing YAML path returns empty options (no error).
        """
        lang_yaml = tmp_path / "lang.yaml"
        lang_yaml.write_text("other_options:\n  - A\n  - B\n")

        doc = Document()
        table = doc.add_table(rows=1, cols=5)

        table.rows[0].cells[0].text = "user_sex"
        table.rows[0].cells[1].text = "User's sex"
        table.rows[0].cells[2].text = "✓"
        table.rows[0].cells[3].text = "enum"
        table.rows[0].cells[4].text = "nonexistent_path"  # This path doesn't exist

        descr_path = tmp_path / "enum_missing_descr.docx"
        doc.save(descr_path)

        result = read_variable_descriptions(descr_path, lang_yaml)

        # Should not raise, just return empty options
        assert result["user_sex"]["type"] == "enum"
        assert result["user_sex"]["options"] == {"enum": []}

    def test_parser_match_type(self, tmp_path):
        """
        Test that match type stores the YAML path.
        """
        lang_yaml = tmp_path / "lang.yaml"
        lang_yaml.write_text("company_1:\n  short: Test Co\n")

        doc = Document()
        table = doc.add_table(rows=1, cols=5)

        table.rows[0].cells[0].text = "company_name"
        table.rows[0].cells[1].text = "Company name"
        table.rows[0].cells[2].text = "✓"
        table.rows[0].cells[3].text = "match"
        table.rows[0].cells[4].text = "company_1"

        descr_path = tmp_path / "match_descr.docx"
        doc.save(descr_path)

        result = read_variable_descriptions(descr_path, lang_yaml)

        assert result["company_name"]["type"] == "match"
        assert result["company_name"]["options"] == {"match": "company_1"}

    def test_parser_braces_stripped(self, tmp_path):
        """
        Test that variable names with {{ }} braces are handled correctly.
        """
        lang_yaml = tmp_path / "lang.yaml"
        lang_yaml.write_text("")

        doc = Document()
        table = doc.add_table(rows=1, cols=4)

        # Variable name with braces
        table.rows[0].cells[0].text = "{{user_name}}"
        table.rows[0].cells[1].text = "User name"
        table.rows[0].cells[2].text = "✓"
        table.rows[0].cells[3].text = "text"

        descr_path = tmp_path / "braces_descr.docx"
        doc.save(descr_path)

        result = read_variable_descriptions(descr_path, lang_yaml)

        # Braces should be stripped
        assert "user_name" in result
        assert "{{user_name}}" not in result

    def test_parser_default_type_is_text(self, tmp_path):
        """
        Test that empty type field defaults to 'text'.
        """
        lang_yaml = tmp_path / "lang.yaml"
        lang_yaml.write_text("")

        doc = Document()
        table = doc.add_table(rows=1, cols=4)

        table.rows[0].cells[0].text = "my_var"
        table.rows[0].cells[1].text = "My variable"
        table.rows[0].cells[2].text = "✓"
        table.rows[0].cells[3].text = ""  # Empty type

        descr_path = tmp_path / "default_type_descr.docx"
        doc.save(descr_path)

        result = read_variable_descriptions(descr_path, lang_yaml)

        assert result["my_var"]["type"] == "text"
        assert result["my_var"]["types"] == ["text"]

    def test_parser_single_type_produces_types_list(self, tmp_path):
        """
        Test that a single type produces a types list with one element.
        """
        lang_yaml = tmp_path / "lang.yaml"
        lang_yaml.write_text("")

        doc = Document()
        table = doc.add_table(rows=3, cols=4)

        table.rows[0].cells[0].text = "user_name"
        table.rows[0].cells[1].text = "Name"
        table.rows[0].cells[2].text = "✓"
        table.rows[0].cells[3].text = "text"

        table.rows[1].cells[0].text = "user_sex"
        table.rows[1].cells[1].text = "Sex"
        table.rows[1].cells[2].text = "✓"
        table.rows[1].cells[3].text = "enum"

        table.rows[2].cells[0].text = "university"
        table.rows[2].cells[1].text = "University"
        table.rows[2].cells[2].text = "✓"
        table.rows[2].cells[3].text = "match"

        descr_path = tmp_path / "single_type_descr.docx"
        doc.save(descr_path)

        result = read_variable_descriptions(descr_path, lang_yaml)

        assert result["user_name"]["types"] == ["text"]
        assert result["user_sex"]["types"] == ["enum"]
        assert result["university"]["types"] == ["match"]

    def test_parser_multi_type_produces_types_list(self, tmp_path):
        """
        Test that comma-separated types produce a types list.
        """
        lang_yaml = tmp_path / "lang.yaml"
        lang_yaml.write_text("")

        doc = Document()
        table = doc.add_table(rows=1, cols=4)

        table.rows[0].cells[0].text = "table"
        table.rows[0].cells[1].text = "Table variable"
        table.rows[0].cells[2].text = "✓"
        table.rows[0].cells[3].text = "match,computed,subdoc"

        descr_path = tmp_path / "multi_type_descr.docx"
        doc.save(descr_path)

        result = read_variable_descriptions(descr_path, lang_yaml)

        assert result["table"]["type"] == "match,computed,subdoc"  # raw preserved
        assert result["table"]["types"] == ["match", "computed", "subdoc"]

    def test_parser_multi_type_with_spaces(self, tmp_path):
        """
        Test that spaces around commas in types are stripped.
        """
        lang_yaml = tmp_path / "lang.yaml"
        lang_yaml.write_text("")

        doc = Document()
        table = doc.add_table(rows=1, cols=4)

        table.rows[0].cells[0].text = "var1"
        table.rows[0].cells[1].text = "Var 1"
        table.rows[0].cells[2].text = "✓"
        table.rows[0].cells[3].text = "match , computed , subdoc"

        descr_path = tmp_path / "spaced_types_descr.docx"
        doc.save(descr_path)

        result = read_variable_descriptions(descr_path, lang_yaml)

        assert result["var1"]["types"] == ["match", "computed", "subdoc"]

    def test_parser_multi_type_match_options(self, tmp_path):
        """
        Test that multi-type variables (e.g., match,computed) parse column 5
        as the YAML key for match via the typed form, not just single-type
        match vars.

        Regression test: before the fix, the parser used exact string match
        (type == "match"), which failed for "match,computed".
        """
        lang_yaml = tmp_path / "lang.yaml"
        lang_yaml.write_text("")

        doc = Document()
        table = doc.add_table(rows=1, cols=5)

        table.rows[0].cells[0].text = "university"
        table.rows[0].cells[1].text = "University"
        table.rows[0].cells[2].text = "✓"
        table.rows[0].cells[3].text = "match,computed"
        table.rows[0].cells[4].text = "match:universities"

        descr_path = tmp_path / "multi_match_descr.docx"
        doc.save(descr_path)

        result = read_variable_descriptions(descr_path, lang_yaml)

        assert result["university"]["types"] == ["match", "computed"]
        assert result["university"]["options"] == {"match": "universities"}

    def test_parser_multi_type_enum_options(self, tmp_path):
        """
        Test that multi-type variables (e.g., enum,form) parse column 5
        as the enum options path.
        """
        lang_yaml = tmp_path / "lang.yaml"
        lang_yaml.write_text("sex_options:\n  - Male\n  - Female\n")

        doc = Document()
        table = doc.add_table(rows=1, cols=5)

        table.rows[0].cells[0].text = "user_sex"
        table.rows[0].cells[1].text = "Sex"
        table.rows[0].cells[2].text = "✓"
        table.rows[0].cells[3].text = "enum,form"
        table.rows[0].cells[4].text = "enum:sex_options"

        descr_path = tmp_path / "multi_enum_descr.docx"
        doc.save(descr_path)

        result = read_variable_descriptions(descr_path, lang_yaml)

        assert result["user_sex"]["types"] == ["enum", "form"]
        assert result["user_sex"]["options"] == {"enum": ["Male", "Female"]}

    def test_parser_show_in_form_false(self, tmp_path):
        """
        Test that show_in_form is False when marked with ❌.
        """
        lang_yaml = tmp_path / "lang.yaml"
        lang_yaml.write_text("")

        doc = Document()
        table = doc.add_table(rows=2, cols=4)

        # Row 1: Show in form
        table.rows[0].cells[0].text = "visible_var"
        table.rows[0].cells[1].text = "Visible"
        table.rows[0].cells[2].text = "✓"
        table.rows[0].cells[3].text = "text"

        # Row 2: Hidden
        table.rows[1].cells[0].text = "hidden_var"
        table.rows[1].cells[1].text = "Hidden"
        table.rows[1].cells[2].text = "❌"
        table.rows[1].cells[3].text = "text"

        descr_path = tmp_path / "hidden_descr.docx"
        doc.save(descr_path)

        result = read_variable_descriptions(descr_path, lang_yaml)

        assert result["visible_var"]["show_in_form"] is True
        assert result["hidden_var"]["show_in_form"] is False

    def test_parser_inflection_cases_text_type(self, tmp_path):
        """Test that text type with column 4 parses the case list into options."""
        lang_yaml = tmp_path / "lang.yaml"
        lang_yaml.write_text("")

        doc = Document()
        table = doc.add_table(rows=1, cols=5)

        table.rows[0].cells[0].text = "company_name"
        table.rows[0].cells[1].text = "Company name"
        table.rows[0].cells[2].text = "✓"
        table.rows[0].cells[3].text = "text"
        table.rows[0].cells[4].text = "no,ge,da,ac,in,pre"

        descr_path = tmp_path / "inflect_descr.docx"
        doc.save(descr_path)

        result = read_variable_descriptions(descr_path, lang_yaml)

        assert "company_name" in result
        assert result["company_name"]["options"] == {"text": ["no", "ge", "da", "ac", "in", "pre"]}

    def test_parser_inflection_cases_with_spaces(self, tmp_path):
        """Test that spaces around case codes are stripped."""
        lang_yaml = tmp_path / "lang.yaml"
        lang_yaml.write_text("")

        doc = Document()
        table = doc.add_table(rows=1, cols=5)

        table.rows[0].cells[0].text = "org_name"
        table.rows[0].cells[1].text = "Organization"
        table.rows[0].cells[2].text = "✓"
        table.rows[0].cells[3].text = "text"
        table.rows[0].cells[4].text = " no , ge , da "

        descr_path = tmp_path / "inflect_spaces.docx"
        doc.save(descr_path)

        result = read_variable_descriptions(descr_path, lang_yaml)

        assert result["org_name"]["options"] == {"text": ["no", "ge", "da"]}

    def test_parser_inflection_dash_skipped(self, tmp_path):
        """Test that '-' in column 4 is treated as no inflection."""
        lang_yaml = tmp_path / "lang.yaml"
        lang_yaml.write_text("")

        doc = Document()
        table = doc.add_table(rows=1, cols=5)

        table.rows[0].cells[0].text = "var1"
        table.rows[0].cells[1].text = "Var 1"
        table.rows[0].cells[2].text = "✓"
        table.rows[0].cells[3].text = "text"
        table.rows[0].cells[4].text = "-"

        descr_path = tmp_path / "inflect_dash.docx"
        doc.save(descr_path)

        result = read_variable_descriptions(descr_path, lang_yaml)

        assert result["var1"]["options"] is None

    def test_parser_inflection_non_text_skipped(self, tmp_path):
        """Test that non-text types don't parse case codes from column 4."""
        lang_yaml = tmp_path / "lang.yaml"
        lang_yaml.write_text("")

        doc = Document()
        table = doc.add_table(rows=1, cols=5)

        table.rows[0].cells[0].text = "user_sex"
        table.rows[0].cells[1].text = "Sex"
        table.rows[0].cells[2].text = "✓"
        table.rows[0].cells[3].text = "enum"
        table.rows[0].cells[4].text = "no,ge,da"

        descr_path = tmp_path / "inflect_enum.docx"
        doc.save(descr_path)

        result = read_variable_descriptions(descr_path, lang_yaml)

        # enum takes the cell; no case list is parsed from it
        assert result["user_sex"]["options"] == {"enum": []}
        assert "text" not in (result["user_sex"]["options"] or {})

    def test_parser_inflection_text_computed(self, tmp_path):
        """Test that text,computed multi-type parses the case list (typed form)."""
        lang_yaml = tmp_path / "lang.yaml"
        lang_yaml.write_text("")

        doc = Document()
        table = doc.add_table(rows=1, cols=5)

        table.rows[0].cells[0].text = "org_name"
        table.rows[0].cells[1].text = "Organization"
        table.rows[0].cells[2].text = "✓"
        table.rows[0].cells[3].text = "text,computed"
        table.rows[0].cells[4].text = "text:no,ge,da"

        descr_path = tmp_path / "inflect_computed.docx"
        doc.save(descr_path)

        result = read_variable_descriptions(descr_path, lang_yaml)

        assert result["org_name"]["types"] == ["text", "computed"]
        assert result["org_name"]["options"] == {"text": ["no", "ge", "da"]}

    def test_parser_with_sample_fixture(self, fixtures_dir):
        """
        Test parsing the sample descr.docx fixture.
        """
        descr_path = fixtures_dir / "descr.docx"
        lang_file = fixtures_dir / "nonexistent.yaml"

        result = read_variable_descriptions(descr_path, lang_file)

        # Check expected variables from our fixture
        assert "user_name" in result
        assert result["user_name"]["description"] == "Name of the user"
        assert result["user_name"]["type"] == "text"
        assert result["user_name"]["show_in_form"] is True

        assert "hidden_var" in result
        assert result["hidden_var"]["show_in_form"] is False


class TestExtractPackDescription:
    """Tests for extract_pack_description() - extracts pack description from descr.docx."""

    def test_extract_pack_description_with_paragraph(self, tmp_path):
        """
        Test extracting a pack description from a paragraph before the table.
        """
        doc = Document()
        # Add a description paragraph
        doc.add_paragraph("This is a template pack for university documents")
        # Add a table
        table = doc.add_table(rows=1, cols=4)
        table.rows[0].cells[0].text = "var1"
        table.rows[0].cells[1].text = "Variable 1"
        table.rows[0].cells[2].text = "✓"
        table.rows[0].cells[3].text = "text"

        descr_path = tmp_path / "described_pack.docx"
        doc.save(descr_path)

        result = extract_pack_description(descr_path)

        assert result == "This is a template pack for university documents"

    def test_extract_pack_description_no_paragraph(self, tmp_path):
        """
        Test that missing description returns default message.
        """
        doc = Document()
        # No paragraph - just a table
        table = doc.add_table(rows=1, cols=4)
        table.rows[0].cells[0].text = "var1"
        table.rows[0].cells[1].text = "Variable 1"
        table.rows[0].cells[2].text = "✓"
        table.rows[0].cells[3].text = "text"

        descr_path = tmp_path / "empty_pack.docx"
        doc.save(descr_path)

        result = extract_pack_description(descr_path)

        assert result == "No description available"

    def test_extract_pack_description_empty_paragraph(self, tmp_path):
        """
        Test that an empty paragraph returns default message.
        """
        doc = Document()
        # Add an empty paragraph
        doc.add_paragraph("")
        # Add a table
        table = doc.add_table(rows=1, cols=4)
        table.rows[0].cells[0].text = "var1"
        table.rows[0].cells[1].text = "Variable 1"
        table.rows[0].cells[2].text = "✓"
        table.rows[0].cells[3].text = "text"

        descr_path = tmp_path / "empty_para_pack.docx"
        doc.save(descr_path)

        result = extract_pack_description(descr_path)

        assert result == "No description available"

    def test_extract_pack_description_multiple_paragraphs(self, tmp_path):
        """
        Test that only the first non-empty paragraph before the table is used.
        """
        doc = Document()
        # Add multiple paragraphs
        doc.add_paragraph("First description")
        doc.add_paragraph("Second description")
        # Add a table
        table = doc.add_table(rows=1, cols=4)
        table.rows[0].cells[0].text = "var1"
        table.rows[0].cells[1].text = "Variable 1"
        table.rows[0].cells[2].text = "✓"
        table.rows[0].cells[3].text = "text"

        descr_path = tmp_path / "multi_para_pack.docx"
        doc.save(descr_path)

        result = extract_pack_description(descr_path)

        # Should only get the first paragraph
        assert result == "First description"

    def test_extract_pack_description_whitespace_stripped(self, tmp_path):
        """
        Test that whitespace is stripped from the description.
        """
        doc = Document()
        # Add a paragraph with leading/trailing whitespace
        doc.add_paragraph("  Description with spaces  ")
        # Add a table
        table = doc.add_table(rows=1, cols=4)
        table.rows[0].cells[0].text = "var1"
        table.rows[0].cells[1].text = "Variable 1"
        table.rows[0].cells[2].text = "✓"
        table.rows[0].cells[3].text = "text"

        descr_path = tmp_path / "whitespace_pack.docx"
        doc.save(descr_path)

        result = extract_pack_description(descr_path)

        assert result == "Description with spaces"

    def test_extract_pack_description_with_sample_fixture(self, fixtures_dir):
        """
        Test extracting description from the sample fixture.

        Note: The fixture has a heading 'Test Variable Descriptions' which
        is picked up as the first paragraph before the table.
        """
        descr_path = fixtures_dir / "descr.docx"

        result = extract_pack_description(descr_path)

        # The fixture has a heading which is extracted as the description
        assert result == "Test Variable Descriptions"

    def test_extract_pack_description_with_sample_fixture_after_adding_desc(self, tmp_path):
        """
        Test that we can create a fixture with a description and extract it.
        """
        # Create a new descr.docx with a description
        doc = Document()
        doc.add_paragraph("Sample test pack description")

        # Add the same table as the fixture
        test_vars = [
            ['user_name', 'Name of the user', '✓', 'text', ''],
            ['user_sex', 'Sex of the user', '✓', 'enum', 'sex_options'],
        ]
        table = doc.add_table(rows=len(test_vars), cols=5)
        for i, var_data in enumerate(test_vars):
            for j, text in enumerate(var_data):
                table.rows[i].cells[j].text = text

        descr_path = tmp_path / "desc_fixture.docx"
        doc.save(descr_path)

        result = extract_pack_description(descr_path)

        assert result == "Sample test pack description"


def _one_row_meta(tmp_path, var, type_str, cell, yaml_text=""):
    """One-row descr.docx → parsed meta for the var (options-cell tests)."""
    lang_yaml = tmp_path / "lang.yaml"
    lang_yaml.write_text(yaml_text)
    doc = Document()
    table = doc.add_table(rows=1, cols=5)
    table.rows[0].cells[0].text = var
    table.rows[0].cells[1].text = "Desc"
    table.rows[0].cells[2].text = "✓"
    table.rows[0].cells[3].text = type_str
    table.rows[0].cells[4].text = cell
    descr_path = tmp_path / "descr.docx"
    doc.save(descr_path)
    return read_variable_descriptions(descr_path, lang_yaml)[var]


class TestOptionsCell:
    """Column-4 rework: typed form, strict bare rule, per-type validation."""

    def test_typed_pair_single_type_sugar(self, tmp_path):
        """`text:no,ge` on a single-type var works as sugar for the bare form."""
        meta = _one_row_meta(tmp_path, "org", "text", "text:no,ge")
        assert meta["options"] == {"text": ["no", "ge"]}

    def test_typed_multi_pair(self, tmp_path):
        """`enum:…;text:…` on an enum,text var gives each type its own value."""
        meta = _one_row_meta(
            tmp_path, "org", "enum,text", "enum:sex_options;text:no,ge",
            yaml_text="sex_options:\n  - Male\n  - Female\n",
        )
        assert meta["options"] == {"enum": ["Male", "Female"], "text": ["no", "ge"]}

    def test_bare_cell_multi_type_is_error(self, tmp_path, caplog):
        """Bare cell on a multi-type var: logged error, nothing set."""
        with caplog.at_level("ERROR", logger="logic.parser"):
            meta = _one_row_meta(tmp_path, "org", "enum,text", "no,ge")
        assert meta["options"] is None
        assert any("bare cell on multi-type" in m for m in caplog.messages)

    def test_typed_pair_undeclared_type_skipped(self, tmp_path, caplog):
        """`match:foo` on a text var: pair skipped + logged."""
        with caplog.at_level("ERROR", logger="logic.parser"):
            meta = _one_row_meta(tmp_path, "org", "text", "match:foo")
        assert meta["options"] is None
        assert any("not in the var's types" in m for m in caplog.messages)

    def test_unknown_prefix_falls_back_to_bare(self, tmp_path):
        """`foo:bar` on a text var: no `foo` type → bare case list →
        `foo:bar` is an unknown code → dropped."""
        meta = _one_row_meta(tmp_path, "org", "text", "foo:bar")
        assert meta["options"] == {"text": []}

    def test_enum_path_not_a_list(self, tmp_path, caplog):
        """Enum dot-path resolving to a scalar: [] + log."""
        with caplog.at_level("ERROR", logger="logic.parser"):
            meta = _one_row_meta(tmp_path, "sex", "enum", "scalar",
                                 yaml_text="scalar: hello\n")
        assert meta["options"] == {"enum": []}
        assert any("is not a list" in m for m in caplog.messages)

    def test_bad_case_codes_dropped(self, tmp_path, caplog):
        """`no,xx,ge`: bad code dropped, valid ones kept, logged."""
        with caplog.at_level("ERROR", logger="logic.parser"):
            meta = _one_row_meta(tmp_path, "org", "text", "no,xx,ge")
        assert meta["options"] == {"text": ["no", "ge"]}
        assert any("unknown case code" in m for m in caplog.messages)

    def test_non_consumer_type_ignored(self, tmp_path):
        """A `table` var with a column-4 value: ignored (no consumer)."""
        meta = _one_row_meta(tmp_path, "tbl", "table", "donor.docx")
        assert meta["options"] is None

    def test_duplicate_pair_last_wins(self, tmp_path, caplog):
        """`text:no;text:ge`: last pair wins + warning."""
        with caplog.at_level("WARNING", logger="logic.parser"):
            meta = _one_row_meta(tmp_path, "org", "text", "text:no;text:ge")
        assert meta["options"] == {"text": ["ge"]}
        assert any("duplicate" in m for m in caplog.messages)

    def test_match_dash_cell_no_options(self, tmp_path):
        """`-` on a match var: no options (yaml_key defaults to var name)."""
        meta = _one_row_meta(tmp_path, "uni", "match", "-")
        assert meta["options"] is None
