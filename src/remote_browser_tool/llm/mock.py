"""Mock LLM clients for testing and offline use."""

from __future__ import annotations

from collections import deque
from typing import Deque, Iterable

from ..models import LLMDirective
from .base import ConversationTurn, LLMClient, LLMContext


class ScriptedLLM(LLMClient):
    """Return directives from a predefined sequence."""

    def __init__(self, directives: Iterable[LLMDirective]) -> None:
        self._directives: Deque[LLMDirective] = deque(directives)

    def complete(self, prompt: str, context: LLMContext) -> LLMDirective:
        if not self._directives:
            raise RuntimeError("ScriptedLLM ran out of directives")
        return self._directives.popleft()

    def start_conversation(self) -> list[ConversationTurn]:
        return []


