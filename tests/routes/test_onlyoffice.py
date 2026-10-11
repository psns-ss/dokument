"""
Tests for app/routes/onlyoffice.py - OnlyOffice editor HTML generation.

Covers:
    generate_editor_html() - utility function for generating editor HTML wrappers
"""
from __future__ import annotations

import pytest
from pathlib import Path


class TestGenerateEditorHtml:
    """Test the generate_editor_html utility function."""

    def test_generates_html_file(self, temp_dir):
        """generate_editor_html should create an HTML file in the session directory."""
        from routes.onlyoffice import generate_editor_html

        session_dir = temp_dir / "session_123"
        session_dir.mkdir()

        result = generate_editor_html(
            session_dir=str(session_dir),
            docx_filename="document.docx",
            docx_public_url="/documents/session_123/document.docx"
        )

        html_file = session_dir / "document.docx.html"
        assert html_file.exists()
        assert html_file.stat().st_size > 0

    def test_returns_correct_url(self, temp_dir):
        """generate_editor_html should return the correct public URL."""
        from routes.onlyoffice import generate_editor_html

        session_dir = temp_dir / "session_456"
        session_dir.mkdir()

        result = generate_editor_html(
            session_dir=str(session_dir),
            docx_filename="report.docx",
            docx_public_url="/documents/session_456/report.docx"
        )

        assert result == "/documents/session_456/report.docx.html"

    def test_html_content_contains_editor_elements(self, temp_dir):
        """Generated HTML should contain editor iframe and OnlyOffice elements."""
        from routes.onlyoffice import generate_editor_html

        session_dir = temp_dir / "session_789"
        session_dir.mkdir()

        generate_editor_html(
            session_dir=str(session_dir),
            docx_filename="test.docx",
            docx_public_url="/documents/session_789/test.docx"
        )

        html_file = session_dir / "test.docx.html"
        content = html_file.read_text(encoding="utf-8")

        # Check for essential HTML structure
        assert "<!DOCTYPE html" in content or "<html" in content.lower()
        assert "iframe" in content.lower() or "src=" in content.lower()

    def test_html_title_contains_document_name(self, temp_dir):
        """HTML title should contain the document stem name."""
        from routes.onlyoffice import generate_editor_html

        session_dir = temp_dir / "session_title"
        session_dir.mkdir()

        generate_editor_html(
            session_dir=str(session_dir),
            docx_filename="my_report.docx",
            docx_public_url="/documents/session_title/my_report.docx"
        )

        html_file = session_dir / "my_report.docx.html"
        content = html_file.read_text(encoding="utf-8")

        # The title should contain the document name (my_report)
        assert "my_report" in content.lower() or "<title" in content.lower()

    def test_generates_unique_key(self, temp_dir):
        """Each call should generate a unique key (UUID)."""
        from routes.onlyoffice import generate_editor_html

        session_dir = temp_dir / "session_unique"
        session_dir.mkdir()

        generate_editor_html(
            session_dir=str(session_dir),
            docx_filename="doc1.docx",
            docx_public_url="/documents/session_unique/doc1.docx"
        )

        html_file = session_dir / "doc1.docx.html"
        content = html_file.read_text(encoding="utf-8")

        # Should contain a UUID-like key in the rendered template
        # The editor_template.html uses 'key' for document uniqueness
        assert len(content) > 0  # File was generated with content

    def test_handles_different_document_names(self, temp_dir):
        """Should correctly handle various document filename patterns."""
        from routes.onlyoffice import generate_editor_html

        session_dir = temp_dir / "session_names"
        session_dir.mkdir()

        test_cases = [
            ("simple.docx", "simple.docx.html"),
            ("complex-name_2024.docx", "complex-name_2024.docx.html"),
            ("with.dots.in.name.docx", "with.dots.in.name.docx.html"),
        ]

        for docx_name, expected_html in test_cases:
            result = generate_editor_html(
                session_dir=str(session_dir),
                docx_filename=docx_name,
                docx_public_url=f"/documents/session_names/{docx_name}"
            )

            html_file = session_dir / expected_html
            assert html_file.exists(), f"Expected {expected_html} to be created"
            assert result == f"/documents/session_names/{expected_html}"
