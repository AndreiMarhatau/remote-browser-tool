"""Configuration models for remote browser tool."""

from __future__ import annotations

from collections.abc import Mapping
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

    model_config = SettingsConfigDict(
        env_prefix="REMOTE_BROWSER_TOOL_",
        env_file=(".env",),
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
    )

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


def load_config(
    path: Path | None = None,
    *,
    env_file: Path | None = None,
    **overrides: object,
) -> RunnerConfig:
    """Load configuration from an optional file and overrides."""

    data: dict[str, Any] = {}
    if path:
        import yaml

        data = yaml.safe_load(path.read_text()) or {}
    if overrides:
        _deep_update(data, overrides)
    settings_kwargs: dict[str, object] = {}
    if env_file is not None:
        settings_kwargs["_env_file"] = env_file
    config = RunnerConfig(**data, **settings_kwargs)
    if not data:
        return config

    merged = config.model_dump(mode="python")
    _deep_update(merged, data)
    return RunnerConfig.model_validate(merged)


def _deep_update(target: dict[str, Any], updates: Mapping[str, Any]) -> None:
    """Recursively merge ``updates`` into ``target`` in-place."""

    for key, value in updates.items():
        if (
            isinstance(value, Mapping)
            and isinstance(existing := target.get(key), Mapping)
        ):
            nested: dict[str, Any]
            if isinstance(existing, dict):
                nested = existing
            else:
                nested = dict(existing)
            _deep_update(nested, value)
            target[key] = nested
        else:
            target[key] = value

