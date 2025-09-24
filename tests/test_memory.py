from datetime import UTC, datetime

from remote_browser_tool.memory.base import InMemoryStore
from remote_browser_tool.models import MemoryEntry


def test_in_memory_store_prunes_to_max_entries():
    store = InMemoryStore(max_entries=3)
    for idx in range(5):
        store.add(MemoryEntry(content=f"entry-{idx}", created_at=datetime.now(UTC)))
    entries = store.get()
    assert len(entries) == 3
    assert [entry.content for entry in entries] == ["entry-2", "entry-3", "entry-4"]

