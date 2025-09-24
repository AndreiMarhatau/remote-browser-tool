"""Interfaces for handing control over to human users."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from ..browser.vnc import VNCConnectionInfo
from ..models import NotificationEvent, UserInterventionRequest


class UserInteractionPortal(ABC):
    """Abstract interface to coordinate manual user steps."""

    @abstractmethod
    def start(self) -> None:
        """Start serving the portal (if required)."""

    @abstractmethod
    def stop(self) -> None:
        """Stop serving the portal."""

    @abstractmethod
    def update_connection_info(self, info: Optional[VNCConnectionInfo]) -> None:
        """Update the VNC connection information presented to the user."""

    @abstractmethod
    def request_intervention(self, request: UserInterventionRequest) -> NotificationEvent:
        """Return a notification event describing how to reach the portal."""

    @abstractmethod
    def wait_until_finished(self, timeout: Optional[float] = None) -> bool:
        """Block until the user indicates the manual step is completed."""

