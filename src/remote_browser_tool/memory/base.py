"""Memory storage abstractions for the agent."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from ..models import MemoryEntry


class MemoryStore(ABC):
    """Interface for storing and retrieving agent memory entries."""

    @abstractmethod
    def add(self, entry: MemoryEntry) -> None:
        """Persist a memory entry."""

    @abstractmethod
    def get(self) -> List[MemoryEntry]:
        """Return a list of stored memory entries."""

    @abstractmethod
    def prune(self, max_entries: int) -> None:
        """Optionally prune memory entries to a maximum count."""


class InMemoryStore(MemoryStore):
    """Simple in-memory store useful for testing."""

    def __init__(self, max_entries: int = 30) -> None:
        self._entries: List[MemoryEntry] = []
        self._max_entries = max_entries

    def add(self, entry: MemoryEntry) -> None:
        self._entries.append(entry)
        self.prune(self._max_entries)

    def get(self) -> List[MemoryEntry]:
        return list(self._entries)

    def prune(self, max_entries: int) -> None:
        if max_entries <= 0:
            self._entries.clear()
            return
        overflow = len(self._entries) - max_entries
        if overflow > 0:
            self._entries = self._entries[overflow:]

