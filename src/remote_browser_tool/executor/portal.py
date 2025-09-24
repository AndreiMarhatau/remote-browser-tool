"""User interaction portal that exposes state for the executor API."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from ..browser.vnc import VNCConnectionInfo
from ..models import NotificationEvent, NotificationLevel, UserInterventionRequest
from ..user_portal.base import UserInteractionPortal


@dataclass
class ActiveIntervention:
    """Information about an ongoing manual intervention."""

    request: UserInterventionRequest
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    connection_info: Optional[VNCConnectionInfo] = None


class ExecutorUserPortal(UserInteractionPortal):
    """Portal implementation that stores manual intervention state in memory."""

    def __init__(
        self,
        *,
        on_change: Optional[Callable[[Optional[ActiveIntervention]], None]] = None,
    ) -> None:
        self._lock = threading.Lock()
        self._current: Optional[ActiveIntervention] = None
        self._finish_event: Optional[threading.Event] = None
        self._on_change = on_change

    def start(self) -> None:  # noqa: D401 - interface requirement
        return

    def stop(self) -> None:
        with self._lock:
            self._current = None
            if self._finish_event:
                self._finish_event.set()
            self._finish_event = None
        self._emit_change()

    def update_connection_info(self, info: Optional[VNCConnectionInfo]) -> None:
        with self._lock:
            if self._current:
                self._current.connection_info = info
        self._emit_change()

    def request_intervention(self, request: UserInterventionRequest) -> NotificationEvent:
        with self._lock:
            self._current = ActiveIntervention(request=request)
            self._finish_event = threading.Event()
        self._emit_change()
        return NotificationEvent(
            type="user_action_required",
            message=request.reason,
            level=NotificationLevel.WARNING,
            data={
                "reason": request.reason,
                "instructions": request.instructions,
                "metadata": request.metadata,
            },
        )

    def wait_until_finished(self, timeout: Optional[float] = None) -> bool:
        with self._lock:
            event = self._finish_event
        if not event:
            return False
        completed = event.wait(timeout)
        if completed:
            with self._lock:
                self._current = None
                self._finish_event = None
            self._emit_change()
        return completed

    # Executor-specific helpers -------------------------------------------------

    def get_active(self) -> Optional[ActiveIntervention]:
        with self._lock:
            return self._current

    def mark_finished(self) -> None:
        with self._lock:
            event = self._finish_event
        if event:
            event.set()

    def _emit_change(self) -> None:
        if not self._on_change:
            return
        with self._lock:
            current = self._current
        self._on_change(current)

