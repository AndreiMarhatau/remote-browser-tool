"""Utilities to expose the Playwright browser via VNC."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional

from pyvirtualdisplay import Display

LOGGER = logging.getLogger(__name__)


@dataclass
class VNCConnectionInfo:
    """Details for connecting to the VNC server."""

    host: str
    port: int
    display: str


class VNCManager:
    """Manage a virtual display and VNC server lifecycle."""

    def __init__(
        self,
        enabled: bool = True,
        width: int = 1920,
        height: int = 1080,
        host: str = "127.0.0.1",
        port: Optional[int] = None,
    ) -> None:
        self.enabled = enabled
        self._width = width
        self._height = height
        self._host = host
        self._port = port
        self._display: Optional[Display] = None
        self._vnc_process: Optional[subprocess.Popen[str]] = None
        self._connection_info: Optional[VNCConnectionInfo] = None

    def __enter__(self) -> Optional[VNCConnectionInfo]:
        self.start()
        return self._connection_info

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()

    def start(self) -> Optional[VNCConnectionInfo]:
        if not self.enabled:
            LOGGER.info("VNC is disabled; continuing without a virtual display")
            return None
        if shutil.which("x11vnc") is None:
            LOGGER.warning("x11vnc not found; disabling VNC support")
            self.enabled = False
            return None
        LOGGER.debug("Starting virtual display for VNC")
        self._display = Display(visible=False, size=(self._width, self._height))
        self._display.start()
        display_var = os.environ.get("DISPLAY")
        if not display_var:
            raise RuntimeError(
                "DISPLAY environment variable missing after starting virtual display"
            )
        display_number = display_var.lstrip(":")
        port = self._port or 5900 + int(display_number)
        LOGGER.debug("Launching x11vnc on display %s port %s", display_var, port)
        args = [
            "x11vnc",
            "-display",
            display_var,
            "-rfbport",
            str(port),
            "-forever",
            "-shared",
            "-nopw",
            "-quiet",
        ]
        self._vnc_process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self._connection_info = VNCConnectionInfo(host=self._host, port=port, display=display_var)
        return self._connection_info

    def stop(self) -> None:
        if self._vnc_process and self._vnc_process.poll() is None:
            LOGGER.debug("Terminating x11vnc process")
            self._vnc_process.terminate()
            try:
                self._vnc_process.wait(timeout=5)
            except subprocess.TimeoutExpired:  # pragma: no cover - defensive code
                self._vnc_process.kill()
        if self._display:
            LOGGER.debug("Stopping virtual display")
            self._display.stop()
        self._display = None
        self._vnc_process = None
        self._connection_info = None

    @property
    def connection_info(self) -> Optional[VNCConnectionInfo]:
        return self._connection_info

