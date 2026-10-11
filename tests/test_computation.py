"""
Tests for app/logic/computation.py

Covers: compute_variables function for regular variables, subdoc variables,
error handling, and NO RULE cases.
"""
import pytest
import types
from pathlib import Path
from unittest.mock import MagicMock

from logic.hints_builder import build_hints_collections


@pytest.fixture
def computation():
    """Import computation module."""
    from logic.computation import compute_variables
    return compute_variables


@pytest.fixture
def sample_modules(user_logic_dir):
    """Load sample logic modules for testing."""
    import sys
    import importlib.util

    modules = {}
    if str(user_logic_dir) not in sys.path:
        sys.path.insert(0, str(user_logic_dir))

    for py_file in user_logic_dir.glob("*.py"):
        if py_file.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            modules[py_file.stem] = module
        except Exception:
            pass

    return modules


class TestComputeVariablesBasic:
    """Basic tests for compute_variables function."""

    def test_returns_tuple(self, computation):
        """compute_variables should return a tuple of (computed_values, subdoc_functions)."""
        hints = build_hints_collections({})
        result = computation({}, set(), hints, {})
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_returns_dicts(self, computation):
        """Both return values should be dictionaries."""
        hints = build_hints_collections({})
        computed, subdocs = computation({}, set(), hints, {})
        assert isinstance(computed, dict)
        assert isinstance(subdocs, dict)

    def test_empty_inputs(self, computation):
        """Empty inputs should return empty outputs."""
        hints = build_hints_collections({})
        computed, subdocs = computation({}, set(), hints, {})
        assert computed == {}
        assert subdocs == {}

    def test_no_missing_vars(self, computation):
        """If all vars are provided, nothing should be computed."""
        cleaned_data = {"name": "John", "age": "30"}
        expected_vars = {"name", "age"}
        hints = build_hints_collections({})
        computed, subdocs = computation(cleaned_data, expected_vars, hints, {})
        assert computed == {}
        assert subdocs == {}



class TestComputeVariablesNoRule:
    """Tests for NO RULE case when no function is found."""

    def test_no_rule_message(self, computation):
        """Should return 'NO RULE for <var>' when no function exists."""
        cleaned_data = {}
        expected_vars = {"missing_var"}
        hints = build_hints_collections({})
        computed, subdocs = computation(cleaned_data, expected_vars, hints, {})
        assert computed.get("missing_var") == "NO RULE for missing_var"

    def test_multiple_no_rule(self, computation):
        """Should handle multiple missing variables with no rules."""
        cleaned_data = {}
        expected_vars = {"var1", "var2", "var3"}
        hints = build_hints_collections({})
        computed, subdocs = computation(cleaned_data, expected_vars, hints, {})
        assert computed.get("var1") == "NO RULE for var1"
        assert computed.get("var2") == "NO RULE for var2"
        assert computed.get("var3") == "NO RULE for var3"


class TestComputeVariablesRegular:
    """Tests for regular variable computation with compute_ functions."""

    def test_compute_birth_year(self, computation, sample_modules):
        """Should compute birth_year using compute_birth_year function."""
        cleaned_data = {"user_age": "25"}
        expected_vars = {"birth_year"}
        var_descs = {"birth_year": {"type": "computed", "types": ["computed"]}}

        hints = build_hints_collections(var_descs)
        computed, subdocs = computation(cleaned_data, expected_vars, hints, sample_modules)

        # birth_year should be computed (current_year - age)
        assert "birth_year" in computed
        assert subdocs == {}  # No subdoc functions

    def test_compute_appeal(self, computation, sample_modules):
        """Should compute appeal using compute_appeal function."""
        cleaned_data = {"sex": "Мужской"}
        expected_vars = {"appeal"}
        var_descs = {"appeal": {"type": "computed", "types": ["computed"]}}

        hints = build_hints_collections(var_descs)
        computed, subdocs = computation(cleaned_data, expected_vars, hints, sample_modules)

        assert "appeal" in computed
        # Appeal returns the grammatical ending from language_rules.yaml (e.g., 'ый' for male)
        assert computed["appeal"] in ["ый", "ая"]  # Male or female ending
        assert subdocs == {}

    def test_compute_with_existing_data(self, computation, sample_modules):
        """Should only compute variables not in cleaned_data."""
        cleaned_data = {"birth_year": "already_set", "user_age": "25"}
        expected_vars = {"birth_year", "appeal"}
        var_descs = {
            "birth_year": {"type": "computed", "types": ["computed"]},
            "appeal": {"type": "computed", "types": ["computed"]}
        }

        hints = build_hints_collections(var_descs)
        computed, subdocs = computation(cleaned_data, expected_vars, hints, sample_modules)

        # birth_year should NOT be recomputed (already in cleaned_data)
        assert "birth_year" not in computed
        # appeal should be computed
        assert "appeal" in computed

    def test_compute_chains_variables(self, computation):
        """A compute_<b> that reads compute_<a>'s output sees it when <a> is
        declared before <b> in descr order (compute vars run in descr order)."""
        mod1 = types.ModuleType("mod1")
        mod1.compute_first = lambda **kwargs: "value1"
        mod1.compute_second = lambda **kwargs: f"depends_on_{kwargs.get('first')}"

        modules = {"mod1": mod1}
        cleaned_data = {}
        expected_vars = {"first", "second"}
        # descr order: first before second -> compute_second sees compute_first's value
        var_descs = {"first": {"type": "computed", "types": ["computed"]},
                     "second": {"type": "computed", "types": ["computed"]}}

        hints = build_hints_collections(var_descs)
        computed, subdocs = computation(cleaned_data, expected_vars, hints, modules)

        assert computed["first"] == "value1"
        assert computed["second"] == "depends_on_value1"

    def test_compute_chain_follows_descr_order(self, computation):
        """Chaining follows descr order, deterministically: if the dependent is
        declared before its dependency, it does NOT see the dependency's value
        (this is the reverse of the coin-flip the old set iteration allowed)."""
        mod1 = types.ModuleType("mod1")
        mod1.compute_first = lambda **kwargs: "value1"
        mod1.compute_second = lambda **kwargs: f"depends_on_{kwargs.get('first')}"

        modules = {"mod1": mod1}
        cleaned_data = {}
        expected_vars = {"first", "second"}
        # descr order: second before first -> compute_second runs first, no 'first' yet
        var_descs = {"second": {"type": "computed", "types": ["computed"]},
                     "first": {"type": "computed", "types": ["computed"]}}

        hints = build_hints_collections(var_descs)
        computed, subdocs = computation(cleaned_data, expected_vars, hints, modules)

        assert computed["second"] == "depends_on_None"
        assert computed["first"] == "value1"

    def test_var_named_session_no_kwarg_collision(self, computation):
        """A form variable literally named `session` must not collide with the
        framework session kwarg (pre-fix: duplicate-kwarg TypeError, swallowed
        into a silent 'ERROR:' string). The framework session wins."""
        framework_session = {"session_id": "test"}
        mod = types.ModuleType("sessionvar")
        mod.compute_note = lambda **kwargs: kwargs["session"]

        modules = {"sessionvar": mod}
        cleaned_data = {"session": "user_value"}  # form var named `session`
        expected_vars = {"note"}
        var_descs = {"note": {"type": "computed", "types": ["computed"]}}

        hints = build_hints_collections(var_descs)
        computed, subdocs = computation(
            cleaned_data, expected_vars, hints, modules, session=framework_session
        )

        # No 'ERROR:' — the plugin received the framework session, not the form value
        assert computed["note"] is framework_session


class TestComputeVariablesErrors:
    """Tests for error handling in computation."""

    def test_error_on_exception(self, computation):
        """Should return 'ERROR: <message>' when computation raises."""
        mod = types.ModuleType("broken")
        mod.compute_broken = lambda **kwargs: (_ for _ in ()).throw(ValueError("test error"))

        modules = {"broken": mod}
        cleaned_data = {}
        expected_vars = {"broken"}
        var_descs = {"broken": {"type": "computed", "types": ["computed"]}}

        hints = build_hints_collections(var_descs)
        computed, subdocs = computation(cleaned_data, expected_vars, hints, modules)

        assert computed.get("broken").startswith("ERROR:")
        assert "test error" in computed["broken"]
        assert subdocs == {}

    def test_error_does_not_break_others(self, computation):
        """Error in one variable should not prevent others from computing."""
        mod = types.ModuleType("mixed")
        mod.compute_working = lambda **kwargs: "success"
        mod.compute_failing = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("fail"))

        modules = {"mixed": mod}
        cleaned_data = {}
        expected_vars = {"working", "failing"}
        var_descs = {"working": {"type": "computed", "types": ["computed"]}, "failing": {"type": "computed", "types": ["computed"]}}

        hints = build_hints_collections(var_descs)
        computed, subdocs = computation(cleaned_data, expected_vars, hints, modules)

        assert computed.get("working") == "success"
        assert computed.get("failing").startswith("ERROR:")


class TestComputeOnErrorStrict:
    """COMPUTE_ON_ERROR=strict — abort generation instead of rendering the
    sentinel strings ("NO RULE for X" / "ERROR: ...") into the document."""

    def test_strict_no_rule_raises(self, computation, monkeypatch):
        import config
        monkeypatch.setattr(config, 'COMPUTE_ON_ERROR', 'strict')

        hints = build_hints_collections({})
        with pytest.raises(RuntimeError, match="No compute rule for variable 'missing_var'"):
            computation({}, {"missing_var"}, hints, {})

    def test_strict_compute_exception_raises(self, computation, monkeypatch):
        import config
        monkeypatch.setattr(config, 'COMPUTE_ON_ERROR', 'strict')

        mod = types.ModuleType("broken")
        mod.compute_broken = lambda **kwargs: (_ for _ in ()).throw(ValueError("boom"))

        hints = build_hints_collections({"broken": {"type": "computed", "types": ["computed"]}})
        with pytest.raises(RuntimeError, match="compute_broken failed: boom"):
            computation({}, {"broken"}, hints, {"broken": mod})

    def test_lenient_keeps_sentinels(self, computation, monkeypatch):
        """Explicit lenient = current behavior (pins the default against drift)."""
        import config
        monkeypatch.setattr(config, 'COMPUTE_ON_ERROR', 'lenient')

        mod = types.ModuleType("broken")
        mod.compute_broken = lambda **kwargs: (_ for _ in ()).throw(ValueError("boom"))

        hints = build_hints_collections({"broken": {"type": "computed", "types": ["computed"]}})
        computed, subdocs = computation({}, {"broken"}, hints, {"broken": mod})

        assert computed["broken"].startswith("ERROR:")
        assert subdocs == {}


class TestComputeVariablesSubdoc:
    """Tests for subdoc variable handling."""

    def test_subdoc_function_stored_as_callable(self, computation):
        """Subdoc functions should be stored as callables, not executed."""
        # Create a mock subdoc function
        mock_subdoc_func = MagicMock(return_value={"key": "subdoc"})

        mod = types.ModuleType("mock_subdoc")
        setattr(mod, "mydoc", mock_subdoc_func)

        modules = {"mock_subdoc": mod}
        cleaned_data = {}
        expected_vars = {"mydoc"}
        var_descs = {"mydoc": {"type": "subdoc", "types": ["subdoc"]}}

        hints = build_hints_collections(var_descs)
        computed, subdocs = computation(cleaned_data, expected_vars, hints, modules)

        # Should be in subdoc_functions, not computed_values
        assert "mydoc" not in computed
        assert "mydoc" in subdocs
        assert callable(subdocs["mydoc"])

        # Function should not have been called yet
        mock_subdoc_func.assert_not_called()

    def test_subdoc_direct_name_match(self, computation, user_logic_dir):
        """Subdoc should use direct name match, not compute_ prefix."""
        # Load actual modules - university has university_historical as subdoc function
        import sys
        import importlib.util

        modules = {}
        if str(user_logic_dir) not in sys.path:
            sys.path.insert(0, str(user_logic_dir))

        for py_file in user_logic_dir.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                modules[py_file.stem] = module
            except Exception:
                pass

        cleaned_data = {}
        expected_vars = {"university_historical"}
        var_descs = {"university_historical": {"type": "subdoc", "types": ["subdoc"]}}

        hints = build_hints_collections(var_descs)
        computed, subdocs = computation(cleaned_data, expected_vars, hints, modules)

        # Should be found as subdoc function (direct name match)
        assert "university_historical" in subdocs
        assert callable(subdocs["university_historical"])

    def test_regular_var_not_treated_as_subdoc(self, computation, sample_modules):
        """Regular computed variables should not be stored as subdoc functions."""
        cleaned_data = {"user_age": "30"}
        expected_vars = {"birth_year"}
        var_descs = {"birth_year": {"type": "computed", "types": ["computed"]}}

        hints = build_hints_collections(var_descs)
        computed, subdocs = computation(cleaned_data, expected_vars, hints, sample_modules)

        assert "birth_year" in computed
        assert "birth_year" not in subdocs

    def test_missing_subdoc_no_rule(self, computation):
        """Missing subdoc function should return NO RULE."""
        cleaned_data = {}
        expected_vars = {"missing_subdoc"}
        var_descs = {"missing_subdoc": {"type": "subdoc", "types": ["subdoc"]}}

        hints = build_hints_collections(var_descs)
        computed, subdocs = computation(cleaned_data, expected_vars, hints, {})

        assert "missing_subdoc" not in subdocs
        assert computed.get("missing_subdoc") == "NO RULE for missing_subdoc"


class TestComputeVariablesIntegration:
    """Integration tests with actual logic modules."""

    def test_multiple_compute_modules(self, computation, user_logic_dir):
        """Should work with multiple compute modules loaded."""
        import sys
        import importlib.util

        modules = {}
        if str(user_logic_dir) not in sys.path:
            sys.path.insert(0, str(user_logic_dir))

        for py_file in user_logic_dir.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                modules[py_file.stem] = module
            except Exception:
                pass

        cleaned_data = {"user_age": "30", "sex": "Женский"}
        expected_vars = {"birth_year", "appeal"}
        var_descs = {
            "birth_year": {"type": "computed", "types": ["computed"]},
            "appeal": {"type": "computed", "types": ["computed"]}
        }

        hints = build_hints_collections(var_descs)
        computed, subdocs = computation(cleaned_data, expected_vars, hints, modules)

        # Both should be computed
        assert "birth_year" in computed
        assert "appeal" in computed
        assert subdocs == {}

    def test_mixed_compute_and_subdoc(self, computation, user_logic_dir):
        """Should handle both compute functions and subdoc functions together."""
        import sys
        import importlib.util

        modules = {}
        if str(user_logic_dir) not in sys.path:
            sys.path.insert(0, str(user_logic_dir))

        for py_file in user_logic_dir.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                modules[py_file.stem] = module
            except Exception:
                pass

        cleaned_data = {}
        expected_vars = {"university_historical"}
        var_descs = {"university_historical": {"type": "subdoc", "types": ["subdoc"]}}

        hints = build_hints_collections(var_descs)
        computed, subdocs = computation(cleaned_data, expected_vars, hints, modules)

        # Subdoc should be in subdoc_functions
        assert "university_historical" in subdocs
        assert callable(subdocs["university_historical"])


class TestMergeResult:
    """Tests for merge_result() — callable detection and dict flattening."""

    def _import_merge(self):
        from logic.computation import merge_result
        return merge_result

    def test_plain_value_stored(self):
        """Plain values go to computed_values."""
        merge_result = self._import_merge()
        computed = {}
        subdocs = {}
        merge_result("my_var", "hello", computed, subdocs)
        assert computed == {"my_var": "hello"}
        assert subdocs == {}

    def test_callable_deferred(self):
        """Callable results go to subdoc_functions."""
        merge_result = self._import_merge()
        computed = {}
        subdocs = {}
        fn = lambda tpl, **ctx: "subdoc_result"
        merge_result("my_var", fn, computed, subdocs)
        assert computed == {}
        assert "my_var" in subdocs
        assert callable(subdocs["my_var"])

    def test_dict_with_callables_flattened(self):
        """Dict with callable values is flattened: callables → subdocs, plain → computed."""
        merge_result = self._import_merge()
        computed = {}
        subdocs = {}
        fn1 = lambda tpl, **ctx: "a"
        fn2 = lambda tpl, **ctx: "b"
        result = {"key_a": fn1, "key_b": fn2, "key_c": "plain_value"}
        merge_result("factory_var", result, computed, subdocs)
        assert computed == {"key_c": "plain_value"}
        assert set(subdocs.keys()) == {"key_a", "key_b"}

    def test_plain_dict_stored_as_single_value(self):
        """Plain dict (no callables) is stored as a single value, not flattened."""
        merge_result = self._import_merge()
        computed = {}
        subdocs = {}
        result = {"nested_key": "nested_value", "another": 42}
        merge_result("my_var", result, computed, subdocs)
        assert computed == {"my_var": {"nested_key": "nested_value", "another": 42}}
        assert subdocs == {}

    def test_empty_dict_stored_as_value(self):
        """Empty dict is stored as a single value (no callables to check)."""
        merge_result = self._import_merge()
        computed = {}
        subdocs = {}
        merge_result("my_var", {}, computed, subdocs)
        assert computed == {"my_var": {}}
        assert subdocs == {}

    def test_list_stored_as_value(self):
        """List results are stored as-is in computed_values."""
        merge_result = self._import_merge()
        computed = {}
        subdocs = {}
        merge_result("my_var", ["a", "b", "c"], computed, subdocs)
        assert computed == {"my_var": ["a", "b", "c"]}
        assert subdocs == {}

    def test_mixed_dict_partial_callables(self):
        """Dict with some callables and some plain values: each dispatched correctly."""
        merge_result = self._import_merge()
        computed = {}
        subdocs = {}
        fn = lambda tpl, **ctx: "extracted"
        result = {"slot_1": fn, "slot_2": "static_text", "slot_3": 42}
        merge_result("table", result, computed, subdocs)
        assert computed == {"slot_2": "static_text", "slot_3": 42}
        assert "slot_1" in subdocs
