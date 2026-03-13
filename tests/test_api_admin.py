"""
tests/test_api_admin.py - Tests for admin API endpoints.

Covers:
- GET  /api/admin/skills      (list registered tools)
- GET  /api/admin/tasks       (list scheduled tasks)
- POST /api/admin/tasks       (create task)
- PUT  /api/admin/tasks/{id}  (update task)
- DELETE /api/admin/tasks/{id}
- GET  /api/admin/audit       (audit log)
- GET  /api/admin/memory      (long-term memory)
- Auth enforcement (whitelist, PIN)
"""

from __future__ import annotations

import sys
import os
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.errors import StoneError
from tests.conftest import make_mock_loader, make_test_app


# ── Fixtures ───────────────────────────────────────────────────────────────────

ADMIN_OPEN_ID = "open_id_admin"
NON_ADMIN_OPEN_ID = "open_id_nobody"

ADMIN_HEADERS = {
    "X-Open-Id": ADMIN_OPEN_ID,
    "X-Admin-Pin": "correct_pin",
}


@pytest.fixture
def loader() -> MagicMock:
    ldr = make_mock_loader(whitelist=[ADMIN_OPEN_ID])
    return ldr


@pytest.fixture
def client(loader: MagicMock) -> TestClient:
    app = make_test_app(loader=loader)
    return TestClient(app, raise_server_exceptions=False)


# ── Auth Enforcement ───────────────────────────────────────────────────────────

class TestAdminAuth:
    def test_no_headers_returns_403(self, client: TestClient) -> None:
        resp = client.get("/api/admin/skills")
        assert resp.status_code == 403

    def test_unknown_open_id_returns_403(self, client: TestClient) -> None:
        resp = client.get(
            "/api/admin/skills",
            headers={"X-Open-Id": NON_ADMIN_OPEN_ID},
        )
        assert resp.status_code == 403

    def test_whitelisted_user_without_pin_gets_skills(self, client: TestClient) -> None:
        """Whitelist verification alone (no PIN required for GET /skills)."""
        resp = client.get(
            "/api/admin/skills",
            headers={"X-Open-Id": ADMIN_OPEN_ID},
        )
        assert resp.status_code == 200

    def test_whitelisted_user_with_correct_pin_gets_skills(self, client: TestClient) -> None:
        resp = client.get("/api/admin/skills", headers=ADMIN_HEADERS)
        assert resp.status_code == 200

    def test_wrong_pin_returns_403(self, client: TestClient, loader: MagicMock) -> None:
        loader.auth.verify_pin = AsyncMock(return_value=False)
        resp = client.get(
            "/api/admin/skills",
            headers={"X-Open-Id": ADMIN_OPEN_ID, "X-Admin-Pin": "wrong"},
        )
        assert resp.status_code == 403


# ── GET /api/admin/skills ──────────────────────────────────────────────────────

class TestAdminSkills:
    def test_returns_200(self, client: TestClient) -> None:
        resp = client.get("/api/admin/skills", headers=ADMIN_HEADERS)
        assert resp.status_code == 200

    def test_response_has_skills_list(self, client: TestClient) -> None:
        data = client.get("/api/admin/skills", headers=ADMIN_HEADERS).json()
        assert "skills" in data
        assert isinstance(data["skills"], list)

    def test_skills_list_has_file_tool(self, client: TestClient) -> None:
        data = client.get("/api/admin/skills", headers=ADMIN_HEADERS).json()
        skill_names = [s["name"] for s in data["skills"]]
        assert "file_tool" in skill_names

    def test_skill_has_required_fields(self, client: TestClient) -> None:
        data = client.get("/api/admin/skills", headers=ADMIN_HEADERS).json()
        if data["skills"]:
            skill = data["skills"][0]
            assert "name" in skill
            assert "description" in skill
            assert "category" in skill
            assert "enabled" in skill

    def test_response_has_total_field(self, client: TestClient) -> None:
        data = client.get("/api/admin/skills", headers=ADMIN_HEADERS).json()
        assert "total" in data
        assert isinstance(data["total"], int)


# ── GET /api/admin/tasks ───────────────────────────────────────────────────────

class TestAdminTasksList:
    def test_returns_200(self, client: TestClient) -> None:
        resp = client.get("/api/admin/tasks", headers=ADMIN_HEADERS)
        assert resp.status_code == 200

    def test_response_has_tasks_list(self, client: TestClient) -> None:
        data = client.get("/api/admin/tasks", headers=ADMIN_HEADERS).json()
        assert "tasks" in data
        assert isinstance(data["tasks"], list)

    def test_empty_tasks_returns_zero_total(self, client: TestClient) -> None:
        data = client.get("/api/admin/tasks", headers=ADMIN_HEADERS).json()
        assert data.get("total", 0) == 0

    def test_requires_auth(self, client: TestClient) -> None:
        resp = client.get("/api/admin/tasks")
        assert resp.status_code == 403


# ── POST /api/admin/tasks ──────────────────────────────────────────────────────

class TestAdminTaskCreate:
    VALID_TASK = {
        "name": "daily_news",
        "cron_expr": "0 8 * * *",
        "action": "每天早上8点总结今日新闻",
    }

    def test_create_task_returns_201_or_200(self, client: TestClient) -> None:
        resp = client.post(
            "/api/admin/tasks",
            json=self.VALID_TASK,
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code in (200, 201)

    def test_create_task_response_has_task_id(self, client: TestClient) -> None:
        resp = client.post(
            "/api/admin/tasks",
            json=self.VALID_TASK,
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert "task_id" in data

    def test_create_task_missing_name_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/admin/tasks",
            json={"cron_expr": "0 8 * * *", "action": "action"},
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 422

    def test_create_task_missing_cron_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/admin/tasks",
            json={"name": "task", "action": "action"},
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 422

    def test_create_task_calls_scheduler(self, client: TestClient, loader: MagicMock) -> None:
        client.post(
            "/api/admin/tasks",
            json=self.VALID_TASK,
            headers=ADMIN_HEADERS,
        )
        loader.scheduler.add_task.assert_called_once()

    def test_create_task_requires_auth(self, client: TestClient) -> None:
        resp = client.post("/api/admin/tasks", json=self.VALID_TASK)
        assert resp.status_code == 403


# ── DELETE /api/admin/tasks/{id} ──────────────────────────────────────────────

class TestAdminTaskDelete:
    def test_delete_task_returns_200(self, client: TestClient) -> None:
        resp = client.delete("/api/admin/tasks/task-001", headers=ADMIN_HEADERS)
        assert resp.status_code == 200

    def test_delete_calls_scheduler(self, client: TestClient, loader: MagicMock) -> None:
        client.delete("/api/admin/tasks/task-001", headers=ADMIN_HEADERS)
        loader.scheduler.delete_task.assert_called_once()

    def test_delete_requires_auth(self, client: TestClient) -> None:
        resp = client.delete("/api/admin/tasks/task-001")
        assert resp.status_code == 403


# ── GET /api/admin/audit ──────────────────────────────────────────────────────

class TestAdminAudit:
    def test_returns_200(self, client: TestClient) -> None:
        resp = client.get("/api/admin/audit", headers=ADMIN_HEADERS)
        assert resp.status_code == 200

    def test_response_has_logs_field(self, client: TestClient) -> None:
        data = client.get("/api/admin/audit", headers=ADMIN_HEADERS).json()
        assert "logs" in data
        assert isinstance(data["logs"], list)

    def test_requires_auth(self, client: TestClient) -> None:
        resp = client.get("/api/admin/audit")
        assert resp.status_code == 403

    def test_level_filter_param_accepted(self, client: TestClient) -> None:
        resp = client.get(
            "/api/admin/audit?level=critical",
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 200

    def test_limit_param_accepted(self, client: TestClient) -> None:
        resp = client.get(
            "/api/admin/audit?limit=10",
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 200


# ── GET /api/admin/memory ─────────────────────────────────────────────────────

class TestAdminMemory:
    def test_returns_200(self, client: TestClient) -> None:
        resp = client.get("/api/admin/memory", headers=ADMIN_HEADERS)
        assert resp.status_code == 200

    def test_response_has_memories_field(self, client: TestClient) -> None:
        data = client.get("/api/admin/memory", headers=ADMIN_HEADERS).json()
        assert "memories" in data
        assert isinstance(data["memories"], list)

    def test_requires_auth(self, client: TestClient) -> None:
        resp = client.get("/api/admin/memory")
        assert resp.status_code == 403

    def test_user_id_param_accepted(self, client: TestClient) -> None:
        resp = client.get(
            "/api/admin/memory?user_id=default_user",
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 200
