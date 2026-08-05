"""Worker-side execution of durable literature work items."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import socket
import time
from pathlib import Path
from threading import Lock

import structlog

from ainrf.domain_control import (
    DomainMaintenanceService,
    DomainWriteParticipant,
    MaintenanceModeError,
)
from ainrf.domain.write_fence import DomainWriteFenceError
from ainrf.literature.models import LiteraturePaper
from ainrf.literature.limits import ArxivRequestLimiter
from ainrf.literature.providers import ArxivRssProvider
from ainrf.literature.summarizer import AnthropicSummarizer
from ainrf.literature.task_saga import LiteratureTaskSagaService
from ainrf.literature.tracking import LiteratureTrackingService, WorkItem


_WORKER_PARTICIPANTS: dict[Path, DomainWriteParticipant] = {}
_WORKER_PARTICIPANTS_LOCK = Lock()
logger = structlog.get_logger(__name__).bind(component="literature-worker")


def _worker_maintenance_participant(state_root: Path) -> DomainWriteParticipant:
    """Return this Dramatiq process's durable literature-writer identity.

    A worker can process multiple messages concurrently, so one process-level
    participant owns a separate maintenance lease for each message.  A process
    that dies without a clean shutdown leaves a stale active row and therefore
    blocks cutover instead of being mistaken for a drained writer.
    """

    root = state_root.resolve()
    with _WORKER_PARTICIPANTS_LOCK:
        participant = _WORKER_PARTICIPANTS.get(root)
        if participant is None:
            participant = DomainWriteParticipant(
                DomainMaintenanceService(root),
                "literature-worker",
                participant_id=f"literature-worker:{socket.gethostname()}:{os.getpid()}",
                details={"component": "dramatiq-literature-worker"},
            )
            participant.start()
            _WORKER_PARTICIPANTS[root] = participant
        return participant


async def execute_work_item(
    service: LiteratureTrackingService,
    item: WorkItem,
    *,
    artifact_sha: str | None = None,
) -> None:
    logger.debug(
        "literature_work_item_started",
        work_item_id=item.work_item_id,
        kind=item.kind,
        check_id=item.payload.get("check_id"),
        scope_id=item.payload.get("scope_id"),
        summary_id=item.payload.get("summary_id"),
    )
    if item.kind == "fetch_rss":
        await _fetch_rss(service, item)
        return
    if item.kind == "summarize":
        await _summarize(service, item)
        return
    if item.kind == "research_task":
        await _recover_research_task(service, item, artifact_sha=artifact_sha)
        return
    raise ValueError(f"Unsupported literature work kind: {item.kind}")


async def _fetch_rss(service: LiteratureTrackingService, item: WorkItem) -> None:
    check_id = str(item.payload["check_id"])
    scope_id = str(item.payload["scope_id"])
    categories = [str(value) for value in item.payload["categories"]]
    scope = service.check_scope(scope_id)
    if scope is None:
        raise KeyError(f"Literature check scope not found: {scope_id}")
    started = time.perf_counter()
    logger.debug(
        "literature_rss_fetch_started",
        work_item_id=item.work_item_id,
        check_id=check_id,
        scope_id=scope_id,
        provider="arxiv-rss",
        categories=categories,
        has_etag=bool(scope.get("etag")),
        has_last_modified=bool(scope.get("last_modified")),
    )
    try:
        await asyncio.to_thread(ArxivRequestLimiter().acquire)
        result = await ArxivRssProvider().fetch(
            categories, etag=scope.get("etag"), last_modified=scope.get("last_modified")
        )
    except Exception as exc:
        logger.error(
            "literature_rss_fetch_failed",
            work_item_id=item.work_item_id,
            check_id=check_id,
            scope_id=scope_id,
            provider="arxiv-rss",
            error_type=type(exc).__name__,
            error=str(exc)[:500],
            elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        raise
    if result.status_code == 304:
        service.store_discovered_papers(check_id, [])
        logger.debug(
            "literature_rss_not_modified",
            work_item_id=item.work_item_id,
            check_id=check_id,
            scope_id=scope_id,
            provider="arxiv-rss",
            elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        return
    if result.status_code != 200 or result.body is None:
        logger.warning(
            "literature_rss_unexpected_status",
            work_item_id=item.work_item_id,
            check_id=check_id,
            scope_id=scope_id,
            provider="arxiv-rss",
            status_code=result.status_code,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        raise RuntimeError(f"arXiv RSS returned HTTP {result.status_code}")
    # arXiv documents 2,000 as the feed cap.  A cap-sized response is never
    # claimed complete; the planner can split the category scope later.
    try:
        service.record_rss_response(
            check_id=check_id,
            scope_id=scope_id,
            body=result.body,
            etag=result.etag,
            last_modified=result.last_modified,
            papers=result.papers,
            is_truncated=len(result.papers) >= 2000,
        )
    except Exception as exc:
        logger.error(
            "literature_rss_persistence_failed",
            work_item_id=item.work_item_id,
            check_id=check_id,
            scope_id=scope_id,
            paper_count=len(result.papers),
            error_type=type(exc).__name__,
            error=str(exc)[:500],
            elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        raise
    logger.debug(
        "literature_rss_fetch_completed",
        work_item_id=item.work_item_id,
        check_id=check_id,
        scope_id=scope_id,
        provider="arxiv-rss",
        status_code=result.status_code,
        paper_count=len(result.papers),
        paper_id_sample=[f"{paper.provider}:{paper.external_id}" for paper in result.papers[:5]],
        response_hash=hashlib.sha256(result.body).hexdigest(),
        elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
    )


async def _summarize(service: LiteratureTrackingService, item: WorkItem) -> None:
    summary_id = str(item.payload["summary_id"])
    started = time.perf_counter()
    logger.debug(
        "literature_summary_started", work_item_id=item.work_item_id, summary_id=summary_id
    )
    context = service.summary_context(summary_id)
    if context is None:
        logger.warning(
            "literature_summary_context_missing",
            work_item_id=item.work_item_id,
            summary_id=summary_id,
        )
        return
    paper = LiteraturePaper(
        paper_id=context["paper_id"],
        title=context["title"],
        authors=json.loads(context["authors_json"]),
        abstract=context["abstract"],
        published_at=context["published_at"] or "",
        arxiv_category=context["primary_category"],
    )
    try:
        async with AnthropicSummarizer(batch_size=1) as summarizer:
            await summarizer.summarize([paper])
        if paper.ai_summary is None:
            raise RuntimeError("Summary provider returned no summary")
        service.complete_summary(summary_id, paper.ai_summary, paper.ai_practice_note)
        logger.debug(
            "literature_summary_completed",
            work_item_id=item.work_item_id,
            summary_id=summary_id,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
        )
    except Exception as exc:
        service.fail_summary(summary_id, str(exc))
        logger.error(
            "literature_summary_failed",
            work_item_id=item.work_item_id,
            summary_id=summary_id,
            error_type=type(exc).__name__,
            error=str(exc)[:500],
            elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        raise


def _research_task_artifact_sha(state_root: Path, supplied: str | None) -> str:
    """Return a verified v2 artifact SHA before crossing the Task-write boundary.

    A ``research_task`` work item is a standard v2 Task mutation, not a
    legacy Literature side effect.  The historical worker may still drain
    fetch and summary work before cutover, but it must leave these intents
    durable and retryable until a committed v2 domain worker with a verified
    artifact takes ownership.
    """

    artifact_sha = (
        supplied
        or os.environ.get(
            "AINRF_DOMAIN_ARTIFACT_SHA", os.environ.get("OPENSCIENCE_DOMAIN_ARTIFACT_SHA", "")
        ).strip()
    )
    if not artifact_sha:
        raise DomainWriteFenceError(
            "AINRF_DOMAIN_ARTIFACT_SHA is required for current Literature research Task work"
        )
    return artifact_sha


async def _recover_research_task(
    service: LiteratureTrackingService,
    item: WorkItem,
    *,
    artifact_sha: str | None,
) -> None:
    """Resume a persisted Literature intent from its existing outbox record.

    This runner is the legacy Literature planner's recovery path.  The v2
    domain worker calls the same saga API with its committed artifact SHA.  A
    retryable saga result deliberately raises so ``process_durable_work_item``
    cannot overwrite its durable retry state with ``completed`` in the common
    worker footer.
    """

    verified_artifact_sha = _research_task_artifact_sha(service.state_root, artifact_sha)
    saga = LiteratureTaskSagaService(service.state_root, artifact_sha=verified_artifact_sha)
    result = await asyncio.to_thread(
        saga.recover_work_item,
        item.work_item_id,
        worker_id=f"literature-worker:{socket.gethostname()}",
    )
    if result is None:
        raise RuntimeError("research Task work item has no durable intent")
    if result.get("status") == "completed":
        return
    error = result.get("last_error")
    detail = str(error) if isinstance(error, str) and error else "research Task intent is retryable"
    raise RuntimeError(detail)


def process_durable_work_item(work_item_id: str) -> None:
    """Entrypoint shared by the Dramatiq actor and direct L1 tests."""
    state_root = Path(os.getenv("AINRF_STATE_ROOT", ".ainrf"))
    logger.debug("literature_work_item_received", work_item_id=work_item_id)
    participant = _worker_maintenance_participant(state_root)
    participant.heartbeat()
    try:
        lease = participant.begin_mutation(source="literature-worker.claim-retry-complete")
    except MaintenanceModeError:
        logger.warning("literature_worker_drained_for_maintenance", work_item_id=work_item_id)
        participant.drain()
        return
    try:
        # Literature initialization can apply SQLite migrations.  It must sit
        # behind the same lease as claim/retry/complete rather than becoming a
        # maintenance-time write before the worker reaches its queue item.
        participant.check_lease(lease)
        service = LiteratureTrackingService(state_root)
        service.initialize()
        participant.check_lease(lease)
        item = service.claim_work_item_by_id(work_item_id, participant.participant_id)
        participant.check_lease(lease)
        if item is None:
            logger.debug("literature_work_item_not_claimed", work_item_id=work_item_id)
            return
        try:
            asyncio.run(execute_work_item(service, item))
            participant.check_lease(lease)
        except MaintenanceModeError:
            participant.drain()
            return
        except Exception as exc:
            try:
                participant.check_lease(lease)
            except MaintenanceModeError:
                participant.drain()
                return
            service.retry_work_item(item.work_item_id, str(exc))
            raise
        # ``execute_work_item`` can take long enough for an operator to
        # enter maintenance immediately after the preceding check.  Keep the
        # terminal durable completion on the safe side of that boundary; a
        # claimed item is recoverable, but a completed item would hide work
        # that crossed the epoch.
        try:
            participant.check_lease(lease)
        except MaintenanceModeError:
            participant.drain()
            return
        service.complete_work_item(item.work_item_id)
    finally:
        participant.finish_mutation(lease)
