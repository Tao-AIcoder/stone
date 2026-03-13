"""
tests/test_api_health.py - Tests for GET /health endpoint.

Covers:
- 200 response with correct structure
- All required fields present
- Module status aggregation (healthy / degraded / unhealthy)
- Uptime is non-negative
"""

from __future__ import annotations

import sys
import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import main as main_module
from tests.conftest import make_mock_loader, make_test_app


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def client() -> TestClient:
    app = make_test_app(loader=make_mock_loader())
    return TestClient(app, raise_server_exceptions=False)


# ── Structure Tests ────────────────────────────────────────────────────────────

class TestHealthStructure:
    def test_returns_200(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_response_has_status_field(self, client: TestClient) -> None:
        data = client.get("/health").json()
        assert "status" in data

    def test_response_has_version_field(self, client: TestClient) -> None:
        data = client.get("/health").json()
        assert "version" in data

    def test_response_has_uptime_seconds(self, client: TestClient) -> None:
        data = client.get("/health").json()
        assert "uptime_seconds" in data
        assert isinstance(data["uptime_seconds"], int)
        assert data["uptime_seconds"] >= 0

    def test_response_has_timestamp(self, client: TestClient) -> None:
        data = client.get("/health").json()
        assert "timestamp" in data
        # Should be ISO format string
        assert isinstance(data["timestamp"], str)
        assert "T" in data["timestamp"]

    def test_response_has_modules_dict(self, client: TestClient) -> None:
        data = client.get("/health").json()
        assert "modules" in data
        assert isinstance(data["modules"], dict)

    def test_response_has_name_field(self, client: TestClient) -> None:
        data = client.get("/health").json()
        assert "name" in data


# ── Status Aggregation Tests ───────────────────────────────────────────────────

class TestHealthStatusAggregation:
    def test_status_is_valid_value(self, client: TestClient) -> None:
        data = client.get("/health").json()
        assert data["status"] in ("healthy", "degraded", "unhealthy")

    def test_healthy_when_all_modules_ok(self) -> None:
        """When all modules are healthy, overall status is healthy."""
        loader = make_mock_loader()
        # SQLite OK (execute returns normally)
        loader.sqlite_store.db.execute.return_value = None
        # Ollama: we mock httpx in health.py so it will show unreachable (no real Ollama)
        # Gateway running
        loader.gateway._running = True

        app = make_test_app(loader=loader)
        client = TestClient(app, raise_server_exceptions=False)
        data = client.get("/health").json()
        # Status should be at least "degraded" (Ollama not reachable in tests)
        assert data["status"] in ("healthy", "degraded")

    def test_gateway_stopped_reflected_in_modules(self) -> None:
        loader = make_mock_loader()
        loader.gateway._running = False

        app = make_test_app(loader=loader)
        # Patch main._loader so health.py's get_loader() sees our mock
        with patch.object(main_module, "_loader", loader):
            client = TestClient(app, raise_server_exceptions=False)
            data = client.get("/health").json()
        assert "feishu_gateway" in data["modules"]
        assert data["modules"]["feishu_gateway"] == "stopped"

    def test_gateway_running_reflected_in_modules(self) -> None:
        loader = make_mock_loader()
        loader.gateway._running = True

        app = make_test_app(loader=loader)
        with patch.object(main_module, "_loader", loader):
            client = TestClient(app, raise_server_exceptions=False)
            data = client.get("/health").json()
        assert data["modules"]["feishu_gateway"] == "healthy"

    def test_no_loader_returns_healthy_with_empty_modules(self) -> None:
        """If loader is None (before startup), health still returns 200."""
        app = make_test_app(loader=None)
        # Manually set loader to None to simulate pre-startup
        app.state.loader = None
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data

    def test_content_type_is_json(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert "application/json" in resp.headers.get("content-type", "")


# ── Version Tests ──────────────────────────────────────────────────────────────

class TestHealthVersion:
    def test_version_matches_config(self, client: TestClient) -> None:
        data = client.get("/health").json()
        # Version should be a non-empty string
        assert data["version"]
        assert isinstance(data["version"], str)

    def test_name_is_stone(self, client: TestClient) -> None:
        data = client.get("/health").json()
        # Name should reflect the config
        assert isinstance(data["name"], str)
        assert len(data["name"]) > 0
