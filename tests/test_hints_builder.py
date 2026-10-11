"""Tests for app/logic/hints_builder.py"""
import pytest
from logic.hints_builder import build_hints_collections, HintsCollections, verify_hooks_exist


class TestBuildHintsCollections:
    """Tests for the build_hints_collections function."""

    def test_build_hints_collections_single_type(self):
        variable_desc = {
            "user_name": {"type": "text", "types": ["text"]},
            "user_sex": {"type": "enum", "types": ["enum"]},
            "university": {"type": "match", "types": ["match"]},
        }

        hints = build_hints_collections(variable_desc)

        assert hints.vars_to_match == {"university": "university"}
        assert hints.vars_to_compute == []
        assert hints.vars_as_subdocs == []
        assert hints.vars_need_init_form == []

    def test_build_hints_collections_match_yaml_key(self):
        """vars_to_match includes yaml_key from options, defaults to var_name."""
        variable_desc = {
            "university": {"type": "match", "types": ["match"], "options": {"match": "universities"}},
            "company": {"type": "match", "types": ["match"], "options": None},
        }

        hints = build_hints_collections(variable_desc)

        assert hints.vars_to_match == {
            "university": "universities",  # explicit options
            "company": "company",           # defaulted to var_name
        }

    def test_build_hints_collections_multi_type(self):
        variable_desc = {
            "table": {"type": "match,computed,subdoc", "types": ["match", "computed", "subdoc"]},
        }

        hints = build_hints_collections(variable_desc)

        assert hints.vars_to_match == {"table": "table"}
        assert "table" in hints.vars_to_compute
        assert "table" in hints.vars_as_subdocs

    def test_build_hints_collections_file_implies_form(self):
        """type=file should imply form semantics (add to vars_need_init_form)."""
        variable_desc = {
            "cv": {"type": "file", "types": ["file"]},
            "name": {"type": "text", "types": ["text"]},
        }

        hints = build_hints_collections(variable_desc)

        assert "cv" in hints.vars_need_init_form  # file implies form
        assert "name" not in hints.vars_need_init_form

    def test_build_hints_collections_multi_type_with_form(self):
        """type=match,form should add to both vars_to_match and vars_need_init_form."""
        variable_desc = {
            "university": {"type": "match,form", "types": ["match", "form"]},
        }

        hints = build_hints_collections(variable_desc)

        assert "university" in hints.vars_to_match
        assert hints.vars_to_match["university"] == "university"  # defaulted
        assert "university" in hints.vars_need_init_form

    def test_build_hints_collections_form_type(self):
        variable_desc = {
            "signature": {"type": "form", "types": ["form"]},
        }

        hints = build_hints_collections(variable_desc)

        assert hints.vars_need_init_form == ["signature"]

    def test_build_hints_collections_subdoc_only(self):
        """type=subdoc should add to vars_as_subdocs but NOT to vars_to_compute."""
        variable_desc = {
            "table": {"type": "subdoc", "types": ["subdoc"]},
        }

        hints = build_hints_collections(variable_desc)

        assert "table" in hints.vars_as_subdocs
        assert "table" not in hints.vars_to_compute  # subdoc-only, not computed

    def test_build_hints_collections_empty(self):
        """Empty variable_desc should produce empty hints."""
        hints = build_hints_collections({})

        assert hints.vars_to_match == {}
        assert hints.vars_to_compute == []
        assert hints.vars_as_subdocs == []
        assert hints.vars_need_init_form == []

    def test_build_hints_collections_fallback_to_type(self):
        """If 'types' key is missing, fall back to parsing 'type' string."""
        variable_desc = {
            "university": {"type": "match"},  # no 'types' key
        }

        hints = build_hints_collections(variable_desc)

        assert hints.vars_to_match == {"university": "university"}

    def test_build_hints_collections_computed_type(self):
        variable_desc = {
            "computed_field": {"type": "computed", "types": ["computed"]},
        }

        hints = build_hints_collections(variable_desc)

        assert "computed_field" in hints.vars_to_compute
        assert hints.vars_to_match == {}
        assert hints.vars_as_subdocs == []

    def test_build_hints_collections_all_types(self):
        """Test with a mix of all types."""
        variable_desc = {
            "name": {"type": "text", "types": ["text"]},
            "role": {"type": "enum", "types": ["enum"]},
            "university": {"type": "match", "types": ["match"], "options": {"match": "unis"}},
            "summary": {"type": "computed", "types": ["computed"]},
            "history": {"type": "subdoc", "types": ["subdoc"]},
            "cv": {"type": "file", "types": ["file"]},
            "signature": {"type": "form", "types": ["form"]},
            "complex": {"type": "match,computed,subdoc", "types": ["match", "computed", "subdoc"]},
        }

        hints = build_hints_collections(variable_desc)

        assert hints.vars_to_match == {"university": "unis", "complex": "complex"}
        assert "summary" in hints.vars_to_compute
        assert "complex" in hints.vars_to_compute
        assert "history" in hints.vars_as_subdocs
        assert "complex" in hints.vars_as_subdocs
        assert "cv" in hints.vars_need_init_form
        assert "signature" in hints.vars_need_init_form


class TestHintsCollections:
    """Tests for the HintsCollections dataclass."""

    def test_defaults(self):
        hints = HintsCollections()
        assert hints.vars_to_match == {}
        assert hints.vars_to_compute == []
        assert hints.vars_as_subdocs == []
        assert hints.vars_need_init_form == []

    def test_custom_values(self):
        hints = HintsCollections(
            vars_to_match={"a": "b"},
            vars_to_compute=["c"],
            vars_as_subdocs=["d"],
            vars_need_init_form=["e"],
        )
        assert hints.vars_to_match == {"a": "b"}
        assert hints.vars_to_compute == ["c"]
        assert hints.vars_as_subdocs == ["d"]
        assert hints.vars_need_init_form == ["e"]


class TestVerifyHooksExist:
    """Tests for the verify_hooks_exist plugin scan."""

    @staticmethod
    def _make_logic_dir(tmp_path, files):
        logic_dir = tmp_path / "logic"
        logic_dir.mkdir()
        for name, body in files.items():
            (logic_dir / name).write_text(body, encoding="utf-8")
        return logic_dir

    def test_found_and_dropped_and_errors(self, tmp_path):
        logic_dir = self._make_logic_dir(tmp_path, {
            "appeal.py": "def compute_appeal(sex, **kwargs):\n    return 'x'\n",
            # Subdoc-only module: no compute_report_annual() -> the engine's
            # loader drops it, but the name-match scan still finds the hook
            "report_annual.py": "def report_annual(tpl, **kwargs):\n    return {}\n",
            "broken.py": "def oops(:\n",
        })
        hints = HintsCollections(
            vars_to_compute=["appeal"],
            vars_as_subdocs=["report_annual"],
        )
        report = verify_hooks_exist(hints, logic_dir)

        assert report["found"]["appeal"] == {"compute": "appeal"}
        assert report["found"]["report_annual"] == {"subdoc": "report_annual"}
        # The subdoc-only module is found but flagged: engine never loads it
        assert "report_annual" in report["dropped"]["compute"]
        assert "appeal" not in report["dropped"]["compute"]
        assert "broken.py" in report["errors"]

    def test_missing_hook_reports_empty(self, tmp_path):
        logic_dir = self._make_logic_dir(tmp_path, {})
        hints = HintsCollections(vars_to_compute=["appeal"])
        report = verify_hooks_exist(hints, logic_dir)
        assert report["found"]["appeal"] == {}
        assert report["dropped"] == {"match": [], "compute": [], "init": []}
        assert report["errors"] == {}

    def test_no_logic_dir(self, tmp_path):
        hints = HintsCollections(vars_to_compute=["appeal"])
        report = verify_hooks_exist(hints, None)
        assert report["found"] == {}
        assert report["errors"] == {}

    def test_match_var_expects_init_hook(self, tmp_path):
        # generate_dynamic_ui_block fires init_<var> for every matched_entities key —
        # match vars included, not just form/file ones
        logic_dir = self._make_logic_dir(tmp_path, {
            "university.py":
                "def match_university(session, yaml_key):\n    return []\n"
                "def init_university(session, matched_list, variable_desc=None):\n    return ''\n",
        })
        hints = HintsCollections(vars_to_match={"university": "university"})
        report = verify_hooks_exist(hints, logic_dir)
        assert report["found"]["university"] == {"match": "university", "init": "university"}
