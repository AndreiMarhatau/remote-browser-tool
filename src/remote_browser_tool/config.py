"""Configuration models for remote browser tool."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMConfig(BaseModel):
    """Settings for the LLM provider."""

    provider: str = Field(default="local")
    model: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class BrowserConfig(BaseModel):
    """Settings for the browser backend."""

    profile_path: Optional[Path] = None
    headless: bool = False
    enable_vnc: bool = True
    viewport_width: int = 1280
    viewport_height: int = 720
    vnc_host: str = "127.0.0.1"
    vnc_port: Optional[int] = None


class NotificationConfig(BaseModel):
    """Notification channel settings."""

    channel: str = Field(default="console")
    target: Optional[str] = None
    options: dict[str, Any] = Field(default_factory=dict)


class PortalConfig(BaseModel):
    """Settings for the user interaction portal."""

    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8765)


class TaskConfig(BaseModel):
    """Task definition provided by the user."""

    description: str
    goal: Optional[str] = None


class RunnerConfig(BaseSettings):
    """Top-level configuration for running the orchestrator."""

    model_config = SettingsConfigDict(env_prefix="REMOTE_BROWSER_TOOL_")

    task: TaskConfig
    llm: LLMConfig = Field(default_factory=LLMConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    notifications: NotificationConfig = Field(default_factory=NotificationConfig)
    portal: PortalConfig = Field(default_factory=PortalConfig)
    wait_for_user_timeout: Optional[float] = Field(
        default=None,
        description="Optional timeout (in seconds) for waiting on manual user steps.",
    )
    memory_max_entries: int = Field(default=50)


def load_config(path: Path | None = None, **overrides: object) -> RunnerConfig:
    """Load configuration from an optional file and overrides."""

    data: dict[str, object] = {}
    if path:
        import yaml

        data = yaml.safe_load(path.read_text()) or {}
    data.update(overrides)
    return RunnerConfig.model_validate(data)

