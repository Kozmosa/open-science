from __future__ import annotations

import time

from ainrf.files.cache import FileTreeCache
from ainrf.files.models import DirectoryListing


def test_cache_returns_none_for_missing_key() -> None:
    cache = FileTreeCache(ttl_seconds=60.0)
    assert cache.get("foo") is None


def test_cache_stores_and_retrieves() -> None:
    cache = FileTreeCache(ttl_seconds=60.0)
    listing = DirectoryListing(path="/workspace", entries=[])
    cache.set("foo", listing)
    assert cache.get("foo") is listing


def test_cache_expires_after_ttl() -> None:
    cache = FileTreeCache(ttl_seconds=0.1)
    listing = DirectoryListing(path="/workspace", entries=[])
    cache.set("foo", listing)
    assert cache.get("foo") is listing
    time.sleep(0.15)
    assert cache.get("foo") is None


def test_cache_lru_eviction() -> None:
    cache = FileTreeCache(ttl_seconds=60.0, max_entries=2)
    cache.set("a", DirectoryListing(path="/a", entries=[]))
    cache.set("b", DirectoryListing(path="/b", entries=[]))
    cache.set("c", DirectoryListing(path="/c", entries=[]))
    assert cache.get("a") is None
    assert cache.get("b") is not None
    assert cache.get("c") is not None


def test_cache_invalidate_by_key() -> None:
    cache = FileTreeCache(ttl_seconds=60.0)
    cache.set("a", DirectoryListing(path="/a", entries=[]))
    cache.invalidate("a")
    assert cache.get("a") is None


def test_cache_invalidate_by_environment() -> None:
    cache = FileTreeCache(ttl_seconds=60.0)
    cache.set("env-1:/a", DirectoryListing(path="/a", entries=[]))
    cache.set("env-1:/b", DirectoryListing(path="/b", entries=[]))
    cache.set("env-2:/a", DirectoryListing(path="/a", entries=[]))
    cache.invalidate_environment("env-1")
    assert cache.get("env-1:/a") is None
    assert cache.get("env-1:/b") is None
    assert cache.get("env-2:/a") is not None
