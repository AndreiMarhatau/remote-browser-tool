"""Task runner that wraps the orchestrator for the executor service."""
from __future__ import annotations

import copy
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..browser.base import BrowserState
from ..browser.vnc import VNCConnectionInfo
from ..config import RunnerConfig
from ..factory import build_browser, build_llm, build_memory, build_notifier
from ..memory.base import MemoryStore
from ..models import BrowserAction, MemoryEntry, NotificationEvent
from ..notifications.base import Notifier
from ..orchestrator.control import ManualPauseController
from ..orchestrator.runner import Orchestrator
from ..user_portal.base import UserInteractionPortal
from .instrumentation import (
    InstrumentedBrowserSession,
    InstrumentedMemoryStore,
    InstrumentedNotifier,
)
from .models import TaskActionRecord, TaskData, TaskLogEntry, TaskStatus
from .portal import ActiveIntervention, ExecutorUserPortal

LOGGER = logging.getLogger(__name__)


class TaskRecorder:
    """Collect task artifacts produced during execution."""

    def __init__(self, task: TaskData, artifacts_dir: Path) -> None:
        self._task = task
        self._artifacts_dir = artifacts_dir
        self._artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._action_index = 0

    def on_action(
        self,
        action: BrowserAction,
        state: BrowserState,
        screenshot: bytes | None,
    ) -> None:
        screenshot_path = None
        if screenshot:
            filename = f"step_{self._action_index:04d}.png"
            path = self._artifacts_dir / filename
            try:
                path.write_bytes(screenshot)
                screenshot_path = path
            except OSError:  # pragma: no cover - defensive file handling
                LOGGER.exception("Failed to write screenshot %s", path)
        record = TaskActionRecord(
            index=self._action_index,
            action=action,
            resulting_state=state,
            screenshot_path=screenshot_path,
        )
        with self._lock:
            self._task.actions.append(record)
        self._action_index += 1

    def on_memory(self, entry: MemoryEntry) -> None:
        with self._lock:
            self._task.memory.append(entry)

    def on_notification(self, event: NotificationEvent) -> None:
        with self._lock:
            self._task.logs.append(TaskLogEntry(event=event))
            if event.type == "vnc_ready":
                data = event.data
                if {"host", "port", "display"} <= data.keys():
                    self._task.connection_info = VNCConnectionInfo(
                        host=str(data["host"]),
                        port=int(data["port"]),
                        display=str(data["display"]),
                    )


class TaskRunner:
    """Run a single orchestrator task in the background."""

    def __init__(
        self,
        *,
        config: RunnerConfig,
        base_artifact_dir: Path,
    ) -> None:
        task_id = uuid.uuid4().hex
        self._task = TaskData(
            id=task_id,
            description=config.task.description,
            goal=config.task.goal,
        )
        self._lock = threading.Lock()
        self._config = config
        self._artifact_dir = base_artifact_dir / task_id
        self._recorder = TaskRecorder(self._task, self._artifact_dir)
        self._manual_controller = ManualPauseController()
        self._portal = ExecutorUserPortal(on_change=self._handle_intervention_update)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._result: bool | None = None

    # Public API --------------------------------------------------------------

    @property
    def task_id(self) -> str:
        return self._task.id

    def start(self) -> None:
        self._thread.start()

    def is_running(self) -> bool:
        return self._thread.is_alive()

    def request_pause(self, reason: str, instructions: str) -> bool:
        return self._manual_controller.request_pause(
            reason=reason,
            instructions=instructions,
        )

    def resume(self) -> bool:
        active = self._portal.get_active()
        if not active:
            return False
        self._portal.mark_finished()
        return True

    def snapshot(self) -> TaskData:
        with self._lock:
            return copy.deepcopy(self._task)

    def get_artifacts_dir(self) -> Path:
        return self._artifact_dir

    def list_screenshots(self) -> list[str]:
        if not self._artifact_dir.exists():
            return []
        return sorted([path.name for path in self._artifact_dir.glob("step_*.png")])

    def get_screenshot_path(self, name: str) -> Path:
        candidate = Path(name)
        if candidate.is_absolute():
            raise ValueError("Screenshot name must be relative")
        base_dir = self._artifact_dir.resolve()
        resolved = (base_dir / candidate).resolve()
        try:
            resolved.relative_to(base_dir)
        except ValueError as exc:
            raise ValueError("Screenshot name escapes artifact directory") from exc
        return resolved

    def mark_intervention_finished(self) -> bool:
        return self.resume()

    # Internal helpers --------------------------------------------------------

    def _run(self) -> None:
        with self._lock:
            self._task.status = TaskStatus.RUNNING
            self._task.started_at = datetime.now(timezone.utc)
        try:
            orchestrator = self._build_orchestrator()
            success = orchestrator.run()
            with self._lock:
                self._result = success
                self._task.finished_at = datetime.now(timezone.utc)
                self._task.status = TaskStatus.COMPLETED if success else TaskStatus.FAILED
                if not success and self._task.error is None:
                    self._task.error = "Task reported failure"
        except Exception as exc:  # pragma: no cover - defensive safeguard
            with self._lock:
                self._result = False
                self._task.finished_at = datetime.now(timezone.utc)
                self._task.status = TaskStatus.FAILED
                self._task.error = str(exc)

    def _build_orchestrator(self) -> Orchestrator:
        llm = build_llm(self._config.llm)
        browser = build_browser(self._config.browser)
        memory_store = build_memory(self._config)
        notifier = build_notifier(self._config.notifications)

        instrumented_browser = InstrumentedBrowserSession(
            browser,
            instrumentation=self._recorder,
            capture_screenshots=True,
        )
        instrumented_memory: MemoryStore = InstrumentedMemoryStore(
            memory_store,
            instrumentation=self._recorder,
        )
        instrumented_notifier: Notifier = InstrumentedNotifier(
            notifier,
            instrumentation=self._recorder,
        )
        portal: UserInteractionPortal = self._portal
        return Orchestrator(
            config=self._config,
            llm=llm,
            browser=instrumented_browser,
            memory=instrumented_memory,
            notifier=instrumented_notifier,
            user_portal=portal,
            manual_controller=self._manual_controller,
        )

    def _handle_intervention_update(self, active: ActiveIntervention | None) -> None:
        with self._lock:
            if active:
                self._task.current_request = active.request
                self._task.current_request_started_at = active.started_at
                self._task.connection_info = active.connection_info
                source = active.request.metadata.get("source")
                if source == "manual_pause":
                    self._task.status = TaskStatus.PAUSED
                else:
                    self._task.status = TaskStatus.WAITING_FOR_USER
            else:
                self._task.current_request = None
                self._task.current_request_started_at = None
                if self._task.status in {TaskStatus.PAUSED, TaskStatus.WAITING_FOR_USER}:
                    self._task.status = TaskStatus.RUNNING

