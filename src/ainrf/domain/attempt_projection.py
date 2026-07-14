"""Shared read-only TaskAttempt and RuntimeSession projections.

The v2 control plane records execution facts on ``agent_task_attempts`` and
``agent_runtime_sessions``.  Compatibility views (the former Session API),
Task history, and cost/usage summaries must all derive from those same rows;
none of them may reach into ``sessions.sqlite3``.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import cast

from ainrf.db import connect, run_pending

TOKEN_TOTAL_FIELDS: tuple[str, ...] = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _optional_int(value: object) -> int | None:
    return int(value) if isinstance(value, int | float) else None


def _number(value: object) -> float:
    return float(value) if isinstance(value, int | float) else 0.0


def _integer(value: object) -> int:
    return int(value) if isinstance(value, int | float) else 0


def _duration_ms(started_at: object, finished_at: object) -> int | None:
    if not isinstance(started_at, str) or not isinstance(finished_at, str):
        return None
    try:
        duration = int(
            (
                datetime.fromisoformat(finished_at) - datetime.fromisoformat(started_at)
            ).total_seconds()
            * 1000
        )
    except ValueError:
        return None
    return max(duration, 0)


def _token_usage(value: object) -> dict[str, object] | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return None
    return decoded if isinstance(decoded, dict) else None


def _object_mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return cast(Mapping[str, object], value)


def _usage_total(usage: Mapping[str, object] | None) -> Mapping[str, object]:
    if usage is None:
        return {}
    return _object_mapping(usage.get("total"))


def _usage_models(usage: Mapping[str, object] | None) -> Mapping[str, object]:
    if usage is None:
        return {}
    return _object_mapping(usage.get("by_model"))


@dataclass(frozen=True, slots=True)
class AttemptAggregate:
    """Usage/cost/duration totals derived from one or more Attempt projections."""

    attempt_count: int
    duration_ms: int
    cost_usd: float
    tokens: int
    has_usage: bool
    token_total: dict[str, int | float]
    by_model: dict[str, dict[str, int | float]]


class AttemptProjectionService:
    """Read TaskAttempt data and aggregate it without a mutable capability."""

    def __init__(self, state_root: Path) -> None:
        self._db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(connect(self._db_path)) as conn:
            run_pending(conn, "agentic_researcher")

    def _connect(self) -> sqlite3.Connection:
        return connect(self._db_path)

    def attempts_for_tasks(
        self,
        conn: sqlite3.Connection,
        task_ids: Sequence[str],
        *,
        include_runtime_diagnostics: bool = False,
    ) -> dict[str, list[dict[str, object]]]:
        """Return Attempt projections grouped by Task with runtime/dispatch state.

        Callers must check visibility before passing IDs.  Keeping authorization
        at the resource layer lets a Project aggregate intentionally include all
        Tasks visible through the Project's membership policy.
        """

        unique_task_ids = tuple(dict.fromkeys(task_id for task_id in task_ids if task_id))
        grouped: dict[str, list[dict[str, object]]] = {task_id: [] for task_id in unique_task_ids}
        if not unique_task_ids:
            return grouped

        task_placeholders = ", ".join("?" for _ in unique_task_ids)
        attempt_rows = conn.execute(
            f"""SELECT * FROM agent_task_attempts
                 WHERE task_id IN ({task_placeholders})
                 ORDER BY task_id ASC, attempt_seq ASC, created_at ASC""",
            unique_task_ids,
        ).fetchall()
        if not attempt_rows:
            return grouped

        attempt_ids = tuple(str(row["attempt_id"]) for row in attempt_rows)
        attempt_placeholders = ", ".join("?" for _ in attempt_ids)
        runtime_by_attempt: dict[str, list[dict[str, object]]] = {
            attempt_id: [] for attempt_id in attempt_ids
        }
        runtime_rows = conn.execute(
            f"""SELECT * FROM agent_runtime_sessions
                 WHERE attempt_id IN ({attempt_placeholders})
                 ORDER BY attempt_id ASC, created_at ASC, runtime_session_id ASC""",
            attempt_ids,
        ).fetchall()
        for row in runtime_rows:
            runtime_by_attempt[str(row["attempt_id"])].append(
                self._runtime_session_dict(
                    row,
                    include_runtime_diagnostics=include_runtime_diagnostics,
                )
            )

        dispatch_by_attempt: dict[str, dict[str, object]] = {}
        dispatch_rows = conn.execute(
            f"""SELECT * FROM task_dispatch_outbox
                 WHERE attempt_id IN ({attempt_placeholders})
                 ORDER BY attempt_id ASC, created_at DESC, dispatch_id DESC""",
            attempt_ids,
        ).fetchall()
        for row in dispatch_rows:
            attempt_id = str(row["attempt_id"])
            dispatch_by_attempt.setdefault(
                attempt_id,
                self._dispatch_dict(
                    row,
                    include_runtime_diagnostics=include_runtime_diagnostics,
                ),
            )

        for row in attempt_rows:
            attempt_id = str(row["attempt_id"])
            task_id = str(row["task_id"])
            grouped[task_id].append(
                self._attempt_dict(
                    row,
                    runtime_sessions=runtime_by_attempt[attempt_id],
                    dispatch=dispatch_by_attempt.get(attempt_id),
                    include_runtime_diagnostics=include_runtime_diagnostics,
                )
            )
        return grouped

    def attempt(
        self,
        conn: sqlite3.Connection,
        attempt_id: str,
        *,
        include_runtime_diagnostics: bool = False,
    ) -> dict[str, object] | None:
        """Return an Attempt projection by ID without performing authorization."""

        row = conn.execute(
            "SELECT task_id FROM agent_task_attempts WHERE attempt_id = ?", (attempt_id,)
        ).fetchone()
        if row is None:
            return None
        attempts = self.attempts_for_tasks(
            conn,
            [str(row["task_id"])],
            include_runtime_diagnostics=include_runtime_diagnostics,
        )
        for attempt in attempts[str(row["task_id"])]:
            if attempt["attempt_id"] == attempt_id:
                return attempt
        return None

    def task_usage_summary(
        self,
        user: Mapping[str, object],
        *,
        include_archived: bool,
    ) -> dict[str, object]:
        """Summarize visible Task usage from their durable Attempts only."""

        clauses: list[str] = ["1 = 1"]
        params: list[object] = []
        if user.get("role") != "admin":
            user_id = user.get("id")
            if not isinstance(user_id, str) or not user_id:
                return self._empty_usage_summary()
            clauses.append("owner_user_id = ?")
            params.append(user_id)
        if not include_archived:
            clauses.append("archived_at IS NULL")

        query = f"SELECT * FROM tasks WHERE {' AND '.join(clauses)}"
        with closing(self._connect()) as conn:
            task_rows = conn.execute(query, tuple(params)).fetchall()
            attempts_by_task = self.attempts_for_tasks(
                conn,
                [str(row["task_id"]) for row in task_rows],
            )

        return self._usage_summary_for_tasks(task_rows, attempts_by_task)

    def project_cost_summary(
        self,
        project_id: str,
        _user: Mapping[str, object],
    ) -> dict[str, object]:
        """Return a Project cost projection after the route checked visibility.

        Project visibility is intentionally enforced by ``DomainService`` at the
        route boundary: project members may see aggregate cost for every Task in
        their visible Project, not just Tasks they personally own.
        """

        with closing(self._connect()) as conn:
            task_rows = conn.execute(
                "SELECT * FROM tasks WHERE project_id = ? ORDER BY task_id ASC",
                (project_id,),
            ).fetchall()
            attempts_by_task = self.attempts_for_tasks(
                conn,
                [str(row["task_id"]) for row in task_rows],
            )

        total = self.aggregate(
            [attempt for row in task_rows for attempt in attempts_by_task[str(row["task_id"])]]
        )
        return {
            "project_id": project_id,
            "total_cost_usd": total.cost_usd,
            "total_tokens": total.tokens,
            # A v2 Session is a compatibility projection of one Task.
            "session_count": len(task_rows),
            "by_model": total.by_model,
        }

    @staticmethod
    def usage_json(attempts: Sequence[Mapping[str, object]]) -> str | None:
        """Serialize a compatibility Task usage value from Attempt aggregates."""

        aggregate = AttemptProjectionService.aggregate(attempts)
        if not aggregate.has_usage:
            return None
        return json.dumps(
            {"total": aggregate.token_total, "by_model": aggregate.by_model},
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )

    @staticmethod
    def _empty_usage_summary() -> dict[str, object]:
        return {
            "task_count": 0,
            "tasks_with_usage": 0,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "total_duration_ms": 0,
            "median_duration_ms": None,
            "top_tasks": [],
            "total": {
                **{field: 0 for field in TOKEN_TOTAL_FIELDS},
                "cost_usd": 0.0,
            },
            "by_model": {},
            "by_engine": {},
        }

    @classmethod
    def _usage_summary_for_tasks(
        cls,
        task_rows: Sequence[sqlite3.Row],
        attempts_by_task: Mapping[str, Sequence[Mapping[str, object]]],
    ) -> dict[str, object]:
        summary = cls._empty_usage_summary()
        summary["task_count"] = len(task_rows)
        durations: list[int] = []
        top_tasks: list[dict[str, int | float | str | None]] = []
        all_attempts: list[Mapping[str, object]] = []
        by_engine: dict[str, dict[str, int | float]] = {}

        for row in task_rows:
            task_id = str(row["task_id"])
            attempts = attempts_by_task[task_id]
            aggregate = cls.aggregate(attempts)
            all_attempts.extend(attempts)
            if aggregate.duration_ms > 0:
                durations.append(aggregate.duration_ms)

            engine = str(row["harness_engine"])
            engine_summary = by_engine.setdefault(
                engine,
                {
                    "task_count": 0,
                    "tasks_with_usage": 0,
                    "tokens": 0,
                    "cost_usd": 0.0,
                },
            )
            engine_summary["task_count"] = _integer(engine_summary["task_count"]) + 1
            engine_summary["tokens"] = _integer(engine_summary["tokens"]) + aggregate.tokens
            engine_summary["cost_usd"] = _number(engine_summary["cost_usd"]) + aggregate.cost_usd
            if aggregate.has_usage:
                summary["tasks_with_usage"] = _integer(summary["tasks_with_usage"]) + 1
                engine_summary["tasks_with_usage"] = (
                    _integer(engine_summary["tasks_with_usage"]) + 1
                )
            if aggregate.tokens > 0:
                top_tasks.append(
                    {
                        "task_id": task_id,
                        "title": str(row["title"]),
                        "status": str(row["status"]),
                        "harness_engine": engine,
                        "total_tokens": aggregate.tokens,
                        "cost_usd": aggregate.cost_usd,
                        "duration_ms": aggregate.duration_ms or None,
                    }
                )

        total = cls.aggregate(all_attempts)
        summary["total_tokens"] = total.tokens
        summary["total_cost_usd"] = total.cost_usd
        summary["total_duration_ms"] = total.duration_ms
        summary["median_duration_ms"] = int(median(durations)) if durations else None
        summary["top_tasks"] = sorted(
            top_tasks,
            key=lambda item: (-_integer(item["total_tokens"]), str(item["task_id"])),
        )[:5]
        summary["total"] = total.token_total
        summary["by_model"] = total.by_model
        summary["by_engine"] = {
            engine: {
                **{
                    "task_count": _integer(values["task_count"]),
                    "tasks_with_usage": _integer(values["tasks_with_usage"]),
                    "tokens": _integer(values["tokens"]),
                },
                "cost_usd": round(_number(values["cost_usd"]), 6),
            }
            for engine, values in by_engine.items()
        }
        return summary

    @staticmethod
    def aggregate(attempts: Sequence[Mapping[str, object]]) -> AttemptAggregate:
        """Aggregate only authoritative Attempt usage, cost, and timestamps."""

        token_total: dict[str, int | float] = {field: 0 for field in TOKEN_TOTAL_FIELDS}
        token_total["cost_usd"] = 0.0
        by_model: dict[str, dict[str, int | float]] = {}
        total_duration_ms = 0
        total_cost_usd = 0.0
        total_tokens = 0
        has_usage = False

        for attempt in attempts:
            duration_ms = attempt.get("duration_ms")
            if isinstance(duration_ms, int):
                total_duration_ms += duration_ms

            usage = _token_usage(attempt.get("token_usage_json"))
            usage_total = _usage_total(usage)
            if usage is not None or attempt.get("cost_usd") is not None:
                has_usage = True
            attempt_cost = attempt.get("cost_usd")
            cost = (
                _number(attempt_cost)
                if attempt_cost is not None
                else _number(usage_total.get("cost_usd"))
            )
            total_cost_usd += cost
            token_total["cost_usd"] = _number(token_total["cost_usd"]) + cost

            for field in TOKEN_TOTAL_FIELDS:
                value = _integer(usage_total.get(field))
                token_total[field] = _integer(token_total[field]) + value
                total_tokens += value

            for model, model_usage_raw in _usage_models(usage).items():
                model_usage_raw = _object_mapping(model_usage_raw)
                if not model_usage_raw:
                    continue
                model_usage = by_model.setdefault(
                    str(model),
                    {field: 0 for field in TOKEN_TOTAL_FIELDS} | {"cost_usd": 0.0, "tokens": 0},
                )
                for field in TOKEN_TOTAL_FIELDS:
                    model_usage[field] = _integer(model_usage[field]) + _integer(
                        model_usage_raw.get(field)
                    )
                model_usage["cost_usd"] = _number(model_usage["cost_usd"]) + _number(
                    model_usage_raw.get("cost_usd")
                )
                model_usage["tokens"] = sum(
                    _integer(model_usage[field]) for field in TOKEN_TOTAL_FIELDS
                )

        return AttemptAggregate(
            attempt_count=len(attempts),
            duration_ms=total_duration_ms,
            cost_usd=round(total_cost_usd, 6),
            tokens=total_tokens,
            has_usage=has_usage,
            token_total={
                **{field: _integer(token_total[field]) for field in TOKEN_TOTAL_FIELDS},
                "cost_usd": round(_number(token_total["cost_usd"]), 6),
            },
            by_model={
                model: {
                    **{field: _integer(values[field]) for field in TOKEN_TOTAL_FIELDS},
                    "cost_usd": round(_number(values["cost_usd"]), 6),
                    "tokens": _integer(values["tokens"]),
                }
                for model, values in by_model.items()
            },
        )

    @staticmethod
    def _attempt_dict(
        row: sqlite3.Row,
        *,
        runtime_sessions: list[dict[str, object]],
        dispatch: dict[str, object] | None,
        include_runtime_diagnostics: bool,
    ) -> dict[str, object]:
        started_at = _optional_str(row["started_at"])
        finished_at = _optional_str(row["finished_at"])
        if started_at is None:
            started_at = next(
                (
                    str(runtime["started_at"])
                    for runtime in runtime_sessions
                    if isinstance(runtime.get("started_at"), str)
                ),
                None,
            )
        if finished_at is None:
            finished_at = next(
                (
                    str(runtime["finished_at"])
                    for runtime in reversed(runtime_sessions)
                    if isinstance(runtime.get("finished_at"), str)
                ),
                None,
            )
        return {
            "attempt_id": str(row["attempt_id"]),
            "task_id": str(row["task_id"]),
            "attempt_seq": int(row["attempt_seq"]),
            "trigger": str(row["trigger"]),
            "status": str(row["status"]),
            "context_snapshot_id": _optional_str(row["context_snapshot_id"]),
            "created_at": str(row["created_at"]),
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_ms": _duration_ms(started_at, finished_at),
            "message_start_seq": _optional_int(row["message_start_seq"]),
            "message_end_seq": _optional_int(row["message_end_seq"]),
            "output_start_seq": _optional_int(row["output_start_seq"]),
            "output_end_seq": _optional_int(row["output_end_seq"]),
            "artifact_refs": AttemptProjectionService._string_list(row["artifact_refs_json"]),
            "code_refs": AttemptProjectionService._string_list(row["code_refs_json"]),
            "data_refs": AttemptProjectionService._string_list(row["data_refs_json"]),
            "token_usage_json": _optional_str(row["token_usage_json"]),
            "cost_usd": float(row["cost_usd"]) if row["cost_usd"] is not None else None,
            # Failure/stop text and authorization snapshots are operational
            # diagnostics, not shared Project content.  In particular, engine
            # errors can contain a tenant-private filesystem path.  Preserve
            # the user-visible Attempt status/timestamps above while exposing
            # these fields only to the admin troubleshooting projection.
            "failure_reason": (
                _optional_str(row["failure_reason"]) if include_runtime_diagnostics else None
            ),
            "stop_reason": (
                _optional_str(row["stop_reason"]) if include_runtime_diagnostics else None
            ),
            "authorization_environment_id": (
                _optional_str(row["authorization_environment_id"])
                if include_runtime_diagnostics
                else None
            ),
            "authorization_grant_version": (
                _optional_int(row["authorization_grant_version"])
                if include_runtime_diagnostics
                else None
            ),
            "authorization_checked_at": (
                _optional_str(row["authorization_checked_at"])
                if include_runtime_diagnostics
                else None
            ),
            "stop_requested_at": (
                _optional_str(row["stop_requested_at"]) if include_runtime_diagnostics else None
            ),
            "stop_requested_reason": (
                _optional_str(row["stop_requested_reason"]) if include_runtime_diagnostics else None
            ),
            "runtime_sessions": runtime_sessions,
            "dispatch": dispatch,
        }

    @staticmethod
    def _runtime_session_dict(
        row: sqlite3.Row,
        *,
        include_runtime_diagnostics: bool,
    ) -> dict[str, object]:
        """Project a RuntimeSession without leaking control-plane credentials.

        Project viewers are entitled to durable execution state, not the
        engine-native session handle or an error string that can contain a
        tenant-private path.  Administrators use the same projection from a
        management/troubleshooting surface and receive the complete fields.
        """

        return {
            "runtime_session_id": str(row["runtime_session_id"]),
            "attempt_id": str(row["attempt_id"]),
            "status": str(row["status"]),
            "engine_name": _optional_str(row["engine_name"]),
            "engine_session_key": (
                _optional_str(row["engine_session_key"]) if include_runtime_diagnostics else None
            ),
            "created_at": str(row["created_at"]),
            "started_at": _optional_str(row["started_at"]),
            "finished_at": _optional_str(row["finished_at"]),
            "last_probe_at": _optional_str(row["last_probe_at"]),
            "adopted_at": _optional_str(row["adopted_at"]),
            "failure_reason": (
                _optional_str(row["failure_reason"]) if include_runtime_diagnostics else None
            ),
        }

    @staticmethod
    def _dispatch_dict(
        row: sqlite3.Row,
        *,
        include_runtime_diagnostics: bool,
    ) -> dict[str, object]:
        """Project dispatch status while hiding worker-control identifiers."""

        return {
            "dispatch_id": str(row["dispatch_id"]),
            "task_id": str(row["task_id"]),
            "attempt_id": str(row["attempt_id"]),
            "status": str(row["status"]),
            "launch_state": str(row["launch_state"]),
            "runtime_launch_key": (
                _optional_str(row["runtime_launch_key"]) if include_runtime_diagnostics else None
            ),
            "dispatcher_id": (
                _optional_str(row["dispatcher_id"]) if include_runtime_diagnostics else None
            ),
            "claimed_at": (
                _optional_str(row["claimed_at"]) if include_runtime_diagnostics else None
            ),
            "claim_expires_at": (
                _optional_str(row["claim_expires_at"]) if include_runtime_diagnostics else None
            ),
            "claim_heartbeat_at": (
                _optional_str(row["claim_heartbeat_at"]) if include_runtime_diagnostics else None
            ),
            "created_at": str(row["created_at"]),
            "updated_at": _optional_str(row["updated_at"]),
            "completed_at": _optional_str(row["completed_at"]),
            "cancelled_at": _optional_str(row["cancelled_at"]),
            "cancel_reason": (
                _optional_str(row["cancel_reason"]) if include_runtime_diagnostics else None
            ),
            "last_error": (
                _optional_str(row["last_error"]) if include_runtime_diagnostics else None
            ),
        }

    @staticmethod
    def _string_list(value: object) -> list[str]:
        if not isinstance(value, str):
            return []
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return []
        if not isinstance(decoded, list):
            return []
        return [item for item in decoded if isinstance(item, str)]
