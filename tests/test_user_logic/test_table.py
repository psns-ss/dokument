"""
Tests for logic/table.py - init_table (table mapping UI).

Covers the pre-population contract: the user's stored slot pick
(table_map[idx]) must re-appear on a hash-bounce re-render, rather than
resetting to the default "— Не использовать —".
"""
import re
import sys
from pathlib import Path

# Add project root to path so `import logic.table` finds the user plugin.
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from logic.table import init_table


def _render(template, session):
    """Render a hook template via the real render_dynamic_ui_block (Option E)."""
    from flask import Flask
    from logic.dynamic_ui import render_dynamic_ui_block
    app = Flask("table_render_test")
    with app.app_context():
        return render_dynamic_ui_block(template, session)


class TestInitTablePrepopulation:
    """init_table pre-populates the slot select from the session."""

    def _variable_desc(self):
        return {'table_1': {'description': 'Slot 1'}, 'table_2': {'description': 'Slot 2'}}

    def _matched_list(self):
        return [{'key': 'cv:0:2', 'preview': [['Name', 'Age']], 'rows': 10, 'cols': 4}]

    def _selected_of(self, html):
        """The option value(s) carrying `selected` in the table_map[0] select."""
        first_select = re.search(r'<select name="table_map\[0\]".*?</select>', html, re.DOTALL)
        assert first_select, "table_map[0] select not found"
        return re.findall(r'<option value="([^"]*)" selected', first_select.group(0))

    def test_prepopulates_slot_from_session(self):
        """The stored slot pick (table_map[0]) is the selected option after render."""
        template = init_table({}, self._matched_list(), self._variable_desc())
        assert self._selected_of(_render(template, {'table_map[0]': 'table_1'})) == ['table_1']

    def test_defaults_to_skip_when_session_empty(self):
        """No stored pick → no option explicitly selected (defaults to skip)."""
        template = init_table({}, self._matched_list(), self._variable_desc())
        assert self._selected_of(_render(template, {})) == []

    def test_template_is_session_independent(self):
        """Option E: the hook emits a template, so its output is identical
        regardless of the session (the convergence hash stays stable)."""
        t1 = init_table({}, self._matched_list(), self._variable_desc())
        t2 = init_table({'table_map[0]': 'table_1'}, self._matched_list(), self._variable_desc())
        assert t1 == t2
        assert "session.get('table_map[0]')" in t1
