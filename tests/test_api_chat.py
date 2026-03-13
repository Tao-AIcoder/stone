"""
tests/test_api_chat.py - Tests for chat API endpoints.

Covers:
- POST /api/chat          (normal reply, dry-run, error paths)
- GET  /api/conversations/{conv_id}/history
- POST /api/chat/{conv_id}/confirm  (confirm / cancel dry-run)
"""

from __future__ import annotations

import sys
import os
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.message import BotResponse
from models.errors import StoneError
from tests.conftest import make_mock_loader, make_test_app


# ── Fixtures ───────────────────────────────────────────────────────────────────

def make_bot_response(**overrides) -> BotResponse:
    defaults = dict(
        response_id=str(uuid.uuid4()),
        conv_id=str(uuid.uuid4()),
        content="测试回复",
        requires_confirmation=False,
        confirmation_token="",
        tools_used=[],
        is_error=False,
        timestamp=datetime.utcnow(),
    )
    defaults.update(overrides)
    return BotResponse(**defaults)


@pytest.fixture
def loader() -> MagicMock:
    return make_mock_loader()


@pytest.fixture
def client(loader: MagicMock) -> TestClient:
    app = make_test_app(loader=loader)
    return TestClient(app, raise_server_exceptions=False)


# ── POST /api/chat ─────────────────────────────────────────────────────────────

class TestChatPost:
    def test_returns_200_on_normal_message(self, client: TestClient) -> None:
        resp = client.post("/api/chat", json={"content": "你好", "user_id": "open_id_admin"})
        assert resp.status_code == 200

    def test_response_has_required_fields(self, client: TestClient) -> None:
        resp = client.post("/api/chat", json={"content": "你好", "user_id": "open_id_admin"})
        data = resp.json()
        assert "response_id" in data
        assert "conv_id" in data
        assert "content" in data
        assert "requires_confirmation" in data
        assert "tools_used" in data
        assert "is_error" in data
        assert "timestamp" in data

    def test_content_is_string(self, client: TestClient) -> None:
        resp = client.post("/api/chat", json={"content": "测试内容", "user_id": "open_id_admin"})
        data = resp.json()
        assert isinstance(data["content"], str)

    def test_is_error_false_on_success(self, client: TestClient) -> None:
        resp = client.post("/api/chat", json={"content": "你好", "user_id": "open_id_admin"})
        assert resp.json()["is_error"] is False

    def test_tools_used_is_list(self, client: TestClient) -> None:
        resp = client.post("/api/chat", json={"content": "你好", "user_id": "open_id_admin"})
        assert isinstance(resp.json()["tools_used"], list)

    def test_custom_user_id_not_whitelisted_returns_403(self, client: TestClient) -> None:
        resp = client.post("/api/chat", json={"content": "你好", "user_id": "user_42"})
        assert resp.status_code == 403

    def test_custom_conv_id_accepted(self, client: TestClient) -> None:
        conv_id = str(uuid.uuid4())
        resp = client.post("/api/chat", json={"content": "继续", "conv_id": conv_id, "user_id": "open_id_admin"})
        assert resp.status_code == 200

    def test_task_type_code_accepted(self, client: TestClient) -> None:
        resp = client.post("/api/chat", json={"content": "写个函数", "task_type": "code", "user_id": "open_id_admin"})
        assert resp.status_code == 200

    def test_privacy_sensitive_flag_accepted(self, client: TestClient) -> None:
        resp = client.post("/api/chat", json={"content": "敏感信息", "privacy_sensitive": True, "user_id": "open_id_admin"})
        assert resp.status_code == 200

    def test_missing_content_returns_422(self, client: TestClient) -> None:
        resp = client.post("/api/chat", json={})
        assert resp.status_code == 422

    def test_empty_content_returns_422(self, client: TestClient) -> None:
        """Empty string fails validation — agent requires non-empty input."""
        resp = client.post("/api/chat", json={"content": "", "user_id": "open_id_admin"})
        assert resp.status_code == 422

    def test_agent_process_is_called(self, client: TestClient, loader: MagicMock) -> None:
        client.post("/api/chat", json={"content": "触发Agent", "user_id": "open_id_admin"})
        loader.agent.process.assert_called_once()

    def test_agent_called_with_correct_content(self, client: TestClient, loader: MagicMock) -> None:
        client.post("/api/chat", json={"content": "测试消息内容", "user_id": "open_id_admin"})
        call_args = loader.agent.process.call_args
        msg = call_args[0][0]  # first positional arg
        assert msg.content == "测试消息内容"

    def test_agent_exception_returns_400(self, client: TestClient, loader: MagicMock) -> None:
        loader.agent.process = AsyncMock(
            side_effect=StoneError("测试错误", code="TEST_ERR")
        )
        resp = client.post("/api/chat", json={"content": "触发错误", "user_id": "open_id_admin"})
        assert resp.status_code == 400

    def test_agent_unexpected_exception_returns_500(self, client: TestClient, loader: MagicMock) -> None:
        loader.agent.process = AsyncMock(side_effect=RuntimeError("crash"))
        resp = client.post("/api/chat", json={"content": "崩溃", "user_id": "open_id_admin"})
        assert resp.status_code == 500


class TestChatDryRun:
    """Test dry-run response flow."""

    def test_dry_run_response_has_requires_confirmation_true(
        self, loader: MagicMock
    ) -> None:
        conv_id = str(uuid.uuid4())
        dry_run_resp = make_bot_response(
            conv_id=conv_id,
            content="【执行计划预览】删除文件...",
            requires_confirmation=True,
            confirmation_token=conv_id,
        )
        loader.agent.process = AsyncMock(return_value=dry_run_resp)

        app = make_test_app(loader=loader)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post("/api/chat", json={"content": "删除 /tmp/test", "user_id": "open_id_admin"})
        data = resp.json()
        assert data["requires_confirmation"] is True
        assert data["confirmation_token"] != ""

    def test_dry_run_confirmation_token_is_conv_id(self, loader: MagicMock) -> None:
        conv_id = str(uuid.uuid4())
        dry_run_resp = make_bot_response(
            conv_id=conv_id,
            requires_confirmation=True,
            confirmation_token=conv_id,
        )
        loader.agent.process = AsyncMock(return_value=dry_run_resp)

        app = make_test_app(loader=loader)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post("/api/chat", json={"content": "危险操作", "user_id": "open_id_admin"})
        data = resp.json()
        assert data["confirmation_token"] == data["conv_id"]


# ── GET /api/conversations/{conv_id}/history ──────────────────────────────────

class TestConversationHistory:
    def test_returns_200(self, client: TestClient) -> None:
        conv_id = str(uuid.uuid4())
        resp = client.get(f"/api/conversations/{conv_id}/history")
        assert resp.status_code == 200

    def test_response_has_conv_id(self, client: TestClient) -> None:
        conv_id = str(uuid.uuid4())
        data = client.get(f"/api/conversations/{conv_id}/history").json()
        assert data["conv_id"] == conv_id

    def test_response_has_messages_list(self, client: TestClient) -> None:
        conv_id = str(uuid.uuid4())
        data = client.get(f"/api/conversations/{conv_id}/history").json()
        assert "messages" in data
        assert isinstance(data["messages"], list)

    def test_response_has_total_field(self, client: TestClient) -> None:
        conv_id = str(uuid.uuid4())
        data = client.get(f"/api/conversations/{conv_id}/history").json()
        assert "total" in data
        assert isinstance(data["total"], int)

    def test_empty_history_returns_zero_total(self, client: TestClient) -> None:
        conv_id = str(uuid.uuid4())
        data = client.get(f"/api/conversations/{conv_id}/history").json()
        assert data["total"] == 0
        assert data["messages"] == []

    def test_limit_param_accepted(self, client: TestClient) -> None:
        conv_id = str(uuid.uuid4())
        resp = client.get(f"/api/conversations/{conv_id}/history?limit=10")
        assert resp.status_code == 200

    def test_offset_param_accepted(self, client: TestClient) -> None:
        conv_id = str(uuid.uuid4())
        resp = client.get(f"/api/conversations/{conv_id}/history?offset=5")
        assert resp.status_code == 200

    def test_sqlite_error_returns_500(self, loader: MagicMock) -> None:
        loader.sqlite_store.get_conversation_messages = AsyncMock(
            side_effect=Exception("db error")
        )
        app = make_test_app(loader=loader)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(f"/api/conversations/{uuid.uuid4()}/history")
        assert resp.status_code == 500


# ── POST /api/chat/{conv_id}/confirm ──────────────────────────────────────────

class TestDryRunConfirm:
    @pytest.fixture
    def pending_client(self, loader: MagicMock) -> TestClient:
        """Client with a pending dry-run in progress."""
        loader.dry_run_manager.has_pending = MagicMock(return_value=True)
        app = make_test_app(loader=loader)
        return TestClient(app, raise_server_exceptions=False)

    def test_confirm_returns_200(self, pending_client: TestClient) -> None:
        conv_id = str(uuid.uuid4())
        resp = pending_client.post(
            f"/api/chat/{conv_id}/confirm",
            json={"action": "confirm"},
        )
        assert resp.status_code == 200

    def test_confirm_response_has_status_confirmed(self, pending_client: TestClient) -> None:
        conv_id = str(uuid.uuid4())
        data = pending_client.post(
            f"/api/chat/{conv_id}/confirm",
            json={"action": "confirm"},
        ).json()
        assert data["status"] == "confirmed"
        assert data["conv_id"] == conv_id

    def test_cancel_returns_200(self, pending_client: TestClient) -> None:
        conv_id = str(uuid.uuid4())
        resp = pending_client.post(
            f"/api/chat/{conv_id}/confirm",
            json={"action": "cancel"},
        )
        assert resp.status_code == 200

    def test_cancel_response_has_status_cancelled(self, pending_client: TestClient) -> None:
        conv_id = str(uuid.uuid4())
        data = pending_client.post(
            f"/api/chat/{conv_id}/confirm",
            json={"action": "cancel"},
        ).json()
        assert data["status"] == "cancelled"

    def test_invalid_action_returns_400(self, pending_client: TestClient) -> None:
        conv_id = str(uuid.uuid4())
        resp = pending_client.post(
            f"/api/chat/{conv_id}/confirm",
            json={"action": "delete"},
        )
        assert resp.status_code == 400

    def test_no_pending_dry_run_returns_404(self, client: TestClient) -> None:
        """has_pending returns False → 404."""
        conv_id = str(uuid.uuid4())
        resp = client.post(
            f"/api/chat/{conv_id}/confirm",
            json={"action": "confirm"},
        )
        assert resp.status_code == 404

    def test_confirm_calls_dry_run_manager(
        self, pending_client: TestClient, loader: MagicMock
    ) -> None:
        conv_id = str(uuid.uuid4())
        pending_client.post(
            f"/api/chat/{conv_id}/confirm",
            json={"action": "confirm"},
        )
        loader.dry_run_manager.confirm.assert_called_once()

    def test_cancel_calls_dry_run_manager(
        self, pending_client: TestClient, loader: MagicMock
    ) -> None:
        conv_id = str(uuid.uuid4())
        pending_client.post(
            f"/api/chat/{conv_id}/confirm",
            json={"action": "cancel"},
        )
        loader.dry_run_manager.cancel.assert_called_once()
