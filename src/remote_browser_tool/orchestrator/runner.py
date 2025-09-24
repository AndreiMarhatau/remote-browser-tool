"""Main orchestrator that coordinates the LLM and the browser."""

from __future__ import annotations

import logging
import time
from typing import Optional

from ..browser.base import BrowserSession, BrowserState
from ..browser.vnc import VNCConnectionInfo, VNCManager
from ..config import RunnerConfig, TaskConfig
from ..llm.base import ConversationTurn, LLMClient, LLMContext
from ..memory.base import MemoryStore
from ..models import (
    DirectiveStatus,
    LLMDirective,
    MemoryEntry,
    NotificationEvent,
    NotificationLevel,
    UserInterventionRequest,
)
from ..notifications.base import Notifier
from ..user_portal.base import UserInteractionPortal
from .control import ManualPauseController
from .prompt_builder import PromptBuilder

LOGGER = logging.getLogger(__name__)


class Orchestrator:
    """Coordinates LLM planning with browser execution."""

    def __init__(
        self,
        config: RunnerConfig,
        llm: LLMClient,
        browser: BrowserSession,
        memory: MemoryStore,
        notifier: Notifier,
        user_portal: Optional[UserInteractionPortal] = None,
        prompt_builder: Optional[PromptBuilder] = None,
        manual_controller: Optional[ManualPauseController] = None,
    ) -> None:
        self._config = config
        self._llm = llm
        self._browser = browser
        self._memory = memory
        self._notifier = notifier
        self._user_portal = user_portal
        self._prompt_builder = prompt_builder or PromptBuilder()
        self._manual_controller = manual_controller
        self._history: list[ConversationTurn] = list(self._llm.start_conversation())

    def run(self) -> bool:
        """Run the orchestrator until completion or failure."""

        LOGGER.info("Starting orchestrator for task: %s", self._config.task.description)
        self._notifier.notify(
            NotificationEvent(
                type="task_started",
                message=f"Starting task: {self._config.task.description}",
                level=NotificationLevel.INFO,
            )
        )
        if self._user_portal:
            self._user_portal.start()
        vnc_manager = VNCManager(enabled=self._config.browser.enable_vnc)
        connection_info = vnc_manager.start()
        if self._user_portal:
            self._user_portal.update_connection_info(connection_info)
        if connection_info:
            self._notify_vnc_ready(connection_info)
        try:
            self._browser.start()
            state = self._browser.snapshot()
            while True:
                if self._manual_controller:
                    pending = self._manual_controller.consume_pending()
                    if pending:
                        self._handle_user_intervention(pending.request)
                        self._manual_controller.clear_active()
                        state = self._browser.snapshot()
                        continue
                directive = self._plan_next_step(state)
                if directive.memory_to_write:
                    for item in directive.memory_to_write:
                        self._memory.add(MemoryEntry(content=item))
                if directive.actions:
                    for action in directive.actions:
                        state = self._browser.execute(action)
                if directive.wait_seconds:
                    LOGGER.info("Waiting for %s seconds", directive.wait_seconds)
                    time.sleep(directive.wait_seconds)
                if directive.status == DirectiveStatus.CONTINUE:
                    continue
                if directive.status == DirectiveStatus.WAIT:
                    continue
                if directive.status == DirectiveStatus.WAIT_FOR_USER:
                    if not self._user_portal:
                        raise RuntimeError("User interaction requested but no portal configured")
                    request = directive.user_request or self._default_user_request(
                        self._config.task
                    )
                    if "source" not in request.metadata:
                        request.metadata = {
                            **request.metadata,
                            "source": "llm_wait",
                        }
                    self._handle_user_intervention(request)
                    if self._manual_controller:
                        self._manual_controller.clear_active()
                    state = self._browser.snapshot()
                    continue
                if directive.status == DirectiveStatus.FINISHED:
                    self._notifier.notify(
                        NotificationEvent(
                            type="task_finished",
                            message=directive.message or "Task completed",
                            level=NotificationLevel.SUCCESS,
                        )
                    )
                    if connection_info:
                        self._notify_vnc_complete(connection_info)
                    return True
                if directive.status == DirectiveStatus.FAILED:
                    self._notifier.notify(
                        NotificationEvent(
                            type="task_failed",
                            message=directive.failure_reason or "Task failed",
                            level=NotificationLevel.ERROR,
                        )
                    )
                    return False
        except Exception as exc:  # pragma: no cover - defensive logging
            LOGGER.exception("Unhandled orchestrator error")
            self._notifier.notify(
                NotificationEvent(
                    type="orchestrator_error",
                    message=str(exc),
                    level=NotificationLevel.ERROR,
                )
            )
            return False
        finally:
            self._browser.stop()
            vnc_manager.stop()
            if self._user_portal:
                self._user_portal.stop()

    def _plan_next_step(self, state: BrowserState) -> LLMDirective:
        memory_entries = self._memory.get()
        prompt = self._prompt_builder.build(
            self._config.task,
            state,
            memory_entries,
            self._history,
        )
        self._history.append(ConversationTurn(role="user", content=prompt))
        directive = self._llm.complete(
            prompt,
            LLMContext(
                task_description=self._config.task.description,
                memory=memory_entries,
                history=self._history,
            ),
        )
        self._history.append(
            ConversationTurn(
                role="assistant",
                content=directive.message or directive.status.value,
            )
        )
        if len(self._history) > 50:
            self._history = self._history[-50:]
        if directive.message:
            self._notifier.notify(
                NotificationEvent(
                    type="llm_step",
                    message=directive.message,
                    level=NotificationLevel.INFO,
                )
            )
        return directive

    @staticmethod
    def _default_user_request(task: TaskConfig) -> UserInterventionRequest:
        return UserInterventionRequest(
            reason=f"Assistance needed while working on: {task.description}",
            instructions="Please resolve the blocking step in the browser and click 'Finished'.",
        )

    def _handle_user_intervention(self, request: UserInterventionRequest) -> None:
        if not self._user_portal:
            raise RuntimeError("User interaction requested but no portal configured")
        event = self._user_portal.request_intervention(request)
        self._notifier.notify(event)
        completed = self._user_portal.wait_until_finished(
            self._config.wait_for_user_timeout
        )
        if not completed:
            raise TimeoutError("User intervention timed out")
        self._history.append(
            ConversationTurn(
                role="system",
                content="User confirmed manual step completed.",
            ),
        )

    def _notify_vnc_ready(self, info: VNCConnectionInfo) -> None:
        self._notifier.notify(
            NotificationEvent(
                type="vnc_ready",
                message="Browser VNC connection available for manual intervention",
                level=NotificationLevel.INFO,
                data={
                    "host": info.host,
                    "port": info.port,
                    "display": info.display,
                },
            )
        )

    def _notify_vnc_complete(self, info: VNCConnectionInfo) -> None:
        self._notifier.notify(
            NotificationEvent(
                type="task_ready_for_review",
                message="Task finished. You may connect via VNC to review the outcome.",
                level=NotificationLevel.SUCCESS,
                data={
                    "host": info.host,
                    "port": info.port,
                    "display": info.display,
                },
            )
        )



