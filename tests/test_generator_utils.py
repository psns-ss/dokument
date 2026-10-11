"""
Tests for core utility functions (logic.loader) + generate_editor_html.

Covers: ensure_file, find_templates, load_plugins (logic.loader) and
generate_editor_html (routes.onlyoffice).

IMPORTANT: Imports are deferred to a fixture because conftest.py must modify
sys.path before these modules import cleanly. Module-level imports would fail.
"""

import pytest
import types
from pathlib import Path


@pytest.fixture
def gen():
    """Lazy import after conftest sys.path setup.

    Config items (Config, cfg) come from app.config.
    Utility functions come from logic.loader: ensure_file, find_templates, load_plugins.
    """
    from logic.loader import (
        ensure_file,
        find_templates,
        load_plugins,
    )
    from routes.onlyoffice import generate_editor_html
    from config import (
        Config,
        cfg,
    )
    return types.SimpleNamespace(
        ensure_file=ensure_file,
        find_templates=find_templates,
        load_plugins=load_plugins,
        generate_editor_html=generate_editor_html,
        Config=Config,
        cfg=cfg,
    )


class TestEnsureFile:
    """Tests for ensure_file() — exists check with FileNotFoundError."""

    def test_existing_file(self, gen, project_root):
        result = gen.ensure_file(project_root / "pytest.ini")
        assert isinstance(result, Path)
        assert result.exists()

    def test_existing_directory(self, gen, project_root):
        result = gen.ensure_file(project_root / "templates")
        assert result.is_dir()

    def test_missing_file_raises(self, gen, tmp_path):
        missing = tmp_path / "does_not_exist.txt"
        with pytest.raises(FileNotFoundError, match="not found"):
            gen.ensure_file(missing)

    def test_custom_what_message(self, gen, tmp_path):
        missing = tmp_path / "nope.txt"
        with pytest.raises(FileNotFoundError, match="my custom thing"):
            gen.ensure_file(missing, what="my custom thing")


class TestFindTemplates:
    """Tests for find_templates() — discover template*.docx files."""

    def test_returns_sorted_paths(self, gen):
        paths = gen.find_templates()
        assert isinstance(paths, list)
        assert all(isinstance(p, Path) for p in paths)
        assert paths == sorted(paths)

    def test_matches_template_pattern(self, gen):
        paths = gen.find_templates()
        for p in paths:
            assert p.name.startswith("template")
            assert p.name.endswith(".docx")

    def test_finds_at_least_one(self, gen):
        paths = gen.find_templates()
        assert len(paths) >= 1

    def test_custom_pattern(self, gen, project_root):
        paths = gen.find_templates(project_root / "templates", pattern="template_*.docx")
        assert len(paths) >= 1

    def test_missing_directory_returns_empty(self, gen, tmp_path):
        """Missing directory returns empty list (loader.py behavior)."""
        paths = gen.find_templates(tmp_path / "nonexistent")
        assert paths == []


# Note: TestLoadLanguageRules and TestLoadCalculationModules removed
# - load_language_rules() was removed during refactoring (logic moved to logic/matching.py)
# - load_calculation_modules() was replaced by logic/computation.py

class TestLoadPlugins:
    """Tests for load_plugins() — category-based plugin discovery.

    Uses cfg.logic_dir (user plugins). In Docker this is /app/templates/logic.
    On host we use the project root logic/ directory.
    """

    @pytest.fixture
    def user_logic_dir(self):
        """Host path to user plugins (mounted to /app/templates/logic in Docker)."""
        return Path(__file__).parent.parent / "logic"

    def test_returns_dict(self, gen, user_logic_dir):
        plugins = gen.load_plugins(user_logic_dir, 'compute')
        assert isinstance(plugins, dict)

    def test_match_category(self, gen, user_logic_dir):
        """match category should find university (has match_university)."""
        plugins = gen.load_plugins(user_logic_dir, 'match')
        if 'university' in plugins:
            assert hasattr(plugins['university'], 'match_university')

    def test_init_category(self, gen, user_logic_dir):
        """init category should find university (has init_university)."""
        plugins = gen.load_plugins(user_logic_dir, 'init')
        if 'university' in plugins:
            assert hasattr(plugins['university'], 'init_university')

    def test_empty_directory(self, gen, tmp_path):
        plugins = gen.load_plugins(tmp_path, 'compute')
        assert plugins == {}

    def test_nonexistent_directory(self, gen, tmp_path):
        plugins = gen.load_plugins(tmp_path / "nope", 'compute')
        assert plugins == {}


class TestGenerateEditorHtml:
    """Tests for generate_editor_html() — OnlyOffice editor HTML."""

    def test_creates_html_file(self, gen, tmp_path):
        session_dir = tmp_path / "session_123"
        session_dir.mkdir()

        result = gen.generate_editor_html(
            str(session_dir),
            "document.docx",
            "/documents/session_123/document.docx"
        )

        html_file = session_dir / "document.docx.html"
        assert html_file.exists()
        assert result == f"/documents/{session_dir.name}/document.docx.html"

    def test_html_contains_title(self, gen, tmp_path):
        session_dir = tmp_path / "session_456"
        session_dir.mkdir()

        gen.generate_editor_html(
            str(session_dir),
            "test_document.docx",
            "/documents/session_456/test_document.docx"
        )

        html_content = (session_dir / "test_document.docx.html").read_text(encoding='utf-8')
        assert 'test_document' in html_content.lower() or 'title' in html_content.lower()
