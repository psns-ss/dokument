"""
Tests for logic/university.py - init and compute functions.

This module tests:
- init_university(): HTML form generation for university selection
- compute_university(): Data computation from form values

Subdocument generation (university_historical) is tested in test_university_subdoc.py.
"""

import pytest
from pathlib import Path
import sys
from unittest.mock import MagicMock

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Module-level state for cleanup
_original_modules = {}
_original_docxtpl_subdoc = None


def _setup_mocks():
    """Set up mocks - called at module load time."""
    global _original_modules, _original_docxtpl_subdoc

    _original_modules['logic.subdoc_helper'] = sys.modules.get('logic.subdoc_helper')
    _original_modules['logic.matcher'] = sys.modules.get('logic.matcher')

    import docxtpl
    _original_docxtpl_subdoc = docxtpl.Subdoc
    docxtpl.Subdoc = MagicMock

    matcher_mock = MagicMock()
    matcher_mock.find_matches = lambda raw_text, yaml_dict, keys=("short", "full"), use_fuzzy=True, threshold=80: []
    sys.modules['logic.matcher'] = matcher_mock

    subdoc_mock = MagicMock()
    subdoc_mock.create_subdoc_from_bookmark = MagicMock()
    sys.modules['logic.subdoc_helper'] = subdoc_mock


def _teardown_mocks():
    """Clean up mocks."""
    global _original_modules, _original_docxtpl_subdoc

    import docxtpl
    docxtpl.Subdoc = _original_docxtpl_subdoc

    for mod_name, original in _original_modules.items():
        if original is None:
            sys.modules.pop(mod_name, None)
        else:
            sys.modules[mod_name] = original

    sys.modules.pop('logic.university', None)


_setup_mocks()

from logic.university import init_university, compute_university, _extract_year


def _render(template, session):
    """Render a hook template via the real render_dynamic_ui_block (Option E).

    The hook emits a Jinja template (session placeholders, no baked value);
    render_dynamic_ui_block fills the placeholders from the session.
    """
    from flask import Flask
    from logic.dynamic_ui import render_dynamic_ui_block
    app = Flask("uni_render_test")
    with app.app_context():
        return render_dynamic_ui_block(template, session)


def teardown_module():
    """Clean up mocks after all tests in this module."""
    _teardown_mocks()


class TestInitUniversity:
    """Tests for the init_university function."""

    def test_init_university_with_matches(self):
        """Test HTML generation with matched universities."""
        session = {}
        matched_list = ["moscow_state_university", "bauman_mgtu"]

        result = init_university(session, matched_list)

        assert '<div class="matching-section"' in result
        assert '<h4>Ваш академический путь:</h4>' in result
        assert 'name="university_order[0]"' in result
        assert 'name="year_0"' in result

    def test_init_university_empty_list(self):
        """Test HTML generation with no matches."""
        session = {}
        matched_list = []

        result = init_university(session, matched_list)

        assert '<div class="matching-section"' in result

    def test_init_university_prepopulates_year_from_session(self):
        """The stored graduation year re-appears after render_dynamic_ui_block fills the tag."""
        template = init_university({}, ["moscow_state_university"])
        assert 'name="year_0" value="2020"' in _render(template, {'year_0': '2020'})

    def test_init_university_prepopulates_order_from_session(self):
        """The stored university pick overrides the matched default after render."""
        import re
        template = init_university({}, ["moscow_state_university", "bauman_mgtu"])
        # idx 0's matched default is moscow_state_university; the stored pick
        # (bauman_mgtu) must be the selected option instead.
        rendered = _render(template, {'university_order[0]': 'bauman_mgtu'})
        first_select = re.search(
            r'<select name="university_order\[0\]".*?</select>', rendered, re.DOTALL
        )
        assert first_select, "university_order[0] select not found"
        selected = re.findall(r'<option value="([^"]*)" selected', first_select.group(0))
        assert selected == ['bauman_mgtu']

    def test_init_university_falls_back_to_cv_year(self):
        """No typed year -> the CV-extracted year (session['cv_years']) is used."""
        template = init_university({}, ["moscow_state_university"])
        rendered = _render(template, {'cv_years': {'moscow_state_university': '2018'}})
        assert 'name="year_0" value="2018"' in rendered

    def test_init_university_typed_year_wins_over_cv(self):
        """A typed year overrides the CV-extracted year."""
        template = init_university({}, ["moscow_state_university"])
        rendered = _render(
            template, {'year_0': '2020', 'cv_years': {'moscow_state_university': '2018'}}
        )
        assert 'name="year_0" value="2020"' in rendered

    def test_init_university_template_is_session_independent(self):
        """Option E: the hook emits a template (session placeholders, no baked
        value), so its output is identical regardless of the session — the
        convergence hash stays stable across a fresh pick."""
        t1 = init_university({}, ["moscow_state_university"])
        t2 = init_university(
            {'year_0': '2099', 'university_order[0]': 'bauman_mgtu'},
            ["moscow_state_university"],
        )
        assert t1 == t2
        assert "session.get('year_0')" in t1


class TestExtractYear:
    """Tests for the _extract_year CV-row helper."""

    def test_finds_year_in_university_row(self):
        cells = ['Московский государственный университет', '2018', 'Прикладная математика']
        assert _extract_year(cells) == '2018'

    def test_no_year_returns_empty(self):
        assert _extract_year(['no year here', 'just text']) == ''

    def test_picks_first_plausible_year(self):
        # A work-history-style range yields the first year.
        assert _extract_year(['ООО «ТехноСтарт»', '2022–2023']) == '2022'


class TestComputeUniversity:
    """Tests for the compute_university function."""

    def test_compute_university_with_data(self):
        """Test data computation with valid university order."""
        kwargs = {
            "university_order[0]": "moscow_state_university",
            "university_order[1]": "bauman_mgtu",
            "year_0": "2020",
            "year_1": "2022",
        }

        result = compute_university(**kwargs)

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["key"] == "moscow_state_university"
        assert result[0]["year"] == "2020"
        assert result[1]["key"] == "bauman_mgtu"
        assert result[1]["year"] == "2022"

    def test_compute_university_empty_kwargs(self):
        """Test computation with no university data."""
        result = compute_university()
        assert result == []

    def test_compute_university_partial_data(self):
        """Test computation with partial year data."""
        kwargs = {
            "university_order[0]": "moscow_state_university",
        }

        result = compute_university(**kwargs)

        assert len(result) == 1
        assert result[0]["key"] == "moscow_state_university"
        assert result[0]["year"] == ""

    def test_compute_university_unknown_key(self):
        """Test that unknown university keys are skipped."""
        kwargs = {
            "university_order[0]": "unknown_university",
        }

        result = compute_university(**kwargs)
        assert result == []
