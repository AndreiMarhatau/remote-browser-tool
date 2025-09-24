"""Helpers for recording task activity for the admin portal."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Protocol

from ..browser.base import BrowserSession, BrowserState
from ..memory.base import MemoryStore
from ..models import BrowserAction, MemoryEntry, NotificationEvent
from ..notifications.base import Notifier

LOGGER = logging.getLogger(__name__)


class TaskInstrumentation(Protocol):
    """Protocol for receiving task lifecycle callbacks."""

    def on_action(
        self,
        action: BrowserAction,
        state: BrowserState,
        screenshot: Optional[bytes],
    ) -> None:
        """Record that a browser action executed."""

    def on_memory(self, entry: MemoryEntry) -> None:
        """Record a memory entry added by the orchestrator."""

    def on_notification(self, event: NotificationEvent) -> None:
        """Record a notification emitted by the orchestrator."""


@dataclass
class NullInstrumentation:
    """No-op implementation used when no recorder is configured."""

    def on_action(
        self,
        action: BrowserAction,
        state: BrowserState,
        screenshot: Optional[bytes],
    ) -> None:  # noqa: D401 - documentation inherited
        return

    def on_memory(self, entry: MemoryEntry) -> None:  # noqa: D401
        return

    def on_notification(self, event: NotificationEvent) -> None:  # noqa: D401
        return


class InstrumentedBrowserSession(BrowserSession):
    """Browser session wrapper that reports executed actions."""

    def __init__(
        self,
        inner: BrowserSession,
        *,
        instrumentation: Optional[TaskInstrumentation] = None,
        capture_screenshots: bool = False,
    ) -> None:
        self._inner = inner
        self._instrumentation = instrumentation or NullInstrumentation()
        self._capture_screenshots = capture_screenshots

    def start(self) -> None:
        self._inner.start()

    def stop(self) -> None:
        self._inner.stop()

    def execute(self, action: BrowserAction) -> BrowserState:
        state = self._inner.execute(action)
        screenshot: Optional[bytes] = None
        if self._capture_screenshots:
            try:
                screenshot = self._inner.screenshot()
            except Exception:  # pragma: no cover - defensive path
                LOGGER.exception("Failed to capture screenshot after action %s", action)
        self._instrumentation.on_action(action, state, screenshot)
        return state

    def snapshot(self) -> BrowserState:
        return self._inner.snapshot()

    def screenshot(self) -> bytes:
        return self._inner.screenshot()


class InstrumentedMemoryStore(MemoryStore):
    """Memory store wrapper that reports added entries."""

    def __init__(
        self,
        inner: MemoryStore,
        *,
        instrumentation: Optional[TaskInstrumentation] = None,
    ) -> None:
        self._inner = inner
        self._instrumentation = instrumentation or NullInstrumentation()

    def add(self, entry: MemoryEntry) -> None:
        self._inner.add(entry)
        self._instrumentation.on_memory(entry)

    def get(self) -> List[MemoryEntry]:
        return self._inner.get()

    def prune(self, max_entries: int) -> None:
        self._inner.prune(max_entries)


class InstrumentedNotifier(Notifier):
    """Notifier wrapper that records emitted events."""

    def __init__(
        self,
        inner: Notifier,
        *,
        instrumentation: Optional[TaskInstrumentation] = None,
    ) -> None:
        self._inner = inner
        self._instrumentation = instrumentation or NullInstrumentation()

    def notify(self, event: NotificationEvent) -> None:
        self._instrumentation.on_notification(event)
        self._inner.notify(event)
