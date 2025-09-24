import socket
import threading
import time

import httpx

from remote_browser_tool.models import UserInterventionRequest
from remote_browser_tool.user_portal.http import SimpleHTTPUserPortal


def _find_free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def test_user_portal_request_and_finish():
    port = _find_free_port()
    portal = SimpleHTTPUserPortal(host="127.0.0.1", port=port)
    portal.start()
    try:
        request = UserInterventionRequest(reason="captcha", instructions="solve it")
        event = portal.request_intervention(request)
        assert "portal_url" in event.data
        client = httpx.Client()
        try:
            response = client.get(f"http://127.0.0.1:{port}/")
            assert response.status_code == 200
            assert "Manual action required" in response.text

            wait_result = {}

            def waiter() -> None:
                wait_result["value"] = portal.wait_until_finished(timeout=5)

            thread = threading.Thread(target=waiter)
            thread.start()
            time.sleep(0.2)
            finish_response = client.post(f"http://127.0.0.1:{port}/finish")
            assert finish_response.status_code == 200
            thread.join(timeout=2)
            assert wait_result.get("value") is True
        finally:
            client.close()
    finally:
        portal.stop()

