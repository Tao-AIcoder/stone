"""
tests/test_blackbox_error_handling.py - Black-box tests for error responses.

Verifies that the API returns consistent, well-formed error responses
across all failure modes, without exposing internal stack traces.
"""

from __future__ import annotations

import sys
import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.errors import (
    AuthError, PromptInjectionError, StoneError,
    ModelError, ToolError, SandboxError,
)
from tests.conftest import make_test_app, make_mock_loader


@pytest.fixture
def loader():
    return make_mock_loader()


@pytest.fixture
def client(loader):
    return TestClient(make_test_app(loader=loader), raise_server_exceptions=False)


HEADERS = {"X-Open-Id": "open_id_admin"}
VALID_MSG = {"user_id": "open_id_admin", "content": "hello"}


# ── Error response shape ───────────────────────────────────────────────────────

class TestErrorShape:
    """Every error response must be JSON with at least one of error/message."""

    def test_403_is_json(self, client):
        resp = client.post("/api/chat", json=VALID_MSG)
        assert "application/json" in resp.headers.get("content-type", "")

    def test_422_is_json(self, client):
        resp = client.post("/api/chat", json={}, headers=HEADERS)
        assert "application/json" in resp.headers.get("content-type", "")

    def test_400_is_json_on_injection(self, client, loader):
        loader.prompt_guard.scan = MagicMock(
            side_effect=PromptInjectionError("role_override")
        )
        resp = client.post("/api/chat", json=VALID_MSG, headers=HEADERS)
        assert "application/json" in resp.headers.get("content-type", "")

    def test_error_body_has_error_or_message_key(self, client):
        data = client.post("/api/chat", json={}, headers=HEADERS).json()
        assert "error" in data or "message" in data or "detail" in data

    def test_no_stack_trace_in_error_response(self, client):
        data = client.post("/api/chat", json={}, headers=HEADERS).json()
        body = str(data)
        assert "Traceback" not in body
        assert "File \"/" not in body


# ── Agent errors surface cleanly ──────────────────────────────────────────────

class TestAgentErrors:
    def test_model_error_returns_error_response(self, client, loader):
        loader.agent.process = AsyncMock(
            side_effect=ModelError("LLM unavailable")
        )
        resp = client.post("/api/chat", json=VALID_MSG, headers=HEADERS)
        assert resp.status_code in (400, 500, 503)

    def test_tool_error_returns_error_response(self, client, loader):
        loader.agent.process = AsyncMock(
            side_effect=ToolError("file not found")
        )
        resp = client.post("/api/chat", json=VALID_MSG, headers=HEADERS)
        assert resp.status_code in (400, 500)

    def test_generic_stone_error_returns_400(self, client, loader):
        loader.agent.process = AsyncMock(
            side_effect=StoneError("generic error")
        )
        resp = client.post("/api/chat", json=VALID_MSG, headers=HEADERS)
        assert resp.status_code in (400, 500)

    def test_agent_error_response_is_not_empty(self, client, loader):
        loader.agent.process = AsyncMock(
            side_effect=StoneError("boom")
        )
        resp = client.post("/api/chat", json=VALID_MSG, headers=HEADERS)
        assert len(resp.content) > 0


# ── HTTP method errors ────────────────────────────────────────────────────────

class TestMethodErrors:
    def test_get_on_chat_returns_405(self, client):
        resp = client.get("/api/chat", headers=HEADERS)
        assert resp.status_code == 405

    def test_put_on_chat_returns_405(self, client):
        resp = client.put("/api/chat", json=VALID_MSG, headers=HEADERS)
        assert resp.status_code == 405

    def test_post_on_health_returns_405(self, client):
        resp = client.post("/health")
        assert resp.status_code == 405


# ── Non-existent routes ───────────────────────────────────────────────────────

class TestNotFound:
    def test_unknown_route_returns_404(self, client):
        assert client.get("/api/nonexistent").status_code == 404

    def test_unknown_admin_route_returns_404(self, client):
        assert client.get("/api/admin/nonexistent", headers={
            "X-Open-Id": "open_id_admin"
        }).status_code == 404


# ── Idempotency ───────────────────────────────────────────────────────────────

class TestIdempotency:
    def test_health_always_same_schema(self, client):
        """Health endpoint must be safe to call repeatedly."""
        schemas = [set(client.get("/health").json().keys()) for _ in range(3)]
        assert all(s == schemas[0] for s in schemas)

    def test_duplicate_chat_requests_both_succeed(self, client):
        r1 = client.post("/api/chat", json=VALID_MSG, headers=HEADERS)
        r2 = client.post("/api/chat", json=VALID_MSG, headers=HEADERS)
        assert r1.status_code == 200
        assert r2.status_code == 200
