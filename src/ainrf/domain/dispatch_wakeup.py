"""Best-effort, no-port wakeups for the durable Task dispatch outbox.

The SQLite outbox remains the only scheduling fact.  This marker merely lets a
separate ``domain-worker`` notice a newly committed dispatch before its normal
poll interval elapses.  Losing a marker is safe: the worker still recovers the
pending row from SQLite after a restart or its next poll.
"""

from __future__ import annotations

import asyncio
from pathlib import Path


class DispatchWakeup:
    """Share a lightweight outbox wake marker through the state volume."""

    def __init__(self, state_root: Path) -> None:
        self._path = state_root / "runtime" / "domain-worker.wakeup"

    def generation(self) -> int:
        """Return a monotonic-enough file generation, or zero before first use."""

        try:
            return self._path.stat().st_mtime_ns
        except FileNotFoundError:
            return 0

    def notify(self, dispatch_id: str) -> None:
        """Publish an advisory post-commit wakeup without encoding task data."""

        if not dispatch_id:
            raise ValueError("dispatch_id is required for a domain-worker wakeup")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.touch(exist_ok=True)

    async def wait_for_change(self, observed_generation: int, *, timeout_seconds: float) -> int:
        """Wait briefly for an outbox marker change, then return the latest generation."""

        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        generation = self.generation()
        while generation == observed_generation and loop.time() < deadline:
            await asyncio.sleep(min(0.05, max(0.0, deadline - loop.time())))
            generation = self.generation()
        return generation
