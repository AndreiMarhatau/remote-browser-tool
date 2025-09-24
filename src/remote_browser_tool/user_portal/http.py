"""HTTP-based portal for manual user interventions."""

from __future__ import annotations

import html
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from ..browser.vnc import VNCConnectionInfo
from ..models import NotificationEvent, NotificationLevel, UserInterventionRequest
from .base import UserInteractionPortal


class SimpleHTTPUserPortal(UserInteractionPortal):
    """Serve a lightweight HTTP page with a finish button for manual steps."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8765) -> None:
        self._host = host
        self._port = port
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._current_request: Optional[UserInterventionRequest] = None
        self._finish_event: Optional[threading.Event] = None
        self._connection_info: Optional[VNCConnectionInfo] = None

    def start(self) -> None:
        if self._server:
            return
        handler = self._build_handler()
        self._server = ThreadingHTTPServer((self._host, self._port), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        if self._thread:
            self._thread.join(timeout=2)
        self._server = None
        self._thread = None
        with self._lock:
            self._current_request = None
            self._finish_event = None

    def update_connection_info(self, info: Optional[VNCConnectionInfo]) -> None:
        with self._lock:
            self._connection_info = info

    def request_intervention(self, request: UserInterventionRequest) -> NotificationEvent:
        with self._lock:
            self._current_request = request
            self._finish_event = threading.Event()
        url = f"http://{self._host}:{self._port}/"
        data = {
            "portal_url": url,
            "reason": request.reason,
            "instructions": request.instructions,
        }
        if self._connection_info:
            data["vnc"] = {
                "host": self._connection_info.host,
                "port": self._connection_info.port,
                "display": self._connection_info.display,
            }
        return NotificationEvent(
            type="user_action_required",
            message=f"Manual intervention requested: {request.reason}",
            level=NotificationLevel.WARNING,
            data=data,
        )

    def wait_until_finished(self, timeout: Optional[float] = None) -> bool:
        with self._lock:
            event = self._finish_event
        if not event:
            return False
        result = event.wait(timeout)
        if result:
            with self._lock:
                self._current_request = None
                self._finish_event = None
        return result

    # Internal helpers -------------------------------------------------

    def _build_handler(self) -> type[BaseHTTPRequestHandler]:
        portal = self

        class PortalHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 (name required by BaseHTTPRequestHandler)
                if self.path not in {"/", "/index.html"}:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                portal._handle_get(self)

            def do_POST(self) -> None:  # noqa: N802
                if self.path == "/finish":
                    portal._handle_finish(self)
                else:
                    self.send_error(HTTPStatus.NOT_FOUND)

            def log_message(self, format: str, *args) -> None:  # noqa: A003 - signature fixed
                return  # Suppress default logging

        return PortalHandler

    def _handle_get(self, handler: BaseHTTPRequestHandler) -> None:
        with self._lock:
            request = self._current_request
            info = self._connection_info
        if not request:
            handler.send_response(HTTPStatus.OK)
            handler.send_header("Content-Type", "text/html; charset=utf-8")
            handler.end_headers()
            handler.wfile.write(
                b"<html><body><h1>No manual action currently required.</h1></body></html>"
            )
            return
        page = self._render_page(request, info)
        handler.send_response(HTTPStatus.OK)
        handler.send_header("Content-Type", "text/html; charset=utf-8")
        handler.end_headers()
        handler.wfile.write(page.encode("utf-8"))

    def _handle_finish(self, handler: BaseHTTPRequestHandler) -> None:
        with self._lock:
            event = self._finish_event
        if not event:
            handler.send_error(HTTPStatus.BAD_REQUEST, "No active intervention")
            return
        event.set()
        handler.send_response(HTTPStatus.OK)
        handler.send_header("Content-Type", "text/html; charset=utf-8")
        handler.end_headers()
        handler.wfile.write(
            b"<html><body><h1>Thank you!</h1><p>You may close this window.</p></body></html>"
        )

    def _render_page(
        self,
        request: UserInterventionRequest,
        info: Optional[VNCConnectionInfo],
    ) -> str:
        instructions = html.escape(request.instructions)
        reason = html.escape(request.reason)
        vnc_block = ""
        if info:
            vnc_block = (
                f"<h2>VNC Connection</h2><p>Host: {html.escape(info.host)}<br/>"
                f"Port: {info.port}<br/>Display: {html.escape(info.display)}</p>"
            )
        return f"""
        <html>
          <head>
            <title>Manual step required</title>
          </head>
          <body>
            <h1>Manual action required</h1>
            <p><strong>Reason:</strong> {reason}</p>
            <p><strong>Instructions:</strong> {instructions}</p>
            {vnc_block}
            <form action="/finish" method="post">
              <button type="submit" style="padding: 1em; font-size: 1.2em;">Finished</button>
            </form>
          </body>
        </html>
        """


