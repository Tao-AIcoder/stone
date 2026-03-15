"""
tests/test_blackbox_contracts.py - API contract tests.

Verifies that the API surface is stable:
- Required fields are always present
- Field types never change
- Optional query params don't break endpoints
- Response bodies are valid JSON in all cases
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
def client():
    return TestClient(make_test_app(), raise_server_exceptions=False)


ADMIN = {"X-Open-Id": "open_id_admin", "X-Admin-Pin": "1234"}
USER  = {"X-Open-Id": "open_id_admin"}
CHAT  = {"user_id": "open_id_admin", "content": "ping"}


# ── GET /health contract ──────────────────────────────────────────────────────

HEALTH_REQUIRED = {"status", "version", "name", "uptime_seconds", "timestamp", "modules"}

class TestHealthContract:
    def test_all_required_fields_present(self, client):
        data = client.get("/health").json()
        missing = HEALTH_REQUIRED - set(data.keys())
        assert not missing, f"Missing fields: {missing}"

    def test_uptime_seconds_is_numeric(self, client):
        assert isinstance(client.get("/health").json()["uptime_seconds"], (int, float))

    def test_modules_is_dict(self, client):
        assert isinstance(client.get("/health").json()["modules"], dict)

    def test_version_is_string(self, client):
        assert isinstance(client.get("/health").json()["version"], str)

    def test_response_is_valid_json(self, client):
        resp = client.get("/health")
        json.loads(resp.content)  # must not raise


# ── POST /api/chat contract ───────────────────────────────────────────────────

CHAT_REQUIRED = {"response_id", "conv_id", "content", "requires_confirmation",
                 "is_error", "tools_used"}

class TestChatContract:
    def test_all_required_fields_present(self, client):
        data = client.post("/api/chat", json=CHAT, headers=USER).json()
        missing = CHAT_REQUIRED - set(data.keys())
        assert not missing, f"Missing fields: {missing}"

    def test_response_id_is_string(self, client):
        data = client.post("/api/chat", json=CHAT, headers=USER).json()
        assert isinstance(data["response_id"], str)

    def test_conv_id_is_string(self, client):
        data = client.post("/api/chat", json=CHAT, headers=USER).json()
        assert isinstance(data["conv_id"], str)

    def test_content_is_string(self, client):
        data = client.post("/api/chat", json=CHAT, headers=USER).json()
        assert isinstance(data["content"], str)

    def test_requires_confirmation_is_bool(self, client):
        data = client.post("/api/chat", json=CHAT, headers=USER).json()
        assert isinstance(data["requires_confirmation"], bool)

    def test_is_error_is_bool(self, client):
        data = client.post("/api/chat", json=CHAT, headers=USER).json()
        assert isinstance(data["is_error"], bool)

    def test_tools_used_is_list(self, client):
        data = client.post("/api/chat", json=CHAT, headers=USER).json()
        assert isinstance(data["tools_used"], list)

    def test_response_is_valid_json(self, client):
        resp = client.post("/api/chat", json=CHAT, headers=USER)
        json.loads(resp.content)


# ── GET /api/admin/skills contract ───────────────────────────────────────────

SKILL_REQUIRED = {"name", "description", "category", "enabled"}

class TestSkillsContract:
    def test_skills_and_total_present(self, client):
        data = client.get("/api/admin/skills", headers=ADMIN).json()
        assert "skills" in data and "total" in data

    def test_total_equals_len_skills(self, client):
        data = client.get("/api/admin/skills", headers=ADMIN).json()
        assert data["total"] == len(data["skills"])

    def test_each_skill_has_required_fields(self, client):
        data = client.get("/api/admin/skills", headers=ADMIN).json()
        for skill in data["skills"]:
            missing = SKILL_REQUIRED - set(skill.keys())
            assert not missing, f"Skill {skill.get('name')} missing: {missing}"

    def test_enabled_is_bool_for_all_skills(self, client):
        data = client.get("/api/admin/skills", headers=ADMIN).json()
        for skill in data["skills"]:
            assert isinstance(skill["enabled"], bool)


# ── GET /api/admin/tasks contract ─────────────────────────────────────────────

class TestTasksContract:
    def test_tasks_and_total_present(self, client):
        data = client.get("/api/admin/tasks", headers=ADMIN).json()
        assert "tasks" in data and "total" in data

    def test_total_is_integer(self, client):
        assert isinstance(client.get("/api/admin/tasks", headers=ADMIN).json()["total"], int)


# ── POST /api/admin/tasks contract ───────────────────────────────────────────

class TestTaskCreateContract:
    def test_task_id_present(self, client):
        data = client.post("/api/admin/tasks", json={
            "name": "t", "cron_expr": "* * * * *", "action": "a"
        }, headers=ADMIN).json()
        assert "task_id" in data

    def test_task_id_is_non_empty_string(self, client):
        data = client.post("/api/admin/tasks", json={
            "name": "t", "cron_expr": "* * * * *", "action": "a"
        }, headers=ADMIN).json()
        assert isinstance(data["task_id"], str)
        assert len(data["task_id"]) > 0


# ── GET /api/admin/audit contract ────────────────────────────────────────────

class TestAuditContract:
    def test_logs_field_present(self, client):
        data = client.get("/api/admin/audit", headers=ADMIN).json()
        assert "logs" in data

    def test_logs_is_list(self, client):
        assert isinstance(client.get("/api/admin/audit", headers=ADMIN).json()["logs"], list)


# ── GET /api/admin/memory contract ───────────────────────────────────────────

class TestMemoryContract:
    def test_memories_field_present(self, client):
        data = client.get("/api/admin/memory", headers=ADMIN).json()
        assert "memories" in data

    def test_memories_is_list(self, client):
        assert isinstance(
            client.get("/api/admin/memory", headers=ADMIN).json()["memories"], list
        )


# ── GET /api/conversations/{id}/history contract ─────────────────────────────

class TestHistoryContract:
    def test_messages_field_present(self, client):
        data = client.get("/api/conversations/any-id/history", headers=USER, params={"user_id": "open_id_admin"}).json()
        assert "messages" in data

    def test_messages_is_list(self, client):
        assert isinstance(
            client.get("/api/conversations/any-id/history", headers=USER, params={"user_id": "open_id_admin"}).json()["messages"],
            list
        )
