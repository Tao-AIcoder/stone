"""
tests/test_blackbox_admin.py - Black-box tests for /api/admin/* endpoints.

Covers:
- GET  /api/admin/skills
- GET  /api/admin/tasks
- POST /api/admin/tasks
- DELETE /api/admin/tasks/{id}
- GET  /api/admin/audit
- GET  /api/admin/memory
- Auth enforcement across all endpoints

Rules:
- Only inspect HTTP status codes and response body.
- No knowledge of internal implementation.
"""

from __future__ import annotations

import sys
import os
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.conftest import make_test_app, make_mock_loader


@pytest.fixture
def loader():
    return make_mock_loader(whitelist=["admin_user"])


@pytest.fixture
def client(loader):
    return TestClient(make_test_app(loader=loader), raise_server_exceptions=False)


ADMIN = {"X-Open-Id": "admin_user", "X-Admin-Pin": "1234"}
NOBODY = {"X-Open-Id": "random_person"}

VALID_TASK = {
    "name": "daily_news",
    "cron_expr": "0 8 * * *",
    "action": "搜索今日头条并发给我",
}


# ── Auth: all endpoints must reject unauthenticated requests ──────────────────

class TestAuthEnforcement:
    ENDPOINTS = [
        ("GET",    "/api/admin/skills"),
        ("GET",    "/api/admin/tasks"),
        ("POST",   "/api/admin/tasks"),
        ("GET",    "/api/admin/audit"),
        ("GET",    "/api/admin/memory"),
    ]

    @pytest.mark.parametrize("method,path", ENDPOINTS)
    def test_no_headers_returns_403(self, client, method, path):
        resp = getattr(client, method.lower())(path)
        assert resp.status_code == 403

    @pytest.mark.parametrize("method,path", ENDPOINTS)
    def test_unknown_user_returns_403(self, client, method, path):
        resp = getattr(client, method.lower())(path, headers=NOBODY)
        assert resp.status_code == 403

    def test_wrong_pin_returns_403(self, client, loader):
        loader.auth.verify_pin = AsyncMock(return_value=False)
        resp = client.get(
            "/api/admin/skills",
            headers={"X-Open-Id": "admin_user", "X-Admin-Pin": "wrong"},
        )
        assert resp.status_code == 403


# ── GET /api/admin/skills ─────────────────────────────────────────────────────

class TestSkills:
    def test_returns_200(self, client):
        assert client.get("/api/admin/skills", headers=ADMIN).status_code == 200

    def test_response_has_skills_list(self, client):
        data = client.get("/api/admin/skills", headers=ADMIN).json()
        assert "skills" in data
        assert isinstance(data["skills"], list)

    def test_response_has_total(self, client):
        data = client.get("/api/admin/skills", headers=ADMIN).json()
        assert "total" in data
        assert data["total"] == len(data["skills"])

    def test_each_skill_has_name(self, client):
        data = client.get("/api/admin/skills", headers=ADMIN).json()
        for skill in data["skills"]:
            assert "name" in skill, f"skill missing 'name': {skill}"

    def test_each_skill_has_description(self, client):
        data = client.get("/api/admin/skills", headers=ADMIN).json()
        for skill in data["skills"]:
            assert "description" in skill

    def test_each_skill_has_enabled_flag(self, client):
        data = client.get("/api/admin/skills", headers=ADMIN).json()
        for skill in data["skills"]:
            assert "enabled" in skill
            assert isinstance(skill["enabled"], bool)

    def test_file_tool_is_present(self, client):
        data = client.get("/api/admin/skills", headers=ADMIN).json()
        names = [s["name"] for s in data["skills"]]
        assert "file_tool" in names


# ── GET /api/admin/tasks ──────────────────────────────────────────────────────

class TestTaskList:
    def test_returns_200(self, client):
        assert client.get("/api/admin/tasks", headers=ADMIN).status_code == 200

    def test_response_has_tasks_list(self, client):
        data = client.get("/api/admin/tasks", headers=ADMIN).json()
        assert "tasks" in data
        assert isinstance(data["tasks"], list)

    def test_response_has_total(self, client):
        data = client.get("/api/admin/tasks", headers=ADMIN).json()
        assert "total" in data

    def test_empty_when_no_tasks(self, client):
        data = client.get("/api/admin/tasks", headers=ADMIN).json()
        assert data["total"] == 0
        assert data["tasks"] == []

    def test_with_tasks_returns_correct_count(self, client, loader):
        mock_task = MagicMock()
        mock_task.task_id = "t1"
        mock_task.name = "test"
        mock_task.cron_expr = "* * * * *"
        mock_task.action = "do it"
        mock_task.enabled = True
        loader.scheduler.list_tasks = MagicMock(return_value=[mock_task])

        data = client.get("/api/admin/tasks", headers=ADMIN).json()
        assert data["total"] == 1


# ── POST /api/admin/tasks ─────────────────────────────────────────────────────

class TestTaskCreate:
    def test_returns_200_or_201(self, client):
        resp = client.post("/api/admin/tasks", json=VALID_TASK, headers=ADMIN)
        assert resp.status_code in (200, 201)

    def test_response_has_task_id(self, client):
        data = client.post("/api/admin/tasks", json=VALID_TASK, headers=ADMIN).json()
        assert "task_id" in data
        assert data["task_id"]

    def test_response_has_name(self, client):
        data = client.post("/api/admin/tasks", json=VALID_TASK, headers=ADMIN).json()
        assert "name" in data

    def test_missing_name_returns_422(self, client):
        bad = {"cron_expr": "0 8 * * *", "action": "do it"}
        assert client.post("/api/admin/tasks", json=bad, headers=ADMIN).status_code == 422

    def test_missing_cron_returns_422(self, client):
        bad = {"name": "task", "action": "do it"}
        assert client.post("/api/admin/tasks", json=bad, headers=ADMIN).status_code == 422

    def test_missing_action_returns_422(self, client):
        bad = {"name": "task", "cron_expr": "0 8 * * *"}
        assert client.post("/api/admin/tasks", json=bad, headers=ADMIN).status_code == 422

    def test_empty_body_returns_422(self, client):
        assert client.post("/api/admin/tasks", json={}, headers=ADMIN).status_code == 422

    def test_different_cron_expressions(self, client):
        for cron in ["* * * * *", "0 0 * * 0", "30 9 1 * *"]:
            resp = client.post(
                "/api/admin/tasks",
                json={**VALID_TASK, "cron_expr": cron},
                headers=ADMIN,
            )
            assert resp.status_code in (200, 201), f"cron {cron!r} failed: {resp.status_code}"


# ── DELETE /api/admin/tasks/{id} ──────────────────────────────────────────────

class TestTaskDelete:
    def test_returns_200(self, client):
        resp = client.delete("/api/admin/tasks/task-001", headers=ADMIN)
        assert resp.status_code == 200

    def test_response_has_status_or_message(self, client):
        data = client.delete("/api/admin/tasks/task-001", headers=ADMIN).json()
        assert "status" in data or "message" in data or "task_id" in data

    def test_no_auth_returns_403(self, client):
        assert client.delete("/api/admin/tasks/task-001").status_code == 403


# ── GET /api/admin/audit ──────────────────────────────────────────────────────

class TestAuditLog:
    def test_returns_200(self, client):
        assert client.get("/api/admin/audit", headers=ADMIN).status_code == 200

    def test_response_has_logs_list(self, client):
        data = client.get("/api/admin/audit", headers=ADMIN).json()
        assert "logs" in data
        assert isinstance(data["logs"], list)

    def test_level_filter_accepted(self, client):
        for level in ("info", "warning", "critical"):
            resp = client.get(f"/api/admin/audit?level={level}", headers=ADMIN)
            assert resp.status_code == 200

    def test_limit_param_accepted(self, client):
        resp = client.get("/api/admin/audit?limit=5", headers=ADMIN)
        assert resp.status_code == 200

    def test_offset_param_accepted(self, client):
        resp = client.get("/api/admin/audit?offset=10", headers=ADMIN)
        assert resp.status_code == 200

    def test_combined_params_accepted(self, client):
        resp = client.get("/api/admin/audit?level=warning&limit=10&offset=0", headers=ADMIN)
        assert resp.status_code == 200

    def test_returns_log_entries_when_populated(self, client, loader):
        loader.sqlite_store.get_audit_logs = AsyncMock(return_value=[
            {"log_id": "1", "level": "info", "action": "chat_request",
             "user_id": "u1", "result": "success"},
        ])
        data = client.get("/api/admin/audit", headers=ADMIN).json()
        assert len(data["logs"]) == 1


# ── GET /api/admin/memory ─────────────────────────────────────────────────────

class TestMemory:
    def test_returns_200(self, client):
        assert client.get("/api/admin/memory", headers=ADMIN).status_code == 200

    def test_response_has_memories_list(self, client):
        data = client.get("/api/admin/memory", headers=ADMIN).json()
        assert "memories" in data
        assert isinstance(data["memories"], list)

    def test_user_id_filter_accepted(self, client):
        resp = client.get("/api/admin/memory?user_id=default_user", headers=ADMIN)
        assert resp.status_code == 200

    def test_category_filter_accepted(self, client):
        resp = client.get("/api/admin/memory?category=preference", headers=ADMIN)
        assert resp.status_code == 200

    def test_limit_param_accepted(self, client):
        resp = client.get("/api/admin/memory?limit=10", headers=ADMIN)
        assert resp.status_code == 200

    def test_returns_memory_entries_when_populated(self, client, loader):
        from datetime import datetime
        m = MagicMock()
        m.memory_id = "m1"
        m.category = MagicMock()
        m.category.value = "preference"
        m.content = "喜欢简洁"
        m.confidence = 1.0
        m.tags = []
        m.created_at = datetime.utcnow()
        m.access_count = 0
        loader.sqlite_store.get_memories = AsyncMock(return_value=[m])
        data = client.get("/api/admin/memory", headers=ADMIN).json()
        assert len(data["memories"]) == 1
