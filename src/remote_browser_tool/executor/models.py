"""Data structures used by the executor service."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import List, Optional

from ..browser.base import BrowserState
from ..browser.vnc import VNCConnectionInfo
from ..models import BrowserAction, MemoryEntry, NotificationEvent, UserInterventionRequest


class TaskStatus(str, Enum):
    """Lifecycle states for executor tasks."""

    PENDING = "pending"
    RUNNING = "running"
    WAITING_FOR_USER = "waiting_for_user"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TaskLogEntry:
    """Notification emitted during task execution."""

    event: NotificationEvent


@dataclass
class TaskActionRecord:
    """Record of a browser action executed by the orchestrator."""

    index: int
    action: BrowserAction
    resulting_state: BrowserState
    screenshot_path: Optional[Path] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class TaskData:
    """Aggregated data captured for a running or finished task."""

    id: str
    description: str
    goal: Optional[str]
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    logs: List[TaskLogEntry] = field(default_factory=list)
    actions: List[TaskActionRecord] = field(default_factory=list)
    memory: List[MemoryEntry] = field(default_factory=list)
    current_request: Optional[UserInterventionRequest] = None
    current_request_started_at: Optional[datetime] = None
    connection_info: Optional[VNCConnectionInfo] = None
    error: Optional[str] = None
