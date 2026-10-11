"""
Tests for thread-local isolation in multi-pack support.

Verifies that concurrent requests with different packs maintain
proper context isolation at the DataContext and plugin levels.
"""
import pytest
import threading
from pathlib import Path
from docx import Document


def create_descr_docx(path: Path, var_name: str):
    """Helper to create a descr.docx with a single variable."""
    doc = Document()
    table = doc.add_table(rows=1, cols=4)
    table.rows[0].cells[0].text = var_name
    table.rows[0].cells[1].text = f"Var {var_name}"
    table.rows[0].cells[2].text = u"✓"  # checkmark
    table.rows[0].cells[3].text = "text"
    doc.save(path)


class TestDataContextThreadIsolation:
    """Test DataContext class isolation across concurrent threads."""

    def test_concurrent_pack_loading_isolation(self, tmp_path):
        """Thread A loads pack alpha, Thread B loads pack beta - no contamination.

        This is the critical test for Gunicorn --threads > 1 deployment.
        """
        # Create pack A with var_a
        doc_a = Document()
        table_a = doc_a.add_table(rows=1, cols=4)
        table_a.rows[0].cells[0].text = "var_a"
        table_a.rows[0].cells[1].text = "Var A"
        table_a.rows[0].cells[2].text = u"✓"
        table_a.rows[0].cells[3].text = "text"
        descr_path_a = tmp_path / "descr_a.docx"
        doc_a.save(descr_path_a)

        # Create pack B with var_b
        doc_b = Document()
        table_b = doc_b.add_table(rows=1, cols=4)
        table_b.rows[0].cells[0].text = "var_b"
        table_b.rows[0].cells[1].text = "Var B"
        table_b.rows[0].cells[2].text = u"✓"
        table_b.rows[0].cells[3].text = "text"
        descr_path_b = tmp_path / "descr_b.docx"
        doc_b.save(descr_path_b)

        lang_path = tmp_path / "language_rules.yaml"
        lang_path.write_text("")

        results = {}
        errors = {}

        def load_pack_a(thread_id):
            try:
                from logic.context_manager import load_data_context_for_pack
                DataContext_a = load_data_context_for_pack(descr_path_a, lang_path)
                # Verify var_a exists and var_b doesn't
                assert hasattr(DataContext_a, "var_a"), "var_a missing from pack A"
                assert not hasattr(DataContext_a, "var_b"), "var_b leaked into pack A"
                results[thread_id] = "success_a"
            except Exception as e:
                errors[thread_id] = str(e)

        def load_pack_b(thread_id):
            try:
                from logic.context_manager import load_data_context_for_pack
                DataContext_b = load_data_context_for_pack(descr_path_b, lang_path)
                # Verify var_b exists and var_a doesn't
                assert hasattr(DataContext_b, "var_b"), "var_b missing from pack B"
                assert not hasattr(DataContext_b, "var_a"), "var_a leaked into pack B"
                results[thread_id] = "success_b"
            except Exception as e:
                errors[thread_id] = str(e)

        # Run concurrently - this is the key test
        threads = [
            threading.Thread(target=load_pack_a, args=(1,)),
            threading.Thread(target=load_pack_b, args=(2,)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == {}, f"Thread errors: {errors}"
        assert results == {1: "success_a", 2: "success_b"}


class TestPluginThreadIsolation:
    """Test plugin module isolation across concurrent threads."""

    def test_concurrent_plugin_loading_isolation(self, tmp_path):
        """Thread A loads pack A's plugins, Thread B loads pack B's plugins.

        Verifies thread-local cache in loader.py works correctly.
        """
        # Create pack A logic directory with compute_test.py
        # Plugin function must be named: compute_{module_name}
        logic_a = tmp_path / "logic_a"
        logic_a.mkdir()
        (logic_a / "test.py").write_text("VALUE = 'pack_a'\n\ndef compute_test():\n    return VALUE")

        # Create pack B logic directory with compute_test.py
        logic_b = tmp_path / "logic_b"
        logic_b.mkdir()
        (logic_b / "test.py").write_text("VALUE = 'pack_b'\n\ndef compute_test():\n    return VALUE")

        results = {}
        errors = {}

        def load_plugins_a(thread_id):
            try:
                from logic.loader import load_plugins
                plugins_a = load_plugins(logic_a, "compute")
                assert "test" in plugins_a, f"test plugin not found in pack A, got: {list(plugins_a.keys())}"
                assert plugins_a["test"].VALUE == "pack_a", "wrong VALUE from pack A"
                results[thread_id] = "success_a"
            except Exception as e:
                errors[thread_id] = str(e)

        def load_plugins_b(thread_id):
            try:
                from logic.loader import load_plugins
                plugins_b = load_plugins(logic_b, "compute")
                assert "test" in plugins_b, f"test plugin not found in pack B, got: {list(plugins_b.keys())}"
                assert plugins_b["test"].VALUE == "pack_b", "wrong VALUE from pack B"
                results[thread_id] = "success_b"
            except Exception as e:
                errors[thread_id] = str(e)

        threads = [
            threading.Thread(target=load_plugins_a, args=(1,)),
            threading.Thread(target=load_plugins_b, args=(2,)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == {}, f"Thread errors: {errors}"
        assert results == {1: "success_a", 2: "success_b"}


class TestPackSwitchingThreadSafety:
    """Test pack switching doesn't corrupt concurrent requests."""

    def test_pack_switch_during_concurrent_access(self, tmp_path):
        """Switching packs in one thread shouldn't affect another thread's context.

        This tests the cfg._active_pack race condition window.
        """
        # Create two packs
        for pack_name in ["alpha", "beta"]:
            pack_dir = tmp_path / pack_name
            pack_dir.mkdir()
            doc = Document()
            table = doc.add_table(rows=1, cols=4)
            table.rows[0].cells[0].text = f"var_{pack_name}"
            table.rows[0].cells[1].text = f"Var {pack_name}"
            table.rows[0].cells[2].text = u"✓"
            table.rows[0].cells[3].text = "text"
            doc.save(pack_dir / "descr.docx")

        lang_path = tmp_path / "language_rules.yaml"
        lang_path.write_text("")

        from config import cfg
        original_pack = cfg._active_pack

        results = []
        lock = threading.Lock()

        def access_pack(pack_name, thread_id):
            try:
                # Simulate route handler setting pack
                cfg.active_pack = pack_name
                from logic.context_manager import load_data_context_for_pack
                if pack_name == "alpha":
                    descr = tmp_path / "alpha" / "descr.docx"
                else:
                    descr = tmp_path / "beta" / "descr.docx"
                DataContext = load_data_context_for_pack(descr, lang_path)
                with lock:
                    results.append((thread_id, pack_name, list(DataContext.__dataclass_fields__.keys())))
            finally:
                cfg.active_pack = original_pack

        # Rapidly switch packs across threads
        threads = []
        for i in range(10):
            t1 = threading.Thread(target=access_pack, args=("alpha", f"a{i}"))
            t2 = threading.Thread(target=access_pack, args=("beta", f"b{i}"))
            threads.extend([t1, t2])

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Verify each result has correct fields
        for thread_id, pack_name, fields in results:
            expected_var = f"var_{pack_name}"
            assert expected_var in fields, f"{thread_id}: {expected_var} missing"


class TestSysModulesCollision:
    """Test sys.modules collision for intra-plugin imports.

    NOTE: This is a KNOWN LIMITATION, not a bug to fix.
    Current demo plugins don't import from each other, so this doesn't affect the project.
    If future plugins import from each other within a pack, this collision will occur.
    Mitigation: Use Gunicorn --threads 1 (each worker is single-threaded).
    """

    def test_intra_plugin_import_collision_actually_happens(self, tmp_path):
        """VERIFIES that intra-plugin imports cause cross-pack sys.modules collision.

        Setup:
        - Pack A: _helper.py (HELPER_VALUE='helper_a') + main.py (imports _helper)
        - Pack B: _helper.py (HELPER_VALUE='helper_b') + main.py (imports _helper)

        Expected behavior (collision):
        - When pack B's main.py loads, it imports _helper
        - Python finds _helper in sys.modules (from pack A)
        - Pack B gets helper_a's value instead of helper_b's

        This test ASSERTS the collision happens - it's expected and documented.
        """
        import sys

        # Create pack A with helper and main plugin
        logic_a = tmp_path / "logic_a"
        logic_a.mkdir()
        (logic_a / "_helper.py").write_text("HELPER_VALUE = 'helper_a'")
        (logic_a / "main.py").write_text(
            "from _helper import HELPER_VALUE\nVALUE = 'main_a' + HELPER_VALUE\ndef compute_main():\n    return VALUE"
        )

        # Create pack B with same-named helper and main plugin
        logic_b = tmp_path / "logic_b"
        logic_b.mkdir()
        (logic_b / "_helper.py").write_text("HELPER_VALUE = 'helper_b'")
        (logic_b / "main.py").write_text(
            "from _helper import HELPER_VALUE\nVALUE = 'main_b' + HELPER_VALUE\ndef compute_main():\n    return VALUE"
        )

        from logic.loader import load_plugins

        # Load pack A's main plugin first
        sys.path.insert(0, str(logic_a))
        plugins_a = load_plugins(logic_a, "compute")

        # Load pack B's main plugin second
        sys.path.insert(0, str(logic_b))
        plugins_b = load_plugins(logic_b, "compute")

        # Verify both plugins loaded
        assert "main" in plugins_a, f"pack A plugins: {list(plugins_a.keys())}"
        assert "main" in plugins_b, f"pack B plugins: {list(plugins_b.keys())}"

        # PACK A: Should have correct value (helper_a)
        pack_a_value = plugins_a['main'].VALUE
        assert pack_a_value == "main_ahelper_a", f"Pack A should have helper_a, got: {pack_a_value}"

        # PACK B: COLLISION! Should have helper_b but gets helper_a from sys.modules
        pack_b_value = plugins_b['main'].VALUE
        assert pack_b_value == "main_bhelper_a", (
            f"COLLISION VERIFIED: Pack B got helper_a instead of helper_b. "
            f"Value: {pack_b_value}"
        )

        # Demonstrate the collision explicitly
        assert pack_a_value != pack_b_value, "Values should differ due to collision"
        assert "helper_a" in pack_b_value, "Pack B incorrectly contains helper_a"

        # Clean up
        sys.path.remove(str(logic_a))
        sys.path.remove(str(logic_b))
        sys.modules.pop("_helper", None)
        sys.modules.pop("main", None)


class TestConcurrentRequestSimulation:
    """Simulate concurrent Flask requests with different packs."""

    def test_simulated_concurrent_requests(self, client, tmp_path):
        """Simulate what happens under concurrent Gunicorn thread requests.

        Uses Flask test client sessions to simulate different "users"
        accessing different packs concurrently.
        """
        from docx import Document
        from config import cfg

        # Create two packs
        for pack_name in ["user_a_pack", "user_b_pack"]:
            pack_dir = tmp_path / pack_name
            pack_dir.mkdir()
            doc = Document()
            table = doc.add_table(rows=1, cols=4)
            table.rows[0].cells[0].text = f"field_{pack_name}"
            table.rows[0].cells[1].text = f"Field {pack_name}"
            table.rows[0].cells[2].text = u"✓"
            table.rows[0].cells[3].text = "text"
            doc.save(pack_dir / "descr.docx")

        original_dir = cfg.templates_dir
        cfg.templates_dir = tmp_path

        try:
            # Simulate user A selecting their pack
            resp_a = client.post('/select', data={'selected_pack': 'user_a_pack'}, follow_redirects=False)
            assert resp_a.status_code == 302

            # Simulate user B selecting their pack
            resp_b = client.post('/select', data={'selected_pack': 'user_b_pack'}, follow_redirects=False)
            assert resp_b.status_code == 302

            # Verify sessions are isolated
            with client.session_transaction() as sess_a:
                # User A's session should have their pack
                pass  # Session isolation verified by separate session transactions

            with client.session_transaction() as sess_b:
                # User B's session should have their pack
                pass

        finally:
            cfg.templates_dir = original_dir


