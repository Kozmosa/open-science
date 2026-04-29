from __future__ import annotations

import time
from collections import OrderedDict

from ainrf.files.models import DirectoryListing


class FileTreeCache:
    """In-memory LRU cache with TTL for directory listings."""

    def __init__(self, ttl_seconds: float = 60.0, max_entries: int = 500) -> None:
        self._ttl = ttl_seconds
        self._max = max_entries
        self._store: OrderedDict[str, tuple[float, DirectoryListing]] = OrderedDict()

    def get(self, key: str) -> DirectoryListing | None:
        now = time.monotonic()
        if key not in self._store:
            return None
        inserted_at, value = self._store[key]
        if now - inserted_at > self._ttl:
            del self._store[key]
            return None
        self._store.move_to_end(key)
        return value

    def set(self, key: str, value: DirectoryListing) -> None:
        now = time.monotonic()
        self._store[key] = (now, value)
        self._store.move_to_end(key)
        if len(self._store) > self._max:
            self._store.popitem(last=False)

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)

    def invalidate_environment(self, environment_id: str) -> None:
        prefix = f"{environment_id}:"
        for key in list(self._store):
            if key.startswith(prefix):
                del self._store[key]
