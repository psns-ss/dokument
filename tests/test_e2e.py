"""
End-to-end tests against the running Docker container.

These tests hit the actual running application at http://localhost:5555
to verify the full stack works correctly.

Run only when container is up:
    pytest tests/test_e2e.py -v --e2e
"""
from __future__ import annotations

import os
import pytest
import requests
import re
from pathlib import Path
from typing import Dict, Any

BASE_URL = "http://localhost:5555"
# Path to Flask log file (mounted from container)
FLASK_LOG_PATH = Path(__file__).parent.parent / "app" / "flask_app.log"


def _skip_if_no_container():
    """Skip test if container is not running."""
    try:
        resp = requests.get(BASE_URL, timeout=5)
        return False
    except requests.ConnectionError:
        return True
    except requests.Timeout:
        return True


def _get_recent_log_tail(lines: int = 100) -> str:
    """Read the last N lines from the Flask log file."""
    if not FLASK_LOG_PATH.exists():
        return ""
    try:
        with open(FLASK_LOG_PATH, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
            return "".join(all_lines[-lines:])
    except Exception:
        return ""


class TestE2ERoutes:
    """End-to-end tests against running container."""

    def test_container_is_running(self):
        """Verify container responds on port 5555."""
        if _skip_if_no_container():
            pytest.skip("Container not running at {}".format(BASE_URL))

        resp = requests.get(BASE_URL, timeout=10)
        assert resp.status_code == 200

    def test_init_endpoint_returns_html(self):
        """GET /init should return HTML form."""
        if _skip_if_no_container():
            pytest.skip("Container not running at {}".format(BASE_URL))

        resp = requests.get(f"{BASE_URL}/init", timeout=10)
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("Content-Type", "")
        html = resp.text.lower()
        assert "<html" in html or "<!doctype" in html
        assert "form" in html

    def test_init_endpoint_clears_session(self):
        """GET /init should clear session (return same content each time)."""
        if _skip_if_no_container():
            pytest.skip("Container not running at {}".format(BASE_URL))

        # First request
        s1 = requests.Session()
        resp1 = s1.get(f"{BASE_URL}/init", timeout=10)

        # Second request
        s2 = requests.Session()
        resp2 = s2.get(f"{BASE_URL}/init", timeout=10)

        assert resp1.status_code == 200
        assert resp2.status_code == 200
        # Both should return similar structure
        assert "form" in resp1.text.lower()
        assert "form" in resp2.text.lower()

    def test_debug_vars_endpoint(self):
        """GET /debug-vars should return variable extraction info."""
        if _skip_if_no_container():
            pytest.skip("Container not running at {}".format(BASE_URL))

        resp = requests.get(f"{BASE_URL}/debug-vars", timeout=10)
        assert resp.status_code == 200
        html = resp.text
        assert "variable" in html.lower() or "template" in html.lower()

    def test_reset_endpoint(self):
        """GET /reset should clear session and return link."""
        if _skip_if_no_container():
            pytest.skip("Container not running at {}".format(BASE_URL))

        resp = requests.get(f"{BASE_URL}/reset", timeout=10)
        assert resp.status_code == 200
        html = resp.text.lower()
        assert "reset" in html or "/init" in html

    def test_generate_post_with_minimal_data(self):
        """POST /generate with minimal form data should process."""
        if _skip_if_no_container():
            pytest.skip("Container not running at {}".format(BASE_URL))

        # First get /init to establish session
        s = requests.Session()
        s.get(f"{BASE_URL}/init", timeout=10)

        # POST to /generate
        resp = s.post(
            f"{BASE_URL}/generate",
            data={"user_name": "E2ETest", "user_age": "25"},
            timeout=30
        )
        # Should return 200 (success page with links or error message)
        assert resp.status_code == 200

    def test_post_init_with_form_data(self):
        """POST /init with form data should return auto-submit or step 2."""
        if _skip_if_no_container():
            pytest.skip("Container not running at {}".format(BASE_URL))

        s = requests.Session()
        resp = s.post(
            f"{BASE_URL}/init",
            data={
                "user_name": "E2ETestUser",
                "user_age": "30",
                "sex": "Мужской"
            },
            timeout=30
        )
        # Should return 200 with either auto-submit form or step 2
        assert resp.status_code == 200
        html = resp.text.lower()
        # Either has genform for auto-submit OR has step 2 content
        assert "genform" in html or "step" in html or "form" in html


class TestE2ESessionFlow:
    """End-to-end tests for complete user flows."""

    def test_full_init_to_generate_flow(self):
        """Test complete flow: GET /init -> POST /init -> POST /generate."""
        if _skip_if_no_container():
            pytest.skip("Container not running at {}".format(BASE_URL))

        s = requests.Session()

        # Step 1: GET /init
        resp = s.get(f"{BASE_URL}/init", timeout=10)
        assert resp.status_code == 200

        # Step 2: POST /init with form data
        resp = s.post(
            f"{BASE_URL}/init",
            data={"user_name": "FlowTest", "user_age": "28"},
            timeout=30
        )
        assert resp.status_code == 200

        # Step 3: POST /generate
        resp = s.post(
            f"{BASE_URL}/generate",
            data={"user_name": "FlowTest", "user_age": "28"},
            timeout=30
        )
        assert resp.status_code == 200

    def test_reset_then_init_flow(self):
        """Test reset clears state: GET /reset -> GET /init."""
        if _skip_if_no_container():
            pytest.skip("Container not running at {}".format(BASE_URL))

        s = requests.Session()

        # Reset
        resp = s.get(f"{BASE_URL}/reset", timeout=10)
        assert resp.status_code == 200

        # Init should still work
        resp = s.get(f"{BASE_URL}/init", timeout=10)
        assert resp.status_code == 200
        assert "form" in resp.text.lower()


@pytest.mark.parametrize("endpoint", [
    "/init",
    "/reset",
    "/debug-vars",
])
def test_basic_endpoints_response(endpoint):
    """Test basic endpoints return 200."""
    if _skip_if_no_container():
        pytest.skip("Container not running at {}".format(BASE_URL))

    resp = requests.get(f"{BASE_URL}{endpoint}", timeout=10)
    assert resp.status_code == 200


class TestE2ELogVerification:
    """Tests that verify Flask log file contains expected data.

    The username assertion depends on a DEBUG-level line (the renderer's
    context dump), so run the container with FLASK_LOG_LEVEL=DEBUG for
    this class (see the commented env var in docker-compose.yml).
    """

    def test_log_contains_post_generate_request(self):
        """Verify POST /generate appears in Flask logs."""
        if _skip_if_no_container():
            pytest.skip("Container not running at {}".format(BASE_URL))

        # First make a request
        s = requests.Session()
        s.get(f"{BASE_URL}/init", timeout=10)
        s.post(f"{BASE_URL}/generate", data={"user_name": "LogTest"}, timeout=30)

        # Check log file
        log_tail = _get_recent_log_tail(100)
        assert 'POST /generate' in log_tail, "POST /generate not found in Flask logs"

    def test_log_contains_user_name_in_form_data(self):
        """Verify user data appears in Flask logs (session-driven)."""
        if _skip_if_no_container():
            pytest.skip("Container not running at {}".format(BASE_URL))

        test_username = f"LogUser{os.getpid()}"

        # Go through /init to save data in session, then /generate reads from session
        s = requests.Session()
        s.get(f"{BASE_URL}/init", timeout=10)
        s.post(f"{BASE_URL}/init", data={"user_name": test_username}, timeout=30)
        s.post(f"{BASE_URL}/generate", timeout=30)

        # Check log file for the username
        log_tail = _get_recent_log_tail(100)
        assert test_username in log_tail, f"Username '{test_username}' not found in Flask logs"

    def test_log_contains_request_status_200(self):
        """Verify successful requests log status 200."""
        if _skip_if_no_container():
            pytest.skip("Container not running at {}".format(BASE_URL))

        # Make request
        resp = requests.get(f"{BASE_URL}/init", timeout=10)
        assert resp.status_code == 200

        # Check log file for status 200
        log_tail = _get_recent_log_tail(50)
        assert '200' in log_tail, "Status 200 not found in Flask logs"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
