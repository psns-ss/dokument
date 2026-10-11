"""
Tests for subdoc error handling in app/logic/renderer.py.

Covers graceful degradation when subdoc functions fail during rendering.
"""

import logging
import pytest
from pathlib import Path
from unittest.mock import MagicMock
import sys

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from logic.renderer import render_templates
from logic.context import make_context_class


def extract_docx_text(doc_path: Path) -> str:
    """Extract all text from a DOCX file."""
    from docx import Document
    doc = Document(str(doc_path))
    paragraphs = [p.text for p in doc.paragraphs]
    return "\n".join(paragraphs)


class TestSubdocErrorHandling:
    """Tests for subdoc function error handling during rendering."""

    def test_subdoc_function_raises_exception(self, project_root, tmp_path, caplog):
        """
        When a subdoc function raises an exception during lazy evaluation,
        DeferredSubdoc should:
        1. Log the error
        2. Fall back to empty string
        3. Continue rendering successfully
        """
        caplog.set_level(logging.ERROR)

        templates_dir = project_root / "templates"

        ContextClass = make_context_class(
            templates_dir / "descr.docx",
            templates_dir / "language_rules.yaml"
        )

        context = ContextClass(
            user_name="ErrorTestUser",
            sex="Мужской",
        )

        # Subdoc function that always raises — use table_1 which IS in template_1.docx
        def broken_subdoc(tpl, **data):
            raise RuntimeError("Simulated subdoc failure")

        store_dir = tmp_path / "test_session"
        store_dir.mkdir(parents=True, exist_ok=True)

        output_files = render_templates(
            templates=[templates_dir / "template_1.docx"],
            context=context,
            store_dir=store_dir,
            subdoc_funcs={"table_1": broken_subdoc},
        )

        # Template should still render despite subdoc failure
        assert len(output_files) == 1
        assert output_files[0].exists()

        # Verify error was logged (fired during lazy eval when template hit {{p table_1}})
        assert "Error executing subdoc function table_1" in caplog.text

    def test_subdoc_function_returns_none(self, project_root, tmp_path, caplog):
        """
        When subdoc function returns None during lazy eval,
        DeferredSubdoc.__str__ should return empty string and rendering continues.
        """
        templates_dir = project_root / "templates"

        ContextClass = make_context_class(
            templates_dir / "descr.docx",
            templates_dir / "language_rules.yaml"
        )

        context = ContextClass(
            user_name="NoneReturnUser",
            sex="Женский",
        )

        # Subdoc function that returns None — use table_1 which IS in template
        def none_subdoc(tpl, **data):
            return None

        store_dir = tmp_path / "test_session"
        store_dir.mkdir(parents=True, exist_ok=True)

        output_files = render_templates(
            templates=[templates_dir / "template_1.docx"],
            context=context,
            store_dir=store_dir,
            subdoc_funcs={"table_1": none_subdoc},
        )

        # Should render successfully — None → empty string
        assert len(output_files) == 1
        text = extract_docx_text(output_files[0])
        assert "NoneReturnUser" in text

    def test_subdoc_function_empty_dict(self, project_root, tmp_path):
        """
        When subdoc function returns empty dict during lazy eval,
        DeferredSubdoc.__str__ returns empty string — rendering continues.
        """
        templates_dir = project_root / "templates"

        ContextClass = make_context_class(
            templates_dir / "descr.docx",
            templates_dir / "language_rules.yaml"
        )

        context = ContextClass(
            user_name="EmptyDictUser",
            sex="Мужской",
        )

        def empty_subdoc(tpl, **data):
            return {}

        store_dir = tmp_path / "test_session"
        store_dir.mkdir(parents=True, exist_ok=True)

        output_files = render_templates(
            templates=[templates_dir / "template_1.docx"],
            context=context,
            store_dir=store_dir,
            subdoc_funcs={"table_1": empty_subdoc},
        )

        # Should render successfully — empty dict → empty string
        assert len(output_files) == 1
        assert output_files[0].exists()

        text = extract_docx_text(output_files[0])
        assert "EmptyDictUser" in text

    def test_mixed_subdoc_success_and_failure(self, project_root, tmp_path, caplog):
        """
        When multiple subdoc functions are provided and one fails,
        successful ones should still be processed (lazy eval).
        """
        caplog.set_level(logging.ERROR)

        templates_dir = project_root / "templates"

        ContextClass = make_context_class(
            templates_dir / "descr.docx",
            templates_dir / "language_rules.yaml"
        )

        context = ContextClass(
            user_name="MixedTestUser",
            sex="Женский",
        )

        def working_subdoc(tpl, **data):
            return tpl.new_subdoc()  # empty but valid Subdoc

        def failing_subdoc(tpl, **data):
            raise ValueError("This one fails")

        store_dir = tmp_path / "test_session"
        store_dir.mkdir(parents=True, exist_ok=True)

        # Use table_1 and table_2 — both are in template_1.docx
        output_files = render_templates(
            templates=[templates_dir / "template_1.docx"],
            context=context,
            store_dir=store_dir,
            subdoc_funcs={
                "table_1": working_subdoc,
                "table_2": failing_subdoc,
            },
        )

        # Should still render
        assert len(output_files) == 1

        # Error should be logged for failing one (fired during lazy eval)
        assert "Error executing subdoc function table_2" in caplog.text

    def test_subdoc_function_with_missing_context_data(self, project_root, tmp_path, caplog):
        """
        Subdoc function that raises KeyError during lazy eval
        should be caught by DeferredSubdoc — rendering continues.
        """
        caplog.set_level(logging.ERROR, logger='logic.subdoc_helper')

        templates_dir = project_root / "templates"

        ContextClass = make_context_class(
            templates_dir / "descr.docx",
            templates_dir / "language_rules.yaml"
        )

        # Context without university field
        context = ContextClass(
            user_name="MissingDataUser",
            sex="Мужской",
        )

        def strict_subdoc(tpl, **data):
            # Expects non-empty 'university' in data — but context has it as empty string
            if not data.get('university'):
                raise ValueError("university is empty")
            return {}

        store_dir = tmp_path / "test_session"
        store_dir.mkdir(parents=True, exist_ok=True)

        output_files = render_templates(
            templates=[templates_dir / "template_1.docx"],
            context=context,
            store_dir=store_dir,
            subdoc_funcs={"table_1": strict_subdoc},
        )

        # Should handle error gracefully — error logged, render continues
        assert len(output_files) == 1
        assert "Error executing subdoc function table_1" in caplog.text

    def test_non_callable_subdoc_value(self, project_root, tmp_path):
        """
        When subdoc_funcs contains a non-callable value,
        renderer should skip it (callable() check in wrapping loop).
        """
        templates_dir = project_root / "templates"

        ContextClass = make_context_class(
            templates_dir / "descr.docx",
            templates_dir / "language_rules.yaml"
        )

        context = ContextClass(
            user_name="NonCallableUser",
            sex="Мужской",
        )

        # Pass a dict instead of a function
        store_dir = tmp_path / "test_session"
        store_dir.mkdir(parents=True, exist_ok=True)

        output_files = render_templates(
            templates=[templates_dir / "template_1.docx"],
            context=context,
            store_dir=store_dir,
            subdoc_funcs={"not_a_func": {"already": "dict"}},
        )

        # Should still render (non-callables are skipped)
        assert len(output_files) == 1
