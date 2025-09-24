"""HTTP client used by the admin service to talk to executor instances."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from pydantic import BaseModel


class ExecutorTaskSummary(BaseModel):
    id: str
    description: str
    goal: Optional[str] = None
    status: str
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class ExecutorNotification(BaseModel):
    type: str
    message: str
    level: str
    timestamp: datetime
    data: Dict[str, Any]


class ExecutorMemory(BaseModel):
    content: str
    created_at: datetime
    importance: Optional[float] = None


class ExecutorAction(BaseModel):
    index: int
    action: Dict[str, Any]
    resulting_state: Dict[str, Any]
    screenshot: Optional[str] = None
    timestamp: datetime


class ExecutorIntervention(BaseModel):
    reason: str
    instructions: str
    metadata: Dict[str, Any]
    started_at: datetime
    connection: Optional[Dict[str, Any]] = None


class ExecutorTaskDetail(ExecutorTaskSummary):
    logs: List[ExecutorNotification]
    memory: List[ExecutorMemory]
    actions: List[ExecutorAction]
    current_request: Optional[ExecutorIntervention] = None
    error: Optional[str] = None


class ExecutorHealth(BaseModel):
    browser: Dict[str, Any]
    llm: Dict[str, Any]
    env_overrides: List[str]


class ExecutorClient:
    """Wrapper around the executor HTTP API."""

    def __init__(self, base_url: str, *, timeout: float = 15.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def list_tasks(self) -> List[ExecutorTaskSummary]:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.get("/tasks")
            response.raise_for_status()
            data = response.json()
        return [ExecutorTaskSummary.model_validate(item) for item in data]

    async def get_task(self, task_id: str) -> ExecutorTaskDetail:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.get(f"/tasks/{task_id}")
            response.raise_for_status()
            data = response.json()
        return ExecutorTaskDetail.model_validate(data)

    async def create_task(
        self,
        *,
        config: Dict[str, Any],
    ) -> ExecutorTaskSummary:
        payload = {"config": config}
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.post("/tasks", json=payload)
            response.raise_for_status()
            data = response.json()
        return ExecutorTaskSummary.model_validate(data)

    async def pause_task(self, task_id: str, *, reason: str, instructions: str) -> None:
        payload = {"reason": reason, "instructions": instructions}
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.post(f"/tasks/{task_id}/pause", params=payload)
            response.raise_for_status()

    async def resume_task(self, task_id: str) -> None:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.post(f"/tasks/{task_id}/resume")
            response.raise_for_status()

    async def list_screenshots(self, task_id: str) -> List[str]:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.get(f"/tasks/{task_id}/screenshots")
            response.raise_for_status()
            return list(response.json())

    async def fetch_screenshot(self, task_id: str, name: str) -> bytes:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.get(f"/tasks/{task_id}/screenshots/{name}")
            response.raise_for_status()
            return response.content

    async def get_env(self) -> Dict[str, str]:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.get("/settings/env")
            response.raise_for_status()
            return dict(response.json())

    async def update_env(self, overrides: Dict[str, str]) -> Dict[str, str]:
        payload = {"overrides": overrides}
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.put("/settings/env", json=payload)
            response.raise_for_status()
            return dict(response.json())

    async def get_health(self) -> ExecutorHealth:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.get("/health")
            response.raise_for_status()
            data = response.json()
        return ExecutorHealth.model_validate(data)
