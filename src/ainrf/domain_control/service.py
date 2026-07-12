"""Durable write barrier used before a domain-model cutover."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
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


@dataclass(frozen=True, slots=True)
class ParticipantStatus:
    """Persistent state advertised by a process that can write domain data."""

    participant_id: str
    participant_type: str
    process_id: int | None
    observed_epoch: int
    status: str
    in_flight_mutations: int
    unflushed_output_count: int
    registered_at: str
    heartbeat_at: str
    drained_at: str | None
    stopped_at: str | None


@dataclass(frozen=True, slots=True)
class MaintenancePreflight:
    """Cutover safety facts collected without changing application state."""

    ready: bool
    maintenance_active: bool
    active_attempt_count: int
    pending_runtime_launch_count: int
    unflushed_output_count: int
    source_stable: bool
    participants_drained: bool
    missing_participant_types: tuple[str, ...]
    stale_participant_ids: tuple[str, ...]
    participants: tuple[ParticipantStatus, ...]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DomainMaintenanceService:
    """Coordinate a persistent, cross-process migration maintenance epoch."""

    def __init__(self, state_root: Path) -> None:
        self._state_root = state_root
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

    def participants(self) -> tuple[ParticipantStatus, ...]:
        """Return all known writers, including stopped instances for audit."""
        self.initialize()
        with closing(connect(self._db_path)) as conn:
            rows = conn.execute(
                """
                SELECT participant_id, participant_type, process_id, observed_epoch, status,
                       in_flight_mutations, unflushed_output_count, registered_at,
                       heartbeat_at, drained_at, stopped_at
                FROM domain_write_participants
                ORDER BY participant_type, participant_id
                """
            ).fetchall()
        return tuple(self._participant_status(row) for row in rows)

    def register_participant(
        self,
        participant_id: str,
        participant_type: str,
        *,
        process_id: int | None = None,
        details: dict[str, object] | None = None,
    ) -> ParticipantStatus:
        """Register or revive a durable domain-write participant.

        A process that starts while maintenance is active is immediately marked
        drained for the current epoch so it cannot claim work before cutover
        completes.
        """
        if not participant_id:
            raise ValueError("participant_id is required")
        if not participant_type:
            raise ValueError("participant_type is required")
        self.initialize()
        now = _now()
        with closing(connect(self._db_path)) as conn:
            state = conn.execute(
                "SELECT maintenance_epoch, is_active FROM domain_maintenance_state WHERE singleton = 1"
            ).fetchone()
            if state is None:
                raise RuntimeError("domain maintenance state is not initialized")
            status = "drained" if bool(state["is_active"]) else "active"
            drained_at = now if status == "drained" else None
            conn.execute(
                """
                INSERT INTO domain_write_participants (
                    participant_id, participant_type, process_id, observed_epoch, status,
                    in_flight_mutations, unflushed_output_count, details_json, registered_at,
                    heartbeat_at, drained_at, stopped_at
                ) VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?, ?, ?, NULL)
                ON CONFLICT(participant_id) DO UPDATE SET
                    participant_type = excluded.participant_type,
                    process_id = excluded.process_id,
                    observed_epoch = excluded.observed_epoch,
                    status = excluded.status,
                    in_flight_mutations = 0,
                    unflushed_output_count = 0,
                    details_json = excluded.details_json,
                    heartbeat_at = excluded.heartbeat_at,
                    drained_at = excluded.drained_at,
                    stopped_at = NULL
                """,
                (
                    participant_id,
                    participant_type,
                    process_id if process_id is not None else os.getpid(),
                    int(state["maintenance_epoch"]),
                    status,
                    json.dumps(details or {}, sort_keys=True),
                    now,
                    now,
                    drained_at,
                ),
            )
            row = conn.execute(
                """
                SELECT participant_id, participant_type, process_id, observed_epoch, status,
                       in_flight_mutations, unflushed_output_count, registered_at,
                       heartbeat_at, drained_at, stopped_at
                FROM domain_write_participants WHERE participant_id = ?
                """,
                (participant_id,),
            ).fetchone()
            conn.commit()
        if row is None:
            raise RuntimeError("participant registration did not persist")
        return self._participant_status(row)

    def heartbeat_participant(
        self,
        participant_id: str,
        *,
        in_flight_mutations: int | None = None,
        unflushed_output_count: int | None = None,
    ) -> ParticipantStatus:
        """Record writer liveness and observe the current maintenance epoch."""
        self.initialize()
        now = _now()
        with closing(connect(self._db_path)) as conn:
            state = conn.execute(
                "SELECT maintenance_epoch, is_active FROM domain_maintenance_state WHERE singleton = 1"
            ).fetchone()
            participant = conn.execute(
                "SELECT * FROM domain_write_participants WHERE participant_id = ?",
                (participant_id,),
            ).fetchone()
            if state is None or participant is None:
                raise LookupError(f"Unknown domain write participant: {participant_id}")
            current_in_flight = (
                int(participant["in_flight_mutations"])
                if in_flight_mutations is None
                else max(0, in_flight_mutations)
            )
            current_unflushed = (
                int(participant["unflushed_output_count"])
                if unflushed_output_count is None
                else max(0, unflushed_output_count)
            )
            maintenance_active = bool(state["is_active"])
            status = (
                "drained"
                if maintenance_active and current_in_flight == 0 and current_unflushed == 0
                else "draining"
                if maintenance_active
                else "active"
            )
            drained_at = now if status == "drained" else None
            conn.execute(
                """
                UPDATE domain_write_participants
                SET observed_epoch = ?, status = ?, in_flight_mutations = ?,
                    unflushed_output_count = ?, heartbeat_at = ?, drained_at = ?, stopped_at = NULL
                WHERE participant_id = ?
                """,
                (
                    int(state["maintenance_epoch"]),
                    status,
                    current_in_flight,
                    current_unflushed,
                    now,
                    drained_at,
                    participant_id,
                ),
            )
            row = conn.execute(
                """
                SELECT participant_id, participant_type, process_id, observed_epoch, status,
                       in_flight_mutations, unflushed_output_count, registered_at,
                       heartbeat_at, drained_at, stopped_at
                FROM domain_write_participants WHERE participant_id = ?
                """,
                (participant_id,),
            ).fetchone()
            conn.commit()
        if row is None:
            raise RuntimeError("participant heartbeat did not persist")
        return self._participant_status(row)

    def drain_participant(self, participant_id: str) -> ParticipantStatus:
        """Mark a participant drained after it has stopped claiming new work."""
        return self.heartbeat_participant(participant_id, in_flight_mutations=0)

    def stop_participant(self, participant_id: str) -> ParticipantStatus:
        """Retire a participant instance while retaining its audit record."""
        self.initialize()
        now = _now()
        with closing(connect(self._db_path)) as conn:
            updated = conn.execute(
                """
                UPDATE domain_write_participants
                SET status = 'stopped', in_flight_mutations = 0, unflushed_output_count = 0,
                    heartbeat_at = ?, stopped_at = ?, drained_at = ?
                WHERE participant_id = ?
                """,
                (now, now, now, participant_id),
            )
            if updated.rowcount != 1:
                raise LookupError(f"Unknown domain write participant: {participant_id}")
            row = conn.execute(
                """
                SELECT participant_id, participant_type, process_id, observed_epoch, status,
                       in_flight_mutations, unflushed_output_count, registered_at,
                       heartbeat_at, drained_at, stopped_at
                FROM domain_write_participants WHERE participant_id = ?
                """,
                (participant_id,),
            ).fetchone()
            conn.commit()
        if row is None:
            raise RuntimeError("participant stop did not persist")
        return self._participant_status(row)

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
            # Existing writers must observe the new epoch and explicitly
            # heartbeat themselves to drained.  We never infer a drain from a
            # stale process record.
            conn.execute(
                """
                UPDATE domain_write_participants
                SET status = CASE WHEN status = 'stopped' THEN 'stopped' ELSE 'draining' END,
                    drained_at = NULL
                """
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

    def begin_mutation(self, *, source: str, participant_id: str | None = None) -> MaintenanceLease:
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
            if participant_id is not None:
                participant = conn.execute(
                    "SELECT status FROM domain_write_participants WHERE participant_id = ?",
                    (participant_id,),
                ).fetchone()
                if participant is None or participant["status"] == "stopped":
                    raise MaintenanceModeError("domain write participant is not active")
            mutation_id = uuid4().hex
            epoch = int(row["maintenance_epoch"])
            conn.execute(
                """
                INSERT INTO domain_maintenance_mutations
                    (mutation_id, maintenance_epoch, started_at, source, participant_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (mutation_id, epoch, _now(), source, participant_id),
            )
            if participant_id is not None:
                conn.execute(
                    """
                    UPDATE domain_write_participants
                    SET in_flight_mutations = in_flight_mutations + 1,
                        status = 'active', observed_epoch = ?, heartbeat_at = ?, drained_at = NULL
                    WHERE participant_id = ?
                    """,
                    (epoch, _now(), participant_id),
                )
            conn.commit()
        return MaintenanceLease(mutation_id=mutation_id, maintenance_epoch=epoch, source=source)

    def finish_mutation(self, lease: MaintenanceLease) -> None:
        self.initialize()
        with closing(connect(self._db_path)) as conn:
            mutation = conn.execute(
                "SELECT participant_id FROM domain_maintenance_mutations WHERE mutation_id = ?",
                (lease.mutation_id,),
            ).fetchone()
            conn.execute(
                "DELETE FROM domain_maintenance_mutations WHERE mutation_id = ?",
                (lease.mutation_id,),
            )
            if mutation is not None and mutation["participant_id"] is not None:
                participant_id = str(mutation["participant_id"])
                state = conn.execute(
                    "SELECT maintenance_epoch, is_active FROM domain_maintenance_state WHERE singleton = 1"
                ).fetchone()
                participant = conn.execute(
                    "SELECT in_flight_mutations, unflushed_output_count FROM domain_write_participants WHERE participant_id = ?",
                    (participant_id,),
                ).fetchone()
                if state is not None and participant is not None:
                    remaining = max(0, int(participant["in_flight_mutations"]) - 1)
                    status = (
                        "drained"
                        if bool(state["is_active"])
                        and remaining == 0
                        and int(participant["unflushed_output_count"]) == 0
                        else "draining"
                        if bool(state["is_active"])
                        else "active"
                    )
                    now = _now()
                    conn.execute(
                        """
                        UPDATE domain_write_participants
                        SET in_flight_mutations = ?, status = ?, observed_epoch = ?,
                            heartbeat_at = ?, drained_at = ?
                        WHERE participant_id = ?
                        """,
                        (
                            remaining,
                            status,
                            int(state["maintenance_epoch"]),
                            now,
                            now if status == "drained" else None,
                            participant_id,
                        ),
                    )
            conn.commit()

    def check_lease(self, lease: MaintenanceLease) -> None:
        """Fail a mutation that crossed a maintenance epoch before commit."""
        self.initialize()
        with closing(connect(self._db_path)) as conn:
            row = conn.execute(
                "SELECT maintenance_epoch, is_active FROM domain_maintenance_state WHERE singleton = 1"
            ).fetchone()
        if (
            row is None
            or bool(row["is_active"])
            or int(row["maintenance_epoch"]) != lease.maintenance_epoch
        ):
            raise MaintenanceModeError("domain write crossed a maintenance epoch")

    def wait_for_drain(self, *, timeout_seconds: float, poll_seconds: float = 0.05) -> bool:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self.status().in_flight_mutations == 0:
                return True
            time.sleep(poll_seconds)
        return self.status().in_flight_mutations == 0

    def preflight(
        self,
        *,
        required_participant_types: tuple[str, ...] = (),
        stability_window_seconds: float = 5.0,
        stale_after_seconds: float = 30.0,
    ) -> MaintenancePreflight:
        """Collect the hard safety facts required before migration/cutover.

        The method is deliberately read-only.  A caller must first enter
        maintenance, then use this report to decide whether it may proceed.
        """
        if stability_window_seconds < 0:
            raise ValueError("stability_window_seconds must be non-negative")
        if stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds must be positive")
        status = self.status()
        participants = self.participants()
        now = datetime.now(timezone.utc)
        active_participants = tuple(item for item in participants if item.status != "stopped")
        stale_ids = tuple(
            item.participant_id
            for item in active_participants
            if self._participant_is_stale(item, now, stale_after_seconds)
        )
        missing_types = tuple(
            participant_type
            for participant_type in required_participant_types
            if not any(
                item.participant_type == participant_type and item.status != "stopped"
                for item in participants
            )
        )
        participants_drained = (
            not missing_types
            and not stale_ids
            and all(item.status == "drained" for item in active_participants)
        )
        with closing(connect(self._db_path)) as conn:
            active_attempt_count = self._count_optional(
                conn,
                """
                SELECT COUNT(*) FROM agent_task_attempts
                WHERE status IN ('starting', 'running', 'pausing', 'cancelling')
                """,
            )
            pending_runtime_launch_count = self._count_optional(
                conn,
                """
                SELECT COUNT(*) FROM task_dispatch_outbox
                WHERE status IN ('pending', 'claimed')
                """,
            )
        unflushed_output_count = sum(item.unflushed_output_count for item in active_participants)
        source_stable = self._sources_are_stable(stability_window_seconds)
        ready = (
            status.is_active
            and status.in_flight_mutations == 0
            and active_attempt_count == 0
            and pending_runtime_launch_count == 0
            and unflushed_output_count == 0
            and source_stable
            and participants_drained
        )
        return MaintenancePreflight(
            ready=ready,
            maintenance_active=status.is_active,
            active_attempt_count=active_attempt_count,
            pending_runtime_launch_count=pending_runtime_launch_count,
            unflushed_output_count=unflushed_output_count,
            source_stable=source_stable,
            participants_drained=participants_drained,
            missing_participant_types=missing_types,
            stale_participant_ids=stale_ids,
            participants=participants,
        )

    @staticmethod
    def _participant_status(row: sqlite3.Row) -> ParticipantStatus:
        return ParticipantStatus(
            participant_id=str(row["participant_id"]),
            participant_type=str(row["participant_type"]),
            process_id=int(row["process_id"]) if row["process_id"] is not None else None,
            observed_epoch=int(row["observed_epoch"]),
            status=str(row["status"]),
            in_flight_mutations=int(row["in_flight_mutations"]),
            unflushed_output_count=int(row["unflushed_output_count"]),
            registered_at=str(row["registered_at"]),
            heartbeat_at=str(row["heartbeat_at"]),
            drained_at=str(row["drained_at"]) if row["drained_at"] is not None else None,
            stopped_at=str(row["stopped_at"]) if row["stopped_at"] is not None else None,
        )

    @staticmethod
    def _participant_is_stale(
        participant: ParticipantStatus, now: datetime, stale_after_seconds: float
    ) -> bool:
        try:
            heartbeat = datetime.fromisoformat(participant.heartbeat_at)
        except ValueError:
            return True
        return (now - heartbeat).total_seconds() > stale_after_seconds

    @staticmethod
    def _count_optional(conn: sqlite3.Connection, query: str) -> int:
        try:
            row = conn.execute(query).fetchone()
        except sqlite3.OperationalError:
            return 0
        return int(row[0]) if row is not None else 0

    def _sources_are_stable(self, stability_window_seconds: float) -> bool:
        before = self._source_fingerprints()
        if stability_window_seconds:
            time.sleep(stability_window_seconds)
        return before == self._source_fingerprints()

    def _source_fingerprints(self) -> dict[str, tuple[int, int, str]]:
        """Fingerprint legacy control-plane sources without mutating them."""
        candidates: list[Path] = []
        for root in (self._runtime_root, self._state_root):
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if not path.is_file() or path.name.endswith(("-wal", "-shm")):
                    continue
                try:
                    relative = path.relative_to(self._state_root).as_posix()
                except ValueError:
                    continue
                if path.suffix in {".json", ".sqlite3"} or relative.startswith(
                    ("session-states/", "detections/")
                ):
                    candidates.append(path)
        fingerprints: dict[str, tuple[int, int, str]] = {}
        for path in sorted(set(candidates)):
            stat = path.stat()
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1 << 16), b""):
                    digest.update(chunk)
            fingerprints[path.relative_to(self._state_root).as_posix()] = (
                stat.st_size,
                stat.st_mtime_ns,
                digest.hexdigest(),
            )
        return fingerprints


class DomainWriteParticipant:
    """Small process-local facade over the durable participant registry."""

    def __init__(
        self,
        service: DomainMaintenanceService,
        participant_type: str,
        *,
        participant_id: str | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        self._service = service
        self.participant_type = participant_type
        self.participant_id = participant_id or f"{participant_type}-{uuid4().hex}"
        self._details = details

    def start(self) -> ParticipantStatus:
        return self._service.register_participant(
            self.participant_id, self.participant_type, details=self._details
        )

    def heartbeat(self, *, unflushed_output_count: int | None = None) -> ParticipantStatus:
        return self._service.heartbeat_participant(
            self.participant_id, unflushed_output_count=unflushed_output_count
        )

    def begin_mutation(self, *, source: str) -> MaintenanceLease:
        return self._service.begin_mutation(source=source, participant_id=self.participant_id)

    def finish_mutation(self, lease: MaintenanceLease) -> None:
        self._service.finish_mutation(lease)

    def drain(self) -> ParticipantStatus:
        return self._service.drain_participant(self.participant_id)

    def stop(self) -> ParticipantStatus:
        return self._service.stop_participant(self.participant_id)
