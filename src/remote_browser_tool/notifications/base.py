"""Notification channels for the remote browser tool."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

from rich.console import Console

from ..models import NotificationEvent


class Notifier(ABC):
    """Interface for sending notifications about orchestrator events."""

    @abstractmethod
    def notify(self, event: NotificationEvent) -> None:
        """Send a notification event."""


class ConsoleNotifier(Notifier):
    """Simple notifier that prints to the console using Rich."""

    def __init__(self) -> None:
        self._console = Console()

    def notify(self, event: NotificationEvent) -> None:
        style = {
            "info": "cyan",
            "warning": "yellow",
            "error": "red",
            "success": "green",
        }.get(event.level.value, "white")
        self._console.print(f"[{event.level.value.upper()}] {event.message}", style=style)
        if event.data:
            self._console.print(event.data, style="dim")


class CompositeNotifier(Notifier):
    """Fan-out notifier that propagates events to multiple notifiers."""

    def __init__(self, notifiers: Iterable[Notifier]) -> None:
        self._notifiers = list(notifiers)

    def notify(self, event: NotificationEvent) -> None:
        for notifier in self._notifiers:
            notifier.notify(event)

