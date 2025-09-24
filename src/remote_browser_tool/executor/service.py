"""HTTP service exposing executor functionality for the admin portal."""

from __future__ import annotations

import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..config import RunnerConfig
from ..models import MemoryEntry, NotificationEvent
from .models import TaskActionRecord, TaskData, TaskStatus
from .task_runner import TaskRunner

ARTIFACTS_DIR = Path(os.environ.get("REMOTE_BROWSER_TOOL_EXECUTOR_DATA", "./executor_artifacts"))
app = FastAPI(title="Remote Browser Tool Executor")


def _merge_dict(target: Dict[str, Any], updates: Dict[str, Any]) -> None:
    for key, value in updates.items():
        existing = target.get(key)
        if isinstance(value, dict) and isinstance(existing, dict):
            _merge_dict(existing, value)
        else:
            target[key] = value


def merge_env_into_config(config: RunnerConfig, env: Dict[str, str]) -> RunnerConfig:
    prefix = "REMOTE_BROWSER_TOOL_"
    updates: Dict[str, Any] = {}
    for key, value in env.items():
        if key.startswith(prefix):
            path = key[len(prefix) :].split("__")
            current = updates
            for segment in path[:-1]:
                current = current.setdefault(segment.lower(), {})
            current[path[-1].lower()] = value
    if "OPENAI_API_KEY" in env:
        updates.setdefault("llm", {}).setdefault("api_key", env["OPENAI_API_KEY"])
    if not updates:
        return config
    data = config.model_dump(mode="python")
    _merge_dict(data, updates)
    return RunnerConfig.model_validate(data)


# Pydantic response models ----------------------------------------------------


class NotificationModel(BaseModel):
    type: str
    message: str
    level: str
    timestamp: datetime
    data: Dict[str, Any]

    @classmethod
    def from_event(cls, event: NotificationEvent) -> "NotificationModel":
        return cls(
            type=event.type,
            message=event.message,
            level=event.level.value,
            timestamp=event.timestamp,
            data=event.data,
        )


class MemoryModel(BaseModel):
    content: str
    created_at: datetime
    importance: Optional[float] = None

    @classmethod
    def from_entry(cls, entry: MemoryEntry) -> "MemoryModel":
        return cls(
            content=entry.content,
            created_at=entry.created_at,
            importance=entry.importance,
        )


class ActionModel(BaseModel):
    index: int
    action: Dict[str, Any]
    resulting_state: Dict[str, Any]
    screenshot: Optional[str] = None
    timestamp: datetime

    @classmethod
    def from_record(cls, record: TaskActionRecord) -> "ActionModel":
        return cls(
            index=record.index,
            action=record.action.model_dump(),
            resulting_state={
                "url": record.resulting_state.url,
                "title": record.resulting_state.title,
                "last_action": record.resulting_state.last_action,
            },
            screenshot=record.screenshot_path.name if record.screenshot_path else None,
            timestamp=record.timestamp,
        )


class InterventionModel(BaseModel):
    reason: str
    instructions: str
    metadata: Dict[str, Any]
    started_at: datetime
    connection: Optional[Dict[str, Any]] = None


class TaskSummaryModel(BaseModel):
    id: str
    description: str
    goal: Optional[str]
    status: TaskStatus
    created_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]


class TaskDetailModel(TaskSummaryModel):
    logs: List[NotificationModel]
    memory: List[MemoryModel]
    actions: List[ActionModel]
    current_request: Optional[InterventionModel]
    error: Optional[str]


class TaskCreateRequest(BaseModel):
    config: Dict[str, Any]
    env: Optional[Dict[str, str]] = None


class EnvironmentUpdate(BaseModel):
    overrides: Dict[str, str] = Field(default_factory=dict)


# Executor state --------------------------------------------------------------


class ExecutorState:
    def __init__(self, artifacts_dir: Path) -> None:
        self._artifacts_dir = artifacts_dir
        self._artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._tasks: Dict[str, TaskRunner] = {}
        self._lock = threading.Lock()
        self._env_overrides: Dict[str, str] = {}
        self._last_config: Optional[RunnerConfig] = None

    def list_tasks(self) -> List[TaskData]:
        with self._lock:
            return [runner.snapshot() for runner in self._tasks.values()]

    def get_task(self, task_id: str) -> TaskRunner:
        with self._lock:
            if task_id not in self._tasks:
                raise KeyError(task_id)
            return self._tasks[task_id]

    def set_env_overrides(self, overrides: Dict[str, str]) -> None:
        with self._lock:
            self._env_overrides = dict(overrides)

    def get_env_overrides(self) -> Dict[str, str]:
        with self._lock:
            return dict(self._env_overrides)

    def create_task(self, config: RunnerConfig) -> TaskRunner:
        with self._lock:
            overrides = dict(self._env_overrides)
        config_with_env = merge_env_into_config(config, overrides)
        runner = TaskRunner(
            config=config_with_env,
            base_artifact_dir=self._artifacts_dir,
        )
        with self._lock:
            self._tasks[runner.task_id] = runner
            self._last_config = config_with_env
        runner.start()
        return runner

    def health(self) -> Dict[str, Any]:
        browser_status = self._check_browser()
        llm_status = self._check_llm()
        return {
            "browser": browser_status,
            "llm": llm_status,
            "env_overrides": list(self.get_env_overrides().keys()),
        }

    def _check_browser(self) -> Dict[str, Any]:
        try:
            from playwright.sync_api import sync_playwright  # type: ignore
        except Exception as exc:  # pragma: no cover - environment dependent
            return {"status": "unavailable", "detail": str(exc)}
        try:  # pragma: no cover - requires Playwright runtime
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                browser.close()
            return {"status": "available"}
        except Exception as exc:  # pragma: no cover - optional diagnostic
            return {"status": "error", "detail": str(exc)}

    def _check_llm(self) -> Dict[str, Any]:
        config = self._last_config
        if not config:
            return {"status": "unknown", "detail": "no tasks executed yet"}
        provider = config.llm.provider.lower()
        if provider in {"openai", "azure", "openai-compatible"}:
            api_key = config.llm.api_key or self._env_overrides.get("OPENAI_API_KEY")
            if api_key:
                return {"status": "configured", "provider": provider}
            return {"status": "missing_credentials", "provider": provider}
        return {"status": "available", "provider": provider}


state = ExecutorState(ARTIFACTS_DIR)


# Helper conversion -----------------------------------------------------------


def _task_to_summary(data: TaskData) -> TaskSummaryModel:
    return TaskSummaryModel(
        id=data.id,
        description=data.description,
        goal=data.goal,
        status=data.status,
        created_at=data.created_at,
        started_at=data.started_at,
        finished_at=data.finished_at,
    )


def _task_to_detail(data: TaskData) -> TaskDetailModel:
    logs = [NotificationModel.from_event(entry.event) for entry in data.logs]
    memory = [MemoryModel.from_entry(entry) for entry in data.memory]
    actions = [ActionModel.from_record(record) for record in data.actions]
    intervention = None
    if data.current_request:
        connection = None
        if data.connection_info:
            connection = {
                "host": data.connection_info.host,
                "port": data.connection_info.port,
                "display": data.connection_info.display,
            }
        intervention = InterventionModel(
            reason=data.current_request.reason,
            instructions=data.current_request.instructions,
            metadata=data.current_request.metadata,
            started_at=data.current_request_started_at or data.created_at,
            connection=connection,
        )
    return TaskDetailModel(
        **_task_to_summary(data).model_dump(),
        logs=logs,
        memory=memory,
        actions=actions,
        current_request=intervention,
        error=data.error,
    )


# API routes -----------------------------------------------------------------


@app.get("/health")
def get_health() -> Dict[str, Any]:
    return state.health()


@app.get("/settings/env")
def get_env_settings() -> Dict[str, str]:
    return state.get_env_overrides()


@app.put("/settings/env")
def update_env_settings(payload: EnvironmentUpdate) -> Dict[str, str]:
    state.set_env_overrides(payload.overrides)
    return state.get_env_overrides()


@app.get("/tasks", response_model=List[TaskSummaryModel])
def list_tasks() -> List[TaskSummaryModel]:
    return [_task_to_summary(data) for data in state.list_tasks()]


@app.post("/tasks", response_model=TaskSummaryModel)
def create_task(payload: TaskCreateRequest) -> TaskSummaryModel:
    try:
        config = RunnerConfig.model_validate(payload.config)
    except Exception as exc:  # pragma: no cover - validation feedback
        raise HTTPException(status_code=400, detail=f"Invalid configuration: {exc}") from exc
    if payload.env:
        raise HTTPException(
            status_code=400,
            detail="Per-task environment overrides are not supported; "
            "configure executor-level settings instead.",
        )
    runner = state.create_task(config)
    return _task_to_summary(runner.snapshot())


@app.get("/tasks/{task_id}", response_model=TaskDetailModel)
def get_task_detail(task_id: str) -> TaskDetailModel:
    try:
        runner = state.get_task(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found") from None
    return _task_to_detail(runner.snapshot())


@app.post("/tasks/{task_id}/pause")
def pause_task(
    task_id: str,
    reason: str = "Manual pause",
    instructions: str = "Take control via VNC and resume when finished",
) -> Dict[str, Any]:
    try:
        runner = state.get_task(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found") from None
    if not runner.request_pause(reason, instructions):
        raise HTTPException(status_code=409, detail="Task already waiting for manual input")
    return {"status": "pause_requested"}


@app.post("/tasks/{task_id}/resume")
def resume_task(task_id: str) -> Dict[str, Any]:
    try:
        runner = state.get_task(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found") from None
    if not runner.mark_intervention_finished():
        raise HTTPException(status_code=409, detail="Task is not waiting for manual intervention")
    return {"status": "resuming"}


@app.get("/tasks/{task_id}/screenshots")
def list_task_screenshots(task_id: str) -> List[str]:
    try:
        runner = state.get_task(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found") from None
    return runner.list_screenshots()


@app.get("/tasks/{task_id}/screenshots/{name}")
def download_screenshot(task_id: str, name: str) -> Response:
    try:
        runner = state.get_task(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found") from None
    try:
        path = runner.get_screenshot_path(name)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid screenshot name") from None
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Screenshot not found")
    return FileResponse(path)


