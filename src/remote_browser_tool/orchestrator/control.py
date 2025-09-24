"""Utilities for coordinating manual control of the orchestrator."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from ..models import UserInterventionRequest


@dataclass
class ManualPauseRequest:
    """Record describing a manual pause request issued by an admin."""

    request: UserInterventionRequest
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ManualPauseController:
    """Coordinate manual pause/resume requests coming from outside the orchestrator."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: Optional[ManualPauseRequest] = None
        self._active: Optional[ManualPauseRequest] = None

    def request_pause(
        self,
        *,
        reason: str,
        instructions: str,
        metadata: Optional[dict[str, str]] = None,
    ) -> bool:
        """Queue a pause request if none is currently being handled."""

        with self._lock:
            if self._pending or self._active:
                return False
            payload = UserInterventionRequest(
                reason=reason,
                instructions=instructions,
                metadata={"source": "manual_pause", **(metadata or {})},
            )
            self._pending = ManualPauseRequest(request=payload)
            return True

    def consume_pending(self) -> Optional[ManualPauseRequest]:
        """Return the next pending request, marking it active."""

        with self._lock:
            if not self._pending:
                return None
            self._active = self._pending
            self._pending = None
            return self._active

    def get_active(self) -> Optional[ManualPauseRequest]:
        with self._lock:
            return self._active

    def clear_active(self) -> None:
        with self._lock:
            self._active = None

    def snapshot(self) -> Optional[ManualPauseRequest]:
        """Return pending or active request information without mutating state."""

        with self._lock:
            return self._pending or self._active
