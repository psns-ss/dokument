"""
Tests for logic/dynamic_ui.py — the init form's dynamic-UI block:
generate_dynamic_ui_block (fire init_* hooks, join unrendered fragments),
dynamic_ui_hash (sha256 of the unrendered template), render_dynamic_ui_block
(post-hash render), build_dynamic_ui_block, and the DynamicUIBlock dataclass.
"""
import hashlib

import pytest
from pathlib import Path
from flask import Flask

from logic.dynamic_ui import (
    generate_dynamic_ui_block,
    dynamic_ui_hash,
    render_dynamic_ui_block,
    build_dynamic_ui_block,
    DynamicUIBlock,
)


@pytest.fixture
def render():
    """render_dynamic_ui_block bound to a throw-away app context."""
    app = Flask("dynamic_ui_test")
    with app.app_context():
        yield render_dynamic_ui_block


# ---------------------------------------------------------------------------
# generate_dynamic_ui_block
# ---------------------------------------------------------------------------

class TestGenerateDynamicUiBlock:
    """generate_dynamic_ui_block fires init_* hooks and joins unrendered fragments."""

    def test_returns_str(self):
        assert isinstance(generate_dynamic_ui_block({}, {}, Path(".")), str)

    def test_empty_matched_entities(self):
        assert generate_dynamic_ui_block({}, {}, Path(".")) == ""

    def test_with_mock_init_plugin(self, temp_dir):
        """Should call the init function and collect HTML fragments."""
        (temp_dir / "university.py").write_text("""
def init_university(session, matched_list, variable_desc=None):
    return "<div>University matches</div>"
""", encoding="utf-8")
        result = generate_dynamic_ui_block({"university": ["uni1", "uni2"]}, {}, temp_dir)
        assert "<div>University matches</div>" in result

    def test_multiple_vars_concatenated(self, temp_dir):
        """HTML from multiple vars should be concatenated."""
        (temp_dir / "university.py").write_text("""
def init_university(session, matched_list, variable_desc=None):
    return "<div>Univ</div>"
""", encoding="utf-8")
        (temp_dir / "company.py").write_text("""
def init_company(session, matched_list, variable_desc=None):
    return "<div>Company</div>"
""", encoding="utf-8")
        result = generate_dynamic_ui_block(
            {"university": ["uni1"], "company": ["comp1"]}, {}, temp_dir
        )
        assert "<div>Univ</div>" in result
        assert "<div>Company</div>" in result

    def test_empty_init_results_not_included(self, temp_dir):
        """Empty init results should not be included."""
        (temp_dir / "university.py").write_text("""
def init_university(session, matched_list, variable_desc=None):
    return ""
""", encoding="utf-8")
        assert generate_dynamic_ui_block({"university": ["uni1"]}, {}, temp_dir) == ""

    def test_none_result_not_included(self, temp_dir):
        """Handle when a plugin returns None instead of a string."""
        (temp_dir / "university.py").write_text("""
def init_university(session, matched_list, variable_desc=None):
    return None
""", encoding="utf-8")
        assert generate_dynamic_ui_block({"university": ["uni1"]}, {}, temp_dir) == ""

    def test_fragment_is_unrendered_template(self, temp_dir):
        """Option E: the joined fragment is an UNRENDERED template — it carries
        the session placeholder, not the baked value, so it's identical regardless
        of the session (the convergence hash stays stable across a fresh pick)."""
        (temp_dir / "university.py").write_text("""
def init_university(session, matched_list, variable_desc=None):
    return "year={{ session.get('year_0', '') | e }}"
""", encoding="utf-8")
        matched = {"university": ["uni1"]}
        t1 = generate_dynamic_ui_block(matched, {}, temp_dir)
        t2 = generate_dynamic_ui_block(matched, {"year_0": "2020"}, temp_dir)
        assert t1 == t2                              # session-independent template
        assert "session.get('year_0', '')" in t1     # the placeholder...
        assert "year=2020" not in t1                 # ...not the baked value

    def test_error_on_exception(self, temp_dir):
        """Should log the error but continue when a plugin raises."""
        (temp_dir / "university.py").write_text("""
def init_university(session, matched_list, variable_desc=None):
    raise RuntimeError("UI error")
""", encoding="utf-8")
        result = generate_dynamic_ui_block({"university": ["uni1"]}, {}, temp_dir)
        assert isinstance(result, str)

    def test_missing_init_plugin(self, temp_dir):
        """When no init plugin exists for a var, skip it gracefully."""
        assert generate_dynamic_ui_block({"university": ["uni1"]}, {}, temp_dir) == ""


# ---------------------------------------------------------------------------
# dynamic_ui_hash
# ---------------------------------------------------------------------------

class TestDynamicUiHash:
    def test_empty_is_sha256_of_empty(self):
        assert dynamic_ui_hash("") == hashlib.sha256(b"").hexdigest()

    def test_deterministic(self):
        assert dynamic_ui_hash("<div>x</div>") == dynamic_ui_hash("<div>x</div>")

    def test_differs_on_structure_change(self):
        assert dynamic_ui_hash("<div>a</div>") != dynamic_ui_hash("<div>b</div>")


# ---------------------------------------------------------------------------
# render_dynamic_ui_block
# ---------------------------------------------------------------------------

def test_render_empty_is_noop(render):
    assert render("", {}) == ""
    assert render("   \n  ", {}) == ""


def test_render_session_placeholder(render):
    tpl = """<input name="year_0" value="{{ session.get('year_0', '') | e }}">"""
    assert 'value="2020"' in render(tpl, {"year_0": "2020"})


def test_render_missing_key_falls_back_not_none(render):
    tpl = """{{ (session.get('year_0') or session.get('cv_years', {}).get('k', '')) | e }}"""
    out = render(tpl, {"cv_years": {"k": "2018"}})
    assert "2018" in out
    assert "None" not in out


def test_render_selected_tag_fills_from_session(render):
    tpl = """<option value="a" {% if session.get('m') == 'a' %}selected{% endif %}>A</option>"""
    assert "selected" in render(tpl, {"m": "a"})
    assert "selected" not in render(tpl, {"m": "b"})


def test_render_static_html_and_js_roundtrip_unchanged(render):
    """All hook output is Jinja-parsed: static HTML/JS (single braces) must pass
    through byte-for-byte — this is what keeps the file-upload hooks safe."""
    frag = (
        '<div class="form-group"><input type="file" name="sticker" multiple id="sticker"></div>\n'
        "<script>(function () {\n"
        "    var el = document.getElementById('sticker');\n"
        "    if (!el) return;\n"
        "    el.addEventListener('change', function () {\n"
        "        if (el.files.length > 2) { el.value = ''; }\n"
        "    });\n"
        "})();</script>"
    )
    assert render(frag, {}) == frag


def test_render_autoescape_off_structure_passes_value_escaped(render):
    """The HTML structure is NOT escaped (injected via |safe); a user value with
    `| e` IS escaped."""
    out = render("""<b>{{ session.get('x') | e }}</b>""", {"x": "<img src=x>"})
    assert "<b>" in out                      # structure unescaped
    assert "&lt;img src=x&gt;" in out        # value escaped


# ---------------------------------------------------------------------------
# build_dynamic_ui_block + DynamicUIBlock
# ---------------------------------------------------------------------------

class TestBuildDynamicUiBlock:
    def test_builds_template_and_hash(self, temp_dir):
        (temp_dir / "university.py").write_text("""
def init_university(session, matched_list, variable_desc=None):
    return "<div>U</div>"
""", encoding="utf-8")
        block = build_dynamic_ui_block({"university": ["u1"]}, {}, temp_dir)
        assert isinstance(block, DynamicUIBlock)
        assert "<div>U</div>" in block.template
        assert block.ui_hash == dynamic_ui_hash(block.template)
        assert not block.is_empty()

    def test_empty_when_no_hooks(self):
        block = build_dynamic_ui_block({}, {}, Path("."))
        assert block.is_empty()
        assert block.template == ""

    def test_render_fills_placeholders(self, temp_dir, render):
        # `render` fixture pushes an app context — block.render() needs current_app.
        (temp_dir / "university.py").write_text("""
def init_university(session, matched_list, variable_desc=None):
    return "year={{ session.get('year_0', '') | e }}"
""", encoding="utf-8")
        block = build_dynamic_ui_block({"university": ["u1"]}, {}, temp_dir)
        assert 'year=2020' in block.render({"year_0": "2020"})

    def test_empty_classmethod(self):
        block = DynamicUIBlock.empty()
        assert block.is_empty()
        assert block.template == ""
        assert block.ui_hash == dynamic_ui_hash("")
