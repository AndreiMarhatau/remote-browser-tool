"""Browser session abstractions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from ..models import BrowserAction


@dataclass
class BrowserState:
    """Snapshot of the browser state used for prompting the LLM."""

    url: Optional[str] = None
    title: Optional[str] = None
    last_action: Optional[str] = None


class BrowserActionError(RuntimeError):
    """Raised when executing a browser action fails."""


class BrowserSession(ABC):
    """Interface for an automation-capable browser session."""

    @abstractmethod
    def start(self) -> None:
        """Launch the browser session."""

    @abstractmethod
    def stop(self) -> None:
        """Terminate the browser session."""

    @abstractmethod
    def execute(self, action: BrowserAction) -> BrowserState:
        """Execute a browser action and return the resulting state."""

    @abstractmethod
    def snapshot(self) -> BrowserState:
        """Return the current state for context."""

