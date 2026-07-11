"""Durable write barrier used before a domain-model cutover."""

from __future__ import annotations

import time
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from ainrf.db import connect, run_pending


class DomainModelMode(StrEnum):
    LEGACY = "legacy"
    VALIDATE = "validate"
    V2 = "v2"


class MaintenanceModeError(RuntimeError):
    """Raised when a domain mutation cannot enter the write barrier."""


@dataclass(frozen=True, slots=True)
class MaintenanceLease:
    mutation_id: str
    maintenance_epoch: int
    source: str


@dataclass(frozen=True, slots=True)
class MaintenanceStatus:
    maintenance_epoch: int
    is_active: bool
    actor_id: str | None
    reason: str | None
    entered_at: str | None
    exited_at: str | None
    in_flight_mutations: int


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DomainMaintenanceService:
    """Coordinate a persistent, cross-process migration maintenance epoch."""

    def __init__(self, state_root: Path) -> None:
        self._runtime_root = state_root / "runtime"
        self._db_path = self._runtime_root / "agentic_researcher.sqlite3"
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            return
        self._runtime_root.mkdir(parents=True, exist_ok=True)
        with closing(connect(self._db_path)) as conn:
            run_pending(conn, "agentic_researcher")
        self._initialized = True

    def status(self) -> MaintenanceStatus:
        self.initialize()
        with closing(connect(self._db_path)) as conn:
            row = conn.execute(
                """
                SELECT maintenance_epoch, is_active, actor_id, reason, entered_at, exited_at
                FROM domain_maintenance_state WHERE singleton = 1
                """
            ).fetchone()
            in_flight = conn.execute("SELECT COUNT(*) FROM domain_maintenance_mutations").fetchone()
        if row is None or in_flight is None:
            raise RuntimeError("domain maintenance state is not initialized")
        return MaintenanceStatus(
            maintenance_epoch=int(row["maintenance_epoch"]),
            is_active=bool(row["is_active"]),
            actor_id=row["actor_id"],
            reason=row["reason"],
            entered_at=row["entered_at"],
            exited_at=row["exited_at"],
            in_flight_mutations=int(in_flight[0]),
        )

    def enter(self, *, actor_id: str, reason: str) -> MaintenanceStatus:
        if not actor_id:
            raise ValueError("actor_id is required")
        if not reason:
            raise ValueError("reason is required")
        self.initialize()
        with closing(connect(self._db_path)) as conn:
            row = conn.execute(
                "SELECT maintenance_epoch, is_active FROM domain_maintenance_state WHERE singleton = 1"
            ).fetchone()
            if row is None:
                raise RuntimeError("domain maintenance state is not initialized")
            if bool(row["is_active"]):
                raise MaintenanceModeError("domain maintenance mode is already active")
            conn.execute(
                """
                UPDATE domain_maintenance_state
                SET maintenance_epoch = ?, is_active = 1, actor_id = ?, reason = ?,
                    entered_at = ?, exited_at = NULL
                WHERE singleton = 1
                """,
                (int(row["maintenance_epoch"]) + 1, actor_id, reason, _now()),
            )
            conn.commit()
        return self.status()

    def exit(self, *, actor_id: str) -> MaintenanceStatus:
        self.initialize()
        with closing(connect(self._db_path)) as conn:
            in_flight = conn.execute("SELECT COUNT(*) FROM domain_maintenance_mutations").fetchone()
            if in_flight is None:
                raise RuntimeError("domain maintenance state is not initialized")
            if int(in_flight[0]) != 0:
                raise MaintenanceModeError(
                    "cannot exit maintenance while mutations are still in flight"
                )
            updated = conn.execute(
                """
                UPDATE domain_maintenance_state
                SET is_active = 0, actor_id = ?, exited_at = ?
                WHERE singleton = 1 AND is_active = 1
                """,
                (actor_id, _now()),
            )
            if updated.rowcount != 1:
                raise MaintenanceModeError("domain maintenance mode is not active")
            conn.commit()
        return self.status()

    def begin_mutation(self, *, source: str) -> MaintenanceLease:
        self.initialize()
        if not source:
            raise ValueError("source is required")
        with closing(connect(self._db_path)) as conn:
            row = conn.execute(
                "SELECT maintenance_epoch, is_active FROM domain_maintenance_state WHERE singleton = 1"
            ).fetchone()
            if row is None:
                raise RuntimeError("domain maintenance state is not initialized")
            if bool(row["is_active"]):
                raise MaintenanceModeError("domain writes are paused for maintenance")
            mutation_id = uuid4().hex
            epoch = int(row["maintenance_epoch"])
            conn.execute(
                """
                INSERT INTO domain_maintenance_mutations
                    (mutation_id, maintenance_epoch, started_at, source)
                VALUES (?, ?, ?, ?)
                """,
                (mutation_id, epoch, _now(), source),
            )
            conn.commit()
        return MaintenanceLease(mutation_id=mutation_id, maintenance_epoch=epoch, source=source)

    def finish_mutation(self, lease: MaintenanceLease) -> None:
        self.initialize()
        with closing(connect(self._db_path)) as conn:
            conn.execute(
                "DELETE FROM domain_maintenance_mutations WHERE mutation_id = ?",
                (lease.mutation_id,),
            )
            conn.commit()

    def wait_for_drain(self, *, timeout_seconds: float, poll_seconds: float = 0.05) -> bool:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self.status().in_flight_mutations == 0:
                return True
            time.sleep(poll_seconds)
        return self.status().in_flight_mutations == 0
