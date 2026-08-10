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
from typing import NoReturn

import httpx
import structlog

from ainrf.domain_control import (
    DomainMaintenanceService,
    DomainWriteParticipant,
    MaintenanceModeError,
)
from ainrf.domain.write_fence import DomainWriteFenceError
from ainrf.literature.attempts import (
    LiteratureExternalCallAdapter,
    request_fingerprint,
)
from ainrf.literature.models import LiteraturePaper
from ainrf.literature.limits import ArxivRequestLimiter
from ainrf.literature.providers import ArxivRssProvider
from ainrf.literature.providers.arxiv_rss import normalize_categories, parse_rss
from ainrf.literature.summarizer import AnthropicSummarizer, DurableAttemptPersistenceFailure
from ainrf.literature.task_saga import LiteratureTaskSagaService
from ainrf.literature.tracking import LiteratureTrackingService, WorkItem


_WORKER_PARTICIPANTS: dict[Path, DomainWriteParticipant] = {}
_WORKER_PARTICIPANTS_LOCK = Lock()
logger = structlog.get_logger(__name__).bind(component="literature-worker")


def _payload_hash_matches(payload: object, response_hash: object) -> bool:
    """Return whether durable text evidence matches its stored hash."""

    return bool(
        isinstance(payload, str)
        and payload.strip()
        and isinstance(response_hash, str)
        and response_hash.strip()
        and hashlib.sha256(payload.encode()).hexdigest() == response_hash
    )


def _snapshot_hash_matches(snapshot: dict[str, object] | None) -> bool:
    """Return whether durable RSS bytes match their stored body hash."""

    if snapshot is None:
        return False
    body = snapshot.get("body")
    if isinstance(body, memoryview):
        body = body.tobytes()
    body_hash = snapshot.get("body_hash")
    return bool(
        isinstance(body, bytes)
        and body
        and isinstance(body_hash, str)
        and body_hash.strip()
        and hashlib.sha256(body).hexdigest() == body_hash
    )


def _rss_attempt_evidence_integrity(
    *,
    response_payload: str | None,
    response_hash: str | None,
    snapshot: dict[str, object] | None,
) -> bool:
    """Validate every raw evidence representation before recovery."""

    if response_payload is not None and not _payload_hash_matches(response_payload, response_hash):
        return False
    if snapshot is not None:
        if not _snapshot_hash_matches(snapshot):
            return False
        snapshot_hash = snapshot.get("body_hash")
        if response_hash is not None and response_hash != snapshot_hash:
            return False
        if response_payload is not None and response_hash != snapshot_hash:
            return False
    return True


def _best_effort_attempt_transition(
    service: LiteratureTrackingService,
    attempt_id: str,
    *,
    state: str,
    error_kind: str,
    error_message: str,
) -> BaseException | None:
    """Try a durable transition and return, rather than replace, its failure."""

    try:
        if state == "unknown":
            service.mark_api_unknown(
                attempt_id,
                error_kind=error_kind,
                error_message=error_message,
                retry_after_seconds=60,
            )
        elif state == "response_persisted":
            service.mark_api_response_persisted(
                attempt_id,
                error_kind=error_kind,
                error_message=error_message,
            )
        else:
            raise ValueError(f"unsupported Literature attempt transition: {state}")
    except BaseException as exc:
        logger.warning(
            "literature_attempt_transition_failed",
            attempt_id=attempt_id,
            target_state=state,
            error_type=type(exc).__name__,
            error=str(exc)[:500],
            exc_info=True,
        )
        return exc
    return None


def _fence_uncertain_attempt(
    service: LiteratureTrackingService,
    attempt_id: str,
    *,
    error_kind: str,
    error_message: str,
    force: bool = False,
) -> None:
    """Fence a response boundary before allowing work-item retry.

    Provider adapters can fail after SQLite has committed a transition.  Read
    the row again and only leave a replayable boundary when raw response
    evidence is durable; otherwise classify the call as ``unknown``.  The
    original exception remains the caller's exception.
    """

    try:
        current = service.api_attempt(attempt_id)
        if current is None or current.state not in {"started", "response_received"}:
            return
        has_replay_evidence = service.api_attempt_has_replay_evidence(attempt_id)
        if force or not has_replay_evidence:
            service.mark_api_unknown(
                attempt_id,
                error_kind=error_kind,
                error_message=error_message,
            )
    except BaseException:
        # Fencing is best effort when the database itself is unavailable.  The
        # original provider/persistence exception must not be replaced.
        logger.exception("literature_attempt_fence_failed", attempt_id=attempt_id)


def _mark_rss_provider_failure(
    service: LiteratureTrackingService,
    attempt_id: str,
    exc: BaseException,
) -> BaseException | None:
    """Classify an RSS provider failure without replacing the primary error."""

    try:
        message = str(exc) or type(exc).__name__
        if isinstance(exc, ValueError):
            service.mark_api_definitive_failure(
                attempt_id,
                error_kind="invalid_request",
                error_message=message,
            )
        elif isinstance(exc, Exception) and not isinstance(
            exc, (TimeoutError, httpx.TimeoutException)
        ):
            service.mark_api_retryable_failure(
                attempt_id,
                error_kind="provider_error",
                error_message=message,
                retry_after_seconds=60,
            )
        else:
            error_kind = (
                "cancelled"
                if isinstance(exc, asyncio.CancelledError)
                else "timeout"
                if isinstance(exc, (TimeoutError, httpx.TimeoutException))
                else "request_uncertain"
            )
            service.mark_api_unknown(
                attempt_id,
                error_kind=error_kind,
                error_message=message,
                retry_after_seconds=60,
            )
    except BaseException as secondary:
        logger.warning(
            "literature_rss_provider_failure_recording_failed",
            attempt_id=attempt_id,
            error_type=type(secondary).__name__,
            error=str(secondary)[:500],
            exc_info=True,
        )
        return secondary
    return None


def _raise_rss_primary_or_durable_failure(
    primary: BaseException,
    secondary: BaseException | None,
    *,
    message: str,
    state: str = "unknown",
) -> NoReturn:
    """Keep an RSS primary error visible while fencing secondary persistence faults."""

    if not isinstance(primary, Exception):
        raise primary
    if secondary is not None:
        failure = DurableAttemptPersistenceFailure(message, state=state)
        failure.add_note(f"primary RSS error: {str(primary) or type(primary).__name__}")
        raise failure from secondary
    raise primary


def _retry_work_item_preserving_primary(
    service: LiteratureTrackingService,
    work_item_id: str,
    primary: BaseException,
    *,
    error: str,
) -> None:
    """Persist retry state without replacing a provider/worker primary error."""

    try:
        service.retry_work_item(work_item_id, error)
    except BaseException as secondary:
        if not isinstance(primary, Exception):
            primary.add_note(f"secondary work-item retry error: {str(secondary)}")
            logger.warning(
                "literature_work_item_retry_persistence_failed",
                work_item_id=work_item_id,
                error_type=type(secondary).__name__,
                error=str(secondary)[:500],
                exc_info=True,
            )
            return
        failure = DurableAttemptPersistenceFailure(
            "durable Literature work-item retry recording failed",
            state="unknown",
        )
        failure.add_note(f"primary worker error: {str(primary) or type(primary).__name__}")
        raise failure from secondary


def _not_modified_evidence(payload: str | None, scope_id: str) -> dict[str, object] | None:
    """Load structured durable evidence for an RSS 304 response."""

    if not isinstance(payload, str) or not payload.strip():
        return None
    try:
        evidence = json.loads(payload)
    except (TypeError, ValueError):
        return None
    if (
        not isinstance(evidence, dict)
        or type(evidence.get("status_code")) is not int
        or evidence.get("status_code") != 304
        or evidence.get("scope_id") != scope_id
    ):
        return None
    return evidence


def _valid_not_modified_evidence(
    payload: str | None,
    scope_id: str,
    response_hash: str | None = None,
) -> bool:
    """Require structured durable evidence before replaying an RSS 304."""

    return _not_modified_evidence(payload, scope_id) is not None and _payload_hash_matches(
        payload, response_hash
    )


def _rss_recovery_evidence_matches(
    *,
    attempt_state: str,
    attempt_request_fingerprint: str,
    expected_request_fingerprint: str,
    snapshot: dict[str, object] | None,
    categories: list[str],
    scope: dict[str, object],
    scope_id: str,
    response_payload: str | None,
    response_hash: str | None,
) -> bool:
    """Allow only durable response evidence to cross a changed validator.

    A non-terminal attempt may be replayed only when its snapshot belongs to
    that attempt and the request identity is still applicable to the current
    scope.  While the scope is ``checking``, the stored validators still
    describe the request that produced the snapshot; response validators are
    applied only when local catalog state commits.  Historical validators
    never become new request-fingerprint candidates.
    """

    if attempt_state not in {"response_received", "response_persisted"}:
        return False
    if not _rss_attempt_evidence_integrity(
        response_payload=response_payload,
        response_hash=response_hash,
        snapshot=snapshot,
    ):
        return False
    scope_key = str(scope.get("scope_key") or "")
    if scope_key and scope_key.split("+") != normalize_categories(categories):
        return False
    if snapshot is not None:
        if snapshot.get("request_fingerprint") != attempt_request_fingerprint:
            return False
        if snapshot.get("scope_id") != scope_id:
            return False
        if scope.get("response_hash") != snapshot.get("body_hash"):
            return False
        # While a scope is checking, its validators still describe the
        # request that produced this snapshot.  The response's validators are
        # not applicable until complete_rss_response commits the catalog and
        # advances the scope.  A different fingerprint in this state is never
        # a recovery candidate.
        if scope.get("status") == "checking":
            return attempt_request_fingerprint == expected_request_fingerprint
        return snapshot.get("etag") == scope.get("etag") and snapshot.get(
            "last_modified"
        ) == scope.get("last_modified")
    evidence = _not_modified_evidence(response_payload, scope_id)
    if evidence is None:
        return False
    if scope.get("status") == "checking":
        return attempt_request_fingerprint == expected_request_fingerprint
    return evidence.get("etag") == scope.get("etag") and evidence.get("last_modified") == scope.get(
        "last_modified"
    )


def _complete_not_modified_response(
    service: LiteratureTrackingService,
    *,
    check_id: str,
    scope_id: str,
    payload: str,
    response_hash: str | None,
) -> str:
    """Persist the complete semantic state for one durable RSS 304."""

    evidence = _not_modified_evidence(payload, scope_id)
    if evidence is None:
        raise RuntimeError("304 response lacks durable not-modified evidence")
    expected_hash = hashlib.sha256(payload.encode()).hexdigest()
    if response_hash != expected_hash:
        raise RuntimeError("304 response evidence hash does not match payload")
    etag = evidence.get("etag")
    last_modified = evidence.get("last_modified")
    effective_hash = expected_hash
    service.complete_rss_not_modified(
        check_id=check_id,
        scope_id=scope_id,
        etag=etag if isinstance(etag, str) else None,
        last_modified=last_modified if isinstance(last_modified, str) else None,
        response_hash=effective_hash,
    )
    return effective_hash


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
    categories = normalize_categories(str(value) for value in item.payload["categories"])
    scope = service.check_scope(scope_id)
    if scope is None:
        raise KeyError(f"Literature check scope not found: {scope_id}")
    etag = scope.get("etag") or None
    last_modified = scope.get("last_modified") or None
    request = {
        "categories": categories,
        "etag": etag,
        "last_modified": last_modified,
    }
    expected_request_fingerprint = request_fingerprint("arxiv-rss", "fetch", request)
    attempt = service.latest_api_attempt(
        work_item_id=item.work_item_id,
        provider="arxiv-rss",
        operation="fetch",
        with_response_evidence=False,
    )
    snapshot = service.rss_snapshot_for_attempt(attempt.attempt_id) if attempt else None
    if attempt is not None and not _rss_attempt_evidence_integrity(
        response_payload=attempt.response_payload,
        response_hash=attempt.response_hash,
        snapshot=snapshot,
    ):
        raise RuntimeError(
            "Literature RSS durable response evidence failed hash-integrity validation"
        )
    if (
        attempt is not None
        and snapshot is not None
        and snapshot.get("request_fingerprint") != attempt.request_fingerprint
    ):
        raise RuntimeError(
            "Literature RSS snapshot request fingerprint does not match its API attempt"
        )
    if snapshot is not None and scope.get("response_hash") != snapshot.get("body_hash"):
        raise RuntimeError(
            "Literature RSS scope response hash does not match durable snapshot evidence"
        )
    if (
        attempt is not None
        and attempt.request_fingerprint != expected_request_fingerprint
        and not _rss_recovery_evidence_matches(
            attempt_state=attempt.state,
            attempt_request_fingerprint=attempt.request_fingerprint,
            expected_request_fingerprint=expected_request_fingerprint,
            snapshot=snapshot,
            categories=categories,
            scope=scope,
            scope_id=scope_id,
            response_payload=attempt.response_payload,
            response_hash=attempt.response_hash,
        )
    ):
        # Every provider request is identified by its complete fingerprint,
        # including categories and validators.  A snapshot from another
        # concrete request must never be reused for this scope.
        attempt = None
        snapshot = None
    if (
        attempt is not None
        and snapshot is not None
        and attempt.state in {"response_received", "response_persisted"}
        and attempt.request_fingerprint == expected_request_fingerprint
        and not _rss_recovery_evidence_matches(
            attempt_state=attempt.state,
            attempt_request_fingerprint=attempt.request_fingerprint,
            expected_request_fingerprint=expected_request_fingerprint,
            snapshot=snapshot,
            categories=categories,
            scope=scope,
            scope_id=scope_id,
            response_payload=attempt.response_payload,
            response_hash=attempt.response_hash,
        )
    ):
        # The raw response is intact, but its validators no longer describe
        # this concrete request.  Keep the evidence for diagnostics and make
        # a fresh, correctly identified provider attempt.
        attempt = None
        snapshot = None
    existing_attempt = attempt is not None
    if attempt is None:
        attempt = service.begin_api_attempt(
            provider="arxiv-rss",
            operation="fetch",
            request=request,
            check_id=check_id,
            work_item_id=item.work_item_id,
            attempt_number=item.attempt_count,
        )
    elif attempt.state == "succeeded":
        logger.debug(
            "literature_rss_attempt_reused",
            work_item_id=item.work_item_id,
            attempt_id=attempt.attempt_id,
            state=attempt.state,
        )
        return
    elif attempt.state == "unknown" and snapshot is None:
        raise RuntimeError(
            "Literature RSS outcome is unknown without durable response evidence; manual reconciliation required"
        )
    elif existing_attempt and attempt.state == "started" and snapshot is None:
        _fence_uncertain_attempt(
            service,
            attempt.attempt_id,
            error_kind="response_boundary_uncertain",
            error_message="RSS attempt was already started before worker recovery",
            force=True,
        )
        raise RuntimeError(
            "Literature RSS attempt started without durable response evidence; manual reconciliation required"
        )
    elif snapshot is None and attempt.state in {"unknown", "definitive_failure"}:
        raise RuntimeError(
            "Literature RSS attempt is not safely retryable without durable response evidence"
        )
    elif (
        snapshot is None
        and attempt.state == "response_persisted"
        and not (
            attempt.status_code == 304
            and _valid_not_modified_evidence(
                attempt.response_payload, scope_id, attempt.response_hash
            )
        )
    ):
        missing_evidence_error = RuntimeError(
            "Literature RSS attempt is not safely retryable without durable response evidence"
        )
        secondary = _best_effort_attempt_transition(
            service,
            attempt.attempt_id,
            state="unknown",
            error_kind="response_evidence_missing",
            error_message=str(missing_evidence_error),
        )
        _raise_rss_primary_or_durable_failure(
            missing_evidence_error,
            secondary,
            message="durable RSS response-evidence fence failed",
        )
    elif (
        snapshot is None
        and attempt.state
        not in {
            "started",
            "response_received",
        }
        and not (
            attempt.state == "response_persisted"
            and attempt.status_code == 304
            and _valid_not_modified_evidence(
                attempt.response_payload, scope_id, attempt.response_hash
            )
        )
    ):
        attempt = service.begin_api_attempt(
            provider="arxiv-rss",
            operation="fetch",
            request=request,
            check_id=check_id,
            work_item_id=item.work_item_id,
            attempt_number=item.attempt_count,
        )
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
    result = None
    if (
        snapshot is None
        and attempt.state == "response_received"
        and attempt.status_code == 304
        and not _valid_not_modified_evidence(
            attempt.response_payload, scope_id, attempt.response_hash
        )
    ):
        _fence_uncertain_attempt(
            service,
            attempt.attempt_id,
            error_kind="response_evidence_missing",
            error_message="304 response lacks durable not-modified evidence",
            force=True,
        )
        raise RuntimeError(
            "Literature RSS 304 response lacks durable evidence; manual reconciliation required"
        )
    if (
        snapshot is None
        and attempt.state in {"response_received", "response_persisted"}
        and attempt.status_code == 304
        and _valid_not_modified_evidence(attempt.response_payload, scope_id, attempt.response_hash)
    ):
        try:
            assert isinstance(attempt.response_payload, str)
            not_modified_hash = _complete_not_modified_response(
                service,
                check_id=check_id,
                scope_id=scope_id,
                payload=attempt.response_payload,
                response_hash=attempt.response_hash,
            )
        except BaseException as exc:
            secondary = _best_effort_attempt_transition(
                service,
                attempt.attempt_id,
                state="response_persisted",
                error_kind="persistence_error",
                error_message=str(exc) or type(exc).__name__,
            )
            _raise_rss_primary_or_durable_failure(
                exc,
                secondary,
                message="durable RSS 304 recovery recording failed",
                state="response_persisted",
            )
        service.mark_api_response_persisted(attempt.attempt_id)
        service.mark_api_succeeded(
            attempt.attempt_id,
            status_code=304,
            response_hash=not_modified_hash,
        )
        return
    if snapshot is None and attempt.state == "response_received":
        _fence_uncertain_attempt(
            service,
            attempt.attempt_id,
            error_kind="response_evidence_missing",
            error_message="Response status was recorded but raw RSS evidence was not durable",
            force=True,
        )
        raise RuntimeError(
            "Literature RSS response evidence is incomplete; manual reconciliation required"
        )
    if snapshot is None:
        try:
            await asyncio.to_thread(ArxivRequestLimiter().acquire)
            result = await ArxivRssProvider().fetch(
                categories, etag=etag, last_modified=last_modified
            )
        except BaseException as exc:
            secondary = _mark_rss_provider_failure(service, attempt.attempt_id, exc)
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
            if secondary is not None and isinstance(exc, Exception):
                failure = DurableAttemptPersistenceFailure(
                    "durable RSS provider failure recording failed",
                    state="unknown",
                )
                failure.add_note(f"primary RSS provider error: {str(exc)}")
                raise failure from secondary
            raise
    if snapshot is None and result is not None and result.status_code == 304:
        not_modified_payload = json.dumps(
            {
                "status_code": 304,
                "scope_id": scope_id,
                "etag": result.etag,
                "last_modified": result.last_modified,
            },
            sort_keys=True,
        )
        not_modified_hash = hashlib.sha256(not_modified_payload.encode()).hexdigest()
        try:
            service.record_api_response(
                attempt.attempt_id,
                status_code=result.status_code,
                response_hash=not_modified_hash,
                response_payload=not_modified_payload,
                retry_after_seconds=result.retry_after_seconds,
            )
        except BaseException as exc:
            _fence_uncertain_attempt(
                service,
                attempt.attempt_id,
                error_kind="response_record_error",
                error_message=str(exc) or type(exc).__name__,
            )
            raise
        try:
            _complete_not_modified_response(
                service,
                check_id=check_id,
                scope_id=scope_id,
                payload=not_modified_payload,
                response_hash=not_modified_hash,
            )
        except BaseException as exc:
            secondary = _best_effort_attempt_transition(
                service,
                attempt.attempt_id,
                state="response_persisted",
                error_kind="persistence_error",
                error_message=str(exc) or type(exc).__name__,
            )
            _raise_rss_primary_or_durable_failure(
                exc,
                secondary,
                message="durable RSS 304 response recording failed",
                state="response_persisted",
            )
        service.mark_api_response_persisted(attempt.attempt_id)
        service.mark_api_succeeded(
            attempt.attempt_id,
            status_code=result.status_code,
            response_hash=not_modified_hash,
        )
        logger.debug(
            "literature_rss_not_modified",
            work_item_id=item.work_item_id,
            check_id=check_id,
            scope_id=scope_id,
            provider="arxiv-rss",
            elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        return
    if (
        snapshot is None
        and result is not None
        and (result.status_code != 200 or result.body is None)
    ):
        try:
            service.record_api_response(
                attempt.attempt_id,
                status_code=result.status_code,
                response_hash=None,
                retry_after_seconds=result.retry_after_seconds,
            )
        except BaseException as exc:
            _fence_uncertain_attempt(
                service,
                attempt.attempt_id,
                error_kind="response_record_error",
                error_message=str(exc) or type(exc).__name__,
                force=True,
            )
            raise
        try:
            if result.status_code == 429 or result.status_code >= 500:
                service.mark_api_retryable_failure(
                    attempt.attempt_id,
                    error_kind="http_error",
                    error_message=f"arXiv RSS returned HTTP {result.status_code}",
                    retry_after_seconds=(
                        result.retry_after_seconds if result.retry_after_seconds is not None else 60
                    ),
                    status_code=result.status_code,
                )
            else:
                service.mark_api_definitive_failure(
                    attempt.attempt_id,
                    error_kind="http_error",
                    error_message=f"arXiv RSS returned HTTP {result.status_code}",
                    status_code=result.status_code,
                )
        except BaseException as exc:
            if not isinstance(exc, Exception):
                raise
            raise DurableAttemptPersistenceFailure(
                "durable RSS HTTP failure recording failed",
                state="unknown",
            ) from exc
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
    if snapshot is None:
        assert result is not None and result.body is not None
        response_hash = hashlib.sha256(result.body).hexdigest()
        try:
            service.record_api_response(
                attempt.attempt_id,
                status_code=result.status_code,
                response_hash=response_hash,
            )
        except BaseException as exc:
            _fence_uncertain_attempt(
                service,
                attempt.attempt_id,
                error_kind="response_record_error",
                error_message=str(exc) or type(exc).__name__,
                force=True,
            )
            raise
        try:
            snapshot = service.persist_rss_snapshot(
                attempt_id=attempt.attempt_id,
                check_id=check_id,
                scope_id=scope_id,
                body=result.body,
                etag=result.etag,
                last_modified=result.last_modified,
                cache_control=result.cache_control,
                status_code=result.status_code,
            )
        except BaseException as exc:
            _fence_uncertain_attempt(
                service,
                attempt.attempt_id,
                error_kind="snapshot_persistence_error",
                error_message=str(exc) or type(exc).__name__,
            )
            raise
        service.mark_api_response_persisted(attempt.attempt_id)
    if not _snapshot_hash_matches(snapshot):
        raise RuntimeError("Literature RSS snapshot evidence failed hash-integrity validation")
    snapshot_hash = str(snapshot["body_hash"])
    if attempt.response_hash is not None and attempt.response_hash != snapshot_hash:
        raise RuntimeError("Literature RSS attempt hash does not match snapshot evidence")
    response_hash = snapshot_hash
    body_value = snapshot["body"]
    if isinstance(body_value, memoryview):
        body_value = body_value.tobytes()
    assert isinstance(body_value, bytes)
    body = body_value
    try:
        papers = result.papers if result is not None and result.papers else parse_rss(body)
    except BaseException as exc:
        secondary = _best_effort_attempt_transition(
            service,
            attempt.attempt_id,
            state="response_persisted",
            error_kind="parser_error",
            error_message=str(exc) or type(exc).__name__,
        )
        logger.error(
            "literature_rss_persistence_failed",
            work_item_id=item.work_item_id,
            check_id=check_id,
            scope_id=scope_id,
            paper_count=0,
            error_type=type(exc).__name__,
            error=str(exc)[:500],
            elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        _raise_rss_primary_or_durable_failure(
            exc,
            secondary,
            message="durable RSS parser-failure recording failed",
            state="response_persisted",
        )
    is_truncated = len(papers) >= 2000
    try:
        service.complete_rss_response(
            check_id=check_id,
            scope_id=scope_id,
            papers=papers,
            is_truncated=is_truncated,
            response_hash=response_hash,
            etag=snapshot.get("etag"),
            last_modified=snapshot.get("last_modified"),
        )
    except BaseException as exc:
        secondary = _best_effort_attempt_transition(
            service,
            attempt.attempt_id,
            state="response_persisted",
            error_kind="persistence_error",
            error_message=str(exc) or type(exc).__name__,
        )
        _raise_rss_primary_or_durable_failure(
            exc,
            secondary,
            message="durable RSS local-response recording failed",
            state="response_persisted",
        )
    service.mark_api_response_persisted(attempt.attempt_id)
    service.mark_api_succeeded(
        attempt.attempt_id,
        status_code=int(snapshot["status_code"] or 200),
        response_hash=response_hash,
    )
    logger.debug(
        "literature_rss_fetch_completed",
        work_item_id=item.work_item_id,
        check_id=check_id,
        scope_id=scope_id,
        provider="arxiv-rss",
        status_code=int(snapshot["status_code"] or 200),
        paper_count=len(papers),
        paper_id_sample=[f"{paper.provider}:{paper.external_id}" for paper in papers[:5]],
        response_hash=response_hash,
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
        recovery = service.latest_api_attempt(
            work_item_id=item.work_item_id,
            provider="anthropic",
            operation=None,
        )
        adapter = LiteratureExternalCallAdapter(
            service,
            work_item_id=item.work_item_id,
            attempt_number=item.attempt_count,
            recovery_attempt=recovery,
        )
        async with AnthropicSummarizer(
            batch_size=1,
            attempt_adapter=adapter,
        ) as summarizer:
            await summarizer.summarize([paper])
        if paper.ai_summary is None:
            raise RuntimeError("Summary provider returned no summary")
        service.complete_summary(summary_id, paper.ai_summary, paper.ai_practice_note)
        for attempt in adapter.attempts:
            current = service.api_attempt(attempt.attempt_id)
            if current is None or current.state not in {"response_received", "response_persisted"}:
                continue
            service.mark_api_response_persisted(attempt.attempt_id)
            service.mark_api_succeeded(
                attempt.attempt_id,
                status_code=current.status_code,
                response_hash=current.response_hash,
            )
        logger.debug(
            "literature_summary_completed",
            work_item_id=item.work_item_id,
            summary_id=summary_id,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
        )
    except BaseException as exc:
        try:
            service.fail_summary(summary_id, str(exc))
        except BaseException:
            logger.error(
                "literature_summary_failure_persistence_failed",
                work_item_id=item.work_item_id,
                summary_id=summary_id,
            )
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
            _retry_work_item_preserving_primary(
                service,
                item.work_item_id,
                exc,
                error=str(exc),
            )
            raise
        except BaseException as exc:
            # A process-level cancellation/interrupt must not be swallowed.
            # ``retry_work_item`` applies the unknown-attempt fence: calls
            # without durable response evidence become manual-reconciliation
            # failures, while snapshot/payload-backed work remains retryable.
            try:
                participant.check_lease(lease)
            except MaintenanceModeError:
                participant.drain()
                raise
            _retry_work_item_preserving_primary(
                service,
                item.work_item_id,
                exc,
                error=str(exc),
            )
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
