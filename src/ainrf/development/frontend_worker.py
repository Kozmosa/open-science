from __future__ import annotations

import asyncio
import json
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path

from ainrf.db import connect
from ainrf.development.frontend_profiles import FRONTEND_DEV_FIXTURE_VERSION
from ainrf.domain import TaskDispatcher
from ainrf.domain_control import DomainCutoverController, DomainCutoverError
from ainrf.harness_engine import (
    EngineEvent,
    ExecutionContext,
    HarnessEngine,
    HarnessEngineType,
    RuntimeProbeResult,
    RuntimeProbeStatus,
)
from ainrf.harness_engine.base import EngineEmit
from ainrf.literature.tracking import LiteratureTrackingService, WorkItem


_PROFILE_MARKER_NAME = "frontend-dev-fixture.json"


class FrontendFixtureEngine(HarnessEngine):
    """Closed-world engine used only by marker-owned frontend fixtures."""

    def __init__(self, engine_type: HarnessEngineType) -> None:
        self._engine_type = engine_type

    @property
    def engine_type(self) -> HarnessEngineType:
        return self._engine_type

    async def start(self, context: ExecutionContext, emit: EngineEmit) -> None:
        _ = context
        await emit(
            EngineEvent(
                event_type="message",
                payload={
                    "role": "assistant",
                    "content": (
                        "Synthetic fixture execution completed without starting an external "
                        "runtime."
                    ),
                },
            )
        )
        await emit(
            EngineEvent(
                event_type="token",
                payload={"source": "frontend-fixture", "turn": 1},
                token_usage={
                    "source": "frontend-fixture",
                    "total": {
                        "input_tokens": 24,
                        "output_tokens": 16,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                        "cost_usd": 0.0,
                    },
                    "by_model": {
                        "frontend-fixture": {
                            "input_tokens": 24,
                            "output_tokens": 16,
                            "cost_usd": 0.0,
                        }
                    },
                },
            )
        )
        await emit(
            EngineEvent(
                event_type="status",
                payload={"status": "succeeded", "exit_code": 0},
            )
        )

    async def cancel(self, task_id: str, *, runtime_launch_key: str | None = None) -> None:
        _ = task_id, runtime_launch_key

    async def probe_runtime(self, *, task_id: str, launch_key: str) -> RuntimeProbeResult:
        _ = task_id, launch_key
        return RuntimeProbeResult(status=RuntimeProbeStatus.ABSENT)


@dataclass(frozen=True, slots=True)
class FrontendFixtureWorkerRunResult:
    outcome: str
    task_outcome: str
    literature_outcome: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


class FrontendFixtureWorker:
    """Deterministic local worker for synthetic frontend interaction feedback."""

    def __init__(self, state_root: Path, *, artifact_sha: str) -> None:
        self.state_root = state_root.expanduser().resolve()
        self.artifact_sha = artifact_sha.strip().lower()
        self._validate_fixture_marker()
        self._literature = LiteratureTrackingService(self.state_root)
        self._literature.initialize()
        self._dispatcher = TaskDispatcher(
            self.state_root,
            dispatcher_id="frontend-fixture-worker:tasks",
            engine_factory=FrontendFixtureEngine,
            lease_seconds=10,
            artifact_sha=self.artifact_sha,
        )

    def _validate_fixture_marker(self) -> None:
        marker_path = self.state_root / "runtime" / _PROFILE_MARKER_NAME
        if not marker_path.is_file():
            raise DomainCutoverError(
                "frontend fixture worker requires a managed synthetic fixture marker"
            )
        try:
            payload = json.loads(marker_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise DomainCutoverError("frontend fixture marker is unreadable") from exc
        if not isinstance(payload, dict):
            raise DomainCutoverError("frontend fixture marker is malformed")
        if payload.get("fixture_version") != FRONTEND_DEV_FIXTURE_VERSION:
            raise DomainCutoverError("frontend fixture version changed; reset the managed fixture")
        if payload.get("artifact_sha") != self.artifact_sha:
            raise DomainCutoverError("frontend fixture artifact SHA does not match the worker")
        status = DomainCutoverController(self.state_root).status()
        if status.state != "v2" or status.artifact_sha != self.artifact_sha:
            raise DomainCutoverError(
                "frontend fixture worker requires the committed fixture v2 fuse"
            )

    async def run_once(self) -> FrontendFixtureWorkerRunResult:
        literature_outcome = self._run_literature_once()
        task_result = await self._dispatcher.run_once()
        task_outcome = task_result.outcome
        outcome = "idle" if task_outcome == "idle" and literature_outcome == "idle" else "processed"
        return FrontendFixtureWorkerRunResult(
            outcome=outcome,
            task_outcome=task_outcome,
            literature_outcome=literature_outcome,
        )

    async def run_forever(self, *, poll_seconds: float = 0.25) -> None:
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        try:
            while True:
                await self.run_once()
                await asyncio.sleep(poll_seconds)
        finally:
            self._dispatcher.stop()

    def stop(self) -> None:
        self._dispatcher.stop()

    def _run_literature_once(self) -> str:
        work_item_id = self._next_literature_work_item_id()
        if work_item_id is None:
            return "idle"
        self._literature.mark_outbox_published(work_item_id)
        item = self._literature.claim_work_item_by_id(
            work_item_id, "frontend-fixture-worker:literature", lease_seconds=30
        )
        if item is None:
            return "claim_lost"
        self._complete_literature_item(item)
        self._literature.complete_work_item(item.work_item_id)
        return item.kind

    def _next_literature_work_item_id(self) -> str | None:
        database = self.state_root / "runtime" / "literature.sqlite3"
        with closing(connect(database)) as conn:
            row = conn.execute(
                """
                SELECT work_item_id FROM literature_work_items
                WHERE kind IN ('fetch_rss', 'summarize')
                  AND status IN ('queued', 'retrying')
                ORDER BY available_at, created_at, work_item_id LIMIT 1
                """
            ).fetchone()
        return str(row["work_item_id"]) if row is not None else None

    def _complete_literature_item(self, item: WorkItem) -> None:
        if item.kind == "fetch_rss":
            categories = sorted(str(value) for value in item.payload.get("categories", []))
            body = json.dumps(
                {"categories": categories, "source": "frontend-fixture"},
                sort_keys=True,
            ).encode("utf-8")
            self._literature.record_rss_response(
                check_id=str(item.payload["check_id"]),
                scope_id=str(item.payload["scope_id"]),
                body=body,
                etag="frontend-fixture",
                last_modified=None,
                papers=[],
                is_truncated=False,
            )
            return
        if item.kind == "summarize":
            summary_id = str(item.payload["summary_id"])
            context = self._literature.summary_context(summary_id)
            if context is None:
                return
            title = str(context["title"])
            self._literature.complete_summary(
                summary_id,
                f"Deterministic fixture summary for {title}.",
                "Generated locally by the frontend fixture worker; no LLM was called.",
            )
            return
        raise ValueError(f"unsupported frontend fixture literature work kind: {item.kind}")
