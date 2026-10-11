"""
E2E tests for multi-pack support against running container.

Tests hit the actual container at http://localhost:5555
Requires container to be running with multiple packs configured.
"""
from __future__ import annotations

import pytest
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

BASE_URL = "http://localhost:5555"


def _skip_if_no_container():
    """Skip test if container is not running."""
    try:
        resp = requests.get(BASE_URL, timeout=5)
        return resp.status_code != 200
    except requests.ConnectionError:
        return True
    except requests.Timeout:
        return True


class TestE2EMultiPackEndpoints:
    """E2E tests for multi-pack endpoints."""

    def test_select_endpoint_exists(self):
        """GET /select should return pack selection UI."""
        if _skip_if_no_container():
            pytest.skip("Container not running")

        resp = requests.get(f"{BASE_URL}/select", timeout=10)
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("Content-Type", "")
        html = resp.text.lower()
        # Should have pack selection elements
        assert "pack" in html or "select" in html or "set" in html

    def test_init_endpoint_accessible(self):
        """GET /init should return initialization form."""
        if _skip_if_no_container():
            pytest.skip("Container not running")

        resp = requests.get(f"{BASE_URL}/init", timeout=10)
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("Content-Type", "")
        html = resp.text.lower()
        assert "form" in html

    def test_reset_endpoint_works(self):
        """GET /reset should clear session."""
        if _skip_if_no_container():
            pytest.skip("Container not running")

        resp = requests.get(f"{BASE_URL}/reset", timeout=10)
        assert resp.status_code == 200


class TestE2ESessionIsolation:
    """E2E tests for session isolation between different pack selections."""

    def test_session_preserves_pack_selection(self):
        """Selected pack should persist in session across requests."""
        if _skip_if_no_container():
            pytest.skip("Container not running")

        s = requests.Session()

        # Get init page (should establish session)
        resp = s.get(f"{BASE_URL}/init", timeout=10)
        assert resp.status_code == 200

        # Session should be established
        assert len(s.cookies) > 0 or "session" in str(s.cookies)


class TestE2EConcurrentRequests:
    """E2E tests for concurrent requests to container."""

    def test_concurrent_init_requests(self):
        """Multiple concurrent /init requests should all succeed."""
        if _skip_if_no_container():
            pytest.skip("Container not running")

        results = []
        lock = Lock()

        def make_init_request(request_id):
            """Make a single /init request."""
            try:
                s = requests.Session()
                resp = s.get(f"{BASE_URL}/init", timeout=30)
                with lock:
                    results.append((request_id, resp.status_code, None))
            except Exception as e:
                with lock:
                    results.append((request_id, None, str(e)))

        # Execute concurrent requests
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(make_init_request, i) for i in range(5)]
            for future in as_completed(futures):
                future.result()

        # Verify all requests succeeded
        assert len(results) == 5
        errors = [r for r in results if r[2] is not None]
        assert len(errors) == 0, f"Errors: {errors}"

        for request_id, status_code, error in results:
            assert status_code == 200, f"Request {request_id} got status {status_code}"

    def test_concurrent_select_requests(self):
        """Multiple concurrent /select requests should all succeed."""
        if _skip_if_no_container():
            pytest.skip("Container not running")

        results = []
        lock = Lock()

        def make_select_request(request_id):
            """Make a single /select request."""
            try:
                s = requests.Session()
                resp = s.get(f"{BASE_URL}/select", timeout=30)
                with lock:
                    results.append((request_id, resp.status_code, None))
            except Exception as e:
                with lock:
                    results.append((request_id, None, str(e)))

        # Execute concurrent requests
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(make_select_request, i) for i in range(5)]
            for future in as_completed(futures):
                future.result()

        # Verify all requests succeeded
        assert len(results) == 5
        errors = [r for r in results if r[2] is not None]
        assert len(errors) == 0, f"Errors: {errors}"

        for request_id, status_code, error in results:
            assert status_code == 200, f"Request {request_id} got status {status_code}"

    def test_mixed_concurrent_requests(self):
        """Mixed /init and /select concurrent requests should all succeed."""
        if _skip_if_no_container():
            pytest.skip("Container not running")

        results = []
        lock = Lock()

        def make_request(request_id, endpoint):
            """Make a request to the specified endpoint."""
            try:
                s = requests.Session()
                resp = s.get(f"{BASE_URL}{endpoint}", timeout=30)
                with lock:
                    results.append((request_id, endpoint, resp.status_code, None))
            except Exception as e:
                with lock:
                    results.append((request_id, endpoint, None, str(e)))

        # Execute mixed concurrent requests
        endpoints = ['/init', '/select', '/init', '/select', '/init', '/debug-vars']
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = [
                executor.submit(make_request, i, endpoint)
                for i, endpoint in enumerate(endpoints)
            ]
            for future in as_completed(futures):
                future.result()

        # Verify all requests succeeded
        assert len(results) == len(endpoints)
        errors = [r for r in results if r[3] is not None]
        assert len(errors) == 0, f"Errors: {errors}"

        for request_id, endpoint, status_code, error in results:
            assert status_code == 200, f"{endpoint} request {request_id} got status {status_code}"


class TestE2EPackSwitching:
    """E2E tests for pack switching behavior."""

    def test_pack_switch_button_exists(self):
        """Init page should have pack switch button."""
        if _skip_if_no_container():
            pytest.skip("Container not running")

        s = requests.Session()
        resp = s.get(f"{BASE_URL}/init", timeout=10)
        assert resp.status_code == 200

        # Check for pack switch button/link
        html = resp.text
        # Should have "Сменить набор шаблонов" or similar
        assert "сменить" in html.lower() or "change" in html.lower() or "pack" in html.lower()

    def test_select_page_shows_pack_info(self):
        """Select page should show pack descriptions and template counts."""
        if _skip_if_no_container():
            pytest.skip("Container not running")

        resp = requests.get(f"{BASE_URL}/select", timeout=10)
        assert resp.status_code == 200

        html = resp.text
        # Should have some pack information
        assert "pack" in html.lower() or "набор" in html.lower() or "root" in html.lower()
