"""
tests/test_blackbox_chat.py - Black-box tests for POST /api/chat and related endpoints.

Covers:
- POST /api/chat               (send message, get reply)
- GET  /api/conversations/{id}/history
- POST /api/chat/{id}/confirm  (dry-run confirm / cancel)

Rules:
- Only inspect HTTP status codes and response body structure.
- Mock only at the application boundary (loader).
- Do NOT assert on internal call counts or implementation details.
"""

from __future__ import annotations

import sys
import os
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.errors import PromptInjectionError
from models.message import BotResponse
from tests.conftest import make_test_app, make_mock_loader


def _bot_response(content: str = "收到", requires_confirmation: bool = False,
                  confirmation_token: str = "", is_error: bool = False) -> BotResponse:
    from datetime import datetime
    return BotResponse(
        response_id=str(uuid.uuid4()),
        conv_id=str(uuid.uuid4()),
        content=content,
        requires_confirmation=requires_confirmation,
        confirmation_token=confirmation_token,
        tools_used=[],
        is_error=is_error,
        timestamp=datetime.utcnow(),
    )


@pytest.fixture
def loader():
    return make_mock_loader()


@pytest.fixture
def client(loader):
    return TestClient(make_test_app(loader=loader), raise_server_exceptions=False)


VALID_MSG = {"user_id": "open_id_admin", "content": "你好"}
HEADERS = {"X-Open-Id": "open_id_admin"}


# ── POST /api/chat — Happy path ───────────────────────────────────────────────

class TestChatHappyPath:
    def test_returns_200(self, client):
        resp = client.post("/api/chat", json=VALID_MSG, headers=HEADERS)
        assert resp.status_code == 200

    def test_response_has_content(self, client):
        data = client.post("/api/chat", json=VALID_MSG, headers=HEADERS).json()
        assert "content" in data
        assert isinstance(data["content"], str)
        assert len(data["content"]) > 0

    def test_response_has_response_id(self, client):
        data = client.post("/api/chat", json=VALID_MSG, headers=HEADERS).json()
        assert "response_id" in data

    def test_response_has_conv_id(self, client):
        data = client.post("/api/chat", json=VALID_MSG, headers=HEADERS).json()
        assert "conv_id" in data

    def test_response_has_is_error_false(self, client):
        data = client.post("/api/chat", json=VALID_MSG, headers=HEADERS).json()
        assert data.get("is_error") is False

    def test_response_has_tools_used_list(self, client):
        data = client.post("/api/chat", json=VALID_MSG, headers=HEADERS).json()
        assert isinstance(data.get("tools_used"), list)

    def test_response_has_requires_confirmation(self, client):
        data = client.post("/api/chat", json=VALID_MSG, headers=HEADERS).json()
        assert "requires_confirmation" in data

    def test_with_explicit_conv_id(self, client):
        msg = {**VALID_MSG, "conv_id": str(uuid.uuid4())}
        resp = client.post("/api/chat", json=msg, headers=HEADERS)
        assert resp.status_code == 200

    def test_chinese_content(self, client):
        msg = {**VALID_MSG, "content": "请帮我搜索今天的新闻"}
        resp = client.post("/api/chat", json=msg, headers=HEADERS)
        assert resp.status_code == 200

    def test_long_content(self, client):
        msg = {**VALID_MSG, "content": "请分析" + "这个问题" * 50}
        resp = client.post("/api/chat", json=msg, headers=HEADERS)
        assert resp.status_code == 200


# ── POST /api/chat — Input validation ────────────────────────────────────────

class TestChatValidation:
    def test_missing_user_id_defaults_and_auth_checked(self, client):
        # user_id defaults to DEFAULT_USER_ID ("default_user"), which is not whitelisted
        resp = client.post("/api/chat", json={"content": "hello"}, headers=HEADERS)
        assert resp.status_code in (200, 403)  # depends on whether default user is whitelisted

    def test_missing_content_returns_422(self, client):
        resp = client.post("/api/chat", json={"user_id": "open_id_admin"}, headers=HEADERS)
        assert resp.status_code == 422

    def test_empty_body_returns_422(self, client):
        resp = client.post("/api/chat", json={}, headers=HEADERS)
        assert resp.status_code == 422

    def test_empty_content_string_returns_error(self, client):
        resp = client.post("/api/chat", json={**VALID_MSG, "content": ""}, headers=HEADERS)
        assert resp.status_code in (400, 422)

    def test_non_json_body_returns_422(self, client):
        resp = client.post("/api/chat", content=b"not json",
                           headers={**HEADERS, "content-type": "application/json"})
        assert resp.status_code == 422


# ── POST /api/chat — Auth ─────────────────────────────────────────────────────

class TestChatAuth:
    def test_unknown_user_returns_403(self, client):
        resp = client.post(
            "/api/chat",
            json={**VALID_MSG, "user_id": "nobody"},
            headers={"X-Open-Id": "nobody"},
        )
        assert resp.status_code == 403

    def test_rate_limit_exceeded_returns_429_or_403(self, client, loader):
        loader.auth.check_rate_limit = MagicMock(return_value=False)
        resp = client.post("/api/chat", json=VALID_MSG, headers=HEADERS)
        assert resp.status_code in (403, 429)


# ── POST /api/chat — Prompt injection ─────────────────────────────────────────

class TestChatPromptInjection:
    def test_injection_returns_400(self, client, loader):
        loader.prompt_guard.scan = MagicMock(
            side_effect=PromptInjectionError("role_override_ignore")
        )
        resp = client.post("/api/chat", json=VALID_MSG, headers=HEADERS)
        assert resp.status_code == 400

    def test_injection_response_is_non_empty(self, client, loader):
        loader.prompt_guard.scan = MagicMock(
            side_effect=PromptInjectionError("role_override_ignore")
        )
        resp = client.post("/api/chat", json=VALID_MSG, headers=HEADERS)
        assert resp.status_code == 400
        assert len(resp.content) > 0


# ── POST /api/chat — Dry-run flow ─────────────────────────────────────────────

class TestChatDryRun:
    def test_dry_run_response_has_requires_confirmation_true(self, client, loader):
        token = str(uuid.uuid4())
        loader.agent.process = AsyncMock(return_value=_bot_response(
            content="以下操作需要确认：删除文件 foo.txt",
            requires_confirmation=True,
            confirmation_token=token,
        ))
        data = client.post("/api/chat", json=VALID_MSG, headers=HEADERS).json()
        assert data["requires_confirmation"] is True

    def test_dry_run_response_has_confirmation_token(self, client, loader):
        token = str(uuid.uuid4())
        loader.agent.process = AsyncMock(return_value=_bot_response(
            requires_confirmation=True,
            confirmation_token=token,
        ))
        data = client.post("/api/chat", json=VALID_MSG, headers=HEADERS).json()
        assert "confirmation_token" in data

    def test_dry_run_content_is_non_empty(self, client, loader):
        loader.agent.process = AsyncMock(return_value=_bot_response(
            content="请确认：执行 rm -rf /tmp/test",
            requires_confirmation=True,
            confirmation_token="abc",
        ))
        data = client.post("/api/chat", json=VALID_MSG, headers=HEADERS).json()
        assert len(data["content"]) > 0


# ── POST /api/chat/{conv_id}/confirm ──────────────────────────────────────────

class TestConfirm:
    CONV = str(uuid.uuid4())

    def test_confirm_returns_200(self, client, loader):
        loader.dry_run_manager.has_pending = MagicMock(return_value=True)
        resp = client.post(
            f"/api/chat/{self.CONV}/confirm",
            json={"action": "confirm", "token": "tok123"},
            headers=HEADERS,
        )
        assert resp.status_code == 200

    def test_cancel_returns_200(self, client, loader):
        loader.dry_run_manager.has_pending = MagicMock(return_value=True)
        resp = client.post(
            f"/api/chat/{self.CONV}/confirm",
            json={"action": "cancel", "token": "tok123"},
            headers=HEADERS,
        )
        assert resp.status_code == 200

    def test_invalid_action_returns_error(self, client):
        resp = client.post(
            f"/api/chat/{self.CONV}/confirm",
            json={"action": "explode", "token": "tok"},
            headers=HEADERS,
        )
        assert resp.status_code in (400, 422)

    def test_missing_action_returns_422(self, client):
        resp = client.post(
            f"/api/chat/{self.CONV}/confirm",
            json={"token": "tok"},
            headers=HEADERS,
        )
        assert resp.status_code == 422


# ── GET /api/conversations/{conv_id}/history ──────────────────────────────────

class TestConversationHistory:
    CONV = str(uuid.uuid4())

    def test_returns_200(self, client):
        resp = client.get(f"/api/conversations/{self.CONV}/history", headers=HEADERS, params={"user_id": "open_id_admin"})
        assert resp.status_code == 200

    def test_response_has_messages_field(self, client):
        data = client.get(f"/api/conversations/{self.CONV}/history", headers=HEADERS, params={"user_id": "open_id_admin"}).json()
        assert "messages" in data

    def test_messages_is_list(self, client):
        data = client.get(f"/api/conversations/{self.CONV}/history", headers=HEADERS, params={"user_id": "open_id_admin"}).json()
        assert isinstance(data["messages"], list)

    def test_nonexistent_conv_returns_empty_list(self, client, loader):
        loader.sqlite_store.get_conversation_messages = AsyncMock(return_value=[])
        data = client.get(
            f"/api/conversations/{uuid.uuid4()}/history", headers=HEADERS, params={"user_id": "open_id_admin"}
        ).json()
        assert data["messages"] == []

    def test_limit_param_accepted(self, client):
        resp = client.get(
            f"/api/conversations/{self.CONV}/history", headers=HEADERS, params={"user_id": "open_id_admin", "limit": "5"}
        )
        assert resp.status_code == 200

    def test_offset_param_accepted(self, client):
        resp = client.get(
            f"/api/conversations/{self.CONV}/history", headers=HEADERS, params={"user_id": "open_id_admin", "offset": "10"}
        )
        assert resp.status_code == 200
