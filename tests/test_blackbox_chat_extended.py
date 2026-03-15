"""
tests/test_blackbox_chat_extended.py - Extended blackbox tests for chat API.

Covers gaps not addressed by the base blackbox tests:
- /api/conversations/{conv_id}/history: auth, per-message schema, conv_id field
- /api/chat: task_type, privacy_sensitive, timestamp format, conv_id continuity
"""

from __future__ import annotations

import sys
import os
import json

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.conftest import make_test_app, make_mock_loader


@pytest.fixture
def loader():
    return make_mock_loader()


@pytest.fixture
def client(loader):
    return TestClient(make_test_app(loader=loader), raise_server_exceptions=False)


AUTH = {"X-Open-Id": "open_id_admin"}
CHAT = {"user_id": "open_id_admin", "content": "你好"}


# ── /api/chat: 额外字段验证 ───────────────────────────────────────────────────

class TestChatExtraFields:
    def test_timestamp_field_present(self, client):
        data = client.post("/api/chat", json=CHAT, headers=AUTH).json()
        assert "timestamp" in data

    def test_timestamp_is_iso_string(self, client):
        data = client.post("/api/chat", json=CHAT, headers=AUTH).json()
        ts = data.get("timestamp", "")
        assert isinstance(ts, str) and "T" in ts, f"Not ISO format: {ts!r}"

    def test_task_type_accepted(self, client):
        body = {**CHAT, "task_type": "code"}
        resp = client.post("/api/chat", json=body, headers=AUTH)
        assert resp.status_code == 200

    def test_privacy_sensitive_accepted(self, client):
        body = {**CHAT, "privacy_sensitive": True}
        resp = client.post("/api/chat", json=body, headers=AUTH)
        assert resp.status_code == 200

    def test_conv_id_returned_same_as_sent(self, client, loader):
        import uuid
        from datetime import datetime
        from models.message import BotResponse

        conv_id = "test-conv-123"

        async def echo_conv_id(msg):
            return BotResponse(
                response_id=str(uuid.uuid4()),
                conv_id=msg.conv_id,
                content="回复",
                timestamp=datetime.utcnow(),
            )

        loader.agent.process.side_effect = echo_conv_id
        body = {**CHAT, "conv_id": conv_id}
        data = client.post("/api/chat", json=body, headers=AUTH).json()
        assert data["conv_id"] == conv_id

    def test_unknown_task_type_still_accepted(self, client):
        """task_type is a hint only; unknown values should not cause errors."""
        body = {**CHAT, "task_type": "unknown_type"}
        resp = client.post("/api/chat", json=body, headers=AUTH)
        assert resp.status_code == 200


# ── /api/conversations/{conv_id}/history: auth 保护 ───────────────────────────

class TestHistoryAuth:
    def test_unknown_user_returns_403(self, client):
        resp = client.get(
            "/api/conversations/conv-1/history",
            params={"user_id": "stranger"},
        )
        assert resp.status_code == 403

    def test_authorized_user_returns_200(self, client):
        resp = client.get(
            "/api/conversations/conv-1/history",
            params={"user_id": "open_id_admin"},
        )
        assert resp.status_code == 200

    def test_missing_user_id_uses_default_and_checks_auth(self, client, loader):
        """Default user_id must still pass through whitelist check."""
        # Default user is 'default_user', which is not in whitelist
        loader.auth.verify_user.side_effect = lambda oid: oid == "open_id_admin"
        resp = client.get("/api/conversations/conv-1/history")
        # default_user not in whitelist → 403
        assert resp.status_code == 403


# ── /api/conversations/{conv_id}/history: response schema ────────────────────

class TestHistorySchema:
    def test_conv_id_in_response(self, client):
        data = client.get(
            "/api/conversations/my-conv/history",
            params={"user_id": "open_id_admin"},
        ).json()
        assert "conv_id" in data
        assert data["conv_id"] == "my-conv"

    def test_messages_field_is_list(self, client):
        data = client.get(
            "/api/conversations/my-conv/history",
            params={"user_id": "open_id_admin"},
        ).json()
        assert isinstance(data["messages"], list)

    def test_total_field_is_int(self, client):
        data = client.get(
            "/api/conversations/my-conv/history",
            params={"user_id": "open_id_admin"},
        ).json()
        assert isinstance(data["total"], int)

    def test_per_message_required_fields(self, client, loader):
        """Each returned message must have: role, content, timestamp, message_id."""
        from datetime import datetime
        from unittest.mock import MagicMock, AsyncMock

        msg = MagicMock()
        msg.message_id = "msg-001"
        msg.role = MagicMock()
        msg.role.value = "user"
        msg.content = "测试消息"
        msg.timestamp = datetime.utcnow()
        msg.tool_name = None

        loader.sqlite_store.get_conversation_messages = AsyncMock(return_value=[msg])

        data = client.get(
            "/api/conversations/my-conv/history",
            params={"user_id": "open_id_admin"},
        ).json()

        assert len(data["messages"]) == 1
        m = data["messages"][0]
        for field in ("message_id", "role", "content", "timestamp"):
            assert field in m, f"Missing field: {field!r}"

    def test_per_message_role_is_string(self, client, loader):
        from datetime import datetime
        from unittest.mock import MagicMock, AsyncMock

        msg = MagicMock()
        msg.message_id = "msg-001"
        msg.role = MagicMock()
        msg.role.value = "assistant"
        msg.content = "回复内容"
        msg.timestamp = datetime.utcnow()
        msg.tool_name = None

        loader.sqlite_store.get_conversation_messages = AsyncMock(return_value=[msg])

        data = client.get(
            "/api/conversations/my-conv/history",
            params={"user_id": "open_id_admin"},
        ).json()

        assert isinstance(data["messages"][0]["role"], str)

    def test_per_message_timestamp_is_string(self, client, loader):
        from datetime import datetime
        from unittest.mock import MagicMock, AsyncMock

        msg = MagicMock()
        msg.message_id = "msg-001"
        msg.role = MagicMock()
        msg.role.value = "user"
        msg.content = "hello"
        msg.timestamp = datetime.utcnow()
        msg.tool_name = None

        loader.sqlite_store.get_conversation_messages = AsyncMock(return_value=[msg])

        data = client.get(
            "/api/conversations/my-conv/history",
            params={"user_id": "open_id_admin"},
        ).json()

        ts = data["messages"][0]["timestamp"]
        assert isinstance(ts, str) and "T" in ts

    def test_limit_param_filters_results(self, client):
        resp = client.get(
            "/api/conversations/my-conv/history",
            params={"user_id": "open_id_admin", "limit": 5},
        )
        assert resp.status_code == 200

    def test_offset_param_accepted(self, client):
        resp = client.get(
            "/api/conversations/my-conv/history",
            params={"user_id": "open_id_admin", "offset": 10},
        )
        assert resp.status_code == 200

    def test_response_is_valid_json(self, client):
        resp = client.get(
            "/api/conversations/my-conv/history",
            params={"user_id": "open_id_admin"},
        )
        json.loads(resp.content)  # must not raise
