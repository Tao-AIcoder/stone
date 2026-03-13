"""
tests/test_blackbox_health.py - Black-box tests for GET /health

Rules:
- Only inspect HTTP status codes and response body.
- No knowledge of internal implementation.
"""

from __future__ import annotations

import sys
import os

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.conftest import make_test_app, make_mock_loader


@pytest.fixture
def client() -> TestClient:
    return TestClient(make_test_app(), raise_server_exceptions=False)


# ── Status & Schema ────────────────────────────────────────────────────────────

class TestHealthSchema:
    def test_returns_200(self, client):
        assert client.get("/health").status_code == 200

    def test_has_status_field(self, client):
        assert "status" in client.get("/health").json()

    def test_has_version_field(self, client):
        assert "version" in client.get("/health").json()

    def test_has_name_field(self, client):
        assert "name" in client.get("/health").json()

    def test_has_uptime_seconds_field(self, client):
        data = client.get("/health").json()
        assert "uptime_seconds" in data
        assert isinstance(data["uptime_seconds"], (int, float))

    def test_has_timestamp_field(self, client):
        assert "timestamp" in client.get("/health").json()

    def test_has_modules_field(self, client):
        data = client.get("/health").json()
        assert "modules" in data
        assert isinstance(data["modules"], dict)

    def test_content_type_is_json(self, client):
        resp = client.get("/health")
        assert "application/json" in resp.headers["content-type"]


# ── Status value ──────────────────────────────────────────────────────────────

class TestHealthStatus:
    def test_status_is_string(self, client):
        data = client.get("/health").json()
        assert isinstance(data["status"], str)

    def test_status_is_known_value(self, client):
        data = client.get("/health").json()
        assert data["status"] in ("ok", "degraded", "error", "healthy", "unhealthy")

    def test_name_is_stone(self, client):
        data = client.get("/health").json()
        assert "默行者" in data["name"] or "STONE" in data["name"]


# ── Repeated calls ────────────────────────────────────────────────────────────

class TestHealthStability:
    def test_two_calls_return_same_schema(self, client):
        r1 = client.get("/health").json()
        r2 = client.get("/health").json()
        assert set(r1.keys()) == set(r2.keys())

    def test_uptime_non_negative(self, client):
        assert client.get("/health").json()["uptime_seconds"] >= 0
