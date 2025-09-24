from __future__ import annotations

import copy
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from remote_browser_tool.browser.base import BrowserSession, BrowserState
from remote_browser_tool.config import RunnerConfig
from remote_browser_tool.executor import service as executor_service
from remote_browser_tool.executor.models import TaskData, TaskLogEntry, TaskStatus
from remote_browser_tool.executor.task_runner import TaskRunner
from remote_browser_tool.llm.mock import ScriptedLLM
from remote_browser_tool.memory.base import InMemoryStore
from remote_browser_tool.models import (
    BrowserAction,
    BrowserActionType,
    DirectiveStatus,
    LLMDirective,
    MemoryEntry,
    NotificationEvent,
    NotificationLevel,
)
from remote_browser_tool.notifications.base import Notifier


class StubBrowser(BrowserSession):
    def __init__(self) -> None:
        self.actions: list[BrowserAction] = []

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def execute(self, action: BrowserAction) -> BrowserState:
        self.actions.append(action)
        return BrowserState(
            url=action.url or "https://example.com",
            title="Example",
            last_action=action.type.value,
        )

    def snapshot(self) -> BrowserState:
        return BrowserState(url="https://example.com", title="Example", last_action=None)

    def screenshot(self) -> bytes:
        return b"screenshot"


class StubNotifier(Notifier):
    def __init__(self) -> None:
        self.events: list[NotificationEvent] = []

    def notify(self, event: NotificationEvent) -> None:
        self.events.append(event)


@pytest.fixture
def runner_config() -> RunnerConfig:
    return RunnerConfig.model_validate(
        {
            "task": {"description": "Instrumentation test", "goal": "Done"},
            "browser": {"enable_vnc": False, "headless": True},
            "llm": {"provider": "mock"},
        }
    )


@pytest.fixture
def directives() -> list[LLMDirective]:
    return [
        LLMDirective(
            status=DirectiveStatus.CONTINUE,
            actions=[
                BrowserAction(type=BrowserActionType.NAVIGATE, url="https://example.com"),
            ],
            memory_to_write=["visited"],
            message="step",
        ),
        LLMDirective(status=DirectiveStatus.FINISHED, message="done"),
    ]


def test_task_runner_records_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    runner_config: RunnerConfig,
    directives: list[LLMDirective],
) -> None:
    stub_llm = ScriptedLLM(directives)
    monkeypatch.setattr(
        "remote_browser_tool.executor.task_runner.build_llm",
        lambda config: stub_llm,
    )
    monkeypatch.setattr(
        "remote_browser_tool.executor.task_runner.build_browser",
        lambda config: StubBrowser(),
    )
    monkeypatch.setattr(
        "remote_browser_tool.executor.task_runner.build_memory",
        lambda config: InMemoryStore(max_entries=10),
    )
    monkeypatch.setattr(
        "remote_browser_tool.executor.task_runner.build_notifier",
        lambda config: StubNotifier(),
    )

    runner = TaskRunner(
        config=runner_config,
        base_artifact_dir=tmp_path,
    )
    runner._run()  # execute synchronously for testing
    data = runner.snapshot()

    assert data.status == TaskStatus.COMPLETED
    assert data.actions
    action_record = data.actions[0]
    assert action_record.action.type is BrowserActionType.NAVIGATE
    assert action_record.screenshot_path is not None
    assert action_record.screenshot_path.exists()
    assert runner.list_screenshots()
    assert data.memory and data.memory[0].content == "visited"
    with pytest.raises(ValueError):
        runner.get_screenshot_path("../secret.png")


class FakeRunner:
    counter = 0

    def __init__(
        self,
        config: RunnerConfig,
        base_artifact_dir: Path,
    ) -> None:
        FakeRunner.counter += 1
        self.task_id = f"task-{FakeRunner.counter}"
        self._artifact_dir = base_artifact_dir / self.task_id
        self._artifact_dir.mkdir(parents=True, exist_ok=True)
        (self._artifact_dir / "preview.png").write_bytes(b"fake")
        self._data = TaskData(
            id=self.task_id,
            description=config.task.description,
            goal=config.task.goal,
            status=TaskStatus.RUNNING,
        )
        event = NotificationEvent(
            type="task_started",
            message="started",
            level=NotificationLevel.INFO,
        )
        self._data.logs.append(TaskLogEntry(event=event))
        self._data.memory.append(MemoryEntry(content="note"))

    def start(self) -> None:
        return None

    def snapshot(self) -> TaskData:
        return copy.deepcopy(self._data)

    def request_pause(self, reason: str, instructions: str) -> bool:
        self._data.status = TaskStatus.PAUSED
        return True

    def mark_intervention_finished(self) -> bool:
        self._data.status = TaskStatus.RUNNING
        return True

    def list_screenshots(self) -> list[str]:
        return ["preview.png"]

    def get_screenshot_path(self, name: str) -> Path:
        base_dir = self._artifact_dir.resolve()
        resolved = (base_dir / name).resolve()
        try:
            resolved.relative_to(base_dir)
        except ValueError as exc:
            raise ValueError("Screenshot name escapes artifact directory") from exc
        return resolved


def test_executor_api_endpoints(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(executor_service, "TaskRunner", FakeRunner)
    monkeypatch.setattr(
        executor_service.ExecutorState,
        "_check_browser",
        lambda self: {"status": "available"},
    )
    monkeypatch.setattr(
        executor_service.ExecutorState,
        "_check_llm",
        lambda self: {"status": "configured", "provider": "mock"},
    )
    executor_service.state = executor_service.ExecutorState(tmp_path)

    client = TestClient(executor_service.app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["browser"]["status"] == "available"

    payload = {"config": {"task": {"description": "Example task"}}}
    response = client.post("/tasks", json=payload)
    assert response.status_code == 200
    task_id = response.json()["id"]

    rejection = client.post(
        "/tasks",
        json={"config": payload["config"], "env": {"OPENAI_API_KEY": "abc"}},
    )
    assert rejection.status_code == 400

    listing = client.get("/tasks")
    assert listing.status_code == 200
    assert listing.json()[0]["id"] == task_id

    detail = client.get(f"/tasks/{task_id}")
    assert detail.status_code == 200
    assert detail.json()["description"] == "Example task"

    pause = client.post(
        f"/tasks/{task_id}/pause",
        params={"reason": "check", "instructions": "do it"},
    )
    assert pause.status_code == 200

    resume = client.post(f"/tasks/{task_id}/resume")
    assert resume.status_code == 200

    env_update = client.put("/settings/env", json={"overrides": {"TEST_KEY": "value"}})
    assert env_update.status_code == 200
    env_fetch = client.get("/settings/env")
    assert env_fetch.status_code == 200
    assert env_fetch.json()["TEST_KEY"] == "value"

    screenshot = client.get(f"/tasks/{task_id}/screenshots/preview.png")
    assert screenshot.status_code == 200
    assert screenshot.content == b"fake"
    with pytest.raises(HTTPException) as exc_info:
        executor_service.download_screenshot(task_id, "../../secret")
    assert exc_info.value.status_code == 400
