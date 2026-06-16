"""In-memory user presence tracking for online-status indicators.

Tracks the last activity time of each authenticated user so the admin
panel can show who is currently online.  Activity is recorded on every
authenticated API request (via the JWT middleware) — no extra database
writes are needed.

Uses ``time.monotonic()`` to be immune to system-clock changes and a
``threading.Lock`` for safe concurrent access (same pattern as the
Prometheus metrics module).
"""

from __future__ import annotations

import threading
import time

# ── Configuration ──────────────────────────────────────────────────────────

# A user is considered "online" if their last activity was within this window.
_ACTIVITY_THRESHOLD_SEC: float = 300.0  # 5 minutes

# ── State ──────────────────────────────────────────────────────────────────

_last_active: dict[str, float] = {}  # user_id → time.monotonic() timestamp
_lock = threading.Lock()


# ── Public API ─────────────────────────────────────────────────────────────


def record_activity(user_id: str) -> None:
    """Record that *user_id* was active right now.

    Should be called by the JWT auth middleware after successfully
    authenticating a request.
    """
    with _lock:
        _last_active[user_id] = time.monotonic()


def is_online(user_id: str, threshold_seconds: float = _ACTIVITY_THRESHOLD_SEC) -> bool:
    """Return ``True`` if *user_id* has been active within *threshold_seconds*."""
    with _lock:
        ts = _last_active.get(user_id)
    if ts is None:
        return False
    return (time.monotonic() - ts) < threshold_seconds


def get_online_user_ids(
    threshold_seconds: float = _ACTIVITY_THRESHOLD_SEC,
) -> set[str]:
    """Return the set of user IDs currently considered online."""
    now = time.monotonic()
    with _lock:
        return {uid for uid, ts in _last_active.items() if (now - ts) < threshold_seconds}
