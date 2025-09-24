"""Playwright-powered browser session implementation."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from playwright.sync_api import Error, sync_playwright

from ..config import BrowserConfig
from ..models import BrowserAction, BrowserActionType
from .base import BrowserActionError, BrowserSession, BrowserState

LOGGER = logging.getLogger(__name__)


class PlaywrightBrowserSession(BrowserSession):
    """Browser session backed by Playwright."""

    def __init__(self, config: Optional[BrowserConfig] = None) -> None:
        self._config = config or BrowserConfig()
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    def start(self) -> None:
        LOGGER.debug("Starting Playwright browser session")
        self._playwright = sync_playwright().start()
        launch_kwargs = {
            "headless": self._config.headless,
            "args": [
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        }
        user_data_dir: Optional[Path] = self._config.profile_path
        viewport = {"width": self._config.viewport_width, "height": self._config.viewport_height}
        if user_data_dir:
            user_data_dir.mkdir(parents=True, exist_ok=True)
            self._context = self._playwright.chromium.launch_persistent_context(
                str(user_data_dir),
                **launch_kwargs,
                viewport=viewport,
            )
            pages = self._context.pages
            self._page = pages[0] if pages else self._context.new_page()
        else:
            self._browser = self._playwright.chromium.launch(**launch_kwargs)
            self._context = self._browser.new_context(viewport=viewport)
            self._page = self._context.new_page()

    def stop(self) -> None:
        LOGGER.debug("Stopping Playwright browser session")
        try:
            if self._context:
                self._context.close()
        finally:
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.stop()
        self._context = None
        self._browser = None
        self._playwright = None
        self._page = None

    def execute(self, action: BrowserAction) -> BrowserState:
        if not self._page:
            raise BrowserActionError("Browser session is not started")
        LOGGER.info("Executing browser action %s", action)
        try:
            if action.type == BrowserActionType.NAVIGATE:
                if not action.url:
                    raise BrowserActionError("Navigate action requires a URL")
                self._page.goto(action.url, wait_until="load")
            elif action.type == BrowserActionType.CLICK:
                if not action.selector:
                    raise BrowserActionError("Click action requires a selector")
                self._page.click(action.selector, timeout=_to_timeout(action.timeout))
            elif action.type == BrowserActionType.TYPE:
                if not action.selector:
                    raise BrowserActionError("Type action requires a selector")
                if action.text is None:
                    raise BrowserActionError("Type action requires text")
                self._page.fill(action.selector, action.text, timeout=_to_timeout(action.timeout))
            elif action.type == BrowserActionType.WAIT_FOR_SELECTOR:
                if not action.selector:
                    raise BrowserActionError("Wait action requires a selector")
                self._page.wait_for_selector(
                    action.selector,
                    timeout=_to_timeout(action.timeout),
                )
            elif action.type == BrowserActionType.WAIT:
                seconds = action.seconds or 0.0
                self._page.wait_for_timeout(seconds * 1000)
            elif action.type == BrowserActionType.SCROLL:
                delta = action.scroll_by or 0
                self._page.mouse.wheel(0, delta)
            else:
                raise BrowserActionError(f"Unsupported action type: {action.type}")
        except Error as exc:  # pragma: no cover - Playwright exception path
            raise BrowserActionError(str(exc)) from exc
        return self.snapshot()

    def snapshot(self) -> BrowserState:
        if not self._page:
            raise BrowserActionError("Browser session is not started")
        return BrowserState(
            url=self._page.url,
            title=self._page.title(),
            last_action=self._page.evaluate("document.activeElement?.outerHTML") or None,
        )


def _to_timeout(timeout: Optional[float]) -> Optional[int]:
    if timeout is None:
        return None
    return int(timeout * 1000)


