"""Read-only projections for authoritative Conversation Tasks.

This Module keeps compatibility serialization behind one Interface.  Ordinary
HTTP callers never need to know how Task/Turn/Item/Submission/Execution facts
map onto the temporarily retained Task summary transport.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from ainrf.domain.attempt_projection import AttemptProjectionService, TOKEN_TOTAL_FIELDS


def _mapping(value: object) -> Mapping[str, object]:
    return cast(Mapping[str, object], value) if isinstance(value, Mapping) else {}


def _integer(value: object) -> int:
    return int(value) if isinstance(value, int | float) else 0


def _number(value: object) -> float:
    return float(value) if isinstance(value, int | float) else 0.0


def _duration_ms(started_at: object, finished_at: object) -> int | None:
    if not isinstance(started_at, str) or not isinstance(finished_at, str):
        return None
    try:
        return max(
            int(
                (datetime.fromisoformat(finished_at) - datetime.fromisoformat(started_at))
                .total_seconds()
                * 1000
            ),
            0,
        )
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class ConversationTaskProjection:
    status: str
    started_at: str | None
    completed_at: str | None
    latest_item_seq: int
    error_summary: str | None
    execution_alive: bool
    last_event_at: str | None
    turns: tuple[dict[str, object], ...]


class ConversationProjectionService:
    """Project Conversation facts without exposing persistence identities."""

    _ACTIVE_EXECUTION = frozenset({"starting", "running", "reconciling"})
    _PENDING_SUBMISSION = frozenset({"queued", "claimed", "delivering", "delivery_unknown"})

    def projections_for_tasks(
        self, conn: sqlite3.Connection, task_ids: Sequence[str]
    ) -> dict[str, ConversationTaskProjection]:
        unique = tuple(dict.fromkeys(task_id for task_id in task_ids if task_id))
        if not unique:
            return {}
        placeholders = ", ".join("?" for _ in unique)
        states = {
            str(row["task_id"]): str(row["work_status"])
            for row in conn.execute(
                f"SELECT task_id, work_status FROM conversation_task_states "
                f"WHERE task_id IN ({placeholders})",
                unique,
            ).fetchall()
        }
        turns_by_task: dict[str, list[sqlite3.Row]] = {task_id: [] for task_id in unique}
        for row in conn.execute(
            f"SELECT * FROM task_turns WHERE task_id IN ({placeholders}) "
            "ORDER BY task_id, turn_seq",
            unique,
        ).fetchall():
            turns_by_task[str(row["task_id"])].append(row)
        executions_by_turn: dict[str, list[sqlite3.Row]] = {}
        for row in conn.execute(
            f"SELECT execution.* FROM runtime_executions AS execution "
            f"WHERE execution.task_id IN ({placeholders}) "
            "ORDER BY execution.turn_id, execution.execution_seq",
            unique,
        ).fetchall():
            executions_by_turn.setdefault(str(row["turn_id"]), []).append(row)
        submissions_by_task: dict[str, list[sqlite3.Row]] = {task_id: [] for task_id in unique}
        for row in conn.execute(
            f"SELECT * FROM turn_submissions WHERE task_id IN ({placeholders}) "
            "ORDER BY task_id, created_at, submission_id",
            unique,
        ).fetchall():
            submissions_by_task[str(row["task_id"])].append(row)
        items_by_turn: dict[str, list[sqlite3.Row]] = {}
        for row in conn.execute(
            f"SELECT * FROM turn_items WHERE task_id IN ({placeholders}) "
            "ORDER BY turn_id, turn_item_seq",
            unique,
        ).fetchall():
            items_by_turn.setdefault(str(row["turn_id"]), []).append(row)

        result: dict[str, ConversationTaskProjection] = {}
        for task_id in unique:
            turns = turns_by_task[task_id]
            executions = [
                execution
                for turn in turns
                for execution in executions_by_turn.get(str(turn["turn_id"]), [])
            ]
            items = [item for turn in turns for item in items_by_turn.get(str(turn["turn_id"]), [])]
            alive = any(str(row["status"]) in self._ACTIVE_EXECUTION for row in executions)
            pending = any(
                str(row["status"]) in self._PENDING_SUBMISSION
                for row in submissions_by_task[task_id]
            )
            work_status = states.get(task_id, "open")
            latest_turn = turns[-1] if turns else None
            status = self._task_status(
                work_status=work_status,
                latest_turn=latest_turn,
                execution_alive=alive,
                submission_pending=pending,
            )
            started = [str(row["started_at"]) for row in turns if row["started_at"]]
            finished = [str(row["finished_at"]) for row in turns if row["finished_at"]]
            last_events = [
                str(value)
                for row in (*executions, *items)
                for value in (row["updated_at"] if "updated_at" in row.keys() else None,
                              row["persisted_at"] if "persisted_at" in row.keys() else None)
                if value
            ]
            turn_projections = tuple(
                self._turn_projection(
                    turn,
                    executions_by_turn.get(str(turn["turn_id"]), []),
                    items_by_turn.get(str(turn["turn_id"]), []),
                )
                for turn in turns
            )
            result[task_id] = ConversationTaskProjection(
                status=status,
                started_at=min(started) if started else None,
                completed_at=max(finished) if finished else None,
                latest_item_seq=max((int(row["task_item_seq"]) for row in items), default=0),
                error_summary=(
                    str(latest_turn["failure_code"])
                    if latest_turn is not None and latest_turn["failure_code"] is not None
                    else None
                ),
                execution_alive=alive,
                last_event_at=max(last_events) if last_events else None,
                turns=turn_projections,
            )
        return result

    @staticmethod
    def _task_status(
        *,
        work_status: str,
        latest_turn: sqlite3.Row | None,
        execution_alive: bool,
        submission_pending: bool,
    ) -> str:
        if execution_alive:
            return "running"
        if submission_pending:
            return "queued"
        if work_status == "cancelled":
            return "cancelled"
        if latest_turn is not None:
            turn_status = str(latest_turn["status"])
            if turn_status == "failed":
                return "failed"
            if turn_status == "interrupted":
                return "cancelled"
            if turn_status == "completed" and work_status == "completed":
                return "succeeded"
        return "completed" if work_status == "completed" else "queued"

    @staticmethod
    def _turn_projection(
        turn: sqlite3.Row,
        executions: Sequence[sqlite3.Row],
        items: Sequence[sqlite3.Row],
    ) -> dict[str, object]:
        usage_total: dict[str, int | float] = {field: 0 for field in TOKEN_TOTAL_FIELDS}
        usage_total["cost_usd"] = 0.0
        by_model: dict[str, dict[str, int | float]] = {}
        has_usage = False
        for item in items:
            try:
                payload = json.loads(str(item["payload_json"]))
            except json.JSONDecodeError:
                continue
            usage = _mapping(_mapping(payload).get("usage"))
            if not usage:
                continue
            has_usage = True
            total = _mapping(usage.get("total")) or usage
            for field in TOKEN_TOTAL_FIELDS:
                usage_total[field] = _integer(usage_total[field]) + _integer(total.get(field))
            usage_total["cost_usd"] = _number(usage_total["cost_usd"]) + _number(
                total.get("cost_usd")
            )
            model = usage.get("model") or payload.get("model")
            if isinstance(model, str) and model:
                aggregate = by_model.setdefault(
                    model,
                    {field: 0 for field in TOKEN_TOTAL_FIELDS}
                    | {"cost_usd": 0.0, "tokens": 0},
                )
                for field in TOKEN_TOTAL_FIELDS:
                    aggregate[field] = _integer(aggregate[field]) + _integer(total.get(field))
                aggregate["cost_usd"] = _number(aggregate["cost_usd"]) + _number(
                    total.get("cost_usd")
                )
                aggregate["tokens"] = sum(_integer(aggregate[field]) for field in TOKEN_TOTAL_FIELDS)
        token_usage_json = None
        if has_usage:
            token_usage_json = json.dumps(
                {"total": usage_total, "by_model": by_model},
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
        latest_execution = executions[-1] if executions else None
        started_at = turn["started_at"] or (
            None if latest_execution is None else latest_execution["started_at"]
        )
        finished_at = turn["finished_at"] or (
            None if latest_execution is None else latest_execution["finished_at"]
        )
        return {
            "turn_id": str(turn["turn_id"]),
            "status": str(turn["status"]),
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_ms": _duration_ms(started_at, finished_at),
            "token_usage_json": token_usage_json,
            "cost_usd": _number(usage_total["cost_usd"]) if has_usage else None,
        }

    @staticmethod
    def usage_json(projection: ConversationTaskProjection) -> str | None:
        return AttemptProjectionService.usage_json(projection.turns)
