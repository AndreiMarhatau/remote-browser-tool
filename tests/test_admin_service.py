from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from remote_browser_tool.admin import service as admin_service
from remote_browser_tool.admin.client import (
    ExecutorAction,
    ExecutorHealth,
    ExecutorMemory,
    ExecutorNotification,
    ExecutorTaskDetail,
    ExecutorTaskSummary,
)


class StubExecutorClient:
    created_payload = None
    updated_env = None
    paused_calls: list[tuple[str, str, str]] = []
    resumed_calls: list[str] = []
    screenshot_calls: list[tuple[str, str]] = []
    instantiated_urls: list[str] = []

    def __init__(self, base_url: str, *, timeout: float = 15.0) -> None:
        self.base_url = base_url
        StubExecutorClient.instantiated_urls.append(base_url)

    async def get_health(self) -> ExecutorHealth:
        if "offline" in self.base_url:
            request = httpx.Request("GET", f"{self.base_url}/health")
            raise httpx.ConnectError("unable to connect", request=request)
        return ExecutorHealth(
            browser={"status": "available"},
            llm={"status": "configured", "provider": "mock"},
            env_overrides=["REMOTE_BROWSER_TOOL_LLM__API_KEY"],
        )

    async def list_tasks(self) -> list[ExecutorTaskSummary]:
        now = datetime.now(timezone.utc)
        return [
            ExecutorTaskSummary(
                id="task-1",
                description="Demo task",
                goal=None,
                status="running",
                created_at=now,
                started_at=None,
                finished_at=None,
            )
        ]

    async def get_env(self) -> dict[str, str]:
        return {"REMOTE_BROWSER_TOOL_LLM__PROVIDER": "mock"}

    async def create_task(
        self,
        *,
        config: dict[str, object],
    ) -> ExecutorTaskSummary:
        StubExecutorClient.created_payload = {"config": config}
        summary = (await self.list_tasks())[0]
        return summary

    async def get_task(self, task_id: str) -> ExecutorTaskDetail:
        now = datetime.now(timezone.utc)
        summary = (await self.list_tasks())[0]
        return ExecutorTaskDetail(
            **summary.model_dump(),
            logs=[
                ExecutorNotification(
                    type="info",
                    message="started",
                    level="info",
                    timestamp=now,
                    data={},
                )
            ],
            memory=[ExecutorMemory(content="note", created_at=now, importance=None)],
            actions=[
                ExecutorAction(
                    index=0,
                    action={"type": "navigate", "url": "https://example.com"},
                    resulting_state={
                        "url": "https://example.com",
                        "title": "Example",
                        "last_action": "navigate",
                    },
                    screenshot="shot.png",
                    timestamp=now,
                )
            ],
            current_request=None,
            error=None,
        )

    async def list_screenshots(self, task_id: str) -> list[str]:
        return ["shot.png"]

    async def fetch_screenshot(self, task_id: str, name: str) -> bytes:
        StubExecutorClient.screenshot_calls.append((task_id, name))
        return b"image"

    async def pause_task(self, task_id: str, *, reason: str, instructions: str) -> None:
        StubExecutorClient.paused_calls.append((task_id, reason, instructions))

    async def resume_task(self, task_id: str) -> None:
        StubExecutorClient.resumed_calls.append(task_id)

    async def update_env(self, overrides: dict[str, str]) -> dict[str, str]:
        StubExecutorClient.updated_env = overrides
        return overrides


def test_admin_portal_routes(monkeypatch) -> None:
    StubExecutorClient.created_payload = None
    StubExecutorClient.updated_env = None
    StubExecutorClient.paused_calls = []
    StubExecutorClient.resumed_calls = []
    StubExecutorClient.screenshot_calls = []
    StubExecutorClient.instantiated_urls = []
    monkeypatch.setattr(admin_service, "ExecutorClient", StubExecutorClient)
    app = admin_service.create_admin_app(["primary=http://executor"])
    client = TestClient(app)

    home = client.get("/")
    assert home.status_code == 200
    assert "Executor Status" in home.text

    add_resp = client.post(
        "/executors",
        data={"label": "Secondary", "base_url": "other-executor:9001"},
        follow_redirects=False,
    )
    assert add_resp.status_code == 303
    assert add_resp.headers["location"].endswith("/executors/secondary")
    assert any(
        url == "http://other-executor:9001" for url in StubExecutorClient.instantiated_urls
    )

    secondary_dashboard = client.get("/executors/secondary")
    assert secondary_dashboard.status_code == 200
    assert "http://other-executor:9001" in secondary_dashboard.text

    dashboard = client.get("/executors/primary")
    assert dashboard.status_code == 200
    assert "Demo task" in dashboard.text

    create_resp = client.post(
        "/executors/primary/tasks",
        data={
            "description": "New task",
            "goal": "Goal",
            "llm_provider": "mock",
            "llm_model": "",
            "llm_api_key": "",
        },
        follow_redirects=False,
    )
    assert create_resp.status_code == 303
    assert StubExecutorClient.created_payload is not None
    assert StubExecutorClient.created_payload["config"]["task"]["description"] == "New task"
    assert "env" not in StubExecutorClient.created_payload

    env_resp = client.post(
        "/executors/primary/settings/env",
        data={"env_text": "REMOTE_BROWSER_TOOL_LLM__API_KEY=abc"},
        follow_redirects=False,
    )
    assert env_resp.status_code == 303
    assert StubExecutorClient.updated_env == {"REMOTE_BROWSER_TOOL_LLM__API_KEY": "abc"}

    task_view = client.get("/executors/primary/tasks/task-1")
    assert task_view.status_code == 200
    assert "Manual Intervention" not in task_view.text

    pause_resp = client.post(
        "/executors/primary/tasks/task-1/pause",
        data={"reason": "Admin", "instructions": "Handle"},
        follow_redirects=False,
    )
    assert pause_resp.status_code == 303
    assert StubExecutorClient.paused_calls and StubExecutorClient.paused_calls[-1][0] == "task-1"

    resume_resp = client.post(
        "/executors/primary/tasks/task-1/resume",
        follow_redirects=False,
    )
    assert resume_resp.status_code == 303
    assert StubExecutorClient.resumed_calls and StubExecutorClient.resumed_calls[-1] == "task-1"

    screenshot = client.get("/executors/primary/tasks/task-1/screenshots/shot.png")
    assert screenshot.status_code == 200
    assert screenshot.content == b"image"

    removal_resp = client.post(
        "/executors/secondary/delete",
        follow_redirects=False,
    )
    assert removal_resp.status_code == 303
    home_after_removal = client.get("/")
    assert home_after_removal.status_code == 200
    assert "Secondary" not in home_after_removal.text

    missing_input = client.post(
        "/executors",
        data={"label": "", "base_url": ""},
    )
    assert missing_input.status_code == 400
    assert "Executor address is required" in missing_input.text

    offline_resp = client.post(
        "/executors",
        data={"label": "Offline", "base_url": "offline-executor:9001"},
    )
    assert offline_resp.status_code == 502
    assert "Could not connect" in offline_resp.text
    home_after_failure = client.get("/")
    assert "offline-executor" not in home_after_failure.text


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("example.com", "http://example.com"),
        ("https://example.com", "https://example.com"),
        ("executor:9001", "http://executor:9001"),
        (" http://executor.local/ ", "http://executor.local"),
        ("https://executor.local/api/", "https://executor.local/api"),
    ],
)
def test_normalize_executor_base_url_valid(raw: str, expected: str) -> None:
    assert admin_service._normalize_executor_base_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "ftp://example.com", "http:///missing", "http://"],
)
def test_normalize_executor_base_url_invalid(raw: str) -> None:
    with pytest.raises(ValueError):
        admin_service._normalize_executor_base_url(raw)
