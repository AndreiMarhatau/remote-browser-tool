"""Base classes and utilities for LLM integrations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable, List

from ..models import LLMDirective, MemoryEntry


@dataclass
class ConversationTurn:
    """Represents a single exchange between the orchestrator and the LLM."""

    role: str
    content: str


@dataclass
class LLMContext:
    """Information passed to the LLM on every turn."""

    task_description: str
    memory: Iterable[MemoryEntry]
    history: Iterable[ConversationTurn]


class LLMClient(ABC):
    """Abstract interface for LLM providers."""

    @abstractmethod
    def complete(self, prompt: str, context: LLMContext) -> LLMDirective:
        """Return the next directive for the orchestrator.

        Implementations may translate the prompt/context into API calls. They must
        return a structured :class:`LLMDirective`.
        """

    @abstractmethod
    def start_conversation(self) -> List[ConversationTurn]:
        """Return the initial conversation history to seed prompts if needed."""


class StaticResponseLLM(LLMClient):
    """A trivial LLM client that always returns a predefined directive.

    Useful for tests and for wiring the orchestrator without calling a real LLM.
    """

    def __init__(self, directive: LLMDirective) -> None:
        self._directive = directive

    def complete(self, prompt: str, context: LLMContext) -> LLMDirective:
        return self._directive

    def start_conversation(self) -> List[ConversationTurn]:
        return []

