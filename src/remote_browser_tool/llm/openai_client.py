"""LLM client for OpenAI-compatible chat completion endpoints."""

from __future__ import annotations

import httpx

from ..config import LLMConfig
from ..models import LLMDirective
from .base import ConversationTurn, LLMClient, LLMContext
from .json_parser import parse_directive

_DEFAULT_SYSTEM_PROMPT = (
    "You are an automation agent that controls a web browser. "
    "Always respond with a strict JSON object describing the next actions to take."
)


class OpenAIChatLLM(LLMClient):
    """Call an OpenAI-compatible chat completion API to obtain directives."""

    def __init__(self, config: LLMConfig) -> None:
        if not config.model:
            raise ValueError("LLM model must be specified for OpenAIChatLLM")
        self._config = config
        headers = {"Content-Type": "application/json"}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        self._client = httpx.Client(
            base_url=config.base_url or "https://api.openai.com/v1",
            timeout=config.parameters.get("timeout", 60),
            headers=headers,
        )
        self._system_prompt = config.parameters.get("system_prompt", _DEFAULT_SYSTEM_PROMPT)
        self._temperature = config.parameters.get("temperature", 0.0)

    def complete(self, prompt: str, context: LLMContext) -> LLMDirective:
        messages = self._build_messages(prompt, context)
        payload = {
            "model": self._config.model,
            "messages": messages,
            "temperature": self._temperature,
        }
        payload.update(
            {
                k: v
                for k, v in self._config.parameters.items()
                if k not in {"timeout", "system_prompt", "temperature"}
            }
        )
        response = self._client.post("/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:  # pragma: no cover - defensive
            raise ValueError(f"Unexpected response format: {data}") from exc
        return parse_directive(content)

    def start_conversation(self) -> list[ConversationTurn]:
        return [ConversationTurn(role="system", content=self._system_prompt)]

    def _build_messages(self, prompt: str, context: LLMContext) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        for turn in context.history:
            messages.append({"role": turn.role, "content": turn.content})
        if not any(turn.role == "user" and turn.content == prompt for turn in context.history):
            messages.append({"role": "user", "content": prompt})
        return messages


