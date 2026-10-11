"""
Tests for logic/cv.py — CV file upload init hook.
"""
import pytest


class TestInitCv:
    """Tests for init_cv() hook."""

    def test_returns_file_input_when_no_upload(self):
        """init_cv should return file input HTML when no CV is uploaded."""
        from logic.cv import init_cv

        result = init_cv({}, [])

        assert 'type="file"' in result
        assert 'name="cv"' in result
        assert 'accept=".docx"' in result

    def test_returns_empty_when_file_uploaded(self):
        """init_cv should return empty string when CV file is already uploaded."""
        from logic.cv import init_cv

        session = {'uploaded_files': {'cv': ['/path/to/cv.docx']}}
        result = init_cv(session, [])

        assert result == ""

    def test_returns_empty_when_file_uploaded_multiple(self):
        """init_cv should return empty string when multiple CV files uploaded."""
        from logic.cv import init_cv

        session = {
            'uploaded_files': {
                'cv': ['/path/to/cv_0.docx', '/path/to/cv_1.docx']
            }
        }
        result = init_cv(session, [])

        assert result == ""

    def test_ignores_matched_list(self):
        """init_cv should ignore matched_list (always [] for file vars)."""
        from logic.cv import init_cv

        session = {}
        result = init_cv(session, ['some', 'matches'])

        # Should still return file input since no files uploaded
        assert 'type="file"' in result
