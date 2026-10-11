"""
Tests for app/logic/inflection.py — InflectedWord dict subclass.
"""

import pytest
import logging
from logic.inflection import InflectedWord, RECOGNIZED_CASES


class TestRecognizedCases:
    def test_expected_cases(self):
        assert RECOGNIZED_CASES == frozenset({"no", "ge", "da", "ac", "in", "pre"})


class TestInflectedWordMultiForm:
    """Multiple forms provided — no expansion."""

    def test_creates_dict_with_forms(self):
        iw = InflectedWord({"no": "Ромашка", "ge": "Ромашки", "da": "Ромашке"})
        assert iw["no"] == "Ромашка"
        assert iw["ge"] == "Ромашки"
        assert iw["da"] == "Ромашке"

    def test_getattr_recognized_case(self):
        iw = InflectedWord({"no": "Ромашка", "ge": "Ромашки"})
        assert iw.no == "Ромашка"
        assert iw.ge == "Ромашки"

    def test_getattr_missing_recognized_case_empty_string(self):
        iw = InflectedWord({"no": "Ромашка"})
        assert iw.ge == ""

    def test_getattr_missing_case_logs_warning(self, caplog):
        iw = InflectedWord({"no": "Ромашка"})
        with caplog.at_level(logging.WARNING):
            iw.ge
        assert "missing case 'ge'" in caplog.text

    def test_getattr_non_case_raises_attribute_error(self):
        iw = InflectedWord({"no": "Ромашка"})
        with pytest.raises(AttributeError):
            iw.xyz

    def test_hasattr_non_case_false(self):
        iw = InflectedWord({"no": "Ромашка"})
        assert not hasattr(iw, "read")
        assert not hasattr(iw, "xyz")

    def test_hasattr_recognized_case_true(self):
        iw = InflectedWord({"no": "Ромашка", "ge": "Ромашки"})
        assert hasattr(iw, "no")
        assert hasattr(iw, "ge")

    def test_str_bare_warning(self, caplog):
        iw = InflectedWord({"no": "Ромашка", "ge": "Ромашки"})
        with caplog.at_level(logging.WARNING):
            s = str(iw)
        assert "[INFLECTED: specify case" in s
        assert "rendered bare" in caplog.text

    def test_isinstance_dict(self):
        iw = InflectedWord({"no": "Ромашка"})
        assert isinstance(iw, dict)

    def test_dict_iteration(self):
        iw = InflectedWord({"no": "A", "ge": "B"})
        assert list(iw.keys()) == ["no", "ge"]
        assert list(iw.values()) == ["A", "B"]


class TestInflectedWordSingleForm:
    """Single form provided — expands to all declared cases."""

    def test_expands_to_all_cases(self):
        iw = InflectedWord({"no": "Дек-1"}, cases=["no", "ge", "da", "ac", "in", "pre"])
        assert iw["no"] == "Дек-1"
        assert iw["ge"] == "Дек-1"
        assert iw["da"] == "Дек-1"
        assert iw["ac"] == "Дек-1"
        assert iw["in"] == "Дек-1"
        assert iw["pre"] == "Дек-1"

    def test_expands_from_non_nominative(self):
        """Single non-no case still expands to all declared cases."""
        iw = InflectedWord({"ge": "Ромашки"}, cases=["no", "ge", "da"])
        assert iw["no"] == "Ромашки"
        assert iw["ge"] == "Ромашки"
        assert iw["da"] == "Ромашки"

    def test_expands_to_subset_of_cases(self):
        """Only declared cases are expanded."""
        iw = InflectedWord({"no": "X"}, cases=["no", "ge"])
        assert iw["no"] == "X"
        assert iw["ge"] == "X"
        assert "da" not in iw

    def test_no_cases_given_keeps_original_form(self):
        """Without cases arg, a single form is kept as-is (not dropped to empty).
        In practice, cases is always provided from variable_descriptions."""
        iw = InflectedWord({"no": "X"})
        assert len(iw) == 1
        assert iw["no"] == "X"

    def test_empty_forms(self):
        """Empty forms dict — no expansion, empty dict."""
        iw = InflectedWord({}, cases=["no", "ge"])
        assert len(iw) == 0


class TestInflectedWordIntegration:
    """Integration: _smart_convert passes dict subclasses through."""

    def test_smart_convert_passes_through(self):
        from logic.context import _smart_convert
        iw = InflectedWord({"no": "Ромашка", "ge": "Ромашки"})
        result = _smart_convert(iw)
        assert result is iw
        assert isinstance(result, InflectedWord)
