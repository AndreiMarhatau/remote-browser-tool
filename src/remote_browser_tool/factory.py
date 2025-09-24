"""Factories for constructing components from configuration."""

from __future__ import annotations

from .browser.playwright_session import PlaywrightBrowserSession
from .config import BrowserConfig, LLMConfig, NotificationConfig, PortalConfig, RunnerConfig
from .llm.base import LLMClient
from .llm.mock import ScriptedLLM
from .llm.openai_client import OpenAIChatLLM
from .memory.base import InMemoryStore, MemoryStore
from .models import LLMDirective
from .notifications.base import ConsoleNotifier, Notifier
from .user_portal.http import SimpleHTTPUserPortal


def build_llm(config: LLMConfig) -> LLMClient:
    provider = config.provider.lower()
    if provider in {"openai", "azure", "openai-compatible"}:
        return OpenAIChatLLM(config)
    if provider == "mock":
        directives = [
            LLMDirective.model_validate(item)
            for item in config.parameters.get("responses", [])
        ]
        return ScriptedLLM(directives)
    raise ValueError(f"Unsupported LLM provider: {config.provider}")


def build_browser(config: BrowserConfig) -> PlaywrightBrowserSession:
    return PlaywrightBrowserSession(config)


def build_memory(config: RunnerConfig) -> MemoryStore:
    return InMemoryStore(max_entries=config.memory_max_entries)


def build_notifier(config: NotificationConfig) -> Notifier:
    channel = config.channel.lower()
    if channel == "console":
        return ConsoleNotifier()
    raise ValueError(f"Unsupported notification channel: {config.channel}")


def build_portal(config: PortalConfig) -> SimpleHTTPUserPortal:
    return SimpleHTTPUserPortal(host=config.host, port=config.port)


