"""
Tests for logic/sticker.py — the file-count-limit init hook.

Only `init_sticker()` is covered: it is the user-side half of the feature (the
`file:<N>` descr cap rendered as a JS FileList gate). The `compute_sticker()`
half — SVG→PNG conversion + subdoc assembly — is demo-only and depends on
cairosvg, which is deliberately kept out of requirements; it is not tested here.
"""
import pytest


def _desc(file_option):
    """A minimal parsed variable_desc for the `sticker` var.

    `file_option` is the value of options['file'] (an int, or None for "no
    options" — the shape the parser yields when the cell is empty).
    """
    return {'sticker': {'options': None if file_option is None else {'file': file_option}}}


class TestInitSticker:
    """Tests for init_sticker() — the upload-count cap (the showcased feature)."""

    def test_renders_capped_input_when_limit_set(self):
        """file:2 + no upload -> multiple input with the JS cap + alert, no accept."""
        from logic.sticker import init_sticker

        result = init_sticker({}, [], _desc(2))

        assert 'type="file"' in result
        assert 'multiple' in result
        # the cap: over-limit batch is rejected + cleared
        assert 'el.files.length > 2' in result
        assert 'alert(' in result
        # no content filtering at the picker — rogue files are allowed in
        assert 'accept' not in result

    def test_uncapped_when_no_limit_option(self):
        """No file option (options is None) -> input renders, but no cap JS."""
        from logic.sticker import init_sticker

        result = init_sticker({}, [], _desc(None))

        assert 'type="file"' in result
        assert 'multiple' in result
        assert 'el.files.length >' not in result

    def test_uncapped_when_limit_zero(self):
        """file:0 means "no cap" (parser degrades non-positive to 0)."""
        from logic.sticker import init_sticker

        result = init_sticker({}, [], _desc(0))

        assert 'multiple' in result
        assert 'el.files.length >' not in result

    def test_silent_when_files_uploaded(self):
        """Files already uploaded -> "" (hash convergence, no re-render)."""
        from logic.sticker import init_sticker

        session = {'uploaded_files': {'sticker': ['/path/a.svg', '/path/b.svg']}}
        assert init_sticker(session, [], _desc(2)) == ""

    def test_ignores_matched_list(self):
        """matched_list is always [] for a file var; it must not affect the UI."""
        from logic.sticker import init_sticker

        result = init_sticker({}, ['some', 'matches'], _desc(2))

        assert 'type="file"' in result
        assert 'el.files.length > 2' in result
