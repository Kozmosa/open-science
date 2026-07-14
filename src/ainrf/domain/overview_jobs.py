"""Durable, control-plane-only Today overview refresh jobs.

The overview is deliberately a projection, not another authority.  Its job
runner only reads the domain SQLite database, the local literature SQLite
database and already persisted environment detection files.  In particular it
does not import collectors, task services, literature fetchers or runtime
engines: scheduling an overview must never cause an external call or an action
on behalf of a user.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterable
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal, cast
from uuid import uuid4
from zoneinfo import ZoneInfo

from ainrf.db import connect, run_pending
from ainrf.domain.write_fence import DomainWriteFence
from ainrf.domain_telemetry import record_overview_event, record_permission_denied
from ainrf.domain_control import (
    DomainMaintenanceService,
    DomainWriteParticipant,
    MaintenanceLease,
    MaintenanceModeError,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")
# A card is a last-success candidate only when every one of its authoritative
# local sources was readable.  In particular, a partial resource scan must not
# replace the last complete Environment snapshot with a smaller subset.
_SUCCESS_CARD_STATUSES = ("ok",)
_PLANNER_HEARTBEAT_TTL = timedelta(minutes=2)
_RETRY_BASE_DELAY_SECONDS = 15
_RETRY_MAX_DELAY_SECONDS = 15 * 60
_MAX_RETRY_COUNT = 3

RefreshTrigger = Literal["manual", "scheduled", "catchup"]


def _maintenance_is_active_read_only(state_root: Path) -> bool:
    """Read the maintenance flag without constructing writable Overview state.

    A planner can be started by the no-port worker, the compatibility CLI, or
    an administrative Python caller while a restore/cutover owns the
    maintenance epoch.  ``OverviewSnapshotService`` creates the runtime
    directory and runs migrations in its constructor, so checking through the
    ordinary maintenance service would already be a source mutation.  Keep
    this narrow read-only probe in front of every writable planner bootstrap.

    An existing WAL cannot be safely observed with SQLite's immutable URI, so
    it is deliberately treated as active/indeterminate and the caller joins
    maintenance as a drained participant instead of risking a write.
    """

    database_path = state_root / "runtime" / "agentic_researcher.sqlite3"
    if not database_path.is_file():
        return False
    if database_path.with_name(f"{database_path.name}-wal").exists():
        return True
    try:
        database_uri = f"{database_path.resolve().as_uri()}?mode=ro&immutable=1"
        with sqlite3.connect(database_uri, uri=True, isolation_level=None) as connection:
            table = connection.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type = 'table' AND name = 'domain_maintenance_state'"
            ).fetchone()
            if table is None:
                return False
            row = connection.execute(
                "SELECT is_active FROM domain_maintenance_state WHERE singleton = 1"
            ).fetchone()
    except sqlite3.Error as exc:
        raise RuntimeError(
            "cannot read persisted domain maintenance state; refusing overview planner startup"
        ) from exc
    if row is None:
        raise RuntimeError(
            "persisted domain maintenance state is malformed; refusing overview planner startup"
        )
    return bool(row[0])


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime | None) -> datetime:
    candidate = value or _utc_now()
    if candidate.tzinfo is None:
        return candidate.replace(tzinfo=UTC)
    return candidate.astimezone(UTC)


def _iso(value: datetime) -> str:
    return _as_utc(value).isoformat()


def _parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        candidate = datetime.fromisoformat(value)
    except ValueError:
        return None
    return _as_utc(candidate)


def _parse_date(value: object) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _json_load(value: object, *, fallback: object) -> object:
    if not isinstance(value, str):
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _json_object(value: object, *, fallback: dict[str, object] | None) -> dict[str, object] | None:
    decoded = _json_load(value, fallback=fallback)
    if not isinstance(decoded, dict):
        return fallback
    return cast(dict[str, object], decoded)


@dataclass(frozen=True, slots=True)
class OverviewRefreshClaim:
    """A leased refresh job; its lease token guards terminal writes."""

    job_id: str
    owner_user_id: str
    trigger: str
    scheduled_for_date: str | None
    lease_token: str
    attempt_count: int


@dataclass(frozen=True, slots=True)
class OverviewRefreshRunResult:
    """The durable outcome of a single overview job execution."""

    job_id: str | None
    outcome: str
    snapshot_id: str | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class OverviewPlannerRunResult:
    """One scheduling and bounded work-draining cycle."""

    outcome: str
    scheduled_job_ids: tuple[str, ...]
    completed_job_ids: tuple[str, ...]
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class _CardResult:
    card_id: str
    data: dict[str, object] | None
    source_status: str
    data_cutoff_at: str
    attention_required: bool
    error_summary: str | None = None


class OverviewSnapshotService:
    """Persist and build user-scoped overview snapshots through durable jobs.

    The public enqueue/claim/complete methods intentionally make the job table
    the only write model used by both manual and scheduled refreshes.  Failed
    jobs retain their user-visible identity while waiting for bounded retries,
    so a planner restart never drops a scheduled Shanghai slot.  The
    compatibility :meth:`refresh` helper merely enqueues and immediately runs
    such a job for an administrative CLI; it does not maintain a second path.
    """

    def __init__(self, state_root: Path, *, artifact_sha: str | None = None) -> None:
        self._state_root = state_root
        self._artifact_sha = artifact_sha
        self._runtime_root = state_root / "runtime"
        self._db_path = self._runtime_root / "agentic_researcher.sqlite3"
        self._literature_db_path = self._runtime_root / "literature.sqlite3"
        self._auth_db_path = self._runtime_root / "auth.sqlite3"
        self._write_fence = DomainWriteFence(state_root, artifact_sha=artifact_sha)
        self._runtime_root.mkdir(parents=True, exist_ok=True)
        with closing(connect(self._db_path)) as conn:
            run_pending(conn, "agentic_researcher")

    @property
    def state_root(self) -> Path:
        return self._state_root

    def _connect(self) -> sqlite3.Connection:
        return connect(self._db_path)

    @staticmethod
    def _assert_maintenance_writable(conn: sqlite3.Connection) -> None:
        """Fence a job transaction against a concurrent maintenance epoch."""

        maintenance = conn.execute(
            "SELECT is_active FROM domain_maintenance_state WHERE singleton = 1"
        ).fetchone()
        if maintenance is None or bool(maintenance["is_active"]):
            raise MaintenanceModeError("overview refresh is paused for maintenance")

    def request_refresh(
        self,
        owner_user_id: str,
        *,
        trigger: RefreshTrigger = "manual",
        scheduled_for_date: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, object]:
        """Create or reuse an active job for one user.

        Scheduled jobs also carry their Shanghai calendar slot.  A completed
        scheduled slot is reused after a restart, while a completed manual job
        does not block a later manual refresh.
        """

        owner = owner_user_id.strip()
        if not owner:
            raise ValueError("owner_user_id is required")
        if trigger not in {"manual", "scheduled", "catchup"}:
            raise ValueError("unsupported overview refresh trigger")
        if trigger == "manual" and scheduled_for_date is not None:
            raise ValueError("manual overview refreshes cannot declare a schedule slot")
        if trigger != "manual" and not scheduled_for_date:
            raise ValueError("scheduled overview refreshes require a schedule slot")
        if scheduled_for_date is not None:
            self._validate_date(scheduled_for_date)

        created_at = _iso(_as_utc(now))
        with closing(self._connect()) as conn:
            # Own the SQLite write transaction before observing maintenance.
            # A concurrent ``enter()`` serializes behind this transaction, so
            # either the job commits before the new epoch or it is rejected
            # before any durable Overview mutation.
            conn.execute("BEGIN IMMEDIATE")
            self._assert_maintenance_writable(conn)
            active = self._active_job_for_owner(conn, owner)
            if active is not None:
                result = self._job_dict(active)
                record_overview_event(
                    "reused",
                    trigger=str(result.get("trigger", trigger)),
                    user_id=owner,
                    job_id=str(result.get("job_id", "")),
                )
                return result
            if scheduled_for_date is not None:
                scheduled = conn.execute(
                    """
                    SELECT * FROM overview_refresh_jobs
                    WHERE owner_user_id = ? AND scheduled_for_date = ?
                    ORDER BY created_at DESC, job_id DESC LIMIT 1
                    """,
                    (owner, scheduled_for_date),
                ).fetchone()
                if scheduled is not None:
                    result = self._job_dict(scheduled)
                    record_overview_event(
                        "reused",
                        trigger=str(result.get("trigger", trigger)),
                        user_id=owner,
                        job_id=str(result.get("job_id", "")),
                    )
                    return result
            job_id = f"overview-refresh-{uuid4().hex}"
            try:
                self._write_fence.record_first_v2_write(conn, actor_id=owner)
                conn.execute(
                    """
                    INSERT INTO overview_refresh_jobs (
                        job_id, owner_user_id, trigger, scheduled_for_date, status,
                        attempt_count, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'queued', 0, ?, ?)
                    """,
                    (job_id, owner, trigger, scheduled_for_date, created_at, created_at),
                )
            except sqlite3.IntegrityError:
                # The partial active-job index is the cross-process arbitration
                # point.  A concurrent caller must observe the winner rather
                # than receiving a transient conflict.
                active = self._active_job_for_owner(conn, owner)
                if active is None:
                    raise
                result = self._job_dict(active)
                record_overview_event(
                    "reused",
                    trigger=str(result.get("trigger", trigger)),
                    user_id=owner,
                    job_id=str(result.get("job_id", "")),
                )
                return result
            row = conn.execute(
                "SELECT * FROM overview_refresh_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            self._assert_maintenance_writable(conn)
            conn.commit()
        if row is None:
            raise RuntimeError("overview refresh job was not persisted")
        result = self._job_dict(row)
        record_overview_event(
            "queued",
            trigger=trigger,
            user_id=owner,
            job_id=str(result.get("job_id", "")),
        )
        return result

    def schedule_due_refreshes(
        self,
        *,
        now: datetime | None = None,
        active_user_ids: Iterable[str] | None = None,
    ) -> list[dict[str, object]]:
        """Plan eligible Shanghai 06:00 slots, including restart catch-up.

        Before 06:00, a restarted worker must still drain historical missed
        slots, but it must not create today's slot early.  A user without any
        prior scheduled history is therefore first initialized at or after
        today's 06:00 boundary; a user with recorded history can catch up
        through yesterday before that boundary.  The unique scheduled slot
        makes repeated worker starts and multiple planners harmless.
        """

        current = _as_utc(now)
        shanghai_now = current.astimezone(_SHANGHAI)
        current_slot_due = (shanghai_now.hour, shanghai_now.minute) >= (6, 0)
        last_eligible_date = (
            shanghai_now.date() if current_slot_due else shanghai_now.date() - timedelta(days=1)
        )
        user_ids = active_user_ids if active_user_ids is not None else self.active_user_ids()
        scheduled: list[dict[str, object]] = []
        for user_id in sorted({item.strip() for item in user_ids if item.strip()}):
            with closing(self._connect()) as conn:
                due_date = self._next_due_schedule_date(
                    conn,
                    user_id,
                    last_eligible_date,
                    allow_initial_slot=current_slot_due,
                )
            if due_date is None:
                continue
            job = self.request_refresh(
                user_id,
                trigger=("scheduled" if due_date == shanghai_now.date() else "catchup"),
                scheduled_for_date=due_date.isoformat(),
                now=current,
            )
            if job.get("scheduled_for_date") == due_date.isoformat():
                scheduled.append(job)
        return scheduled

    def active_user_ids(self) -> tuple[str, ...]:
        """Read active users from the local auth DB without initializing it."""

        if not self._auth_db_path.exists():
            return ()
        try:
            with closing(self._read_only_connection(self._auth_db_path)) as conn:
                rows = conn.execute(
                    "SELECT id FROM users WHERE status = 'active' ORDER BY id"
                ).fetchall()
        except (OSError, sqlite3.Error):
            return ()
        return tuple(str(row["id"]) for row in rows if isinstance(row["id"], str))

    def claim_next_job(
        self,
        worker_id: str,
        *,
        now: datetime | None = None,
        lease_seconds: int = 60,
        job_id: str | None = None,
    ) -> OverviewRefreshClaim | None:
        """Claim one due queued/retry job using a lease token CAS fence.

        A crashed planner makes only its expired ``running`` lease eligible
        again.  A completed failure waits for ``next_retry_at`` instead of
        becoming immediately hot-loopable by every worker.
        """

        if not worker_id.strip():
            raise ValueError("worker_id is required")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        current = _as_utc(now)
        current_iso = _iso(current)
        expiry_iso = _iso(current + timedelta(seconds=lease_seconds))
        with closing(self._connect()) as conn:
            # Take the writer lock before checking the epoch.  Maintenance
            # either starts before this claim (which rejects it) or waits for
            # this bounded transaction to complete; a direct service caller
            # cannot acquire work behind the planner's participant fence.
            conn.execute("BEGIN IMMEDIATE")
            self._assert_maintenance_writable(conn)
            conn.execute(
                """
                UPDATE overview_refresh_jobs
                SET status = 'queued', lease_owner = NULL, lease_token = NULL,
                    lease_expires_at = NULL, next_retry_at = NULL, updated_at = ?
                WHERE status = 'running' AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?
                """,
                (current_iso, current_iso),
            )
            if job_id is None:
                row = conn.execute(
                    """
                    SELECT * FROM overview_refresh_jobs
                    WHERE status = 'queued'
                       OR (status = 'retry_wait' AND next_retry_at IS NOT NULL
                           AND next_retry_at <= ?)
                    ORDER BY created_at ASC, job_id ASC LIMIT 1
                    """,
                    (current_iso,),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT * FROM overview_refresh_jobs
                    WHERE job_id = ?
                      AND (
                          status = 'queued'
                          OR (status = 'retry_wait' AND next_retry_at IS NOT NULL
                              AND next_retry_at <= ?)
                      )
                    """,
                    (job_id, current_iso),
                ).fetchone()
            if row is None:
                conn.commit()
                return None
            token = uuid4().hex
            updated = conn.execute(
                """
                UPDATE overview_refresh_jobs
                SET status = 'running', lease_owner = ?, lease_token = ?,
                    lease_expires_at = ?, heartbeat_at = ?, started_at = COALESCE(started_at, ?),
                    attempt_count = attempt_count + 1, next_retry_at = NULL, updated_at = ?
                WHERE job_id = ?
                  AND (
                      status = 'queued'
                      OR (status = 'retry_wait' AND next_retry_at IS NOT NULL
                          AND next_retry_at <= ?)
                  )
                  AND lease_token IS NULL
                """,
                (
                    worker_id,
                    token,
                    expiry_iso,
                    current_iso,
                    current_iso,
                    current_iso,
                    str(row["job_id"]),
                    current_iso,
                ),
            ).rowcount
            if updated != 1:
                conn.commit()
                return None
            claimed = conn.execute(
                "SELECT * FROM overview_refresh_jobs WHERE job_id = ?", (str(row["job_id"]),)
            ).fetchone()
            conn.commit()
        if claimed is None:
            raise RuntimeError("overview refresh claim disappeared")
        return OverviewRefreshClaim(
            job_id=str(claimed["job_id"]),
            owner_user_id=str(claimed["owner_user_id"]),
            trigger=str(claimed["trigger"]),
            scheduled_for_date=self._optional_str(claimed["scheduled_for_date"]),
            lease_token=token,
            attempt_count=int(claimed["attempt_count"]),
        )

    def heartbeat_job(
        self,
        claim: OverviewRefreshClaim,
        *,
        now: datetime | None = None,
        lease_seconds: int = 60,
    ) -> bool:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        current = _as_utc(now)
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._assert_maintenance_writable(conn)
            updated = self._heartbeat_claim(
                conn,
                claim,
                current=current,
                lease_seconds=lease_seconds,
            )
            conn.commit()
        return updated == 1

    @staticmethod
    def _heartbeat_claim(
        conn: sqlite3.Connection,
        claim: OverviewRefreshClaim,
        *,
        current: datetime,
        lease_seconds: int,
    ) -> int:
        """Renew an exact claim only while it has not expired.

        The lease token is a compare-and-swap fence between workers.  The
        expiry check is equally important: a stalled worker must not revive a
        lease after its recovery window has elapsed merely because another
        worker has not reached the row yet.
        """

        current_iso = _iso(current)
        return conn.execute(
            """
            UPDATE overview_refresh_jobs
            SET heartbeat_at = ?, lease_expires_at = ?, updated_at = ?
            WHERE job_id = ? AND status = 'running' AND lease_token = ?
              AND lease_expires_at IS NOT NULL AND lease_expires_at > ?
            """,
            (
                current_iso,
                _iso(current + timedelta(seconds=lease_seconds)),
                current_iso,
                claim.job_id,
                claim.lease_token,
                current_iso,
            ),
        ).rowcount

    def run_next_job(
        self,
        worker_id: str,
        *,
        now: datetime | None = None,
        lease_seconds: int = 60,
    ) -> OverviewRefreshRunResult:
        claim = self.claim_next_job(worker_id, now=now, lease_seconds=lease_seconds)
        if claim is None:
            return OverviewRefreshRunResult(job_id=None, outcome="idle")
        return self._run_claim(claim, now=now)

    def run_job(
        self,
        job_id: str,
        worker_id: str,
        *,
        now: datetime | None = None,
        lease_seconds: int = 60,
    ) -> OverviewRefreshRunResult:
        claim = self.claim_next_job(worker_id, now=now, lease_seconds=lease_seconds, job_id=job_id)
        if claim is None:
            return OverviewRefreshRunResult(job_id=job_id, outcome="not_claimed")
        return self._run_claim(claim, now=now)

    def refresh(self, owner_user_id: str) -> dict[str, object]:
        """Synchronously refresh through a maintenance-aware planner facade.

        This compatibility helper remains useful to administrative callers,
        but it must not become a second writer that bypasses the durable
        participant registry.  API callers enqueue only; the CLI facade below
        uses this same planner-owned job path.
        """

        planner = OverviewSnapshotPlanner(
            self._state_root,
            artifact_sha=self._artifact_sha,
            active_user_ids=lambda: (),
        )
        try:
            job = planner.request_refresh(owner_user_id)
            result = planner.run_job(str(job["job_id"]))
            payload = self.latest(owner_user_id)
            if payload is None:
                raise RuntimeError(result.detail or "overview refresh did not produce a snapshot")
            return payload
        finally:
            planner.stop()

    def latest(self, owner_user_id: str) -> dict[str, object] | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT snapshot_id, owner_user_id, snapshot_date, payload_json, created_at,
                       data_cutoff_at, source_status, attention_required
                FROM overview_snapshots
                WHERE owner_user_id = ?
                ORDER BY snapshot_date DESC, created_at DESC LIMIT 1
                """,
                (owner_user_id,),
            ).fetchone()
        if row is None:
            return None
        result = _json_object(row["payload_json"], fallback={}) or {}
        if "snapshot_id" not in result:
            result["snapshot_id"] = str(row["snapshot_id"])
        if "snapshot_date" not in result:
            result["snapshot_date"] = str(row["snapshot_date"])
        if "data_cutoff_at" not in result:
            result["data_cutoff_at"] = self._optional_str(row["data_cutoff_at"])
        if "source_status" not in result:
            result["source_status"] = self._optional_str(row["source_status"]) or "ok"
        if "attention_required" not in result:
            result["attention_required"] = bool(row["attention_required"] or 0)
        return result

    def get_job(self, owner_user_id: str, job_id: str) -> dict[str, object] | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT * FROM overview_refresh_jobs
                WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        if str(row["owner_user_id"]) != owner_user_id:
            # Keep the external result indistinguishable from an absent job,
            # but retain a bounded audit signal for cross-user probing.
            record_permission_denied(
                resource="overview",
                reason="not_visible",
                user_id=owner_user_id,
                state_root=self._state_root,
            )
            return None
        return self._job_dict(row)

    def job_store_ready(self) -> bool:
        """Whether the durable overview schema exists in the control plane."""

        try:
            with closing(self._connect()) as conn:
                rows = conn.execute(
                    """
                    SELECT name FROM sqlite_master
                    WHERE type = 'table' AND name IN (
                        'overview_refresh_jobs', 'overview_refresh_card_states',
                        'overview_planner_state'
                    )
                    """
                ).fetchall()
        except sqlite3.Error:
            return False
        return {str(row["name"]) for row in rows} == {
            "overview_refresh_jobs",
            "overview_refresh_card_states",
            "overview_planner_state",
        }

    def planner_readiness(self, *, now: datetime | None = None) -> dict[str, object]:
        """Return real persistent job-store and planner-heartbeat readiness."""

        if not self.job_store_ready():
            return {"job_store_ready": False, "planner_ready": False, "planner_status": "missing"}
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT planner_id, status, heartbeat_at, last_schedule_at, last_error
                FROM overview_planner_state WHERE singleton = 1
                """
            ).fetchone()
        heartbeat = _parse_iso(row["heartbeat_at"]) if row is not None else None
        current = _as_utc(now)
        planner_ready = (
            row is not None
            and str(row["status"]) == "running"
            and heartbeat is not None
            and current - heartbeat <= _PLANNER_HEARTBEAT_TTL
        )
        return {
            "job_store_ready": True,
            "planner_ready": planner_ready,
            "planner_status": str(row["status"]) if row is not None else "missing",
            "planner_id": self._optional_str(row["planner_id"]) if row is not None else None,
            "heartbeat_at": self._optional_str(row["heartbeat_at"]) if row is not None else None,
            "last_schedule_at": self._optional_str(row["last_schedule_at"])
            if row is not None
            else None,
            "last_error": self._optional_str(row["last_error"]) if row is not None else None,
        }

    def _run_claim(
        self, claim: OverviewRefreshClaim, *, now: datetime | None = None
    ) -> OverviewRefreshRunResult:
        current = _as_utc(now)
        cutoff_at = _iso(current)
        # The projection is intentionally local and bounded, but refreshing the
        # lease on both sides of the read phase prevents an unusually large
        # persisted state from being completed by a stale worker.
        if not self.heartbeat_job(claim, now=current, lease_seconds=300):
            return OverviewRefreshRunResult(
                job_id=claim.job_id,
                outcome="claim_lost",
                detail="overview refresh lease was lost before projection",
            )
        try:
            with closing(self._connect()) as conn:
                # Hold the same writer boundary across the local projection
                # and its result write.  A maintenance epoch cannot begin
                # halfway through and turn a direct service call into an
                # untracked snapshot mutation.
                conn.execute("BEGIN IMMEDIATE")
                self._assert_maintenance_writable(conn)
                cards = self._build_cards(conn, claim.owner_user_id, cutoff_at)
                if self._heartbeat_claim(conn, claim, current=current, lease_seconds=300) != 1:
                    return OverviewRefreshRunResult(
                        job_id=claim.job_id,
                        outcome="claim_lost",
                        detail="overview refresh lease was lost during projection",
                    )
                return self._persist_claim_result(conn, claim, cards, current)
        except Exception as exc:
            # A job-level exception must not erase a previously good snapshot.
            failure_outcome = self._fail_claim(claim, str(exc), current)
            if failure_outcome is None:
                return OverviewRefreshRunResult(
                    job_id=claim.job_id,
                    outcome="claim_lost",
                    detail="overview refresh lease was lost before failure was recorded",
                )
            return OverviewRefreshRunResult(
                job_id=claim.job_id,
                outcome=failure_outcome,
                detail=str(exc),
            )

    def _build_cards(
        self, conn: sqlite3.Connection, owner_user_id: str, cutoff_at: str
    ) -> list[_CardResult]:
        candidates = (
            self._build_domain_card(conn, owner_user_id, cutoff_at),
            self._build_literature_card(owner_user_id, cutoff_at),
            self._build_resource_card(conn, owner_user_id, cutoff_at),
        )
        return [self._with_last_success(conn, owner_user_id, card) for card in candidates]

    def _build_domain_card(
        self, conn: sqlite3.Connection, owner_user_id: str, cutoff_at: str
    ) -> _CardResult:
        try:
            projects_active = int(
                conn.execute(
                    "SELECT COUNT(*) FROM projects WHERE owner_user_id = ? AND status = 'active'",
                    (owner_user_id,),
                ).fetchone()[0]
            )
            workspaces_active = int(
                conn.execute(
                    "SELECT COUNT(*) FROM workspaces WHERE owner_user_id = ? AND status = 'active'",
                    (owner_user_id,),
                ).fetchone()[0]
            )
            task_statuses = {
                str(row["status"]): int(row["count"])
                for row in conn.execute(
                    """
                    SELECT status, COUNT(*) AS count FROM tasks
                    WHERE owner_user_id = ? GROUP BY status
                    """,
                    (owner_user_id,),
                )
            }
            active_attempts = int(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM agent_task_attempts AS attempt
                    JOIN tasks AS task ON task.task_id = attempt.task_id
                    WHERE task.owner_user_id = ?
                      AND attempt.status IN ('queued', 'starting', 'running', 'paused')
                    """,
                    (owner_user_id,),
                ).fetchone()[0]
            )
        except sqlite3.Error as exc:
            return _CardResult(
                card_id="domain",
                data=None,
                source_status="failed",
                data_cutoff_at=cutoff_at,
                attention_required=True,
                error_summary=f"domain projection unavailable: {exc}",
            )
        return _CardResult(
            card_id="domain",
            data={
                "projects_active": projects_active,
                "workspaces_active": workspaces_active,
                "tasks_by_status": task_statuses,
                "active_attempts": active_attempts,
            },
            source_status="ok",
            data_cutoff_at=cutoff_at,
            attention_required=False,
        )

    def _build_literature_card(self, owner_user_id: str, cutoff_at: str) -> _CardResult:
        if not self._literature_db_path.exists():
            return _CardResult(
                card_id="literature",
                data=None,
                source_status="unavailable",
                data_cutoff_at=cutoff_at,
                attention_required=True,
                error_summary="no persisted literature snapshot is available",
            )
        try:
            with closing(self._read_only_connection(self._literature_db_path)) as conn:
                counts = conn.execute(
                    """
                    SELECT
                      SUM(CASE WHEN is_read = 0 AND is_ignored = 0 THEN 1 ELSE 0 END) AS unread,
                      SUM(CASE WHEN is_saved = 1 THEN 1 ELSE 0 END) AS saved,
                      COUNT(*) AS papers
                    FROM literature_user_paper_states
                    WHERE user_id = ?
                    """,
                    (owner_user_id,),
                ).fetchone()
                last = conn.execute(
                    """
                    SELECT completed_at FROM literature_checks
                    WHERE user_id = ? AND status = 'completed'
                    ORDER BY completed_at DESC LIMIT 1
                    """,
                    (owner_user_id,),
                ).fetchone()
        except (OSError, sqlite3.Error) as exc:
            return _CardResult(
                card_id="literature",
                data=None,
                source_status="unavailable",
                data_cutoff_at=cutoff_at,
                attention_required=True,
                error_summary=f"literature projection unavailable: {exc}",
            )
        return _CardResult(
            card_id="literature",
            data={
                "paper_count": int(counts["papers"] or 0) if counts is not None else 0,
                "unread_count": int(counts["unread"] or 0) if counts is not None else 0,
                "saved_count": int(counts["saved"] or 0) if counts is not None else 0,
                "last_successful_check_at": self._optional_str(last["completed_at"])
                if last is not None
                else None,
            },
            source_status="ok",
            data_cutoff_at=cutoff_at,
            attention_required=False,
        )

    def _build_resource_card(
        self, conn: sqlite3.Connection, owner_user_id: str, cutoff_at: str
    ) -> _CardResult:
        try:
            environments = conn.execute(
                """
                SELECT environment_id FROM environments
                WHERE owner_user_id = ? AND status = 'active'
                ORDER BY environment_id
                """,
                (owner_user_id,),
            ).fetchall()
        except sqlite3.Error as exc:
            return _CardResult(
                card_id="resources",
                data=None,
                source_status="failed",
                data_cutoff_at=cutoff_at,
                attention_required=True,
                error_summary=f"resource scope unavailable: {exc}",
            )

        snapshots: list[dict[str, object]] = []
        missing = 0
        invalid = 0
        for row in environments:
            environment_id = str(row["environment_id"])
            if Path(environment_id).name != environment_id:
                invalid += 1
                continue
            source_path = self._state_root / "detections" / f"{environment_id}.json"
            if not source_path.exists():
                missing += 1
                continue
            try:
                raw = json.loads(source_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                invalid += 1
                continue
            if not isinstance(raw, dict) or raw.get("environment_id") != environment_id:
                invalid += 1
                continue
            snapshots.append(
                {
                    "environment_id": environment_id,
                    "status": raw.get("status")
                    if isinstance(raw.get("status"), str)
                    else "unknown",
                    "detected_at": raw.get("detected_at")
                    if isinstance(raw.get("detected_at"), str)
                    else None,
                    "summary": raw.get("summary") if isinstance(raw.get("summary"), str) else None,
                    "warning_count": len(raw.get("warnings", []))
                    if isinstance(raw.get("warnings"), list)
                    else 0,
                }
            )
        source_status = "ok" if missing == 0 and invalid == 0 else "partial"
        attention = source_status != "ok"
        return _CardResult(
            card_id="resources",
            data={
                "environment_count": len(environments),
                "snapshot_count": len(snapshots),
                "snapshots": snapshots,
                "missing_snapshot_count": missing + invalid,
            },
            source_status=source_status,
            data_cutoff_at=cutoff_at,
            attention_required=attention,
            error_summary=(
                "some persisted resource snapshots are unavailable" if attention else None
            ),
        )

    def _with_last_success(
        self, conn: sqlite3.Connection, owner_user_id: str, card: _CardResult
    ) -> _CardResult:
        if card.source_status in _SUCCESS_CARD_STATUSES:
            return card
        previous = conn.execute(
            """
            SELECT last_success_data_json, last_success_at, last_success_cutoff_at
            FROM overview_refresh_card_states
            WHERE owner_user_id = ? AND card_id = ?
            """,
            (owner_user_id, card.card_id),
        ).fetchone()
        if previous is None:
            return card
        data = _json_object(previous["last_success_data_json"], fallback=None)
        if data is None:
            return card
        cutoff = self._optional_str(previous["last_success_cutoff_at"]) or card.data_cutoff_at
        return _CardResult(
            card_id=card.card_id,
            data=data,
            source_status="stale",
            data_cutoff_at=cutoff,
            attention_required=True,
            error_summary=card.error_summary,
        )

    def _persist_claim_result(
        self,
        conn: sqlite3.Connection,
        claim: OverviewRefreshClaim,
        cards: list[_CardResult],
        current: datetime,
    ) -> OverviewRefreshRunResult:
        current_iso = _iso(current)
        self._write_fence.record_first_v2_write(conn, actor_id=claim.owner_user_id)
        fresh_cards = [card for card in cards if card.source_status in _SUCCESS_CARD_STATUSES]
        if not fresh_cards:
            # Retain per-card error/staleness evidence even though the snapshot
            # pointer itself remains on the last successful whole snapshot.
            for card in cards:
                self._upsert_card_state(conn, claim, card, current_iso)
            failure_outcome = self._retry_or_fail_claim_in_transaction(
                conn,
                claim,
                detail="all overview cards failed; last successful snapshot was retained",
                current=current,
            )
            if failure_outcome is None:
                conn.rollback()
                return OverviewRefreshRunResult(
                    job_id=claim.job_id,
                    outcome="claim_lost",
                    detail="overview refresh lease was lost before failure completion",
                )
            conn.commit()
            record_overview_event(
                failure_outcome,
                trigger=claim.trigger,
                user_id=claim.owner_user_id,
                job_id=claim.job_id,
            )
            return OverviewRefreshRunResult(
                job_id=claim.job_id,
                outcome=failure_outcome,
                detail="all overview cards failed; last successful snapshot was retained",
            )

        source_status = "ok" if len(fresh_cards) == len(cards) else "partial"
        job_status = "succeeded" if source_status == "ok" else "partial"
        attention_required = any(card.attention_required for card in cards)
        slot_date = claim.scheduled_for_date or current.astimezone(_SHANGHAI).date().isoformat()
        snapshot_id = f"overview-{uuid4().hex}"
        payload = self._snapshot_payload(
            snapshot_id=snapshot_id,
            owner_user_id=claim.owner_user_id,
            snapshot_date=slot_date,
            cards=cards,
            source_status=source_status,
            data_cutoff_at=current_iso,
            attention_required=attention_required,
        )
        conn.execute(
            """
            INSERT INTO overview_snapshots (
                snapshot_id, owner_user_id, snapshot_date, payload_json, created_at,
                data_cutoff_at, source_status, attention_required
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(owner_user_id, snapshot_date) DO UPDATE SET
                snapshot_id = excluded.snapshot_id,
                payload_json = excluded.payload_json,
                created_at = excluded.created_at,
                data_cutoff_at = excluded.data_cutoff_at,
                source_status = excluded.source_status,
                attention_required = excluded.attention_required
            """,
            (
                snapshot_id,
                claim.owner_user_id,
                slot_date,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                current_iso,
                current_iso,
                source_status,
                int(attention_required),
            ),
        )
        for card in cards:
            self._upsert_card_state(conn, claim, card, current_iso)
        if not self._finish_job_row(
            conn,
            claim,
            status=job_status,
            snapshot_id=snapshot_id,
            source_status=source_status,
            error_summary=None if source_status == "ok" else "one or more overview cards are stale",
            current_iso=current_iso,
        ):
            conn.rollback()
            return OverviewRefreshRunResult(
                job_id=claim.job_id,
                outcome="claim_lost",
                detail="overview refresh lease was lost before completion",
            )
        conn.commit()
        record_overview_event(
            job_status,
            trigger=claim.trigger,
            user_id=claim.owner_user_id,
            job_id=claim.job_id,
        )
        return OverviewRefreshRunResult(
            job_id=claim.job_id,
            outcome=job_status,
            snapshot_id=snapshot_id,
        )

    def _upsert_card_state(
        self,
        conn: sqlite3.Connection,
        claim: OverviewRefreshClaim,
        card: _CardResult,
        current_iso: str,
    ) -> None:
        successful = card.source_status in _SUCCESS_CARD_STATUSES
        current_data = (
            json.dumps(card.data, ensure_ascii=False, sort_keys=True)
            if card.data is not None
            else None
        )
        conn.execute(
            """
            INSERT INTO overview_refresh_card_states (
                owner_user_id, card_id, last_job_id, status, data_json, data_cutoff_at,
                last_success_data_json, last_success_at, last_success_cutoff_at,
                error_summary, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(owner_user_id, card_id) DO UPDATE SET
                last_job_id = excluded.last_job_id,
                status = excluded.status,
                data_json = excluded.data_json,
                data_cutoff_at = excluded.data_cutoff_at,
                last_success_data_json = CASE
                    WHEN excluded.last_success_data_json IS NOT NULL THEN excluded.last_success_data_json
                    ELSE overview_refresh_card_states.last_success_data_json
                END,
                last_success_at = CASE
                    WHEN excluded.last_success_at IS NOT NULL THEN excluded.last_success_at
                    ELSE overview_refresh_card_states.last_success_at
                END,
                last_success_cutoff_at = CASE
                    WHEN excluded.last_success_cutoff_at IS NOT NULL THEN excluded.last_success_cutoff_at
                    ELSE overview_refresh_card_states.last_success_cutoff_at
                END,
                error_summary = excluded.error_summary,
                updated_at = excluded.updated_at
            """,
            (
                claim.owner_user_id,
                card.card_id,
                claim.job_id,
                card.source_status,
                current_data,
                card.data_cutoff_at,
                current_data if successful else None,
                current_iso if successful else None,
                card.data_cutoff_at if successful else None,
                card.error_summary,
                current_iso,
            ),
        )

    def _finish_job_row(
        self,
        conn: sqlite3.Connection,
        claim: OverviewRefreshClaim,
        *,
        status: str,
        snapshot_id: str | None,
        source_status: str,
        error_summary: str | None,
        current_iso: str,
    ) -> bool:
        updated = conn.execute(
            """
            UPDATE overview_refresh_jobs
            SET status = ?, snapshot_id = ?, source_status = ?, error_summary = ?,
                finished_at = ?, heartbeat_at = ?, lease_owner = NULL, lease_token = NULL,
                lease_expires_at = NULL, next_retry_at = NULL, updated_at = ?
            WHERE job_id = ? AND status = 'running' AND lease_token = ?
              AND lease_expires_at IS NOT NULL AND lease_expires_at > ?
            """,
            (
                status,
                snapshot_id,
                source_status,
                error_summary,
                current_iso,
                current_iso,
                current_iso,
                claim.job_id,
                claim.lease_token,
                current_iso,
            ),
        ).rowcount
        return updated == 1

    def _fail_claim(
        self, claim: OverviewRefreshClaim, detail: str, current: datetime
    ) -> str | None:
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._assert_maintenance_writable(conn)
            self._write_fence.record_first_v2_write(conn, actor_id=claim.owner_user_id)
            outcome = self._retry_or_fail_claim_in_transaction(
                conn,
                claim,
                detail=detail,
                current=current,
            )
            if outcome is not None:
                conn.commit()
            else:
                conn.rollback()
        return outcome

    def _retry_or_fail_claim_in_transaction(
        self,
        conn: sqlite3.Connection,
        claim: OverviewRefreshClaim,
        *,
        detail: str,
        current: datetime,
    ) -> str | None:
        """Release one failed claim into bounded retry or terminal failure.

        The exact running-lease predicate makes a stale worker unable to
        override a later claimant.  ``retry_wait`` remains an active job for
        its owner, which both makes repeated manual clicks idempotent and
        prevents a restarted scheduler from skipping the failed daily slot.
        """

        current_iso = _iso(current)
        row = conn.execute(
            """
            SELECT retry_count FROM overview_refresh_jobs
            WHERE job_id = ? AND status = 'running' AND lease_token = ?
              AND lease_expires_at IS NOT NULL AND lease_expires_at > ?
            """,
            (claim.job_id, claim.lease_token, current_iso),
        ).fetchone()
        if row is None:
            return None
        retry_count = int(row["retry_count"]) + 1
        if retry_count <= _MAX_RETRY_COUNT:
            delay_seconds = min(
                _RETRY_BASE_DELAY_SECONDS * (2 ** (retry_count - 1)),
                _RETRY_MAX_DELAY_SECONDS,
            )
            next_retry_at = _iso(current + timedelta(seconds=delay_seconds))
            updated = conn.execute(
                """
                UPDATE overview_refresh_jobs
                SET status = 'retry_wait', retry_count = ?, next_retry_at = ?,
                    last_failure_at = ?, snapshot_id = NULL, source_status = 'failed',
                    error_summary = ?, finished_at = NULL, heartbeat_at = ?,
                    lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
                    updated_at = ?
                WHERE job_id = ? AND status = 'running' AND lease_token = ?
                  AND lease_expires_at IS NOT NULL AND lease_expires_at > ?
                """,
                (
                    retry_count,
                    next_retry_at,
                    current_iso,
                    detail[:1000],
                    current_iso,
                    current_iso,
                    claim.job_id,
                    claim.lease_token,
                    current_iso,
                ),
            ).rowcount
            return "retry_wait" if updated == 1 else None
        updated = conn.execute(
            """
            UPDATE overview_refresh_jobs
            SET status = 'failed', retry_count = ?, next_retry_at = NULL,
                last_failure_at = ?, snapshot_id = NULL, source_status = 'failed',
                error_summary = ?, finished_at = ?, heartbeat_at = ?,
                lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
                updated_at = ?
            WHERE job_id = ? AND status = 'running' AND lease_token = ?
              AND lease_expires_at IS NOT NULL AND lease_expires_at > ?
            """,
            (
                retry_count,
                current_iso,
                detail[:1000],
                current_iso,
                current_iso,
                current_iso,
                claim.job_id,
                claim.lease_token,
                current_iso,
            ),
        ).rowcount
        return "failed" if updated == 1 else None

    def _snapshot_payload(
        self,
        *,
        snapshot_id: str,
        owner_user_id: str,
        snapshot_date: str,
        cards: list[_CardResult],
        source_status: str,
        data_cutoff_at: str,
        attention_required: bool,
    ) -> dict[str, object]:
        card_payloads = [
            {
                "id": card.card_id,
                "data": card.data,
                "data_cutoff_at": card.data_cutoff_at,
                "source_status": card.source_status,
                "attention_required": card.attention_required,
                "error_summary": card.error_summary,
            }
            for card in cards
        ]
        domain_data = next(
            (card.data for card in cards if card.card_id == "domain" and card.data is not None), {}
        )
        return {
            "snapshot_id": snapshot_id,
            "owner_user_id": owner_user_id,
            "snapshot_date": snapshot_date,
            "data_cutoff_at": data_cutoff_at,
            "source_status": source_status,
            "attention_required": attention_required,
            "cards": card_payloads,
            # Compatibility scalar fields let legacy consumers render the new
            # persisted projection without reconstructing it themselves.
            "source": "control_plane_only",
            "projects_active": domain_data.get("projects_active", 0)
            if isinstance(domain_data, dict)
            else 0,
            "tasks_by_status": domain_data.get("tasks_by_status", {})
            if isinstance(domain_data, dict)
            else {},
            "active_attempts": domain_data.get("active_attempts", 0)
            if isinstance(domain_data, dict)
            else 0,
        }

    @staticmethod
    def _read_only_connection(path: Path) -> sqlite3.Connection:
        # ``mode=ro`` is important: an absent/corrupt literature DB must not
        # be created or repaired by an overview refresh.
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _optional_str(value: object) -> str | None:
        return value if isinstance(value, str) else None

    @staticmethod
    def _validate_date(value: str) -> None:
        try:
            datetime.fromisoformat(f"{value}T00:00:00+00:00")
        except ValueError as exc:
            raise ValueError("scheduled_for_date must be ISO YYYY-MM-DD") from exc

    @staticmethod
    def _active_job_for_owner(conn: sqlite3.Connection, owner_user_id: str) -> sqlite3.Row | None:
        return conn.execute(
            """
            SELECT * FROM overview_refresh_jobs
            WHERE owner_user_id = ? AND status IN ('queued', 'retry_wait', 'running')
            ORDER BY created_at ASC, job_id ASC LIMIT 1
            """,
            (owner_user_id,),
        ).fetchone()

    @staticmethod
    def _next_due_schedule_date(
        conn: sqlite3.Connection,
        owner_user_id: str,
        current_date: date,
        *,
        allow_initial_slot: bool = True,
    ) -> date | None:
        """Return the oldest outstanding Shanghai daily slot for one user.

        The active-job invariant intentionally permits only one queued,
        retry-wait, or running job per user.  The planner repeatedly calls this
        helper after each completion, thereby draining missed days in order
        without creating a second active job for the same user.
        """

        row = conn.execute(
            """
            SELECT MAX(scheduled_for_date) AS scheduled_for_date
            FROM overview_refresh_jobs WHERE owner_user_id = ?
            """,
            (owner_user_id,),
        ).fetchone()
        latest = _parse_date(row["scheduled_for_date"] if row is not None else None)
        if latest is None:
            # Before today's 06:00 boundary, there is no auditable basis to
            # infer a pre-registration historical slot for a new user.  Once
            # the boundary passes, initialize that user's current daily slot.
            return current_date if allow_initial_slot else None
        if latest >= current_date:
            return None
        # Do not silently discard older missed days.  The planner creates one
        # active job per user and drains sequentially, so a long outage remains
        # bounded per cycle while every Shanghai slot stays auditable.
        return latest + timedelta(days=1)

    @staticmethod
    def _job_dict(row: sqlite3.Row) -> dict[str, object]:
        return {
            "job_id": str(row["job_id"]),
            "owner_user_id": str(row["owner_user_id"]),
            "trigger": str(row["trigger"]),
            "scheduled_for_date": OverviewSnapshotService._optional_str(row["scheduled_for_date"]),
            "status": str(row["status"]),
            "attempt_count": int(row["attempt_count"]),
            "retry_count": int(row["retry_count"]),
            "next_retry_at": OverviewSnapshotService._optional_str(row["next_retry_at"]),
            "last_failure_at": OverviewSnapshotService._optional_str(row["last_failure_at"]),
            "snapshot_id": OverviewSnapshotService._optional_str(row["snapshot_id"]),
            "source_status": OverviewSnapshotService._optional_str(row["source_status"]),
            "error_summary": OverviewSnapshotService._optional_str(row["error_summary"]),
            "created_at": str(row["created_at"]),
            "started_at": OverviewSnapshotService._optional_str(row["started_at"]),
            "finished_at": OverviewSnapshotService._optional_str(row["finished_at"]),
            "heartbeat_at": OverviewSnapshotService._optional_str(row["heartbeat_at"]),
        }


class OverviewSnapshotPlanner:
    """Maintenance-aware 06:00 Asia/Shanghai overview scheduler.

    This is a no-port worker component.  It shares the durable participant
    registry with the Task dispatcher, so maintenance drains it before it can
    claim or write another overview job.
    """

    def __init__(
        self,
        state_root: Path,
        *,
        planner_id: str | None = None,
        artifact_sha: str | None = None,
        active_user_ids: Callable[[], Iterable[str]] | None = None,
        max_jobs_per_cycle: int = 20,
    ) -> None:
        if max_jobs_per_cycle <= 0:
            raise ValueError("max_jobs_per_cycle must be positive")
        self._maintenance = DomainMaintenanceService(state_root)
        self.planner_id = planner_id or f"overview-planner-{uuid4().hex[:12]}"
        self._participant = DomainWriteParticipant(
            self._maintenance,
            "overview-planner",
            participant_id=self.planner_id,
            details={"component": "domain-worker-overview"},
        )
        self._state_root = state_root
        self._artifact_sha = artifact_sha
        self._configured_active_user_ids = active_user_ids
        self._max_jobs_per_cycle = max_jobs_per_cycle
        self._started = False
        self._maintenance_startup_read_only = _maintenance_is_active_read_only(state_root)
        self._service: OverviewSnapshotService | None = None
        if not self._maintenance_startup_read_only:
            self._initialize_writable_service()

    def _initialize_writable_service(self) -> None:
        """Construct migration-capable Overview state behind one writer lease.

        The initial read-only probe covers a maintenance epoch that was
        already active when this process began.  The bootstrap lease closes
        the race with an epoch that starts between that probe and the
        constructor: the restore/cutover preflight sees the in-flight row and
        the post-construction check prevents this planner from starting.
        """

        try:
            lease = self._maintenance.begin_mutation(source="overview-planner.bootstrap")
        except MaintenanceModeError:
            self._maintenance_startup_read_only = True
            return
        try:
            self._maintenance.check_lease(lease)
            self._service = OverviewSnapshotService(
                self._state_root,
                artifact_sha=self._artifact_sha,
            )
            self._maintenance.check_lease(lease)
        except MaintenanceModeError:
            self._maintenance_startup_read_only = True
        finally:
            self._maintenance.finish_mutation(lease)

    def _start_as_drained_maintenance_participant(self) -> None:
        """Register this incomplete process without recreating writable state."""

        self._maintenance.adopt_existing_maintenance_schema()
        participant_status = self._participant.start()
        self._started = True
        if participant_status.status != "drained":
            # The epoch may have ended after the read-only probe.  This
            # process intentionally has no writable service graph; require a
            # clean restart rather than partially reconstructing one.
            self._participant.stop()

    def _require_service(self) -> OverviewSnapshotService:
        if self._service is None:
            raise MaintenanceModeError(
                "overview planner started read-only during maintenance; restart after maintenance exits"
            )
        return self._service

    def _active_user_ids(self) -> Iterable[str]:
        if self._configured_active_user_ids is not None:
            return self._configured_active_user_ids()
        return self._require_service().active_user_ids()

    @property
    def service(self) -> OverviewSnapshotService:
        return self._require_service()

    def request_refresh(
        self, owner_user_id: str, *, now: datetime | None = None
    ) -> dict[str, object]:
        """Enqueue a manual refresh while registered as a domain writer."""

        current = _as_utc(now)
        self.start(now=current)
        if self._maintenance_startup_read_only:
            raise MaintenanceModeError(
                "overview planner started read-only during maintenance; restart after maintenance exits"
            )
        participant_status = self._participant.heartbeat()
        if participant_status.status != "active":
            raise MaintenanceModeError("overview planner is drained for maintenance")
        try:
            lease = self._participant.begin_mutation(source="overview-planner.manual-refresh")
        except MaintenanceModeError:
            self._participant.drain()
            raise
        try:
            self._maintenance.check_lease(lease)
            job = self._require_service().request_refresh(
                owner_user_id, trigger="manual", now=current
            )
            self._maintenance.check_lease(lease)
            self._set_planner_state(status="running", now=current, last_error=None, lease=lease)
            return job
        except MaintenanceModeError:
            self._participant.drain()
            raise
        except Exception as exc:
            self._set_planner_state(status="running", now=current, last_error=str(exc), lease=lease)
            raise
        finally:
            self._participant.finish_mutation(lease)

    def run_job(self, job_id: str, *, now: datetime | None = None) -> OverviewRefreshRunResult:
        """Run one selected job through the planner's maintenance participant."""

        current = _as_utc(now)
        self.start(now=current)
        if self._maintenance_startup_read_only:
            return OverviewRefreshRunResult(job_id=job_id, outcome="maintenance_drained")
        participant_status = self._participant.heartbeat()
        if participant_status.status != "active":
            return OverviewRefreshRunResult(job_id=job_id, outcome="maintenance_drained")
        try:
            lease = self._participant.begin_mutation(source="overview-planner.manual-run")
        except MaintenanceModeError:
            self._participant.drain()
            return OverviewRefreshRunResult(job_id=job_id, outcome="maintenance_drained")
        try:
            self._maintenance.check_lease(lease)
            result = self._require_service().run_job(job_id, self.planner_id, now=current)
            self._maintenance.check_lease(lease)
            self._set_planner_state(
                status="running", now=current, last_error=result.detail, lease=lease
            )
            return result
        except MaintenanceModeError:
            self._participant.drain()
            return OverviewRefreshRunResult(job_id=job_id, outcome="maintenance_drained")
        except Exception as exc:
            self._set_planner_state(status="running", now=current, last_error=str(exc), lease=lease)
            return OverviewRefreshRunResult(job_id=job_id, outcome="failed", detail=str(exc))
        finally:
            self._participant.finish_mutation(lease)

    def start(self, *, now: datetime | None = None) -> None:
        if self._started:
            return
        if self._maintenance_startup_read_only or _maintenance_is_active_read_only(
            self._state_root
        ):
            self._maintenance_startup_read_only = True
            self._start_as_drained_maintenance_participant()
            return
        if self._service is None:
            # A bootstrap that raced a new maintenance epoch intentionally
            # leaves this process without an Overview service.  Never revive
            # such a partial graph after the epoch exits.
            self._maintenance_startup_read_only = True
            self._start_as_drained_maintenance_participant()
            return
        current = _as_utc(now)
        participant_status = self._participant.start()
        if participant_status.status != "active":
            # Registering while maintenance is active is required so the
            # process becomes a known drained writer.  It must not create a
            # planner-state heartbeat or a refresh job in that epoch.
            self._started = True
            return
        try:
            lease = self._participant.begin_mutation(source="overview-planner.start")
        except MaintenanceModeError:
            self._participant.drain()
            self._started = True
            return
        try:
            self._set_planner_state(status="running", now=current, last_error=None, lease=lease)
        except MaintenanceModeError:
            self._participant.drain()
            self._started = True
            return
        finally:
            self._participant.finish_mutation(lease)
        self._started = True

    def stop(self, *, now: datetime | None = None) -> None:
        if not self._started:
            return
        if self._maintenance_startup_read_only:
            self._participant.stop()
            self._started = False
            return
        current = _as_utc(now)
        try:
            participant_status = self._participant.heartbeat()
            if participant_status.status == "active":
                try:
                    lease = self._participant.begin_mutation(source="overview-planner.stop")
                except MaintenanceModeError:
                    self._participant.drain()
                else:
                    try:
                        self._set_planner_state(
                            status="stopped", now=current, last_error=None, lease=lease
                        )
                    except MaintenanceModeError:
                        self._participant.drain()
                    finally:
                        self._participant.finish_mutation(lease)
        finally:
            self._participant.stop()
            self._started = False

    def run_once(self, *, now: datetime | None = None) -> OverviewPlannerRunResult:
        current = _as_utc(now)
        self.start(now=current)
        if self._maintenance_startup_read_only:
            return OverviewPlannerRunResult(
                outcome="maintenance_drained", scheduled_job_ids=(), completed_job_ids=()
            )
        participant_status = self._participant.heartbeat()
        if participant_status.status == "drained":
            return OverviewPlannerRunResult(
                outcome="maintenance_drained", scheduled_job_ids=(), completed_job_ids=()
            )
        try:
            lease = self._participant.begin_mutation(source="overview-planner.refresh")
        except MaintenanceModeError:
            self._participant.drain()
            return OverviewPlannerRunResult(
                outcome="maintenance_drained", scheduled_job_ids=(), completed_job_ids=()
            )
        try:
            active_user_ids = tuple(self._active_user_ids())
            service = self._require_service()
            scheduled_by_id: dict[str, None] = {}
            completed: list[str] = []
            for _ in range(self._max_jobs_per_cycle):
                self._maintenance.check_lease(lease)
                for job in service.schedule_due_refreshes(
                    now=current, active_user_ids=active_user_ids
                ):
                    job_id = job.get("job_id")
                    if isinstance(job_id, str):
                        scheduled_by_id[job_id] = None
                result = service.run_next_job(self.planner_id, now=current)
                if result.outcome == "idle":
                    break
                if result.job_id is not None:
                    completed.append(result.job_id)
            self._maintenance.check_lease(lease)
            self._set_planner_state(
                status="running",
                now=current,
                last_error=None,
                last_schedule_at=current,
                lease=lease,
            )
            return OverviewPlannerRunResult(
                outcome="ok",
                scheduled_job_ids=tuple(scheduled_by_id),
                completed_job_ids=tuple(completed),
            )
        except MaintenanceModeError:
            self._participant.drain()
            return OverviewPlannerRunResult(
                outcome="maintenance_drained", scheduled_job_ids=(), completed_job_ids=()
            )
        except Exception as exc:
            self._set_planner_state(status="running", now=current, last_error=str(exc), lease=lease)
            return OverviewPlannerRunResult(
                outcome="failed", scheduled_job_ids=(), completed_job_ids=(), detail=str(exc)
            )
        finally:
            self._participant.finish_mutation(lease)

    def _set_planner_state(
        self,
        *,
        status: str,
        now: datetime,
        last_error: str | None,
        last_schedule_at: datetime | None = None,
        lease: MaintenanceLease,
    ) -> None:
        self._maintenance.check_lease(lease)
        current_iso = _iso(now)
        service = self._require_service()
        with closing(service._connect()) as conn:
            # Planner heartbeats are control-plane writes too.  Keep them
            # behind the same committed-v2 fuse as enqueue/claim/completion so
            # a legacy or prepared process cannot advertise a false-ready
            # Overview planner.
            service._write_fence.record_first_v2_write(conn, actor_id=self.planner_id)
            conn.execute(
                """
                INSERT INTO overview_planner_state (
                    singleton, planner_id, status, heartbeat_at, last_schedule_at,
                    last_error, updated_at
                ) VALUES (1, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(singleton) DO UPDATE SET
                    planner_id = excluded.planner_id,
                    status = excluded.status,
                    heartbeat_at = excluded.heartbeat_at,
                    last_schedule_at = COALESCE(excluded.last_schedule_at,
                                                overview_planner_state.last_schedule_at),
                    last_error = excluded.last_error,
                    updated_at = excluded.updated_at
                """,
                (
                    self.planner_id,
                    status,
                    current_iso,
                    _iso(last_schedule_at) if last_schedule_at is not None else None,
                    last_error,
                    current_iso,
                ),
            )
            self._check_state_write_lease(conn, lease)
            conn.commit()

    def _check_state_write_lease(self, conn: sqlite3.Connection, lease: MaintenanceLease) -> None:
        """Check a planner-state commit while its SQLite write lock is held."""

        state = conn.execute(
            "SELECT maintenance_epoch, is_active FROM domain_maintenance_state WHERE singleton = 1"
        ).fetchone()
        mutation = conn.execute(
            "SELECT 1 FROM domain_maintenance_mutations WHERE mutation_id = ?",
            (lease.mutation_id,),
        ).fetchone()
        if (
            state is None
            or mutation is None
            or bool(state["is_active"])
            or int(state["maintenance_epoch"]) != lease.maintenance_epoch
        ):
            raise MaintenanceModeError("overview planner write crossed a maintenance epoch")
