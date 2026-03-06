"""Simple in-memory TTL cache (no Redis required).

Used by GrowwService to avoid redundant API calls within the same polling window.
Thread-safe via asyncio (single-threaded event loop).
"""

import time
from typing import Any, Optional


class TTLCache:
    """In-memory key-value cache with per-entry TTL expiration.

    Usage:
        cache = TTLCache(default_ttl=8)
        cache.set("NSE_RELIANCE", 2847.5)
        price = cache.get("NSE_RELIANCE")   # None if expired
    """

    def __init__(self, default_ttl: float = 8.0) -> None:
        self._store: dict[str, tuple[Any, float]] = {}  # key -> (value, expires_at)
        self.default_ttl = default_ttl

    def get(self, key: str) -> Optional[Any]:
        """Return cached value or None if missing/expired."""
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.monotonic() > expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """Store a value with optional custom TTL (seconds)."""
        ttl = ttl if ttl is not None else self.default_ttl
        self._store[key] = (value, time.monotonic() + ttl)

    def set_many(self, mapping: dict[str, Any], ttl: Optional[float] = None) -> None:
        """Batch store multiple key-value pairs."""
        for key, value in mapping.items():
            self.set(key, value, ttl)

    def invalidate(self, key: str) -> None:
        """Remove a specific key from the cache."""
        self._store.pop(key, None)

    def clear(self) -> None:
        """Clear all cached entries."""
        self._store.clear()

    def size(self) -> int:
        """Return number of non-expired entries."""
        now = time.monotonic()
        return sum(1 for _, expires_at in self._store.values() if expires_at > now)
