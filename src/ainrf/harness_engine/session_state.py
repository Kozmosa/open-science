from __future__ import annotations

import json
import os
import secrets
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

if TYPE_CHECKING:
    from ainrf.harness_engine.base import ExecutionContext


_RUNTIME_LAUNCH_RECORD_VERSION = 1
_RUNTIME_LAUNCH_PHASES = frozenset({"armed", "launching", "running", "finished"})
_RUNTIME_PROBE_TOKEN_ENV = "OPENSCIENCE_RUNTIME_PROBE_TOKEN"


class RuntimeLaunchRecordError(ValueError):
    """A durable engine launch record cannot be trusted."""


@dataclass(frozen=True, slots=True)
class RuntimeLaunchRecord:
    """Durable evidence about one engine-side launch boundary.

    The domain dispatcher persists its own ``starting`` record before it
    reaches an engine.  This companion record narrows the process-level race:
    ``armed`` proves that the engine has *not* started an external process;
    ``launching`` means the process boundary may have been crossed and is
    therefore deliberately uncertain until a PID/start-time pair or marker
    proves it is still alive.

    It is intentionally local to an Attempt's checkpoint directory.  It does
    not make a stdio process reconnectable; it only gives recovery code enough
    durable evidence to avoid treating uncertainty as absence.
    """

    version: int
    engine_type: str
    task_id: str
    launch_key: str
    phase: Literal["armed", "launching", "running", "finished"]
    probe_token: str
    created_at: str
    updated_at: str
    engine_session_key: str | None = None
    process_id: int | None = None
    process_start_ticks: int | None = None
    finished_at: str | None = None

    @classmethod
    def from_json(cls, payload: object) -> RuntimeLaunchRecord:
        """Parse a record strictly so corrupted evidence never proves absence."""

        if not isinstance(payload, dict):
            raise RuntimeLaunchRecordError("Runtime launch record must be an object")
        data = cast(dict[str, object], payload)
        required_strings = (
            "engine_type",
            "task_id",
            "launch_key",
            "phase",
            "probe_token",
            "created_at",
            "updated_at",
        )
        if data.get("version") != _RUNTIME_LAUNCH_RECORD_VERSION:
            raise RuntimeLaunchRecordError("Unsupported runtime launch record version")
        for key in required_strings:
            value = data.get(key)
            if not isinstance(value, str) or not value:
                raise RuntimeLaunchRecordError(f"Runtime launch record has invalid {key}")
        phase = data["phase"]
        if phase not in _RUNTIME_LAUNCH_PHASES:
            raise RuntimeLaunchRecordError("Runtime launch record has invalid phase")
        process_id = data.get("process_id")
        process_start_ticks = data.get("process_start_ticks")
        if process_id is not None and (not isinstance(process_id, int) or process_id <= 0):
            raise RuntimeLaunchRecordError("Runtime launch record has invalid process_id")
        if process_start_ticks is not None and (
            not isinstance(process_start_ticks, int) or process_start_ticks < 0
        ):
            raise RuntimeLaunchRecordError("Runtime launch record has invalid process_start_ticks")
        engine_session_key = data.get("engine_session_key")
        if engine_session_key is not None and not isinstance(engine_session_key, str):
            raise RuntimeLaunchRecordError("Runtime launch record has invalid engine_session_key")
        finished_at = data.get("finished_at")
        if finished_at is not None and not isinstance(finished_at, str):
            raise RuntimeLaunchRecordError("Runtime launch record has invalid finished_at")
        return cls(
            version=_RUNTIME_LAUNCH_RECORD_VERSION,
            engine_type=str(data["engine_type"]),
            task_id=str(data["task_id"]),
            launch_key=str(data["launch_key"]),
            phase=cast(Literal["armed", "launching", "running", "finished"], phase),
            probe_token=str(data["probe_token"]),
            created_at=str(data["created_at"]),
            updated_at=str(data["updated_at"]),
            engine_session_key=engine_session_key,
            process_id=process_id,
            process_start_ticks=process_start_ticks,
            finished_at=finished_at,
        )


@dataclass(frozen=True, slots=True)
class RuntimeLaunchInspection:
    """The engine-local evidence available for a recovery decision."""

    status: Literal["running", "absent", "unknown"]
    engine_session_key: str | None = None
    process_id: int | None = None
    reason: str | None = None


class RuntimeLaunchRegistry:
    """Atomic per-Attempt launch evidence for a harness engine.

    A registry is rooted beside the existing checkpoint file.  The dispatcher
    binds the same :class:`~ainrf.harness_engine.base.ExecutionContext` before
    probing a recovered claim, so a fresh engine process reads the exact record
    written by the predecessor instead of guessing from a global process list.
    """

    def __init__(self, checkpoint_path: Path) -> None:
        self._checkpoint_path = checkpoint_path
        self._record_path = checkpoint_path.with_name("runtime-launch.json")

    @property
    def record_path(self) -> Path:
        return self._record_path

    def arm(self, *, engine_type: str, task_id: str, launch_key: str) -> RuntimeLaunchRecord:
        """Persist proof that an engine has not crossed its external boundary.

        This must be called before the dispatcher commits its launch fence.
        Repeating it for the same identity is safe; changing the identity is
        rejected instead of overwriting evidence for another Attempt.
        """

        existing = self.load()
        if existing is not None:
            self._assert_identity(
                existing,
                engine_type=engine_type,
                task_id=task_id,
                launch_key=launch_key,
            )
            return existing
        now = _utc_now()
        record = RuntimeLaunchRecord(
            version=_RUNTIME_LAUNCH_RECORD_VERSION,
            engine_type=engine_type,
            task_id=task_id,
            launch_key=launch_key,
            phase="armed",
            probe_token=secrets.token_urlsafe(32),
            created_at=now,
            updated_at=now,
        )
        self._save(record)
        return record

    def begin_launch(
        self,
        *,
        engine_type: str,
        task_id: str,
        launch_key: str,
        engine_session_key: str | None = None,
    ) -> RuntimeLaunchRecord:
        """Record entry into an external startup call before invoking it."""

        record = self.arm(engine_type=engine_type, task_id=task_id, launch_key=launch_key)
        return self._replace(
            record,
            phase="launching",
            engine_session_key=engine_session_key or record.engine_session_key,
            finished_at=None,
        )

    def mark_running(
        self,
        *,
        engine_type: str,
        task_id: str,
        launch_key: str,
        process_id: int | None,
        engine_session_key: str | None = None,
    ) -> RuntimeLaunchRecord:
        """Store PID/start-time evidence after a subprocess was returned."""

        record = self.begin_launch(
            engine_type=engine_type,
            task_id=task_id,
            launch_key=launch_key,
            engine_session_key=engine_session_key,
        )
        start_ticks = _process_start_ticks(process_id) if process_id is not None else None
        return self._replace(
            record,
            phase="running",
            process_id=process_id,
            process_start_ticks=start_ticks,
            engine_session_key=engine_session_key or record.engine_session_key,
        )

    def update_engine_session_key(
        self,
        *,
        engine_type: str,
        task_id: str,
        launch_key: str,
        engine_session_key: str | None,
    ) -> RuntimeLaunchRecord:
        """Persist a provider session/thread identifier once it is known."""

        record = self.arm(engine_type=engine_type, task_id=task_id, launch_key=launch_key)
        return self._replace(record, engine_session_key=engine_session_key)

    def mark_finished(
        self,
        *,
        engine_type: str,
        task_id: str,
        launch_key: str,
    ) -> RuntimeLaunchRecord:
        """Record a locally observed clean process/session shutdown."""

        record = self.arm(engine_type=engine_type, task_id=task_id, launch_key=launch_key)
        now = _utc_now()
        return self._replace(record, phase="finished", finished_at=now)

    def environment(self, *, engine_type: str, task_id: str, launch_key: str) -> dict[str, str]:
        """Return a non-secret marker for runtimes whose SDK hides their PID.

        The random token is only a correlation proof against this durable
        record.  It is deliberately not included in API responses or logs.
        """

        record = self.arm(engine_type=engine_type, task_id=task_id, launch_key=launch_key)
        return {_RUNTIME_PROBE_TOKEN_ENV: record.probe_token}

    def inspect(
        self, *, engine_type: str, task_id: str, launch_key: str
    ) -> RuntimeLaunchInspection:
        """Return only conclusions that the durable evidence can prove."""

        try:
            record = self.load()
        except RuntimeLaunchRecordError as exc:
            return RuntimeLaunchInspection(status="unknown", reason=str(exc))
        if record is None:
            return RuntimeLaunchInspection(
                status="unknown",
                reason="No engine launch record was persisted before recovery",
            )
        try:
            self._assert_identity(
                record,
                engine_type=engine_type,
                task_id=task_id,
                launch_key=launch_key,
            )
        except RuntimeLaunchRecordError as exc:
            return RuntimeLaunchInspection(status="unknown", reason=str(exc))
        if record.phase == "armed":
            return RuntimeLaunchInspection(
                status="absent",
                engine_session_key=record.engine_session_key,
                reason="Engine had not entered its external launch boundary",
            )
        if record.phase == "finished":
            return RuntimeLaunchInspection(
                status="absent",
                engine_session_key=record.engine_session_key,
                reason="Engine recorded a completed runtime shutdown",
            )
        if record.process_id is not None and record.process_start_ticks is not None:
            if _same_process_is_alive(record.process_id, record.process_start_ticks):
                return RuntimeLaunchInspection(
                    status="running",
                    engine_session_key=record.engine_session_key,
                    process_id=record.process_id,
                )
            return RuntimeLaunchInspection(
                status="unknown",
                engine_session_key=record.engine_session_key,
                process_id=record.process_id,
                reason="Recorded process disappeared without a durable finished record",
            )
        marker_pid = _find_marked_process(record.probe_token)
        if marker_pid is not None:
            return RuntimeLaunchInspection(
                status="running",
                engine_session_key=record.engine_session_key,
                process_id=marker_pid,
            )
        return RuntimeLaunchInspection(
            status="unknown",
            engine_session_key=record.engine_session_key,
            reason="External launch may have crossed the boundary but cannot be proven",
        )

    def load(self) -> RuntimeLaunchRecord | None:
        if not self._record_path.exists():
            return None
        try:
            payload = json.loads(self._record_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeLaunchRecordError("Runtime launch record is unreadable") from exc
        return RuntimeLaunchRecord.from_json(payload)

    def _replace(self, record: RuntimeLaunchRecord, **changes: object) -> RuntimeLaunchRecord:
        values = asdict(record)
        values.update(changes)
        values["updated_at"] = _utc_now()
        updated = RuntimeLaunchRecord.from_json(values)
        self._save(updated)
        return updated

    def _save(self, record: RuntimeLaunchRecord) -> None:
        from ainrf.db.connection import atomic_write_json

        atomic_write_json(self._record_path, asdict(record))

    @staticmethod
    def _assert_identity(
        record: RuntimeLaunchRecord,
        *,
        engine_type: str,
        task_id: str,
        launch_key: str,
    ) -> None:
        if (
            record.engine_type != engine_type
            or record.task_id != task_id
            or record.launch_key != launch_key
        ):
            raise RuntimeLaunchRecordError(
                "Runtime launch record belongs to a different engine, Task, or launch key"
            )


class RuntimeLaunchTracker:
    """Adapter helper that binds registry evidence to execution contexts.

    Keeping this tiny state in the engine instance is safe because the source
    of truth remains the JSON record.  A replacement dispatcher calls
    :meth:`bind` with its reconstructed context before it probes, restoring the
    mapping without relying on the predecessor's process memory.
    """

    def __init__(self, engine_type: str) -> None:
        self._engine_type = engine_type
        self._registries: dict[str, RuntimeLaunchRegistry] = {}

    def bind(self, context: ExecutionContext) -> None:
        if not (context.runtime_launch_key and context.session_state_path):
            return
        self._registries[context.runtime_launch_key] = RuntimeLaunchRegistry(
            Path(context.session_state_path)
        )

    def arm(self, context: ExecutionContext) -> None:
        registry = self._registry_for_context(context)
        if registry is None:
            return
        registry.arm(
            engine_type=self._engine_type,
            task_id=context.task_id,
            launch_key=context.runtime_launch_key or context.task_id,
        )

    def begin(self, context: ExecutionContext, *, engine_session_key: str | None = None) -> None:
        registry = self._registry_for_context(context)
        if registry is None:
            return
        registry.begin_launch(
            engine_type=self._engine_type,
            task_id=context.task_id,
            launch_key=context.runtime_launch_key or context.task_id,
            engine_session_key=engine_session_key,
        )

    def mark_running(
        self,
        context: ExecutionContext,
        *,
        process_id: int | None,
        engine_session_key: str | None = None,
    ) -> None:
        registry = self._registry_for_context(context)
        if registry is None:
            return
        registry.mark_running(
            engine_type=self._engine_type,
            task_id=context.task_id,
            launch_key=context.runtime_launch_key or context.task_id,
            process_id=process_id,
            engine_session_key=engine_session_key,
        )

    def update_session_key(self, context: ExecutionContext, engine_session_key: str | None) -> None:
        registry = self._registry_for_context(context)
        if registry is None:
            return
        registry.update_engine_session_key(
            engine_type=self._engine_type,
            task_id=context.task_id,
            launch_key=context.runtime_launch_key or context.task_id,
            engine_session_key=engine_session_key,
        )

    def finish(self, context: ExecutionContext) -> None:
        registry = self._registry_for_context(context)
        if registry is None:
            return
        registry.mark_finished(
            engine_type=self._engine_type,
            task_id=context.task_id,
            launch_key=context.runtime_launch_key or context.task_id,
        )

    def environment(self, context: ExecutionContext) -> dict[str, str]:
        registry = self._registry_for_context(context)
        if registry is None:
            return {}
        return registry.environment(
            engine_type=self._engine_type,
            task_id=context.task_id,
            launch_key=context.runtime_launch_key or context.task_id,
        )

    def inspect(self, *, task_id: str, launch_key: str) -> RuntimeLaunchInspection:
        registry = self._registries.get(launch_key)
        if registry is None:
            return RuntimeLaunchInspection(
                status="unknown",
                reason="No Attempt-scoped runtime context was bound before probing",
            )
        return registry.inspect(
            engine_type=self._engine_type,
            task_id=task_id,
            launch_key=launch_key,
        )

    def _registry_for_context(self, context: ExecutionContext) -> RuntimeLaunchRegistry | None:
        if context.runtime_launch_key is None:
            return None
        return self._registries.get(context.runtime_launch_key)


def _utc_now() -> str:
    from ainrf.environments.models import utc_now

    return utc_now().isoformat()


def _process_start_ticks(process_id: int | None) -> int | None:
    """Return Linux process start ticks, or ``None`` when unverifiable."""

    if process_id is None or process_id <= 0:
        return None
    stat_path = Path("/proc") / str(process_id) / "stat"
    try:
        stat = stat_path.read_text(encoding="utf-8")
    except OSError:
        return None
    closing_paren = stat.rfind(")")
    if closing_paren == -1:
        return None
    fields = stat[closing_paren + 2 :].split()
    # /proc/<pid>/stat field 22 is starttime. The slice begins at field 3.
    if len(fields) <= 19:
        return None
    try:
        return int(fields[19])
    except ValueError:
        return None


def _same_process_is_alive(process_id: int, expected_start_ticks: int) -> bool:
    if _process_start_ticks(process_id) != expected_start_ticks:
        return False
    try:
        os.kill(process_id, 0)
    except OSError:
        return False
    return True


def _find_marked_process(probe_token: str) -> int | None:
    """Find an SDK-spawned process carrying an exact durable marker.

    This is intentionally a positive-only probe.  Permission filtering,
    process races, and a missing ``/proc`` mount make a negative scan
    inconclusive, so callers must still report ``UNKNOWN`` rather than
    ``ABSENT`` when no marker is found.
    """

    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return None
    try:
        entries = tuple(proc_root.iterdir())
    except OSError:
        return None
    expected = f"{_RUNTIME_PROBE_TOKEN_ENV}={probe_token}".encode()
    for entry in entries:
        if not entry.name.isdecimal():
            continue
        try:
            environment = (entry / "environ").read_bytes()
        except OSError:
            continue
        if expected not in environment.split(b"\0"):
            continue
        process_id = int(entry.name)
        if _process_start_ticks(process_id) is not None:
            return process_id
    return None


@dataclass(slots=True)
class SessionCheckpoint:
    version: int = 2
    task_id: str = ""
    # A v2 Task can have multiple Attempts.  These fields bind a checkpoint
    # to the one durable launch that wrote it instead of letting a retry
    # accidentally resume another Attempt's external session.
    attempt_id: str | None = None
    runtime_launch_key: str | None = None
    session_id: str | None = None
    cwd: str = ""
    created_at: str = ""
    turn_count: int = 0
    total_cost_usd: float = 0.0
    pending_prompts: list[str] | None = None
    metadata: dict[str, object] | None = None

    def assert_matches_runtime(
        self,
        *,
        task_id: str,
        attempt_id: str | None,
        runtime_launch_key: str | None,
    ) -> None:
        """Reject a v2 checkpoint that belongs to another runtime identity.

        Legacy callers deliberately omit ``runtime_launch_key`` and retain
        their historical task-scoped checkpoint behavior.  A durable context,
        however, must have both an Attempt and launch key and may only restore
        a checkpoint written by that exact pair.
        """

        if runtime_launch_key is None:
            return
        if attempt_id is None:
            raise ValueError("Durable runtime checkpoint validation requires an attempt ID")
        if (
            self.task_id != task_id
            or self.attempt_id != attempt_id
            or self.runtime_launch_key != runtime_launch_key
        ):
            raise ValueError("Checkpoint runtime identity does not match this durable Attempt")


class SessionStateStore:
    def __init__(self, state_root: Path) -> None:
        self._root = state_root / "session-states"

    def checkpoint_path(self, task_id: str, *, attempt_id: str | None = None) -> Path:
        """Return the legacy Task or durable Attempt checkpoint path."""

        identity = attempt_id or task_id
        return self._root / identity / "checkpoint.json"

    def save(self, checkpoint: SessionCheckpoint) -> None:
        from ainrf.db.connection import atomic_write_json

        path = self.checkpoint_path(checkpoint.task_id, attempt_id=checkpoint.attempt_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, asdict(checkpoint))

    def load(self, task_id: str, *, attempt_id: str | None = None) -> SessionCheckpoint | None:
        path = self.checkpoint_path(task_id, attempt_id=attempt_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return SessionCheckpoint(**data)

    def delete(self, task_id: str, *, attempt_id: str | None = None) -> None:
        path = self.checkpoint_path(task_id, attempt_id=attempt_id)
        if path.exists():
            path.unlink()
