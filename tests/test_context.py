"""
Tests for app/logic/context.py

These tests cover the DataContext dataclass factory.
The context module dynamically creates dataclasses for template rendering.
"""

import pytest
from pathlib import Path
import io
from unittest.mock import MagicMock

# Mock the Subdoc import before importing the module
import sys
from unittest.mock import MagicMock, patch
import docxtpl
docxtpl.Subdoc = MagicMock

# Import the module under test
from logic.context import make_context_class, _smart_convert, _normalize_fields, _from_dict, _valid_field_name


class TestSmartConvert:
    """Tests for the _smart_convert helper function."""

    @pytest.mark.parametrize("input_val,expected", [
        ("hello", "hello"),
        (42, "42"),
        (3.14, "3.14"),
        (None, "None"),
    ])
    def test_convert_to_string(self, input_val, expected):
        """Test that values are converted to strings."""
        result = _smart_convert(input_val)
        assert result == expected
        assert isinstance(result, str)

    @pytest.mark.parametrize("input_val", [
        [1, 2, 3],
        {"key": "value"},
        io.BytesIO(b"test data"),
    ])
    def test_convert_pass_through(self, input_val):
        """Test that special types (list, dict, BytesIO) are passed through unchanged."""
        result = _smart_convert(input_val)
        assert result is input_val  # Same object


class TestMakeContextClass:
    """Tests for the make_context_class function."""

    def test_make_context_class_creates_dataclass(self, fixtures_dir):
        """Test that make_context_class returns a dataclass."""
        descr_path = fixtures_dir / "descr.docx"
        lang_path = fixtures_dir / "nonexistent.yaml"

        ContextClass = make_context_class(descr_path, lang_path)

        # Should be a class
        assert isinstance(ContextClass, type)
        assert ContextClass.__name__ == "DataContext"

    def test_context_class_has_fields(self, fixtures_dir):
        """Test that the created dataclass has the expected fields."""
        descr_path = fixtures_dir / "descr.docx"
        lang_path = fixtures_dir / "nonexistent.yaml"

        ContextClass = make_context_class(descr_path, lang_path)
        instance = ContextClass()

        # Should have fields from descr.docx
        assert hasattr(instance, "user_name")
        assert hasattr(instance, "birth_year")

    def test_context_class_default_values(self, fixtures_dir):
        """Test that fields have empty string defaults."""
        descr_path = fixtures_dir / "descr.docx"
        lang_path = fixtures_dir / "nonexistent.yaml"

        ContextClass = make_context_class(descr_path, lang_path)
        instance = ContextClass()

        # All fields should default to empty string
        assert instance.user_name == ""
        assert instance.birth_year == ""

    def test_context_class_instantiation_with_values(self, fixtures_dir):
        """Test creating instance with initial values."""
        descr_path = fixtures_dir / "descr.docx"
        lang_path = fixtures_dir / "nonexistent.yaml"

        ContextClass = make_context_class(descr_path, lang_path)
        instance = ContextClass(user_name="John", birth_year="1990")

        assert instance.user_name == "John"
        assert instance.birth_year == "1990"

    def test_context_class_allows_extra_attributes(self, fixtures_dir):
        """Test that dataclass allows extra attributes (Python default behavior)."""
        descr_path = fixtures_dir / "descr.docx"
        lang_path = fixtures_dir / "nonexistent.yaml"

        ContextClass = make_context_class(descr_path, lang_path)
        instance = ContextClass()

        # Dataclass allows arbitrary attributes by default
        instance.extra_field = "value"
        assert instance.extra_field == "value"


class TestFromDict:
    """Tests for the from_dict classmethod."""

    @pytest.mark.parametrize("data,expected_name,expected_year", [
        ({"user_name": "Alice", "birth_year": "1985"}, "Alice", "1985"),
        ({"user_name": "Bob", "birth_year": 1995}, "Bob", "1995"),  # Numeric converted
    ])
    def test_from_dict_creates_instance(self, fixtures_dir, data, expected_name, expected_year):
        """Test creating instance from dictionary."""
        descr_path = fixtures_dir / "descr.docx"
        lang_path = fixtures_dir / "nonexistent.yaml"

        ContextClass = make_context_class(descr_path, lang_path)
        instance = ContextClass.from_dict(data)

        assert instance.user_name == expected_name
        assert instance.birth_year == expected_year

    def test_from_dict_partial_data(self, fixtures_dir):
        """Test creating instance with partial data (some fields missing)."""
        descr_path = fixtures_dir / "descr.docx"
        lang_path = fixtures_dir / "nonexistent.yaml"

        ContextClass = make_context_class(descr_path, lang_path)

        # Only provide some fields
        data = {"user_name": "Bob"}
        instance = ContextClass.from_dict(data)

        assert instance.user_name == "Bob"
        # Other fields should have defaults
        assert instance.birth_year == ""

    def test_from_dict_extra_data_raises(self, fixtures_dir):
        """Test that extra keys in data dict raise TypeError."""
        descr_path = fixtures_dir / "descr.docx"
        lang_path = fixtures_dir / "nonexistent.yaml"

        ContextClass = make_context_class(descr_path, lang_path)

        # Provide extra key that doesn't exist in dataclass
        data = {"user_name": "Charlie", "extra_field": "should_raise"}

        # This will raise because extra_field is not a valid field
        with pytest.raises(TypeError):
            ContextClass.from_dict(data)

    def test_from_dict_with_list_values(self, fixtures_dir):
        """Test that list values are preserved (not converted to string)."""
        descr_path = fixtures_dir / "descr.docx"
        lang_path = fixtures_dir / "nonexistent.yaml"

        ContextClass = make_context_class(descr_path, lang_path)

        data = {"user_name": ["list", "of", "names"]}
        instance = ContextClass.from_dict(data)

        # List should be preserved
        assert instance.user_name == ["list", "of", "names"]
        assert isinstance(instance.user_name, list)


class TestNormalizeFields:
    """Tests for the _normalize_fields function."""

    def test_normalize_fields_applies_conversion(self, fixtures_dir):
        """Test that normalization converts field values."""
        descr_path = fixtures_dir / "descr.docx"
        lang_path = fixtures_dir / "nonexistent.yaml"

        ContextClass = make_context_class(descr_path, lang_path)

        # Create instance with numeric value
        instance = ContextClass(birth_year=2000)

        # Post-init should have normalized it
        assert instance.birth_year == "2000"

    def test_normalize_fields_preserves_lists(self, fixtures_dir):
        """Test that lists are preserved during normalization."""
        descr_path = fixtures_dir / "descr.docx"
        lang_path = fixtures_dir / "nonexistent.yaml"

        ContextClass = make_context_class(descr_path, lang_path)

        test_list = [1, 2, 3]
        instance = ContextClass(user_name=test_list)

        # List should be preserved
        assert instance.user_name is test_list


class TestValidFieldName:
    """Tests for the _valid_field_name guard (descr var names must be usable fields)."""

    @pytest.mark.parametrize("name,expected", [
        ("user_name", True),
        ("birth_year", True),
        ("class", False),         # Python keyword
        ("123", False),           # non-identifier
        ("from_dict", False),     # injected classmethod
        ("__post_init__", False), # dunder (injected method)
        ("__init__", False),      # dunder (dataclass-generated)
    ])
    def test_valid_field_name(self, name, expected):
        assert _valid_field_name(name) is expected


class TestMakeContextClassSkipsBadNames:
    """make_context_class degrades (skips) bad var names instead of raising a 500."""

    def test_skips_bad_names_keeps_from_dict_callable(self):
        """A from_dict/keyword/non-identifier var is skipped; the injected
        from_dict classmethod stays intact (not shadowed by a field)."""
        bad_desc = {"user_name": {}, "from_dict": {}, "class": {}, "123": {}}
        with patch("logic.context.read_variable_descriptions", return_value=bad_desc):
            ContextClass = make_context_class(Path("x"), Path("y"))

        # valid var kept; bad vars skipped (not fields)
        assert "user_name" in ContextClass.__dataclass_fields__
        for bad in ("from_dict", "class", "123"):
            assert bad not in ContextClass.__dataclass_fields__
        # injected from_dict is still a working classmethod
        assert callable(ContextClass.from_dict)
        assert ContextClass.from_dict({"user_name": "A"}).user_name == "A"
