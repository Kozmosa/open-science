"""Worker-side execution of durable literature work items."""

from __future__ import annotations

import asyncio
import json
import os
import socket
from pathlib import Path

from ainrf.domain_control import DomainCutoverController, DomainCutoverError
from ainrf.literature.models import LiteraturePaper
from ainrf.literature.limits import ArxivRequestLimiter
from ainrf.literature.providers import ArxivRssProvider
from ainrf.literature.summarizer import AnthropicSummarizer
from ainrf.literature.task_saga import LiteratureTaskSagaService
from ainrf.literature.tracking import LiteratureTrackingService, WorkItem


async def execute_work_item(
    service: LiteratureTrackingService,
    item: WorkItem,
    *,
    artifact_sha: str | None = None,
) -> None:
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
    await asyncio.to_thread(ArxivRequestLimiter().acquire)
    result = await ArxivRssProvider().fetch(
        categories, etag=scope.get("etag"), last_modified=scope.get("last_modified")
    )
    if result.status_code == 304:
        service.store_discovered_papers(check_id, [])
        return
    if result.status_code != 200 or result.body is None:
        raise RuntimeError(f"arXiv RSS returned HTTP {result.status_code}")
    # arXiv documents 2,000 as the feed cap.  A cap-sized response is never
    # claimed complete; the planner can split the category scope later.
    service.record_rss_response(
        check_id=check_id,
        scope_id=scope_id,
        body=result.body,
        etag=result.etag,
        last_modified=result.last_modified,
        papers=result.papers,
        is_truncated=len(result.papers) >= 2000,
    )


async def _summarize(service: LiteratureTrackingService, item: WorkItem) -> None:
    context = service.summary_context(str(item.payload["summary_id"]))
    if context is None:
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
        service.complete_summary(
            str(item.payload["summary_id"]), paper.ai_summary, paper.ai_practice_note
        )
    except Exception as exc:
        service.fail_summary(str(item.payload["summary_id"]), str(exc))
        raise


def _research_task_artifact_sha(state_root: Path, supplied: str | None) -> str | None:
    """Return a verified v2 artifact SHA before crossing the Task-write boundary.

    The historical Literature worker may still drain legacy records while the
    domain is in legacy mode.  Once cutover is prepared or committed, however,
    it must never create a Task with an unverified or process-local artifact.
    """

    controller = DomainCutoverController(state_root)
    status = controller.status()
    if status.state == "legacy":
        return None
    if status.state != "v2":
        raise DomainCutoverError(
            "Literature research Task work is unavailable while domain cutover is prepared"
        )
    artifact_sha = (
        supplied
        or os.environ.get(
            "OPENSCIENCE_DOMAIN_ARTIFACT_SHA", os.environ.get("AINRF_DOMAIN_ARTIFACT_SHA", "")
        ).strip()
    )
    if not artifact_sha:
        raise DomainCutoverError(
            "OPENSCIENCE_DOMAIN_ARTIFACT_SHA is required for v2 Literature research Task work"
        )
    controller.assert_v2_writable(artifact_sha=artifact_sha)
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
    service = LiteratureTrackingService(Path(os.getenv("AINRF_STATE_ROOT", ".ainrf")))
    service.initialize()
    item = service.claim_work_item_by_id(work_item_id, socket.gethostname())
    if item is None:
        return
    try:
        asyncio.run(execute_work_item(service, item))
    except Exception as exc:
        service.retry_work_item(item.work_item_id, str(exc))
        raise
    else:
        service.complete_work_item(item.work_item_id)
