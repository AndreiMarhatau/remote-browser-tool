"""Shared models used across the remote browser tool."""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field


class BrowserActionType(str, enum.Enum):
    """Enumerated browser commands that the orchestrator can execute."""

    NAVIGATE = "navigate"
    CLICK = "click"
    TYPE = "type"
    WAIT_FOR_SELECTOR = "wait_for_selector"
    WAIT = "wait"
    SCROLL = "scroll"


class BrowserAction(BaseModel):
    """An instruction for the browser session to execute."""

    type: BrowserActionType
    selector: Optional[str] = None
    text: Optional[str] = None
    url: Optional[str] = None
    seconds: Optional[float] = None
    description: Optional[str] = None
    timeout: Optional[float] = Field(default=None, description="Optional timeout for waits")
    scroll_by: Optional[int] = Field(
        default=None,
        description="Number of pixels to scroll vertically (positive = down).",
    )


class MemoryEntry(BaseModel):
    """Item stored in the agent memory."""

    content: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    importance: Optional[float] = Field(default=None, description="Optional ranking for pruning.")


class UserInterventionRequest(BaseModel):
    """Information for requesting a user to take over the browser."""

    reason: str
    instructions: str
    allow_finish_without_return: bool = Field(
        default=False,
        description="If True, orchestrator may finish without waiting for manual return.",
    )


class DirectiveStatus(str, enum.Enum):
    """Status returned by the LLM after producing a directive."""

    CONTINUE = "continue"
    WAIT_FOR_USER = "wait_for_user"
    WAIT = "wait"
    FINISHED = "finished"
    FAILED = "failed"


class LLMDirective(BaseModel):
    """Structured response from the LLM planner."""

    status: DirectiveStatus = DirectiveStatus.CONTINUE
    actions: list[BrowserAction] = Field(default_factory=list)
    wait_seconds: Optional[float] = None
    user_request: Optional[UserInterventionRequest] = None
    memory_to_write: list[str] = Field(default_factory=list)
    message: Optional[str] = Field(default=None, description="Human-readable summary of the step.")
    failure_reason: Optional[str] = None


class NotificationLevel(str, enum.Enum):
    """Severity of notification events."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    SUCCESS = "success"


class NotificationEvent(BaseModel):
    """Event emitted to notify users."""

    type: str
    message: str
    level: NotificationLevel = NotificationLevel.INFO
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

