"""Durable external-call attempt tests for the Literature worker seam."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import NoReturn
from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import pytest
import httpx

from ainrf.literature.providers.arxiv_rss import RssFetchResult
from ainrf.literature.summarizer import DurableAttemptPersistenceFailure, ExternalCallFailure
from ainrf.literature.tracking import DiscoveredPaper, LiteratureTrackingService
from ainrf.literature.work import execute_work_item

pytestmark = [pytest.mark.unit]


def _service(tmp_path: Path) -> LiteratureTrackingService:
    service = LiteratureTrackingService(tmp_path)
    service.initialize()
    topic = service.create_topic(
        user_id="owner",
        label="Agents",
        include_terms=[],
        exclude_terms=[],
        categories=["cs.AI"],
    )
    service.create_check(user_id="owner", topic_ids=[topic["topic_id"]])
    return service


def _paper() -> DiscoveredPaper:
    return DiscoveredPaper(
        provider="arxiv",
        external_id="2401.00001",
        provider_version="v1",
        title="Durable attempt state",
        authors=["Ada"],
        abstract="A response boundary fixture.",
        primary_category="cs.AI",
        categories=["cs.AI"],
        published_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        source_url="https://arxiv.org/abs/2401.00001",
        pdf_url="https://arxiv.org/pdf/2401.00001",
    )


def _claim(service: LiteratureTrackingService):
    work_item_id = service.pending_outbox_work_ids()[0]
    item = service.claim_work_item_by_id(work_item_id, worker_id="attempt-test")
    assert item is not None
    return item


def _disable_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run_inline(func: Callable[..., object], /, *args: object, **kwargs: object) -> object:
        return func(*args, **kwargs)

    monkeypatch.setattr(
        "ainrf.literature.work.ArxivRequestLimiter",
        lambda: SimpleNamespace(acquire=lambda: None),
    )
    # The worker uses ``asyncio.to_thread`` for the production limiter.  This
    # test fixture does not exercise the limiter itself, and creating the
    # default executor leaves an idle thread that some supported Python/
    # pytest-asyncio combinations wait on during runner teardown.  Execute
    # the patched no-op inline so the test remains deterministic and focused
    # on durable attempt state.
    monkeypatch.setattr("ainrf.literature.work.asyncio.to_thread", run_inline)


@pytest.mark.asyncio
async def test_rss_worker_persists_response_before_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(tmp_path)
    item = _claim(service)
    body = b"<rss><channel /></rss>"

    async def fetch(*_args: object, **_kwargs: object) -> RssFetchResult:
        return RssFetchResult(
            status_code=200,
            body=body,
            etag="etag-1",
            last_modified=None,
            cache_control=None,
            papers=[_paper()],
        )

    _disable_limiter(monkeypatch)
    monkeypatch.setattr("ainrf.literature.work.ArxivRssProvider.fetch", fetch)
    await execute_work_item(service, item)

    attempts = service.list_api_attempts(work_item_id=item.work_item_id)
    assert len(attempts) == 1
    assert attempts[0].state == "succeeded"
    assert attempts[0].response_received_at is not None
    assert attempts[0].response_persisted_at is not None
    assert attempts[0].response_hash is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", [RuntimeError("after commit"), KeyboardInterrupt("stop")])
async def test_rss_response_record_fault_is_fenced_without_refetch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: BaseException,
) -> None:
    """A post-commit response-record fault cannot reopen the provider call."""

    service = _service(tmp_path)
    item = _claim(service)
    body = b"<rss><channel /></rss>"
    provider_calls = 0

    async def fetch(*_args: object, **_kwargs: object) -> RssFetchResult:
        nonlocal provider_calls
        provider_calls += 1
        return RssFetchResult(
            status_code=200,
            body=body,
            etag=None,
            last_modified=None,
            cache_control=None,
            papers=[_paper()],
        )

    original_record = service.record_api_response

    def record_then_fault(
        attempt_id: str,
        *,
        status_code: int | None,
        response_hash: str | None,
        response_payload: str | None = None,
        retry_after_seconds: int | None = None,
    ) -> NoReturn:
        original_record(
            attempt_id,
            status_code=status_code,
            response_hash=response_hash,
            response_payload=response_payload,
            retry_after_seconds=retry_after_seconds,
        )
        raise fault

    _disable_limiter(monkeypatch)
    monkeypatch.setattr("ainrf.literature.work.ArxivRssProvider.fetch", fetch)
    monkeypatch.setattr(service, "record_api_response", record_then_fault)
    with pytest.raises(type(fault)):
        await execute_work_item(service, item)

    attempt = service.list_api_attempts(work_item_id=item.work_item_id)[0]
    assert attempt.state == "unknown"
    service.retry_work_item(item.work_item_id, "response record fault", delay_seconds=0)
    assert _claim_or_none(service) is None
    assert provider_calls == 1


@pytest.mark.asyncio
async def test_rss_cancelled_response_record_fault_is_fenced_without_refetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(tmp_path)
    item = _claim(service)
    body = b"<rss><channel /></rss>"
    provider_calls = 0

    async def fetch(*_args: object, **_kwargs: object) -> RssFetchResult:
        nonlocal provider_calls
        provider_calls += 1
        return RssFetchResult(
            status_code=200,
            body=body,
            etag=None,
            last_modified=None,
            cache_control=None,
            papers=[_paper()],
        )

    original_record = service.record_api_response

    def record_then_cancel(
        attempt_id: str,
        *,
        status_code: int | None,
        response_hash: str | None,
        response_payload: str | None = None,
        retry_after_seconds: int | None = None,
    ) -> NoReturn:
        original_record(
            attempt_id,
            status_code=status_code,
            response_hash=response_hash,
            response_payload=response_payload,
            retry_after_seconds=retry_after_seconds,
        )
        raise asyncio.CancelledError()

    _disable_limiter(monkeypatch)
    monkeypatch.setattr("ainrf.literature.work.ArxivRssProvider.fetch", fetch)
    monkeypatch.setattr(service, "record_api_response", record_then_cancel)
    with pytest.raises(asyncio.CancelledError):
        await execute_work_item(service, item)

    attempt = service.list_api_attempts(work_item_id=item.work_item_id)[0]
    assert attempt.state == "unknown"
    service.retry_work_item(item.work_item_id, "response record cancelled", delay_seconds=0)
    assert _claim_or_none(service) is None
    assert provider_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exc", "state", "kind"),
    [
        (TimeoutError("provider timeout"), "unknown", "timeout"),
        (asyncio.CancelledError(), "unknown", "cancelled"),
    ],
)
async def test_rss_worker_records_unknown_failure_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    exc: BaseException,
    state: str,
    kind: str,
) -> None:
    service = _service(tmp_path)
    item = _claim(service)

    async def fetch(*_args: object, **_kwargs: object) -> RssFetchResult:
        raise exc

    _disable_limiter(monkeypatch)
    monkeypatch.setattr("ainrf.literature.work.ArxivRssProvider.fetch", fetch)
    with pytest.raises((TimeoutError, asyncio.CancelledError)):
        await execute_work_item(service, item)

    attempts = service.list_api_attempts(work_item_id=item.work_item_id)
    assert len(attempts) == 1
    assert attempts[0].state == state
    assert attempts[0].error_kind == kind
    assert attempts[0].completed_at is not None


@pytest.mark.asyncio
async def test_unknown_without_response_evidence_blocks_automatic_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(tmp_path)
    first = _claim(service)

    async def timeout(*_args: object, **_kwargs: object) -> RssFetchResult:
        raise TimeoutError("first attempt timed out")

    _disable_limiter(monkeypatch)
    monkeypatch.setattr("ainrf.literature.work.ArxivRssProvider.fetch", timeout)
    with pytest.raises(TimeoutError):
        await execute_work_item(service, first)
    service.retry_work_item(first.work_item_id, "provider timeout", delay_seconds=0)

    assert _claim_or_none(service) is None
    attempts = service.list_api_attempts(work_item_id=first.work_item_id)
    assert [attempt.state for attempt in attempts] == ["unknown"]


def _claim_or_none(service: LiteratureTrackingService):
    work_item_id = service.pending_outbox_work_ids()[0]
    return service.claim_work_item_by_id(work_item_id, worker_id="attempt-test")


def _summary_service(tmp_path: Path) -> LiteratureTrackingService:
    service = LiteratureTrackingService(tmp_path)
    service.initialize()
    topic = service.create_topic(
        user_id="owner",
        label="Agents",
        include_terms=[],
        exclude_terms=[],
        categories=["cs.AI"],
    )
    service.store_discovered_papers("seed-check", [_paper()])
    assert topic["topic_id"]
    service.request_summary("owner", "arxiv:2401.00001")
    return service


def _summary_message() -> MagicMock:
    message = MagicMock()
    block = MagicMock()
    block.text = (
        '[{"paper_id": "arxiv:2401.00001", "title_zh": "标题", '
        '"ai_summary": ["a"], "ai_practice_note": "可以"}]'
    )
    message.content = [block]
    return message


@pytest.mark.asyncio
async def test_summary_local_write_failure_reconciles_payload_without_refetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _summary_service(tmp_path)
    first = _claim(service)
    calls = 0

    async def create(*_args: object, **_kwargs: object) -> MagicMock:
        nonlocal calls
        calls += 1
        return _summary_message()

    original_complete = service.complete_summary

    def fail_local_write(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("summary local write interrupted")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(service, "complete_summary", fail_local_write)
    with patch(
        "anthropic.resources.messages.messages.AsyncMessages.create",
        new=AsyncMock(side_effect=create),
    ):
        with pytest.raises(RuntimeError, match="summary local write interrupted"):
            await execute_work_item(service, first)
    attempt = service.list_api_attempts(work_item_id=first.work_item_id)[0]
    assert attempt.state == "response_received"
    assert attempt.response_payload is not None

    service.retry_work_item(first.work_item_id, "summary local write interrupted", delay_seconds=0)
    monkeypatch.setattr(service, "complete_summary", original_complete)
    second = _claim(service)
    with patch(
        "anthropic.resources.messages.messages.AsyncMessages.create",
        new=AsyncMock(side_effect=create),
    ) as mock_create:
        await execute_work_item(service, second)
    assert calls == 1
    mock_create.assert_not_awaited()
    assert service.list_api_attempts(work_item_id=first.work_item_id)[0].state == "succeeded"


@pytest.mark.asyncio
async def test_rss_snapshot_reconciles_local_failure_without_refetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(tmp_path)
    first = _claim(service)
    body = b"<rss><channel /></rss>"
    calls = 0

    async def fetch(*_args: object, **_kwargs: object) -> RssFetchResult:
        nonlocal calls
        calls += 1
        return RssFetchResult(
            status_code=200,
            body=body,
            etag="etag-1",
            last_modified=None,
            cache_control=None,
            papers=[_paper()],
        )

    original_complete = service.complete_rss_response

    def fail_local_write(**_kwargs: object) -> None:
        raise RuntimeError("catalog write interrupted")

    _disable_limiter(monkeypatch)
    monkeypatch.setattr("ainrf.literature.work.ArxivRssProvider.fetch", fetch)
    monkeypatch.setattr(service, "complete_rss_response", fail_local_write)
    with pytest.raises(RuntimeError, match="catalog write interrupted"):
        await execute_work_item(service, first)
    attempt = service.list_api_attempts(work_item_id=first.work_item_id)[0]
    assert attempt.state == "response_persisted"
    assert service.rss_snapshot_for_attempt(attempt.attempt_id) is not None

    service.retry_work_item(first.work_item_id, "catalog write interrupted", delay_seconds=0)
    monkeypatch.setattr(service, "complete_rss_response", original_complete)
    second = _claim(service)
    await execute_work_item(service, second)
    assert calls == 1
    assert service.list_api_attempts(work_item_id=first.work_item_id)[0].state == "succeeded"


@pytest.mark.asyncio
async def test_rss_304_response_persisted_replays_semantic_evidence_without_refetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(tmp_path)
    first = _claim(service)
    calls = 0

    async def fetch(*_args: object, **_kwargs: object) -> RssFetchResult:
        nonlocal calls
        calls += 1
        return RssFetchResult(
            status_code=304,
            body=None,
            etag="etag-304",
            last_modified="Mon, 10 Aug 2026 00:00:00 GMT",
            cache_control=None,
            papers=[],
        )

    original_store = service.store_discovered_papers

    def fail_local_write(*_args: object, **_kwargs: object) -> int:
        raise RuntimeError("304 local write interrupted")

    _disable_limiter(monkeypatch)
    monkeypatch.setattr("ainrf.literature.work.ArxivRssProvider.fetch", fetch)
    monkeypatch.setattr(service, "store_discovered_papers", fail_local_write)
    with pytest.raises(RuntimeError, match="304 local write interrupted"):
        await execute_work_item(service, first)

    attempt = service.list_api_attempts(work_item_id=first.work_item_id)[0]
    assert attempt.state == "response_persisted"
    assert attempt.response_payload is not None

    service.retry_work_item(first.work_item_id, "304 local write interrupted", delay_seconds=0)
    monkeypatch.setattr(service, "store_discovered_papers", original_store)
    second = _claim(service)
    await execute_work_item(service, second)

    assert calls == 1
    attempt = service.list_api_attempts(work_item_id=first.work_item_id)[0]
    assert attempt.state == "succeeded"
    assert attempt.response_hash is not None
    scope = service.check_scope(str(first.payload["scope_id"]))
    assert scope is not None
    assert scope["status"] == "completed"
    assert scope["etag"] == "etag-304"
    assert scope["last_modified"] == "Mon, 10 Aug 2026 00:00:00 GMT"
    assert scope["response_hash"] == attempt.response_hash
    check = service.get_check("owner", str(first.payload["check_id"]))
    assert check["status"] == "completed"
    assert check["completed_at"] is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper_field", ["response_payload", "response_hash", "missing_hash"])
async def test_rss_304_tampered_durable_evidence_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tamper_field: str
) -> None:
    service = _service(tmp_path)
    first = _claim(service)
    calls = 0

    async def fetch(*_args: object, **_kwargs: object) -> RssFetchResult:
        nonlocal calls
        calls += 1
        return RssFetchResult(
            status_code=304,
            body=None,
            etag="etag-304",
            last_modified="Mon, 10 Aug 2026 00:00:00 GMT",
            cache_control=None,
            papers=[],
        )

    def fail_local_write(*_args: object, **_kwargs: object) -> NoReturn:
        raise RuntimeError("304 tamper fixture local write interrupted")

    _disable_limiter(monkeypatch)
    monkeypatch.setattr("ainrf.literature.work.ArxivRssProvider.fetch", fetch)
    monkeypatch.setattr(service, "store_discovered_papers", fail_local_write)
    with pytest.raises(RuntimeError, match="304 tamper fixture local write interrupted"):
        await execute_work_item(service, first)

    service.retry_work_item(first.work_item_id, "tampered 304 evidence", delay_seconds=0)
    with service._connect() as conn:
        if tamper_field == "response_payload":
            conn.execute(
                "UPDATE literature_api_attempts SET response_payload = ? WHERE work_item_id = ?",
                ('{"status_code":304,"scope_id":"tampered"}', first.work_item_id),
            )
        elif tamper_field == "response_hash":
            conn.execute(
                "UPDATE literature_api_attempts SET response_hash = ? WHERE work_item_id = ?",
                ("0" * 64, first.work_item_id),
            )
        else:
            conn.execute(
                "UPDATE literature_api_attempts SET response_hash = NULL WHERE work_item_id = ?",
                (first.work_item_id,),
            )

    second = _claim(service)
    with pytest.raises(RuntimeError, match="hash-integrity validation"):
        await execute_work_item(service, second)

    assert calls == 1
    attempt = service.list_api_attempts(work_item_id=first.work_item_id)[0]
    assert attempt.state == "response_persisted"
    scope = service.check_scope(str(first.payload["scope_id"]))
    assert scope is not None
    assert scope["status"] == "planned"


@pytest.mark.asyncio
async def test_rss_mismatched_request_fingerprint_starts_new_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(tmp_path)
    first = _claim(service)
    old = service.begin_api_attempt(
        provider="arxiv-rss",
        operation="fetch",
        request={"categories": ["cs.AI"], "etag": "old", "last_modified": None},
        work_item_id=first.work_item_id,
        attempt_number=first.attempt_count,
    )
    service.mark_api_unknown(
        old.attempt_id,
        error_kind="request_uncertain",
        error_message="old request",
    )
    calls = 0

    async def fetch(*_args: object, **_kwargs: object) -> RssFetchResult:
        nonlocal calls
        calls += 1
        return RssFetchResult(
            status_code=200,
            body=b"<rss><channel /></rss>",
            etag=None,
            last_modified=None,
            cache_control=None,
            papers=[_paper()],
        )

    _disable_limiter(monkeypatch)
    monkeypatch.setattr("ainrf.literature.work.ArxivRssProvider.fetch", fetch)
    await execute_work_item(service, first)

    attempts = service.list_api_attempts(work_item_id=first.work_item_id)
    assert calls == 1
    assert len(attempts) == 2
    assert attempts[-1].state == "succeeded"


@pytest.mark.asyncio
async def test_rss_snapshot_mismatched_request_fingerprint_starts_new_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A raw snapshot from another category request is never replayed."""

    service = _service(tmp_path)
    first = _claim(service)
    body = b"<rss><channel /></rss>"
    calls = 0

    async def fetch(*_args: object, **_kwargs: object) -> RssFetchResult:
        nonlocal calls
        calls += 1
        return RssFetchResult(
            status_code=200,
            body=body,
            etag="etag-1",
            last_modified=None,
            cache_control=None,
            papers=[_paper()],
        )

    _disable_limiter(monkeypatch)
    monkeypatch.setattr("ainrf.literature.work.ArxivRssProvider.fetch", fetch)
    await execute_work_item(service, first)
    service.retry_work_item(first.work_item_id, "category scope changed", delay_seconds=0)
    with service._connect() as conn:
        payload = dict(first.payload)
        payload["categories"] = ["cs.LG"]
        conn.execute(
            "UPDATE literature_work_items SET payload_json = ? WHERE work_item_id = ?",
            (json.dumps(payload), first.work_item_id),
        )

    second = _claim(service)
    await execute_work_item(service, second)

    attempts = service.list_api_attempts(work_item_id=first.work_item_id)
    assert calls == 2
    assert len(attempts) == 2
    assert attempts[0].request_fingerprint != attempts[1].request_fingerprint
    assert attempts[1].state == "succeeded"


@pytest.mark.asyncio
async def test_rss_checking_snapshot_changed_validator_is_not_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(tmp_path)
    first = _claim(service)
    calls: list[tuple[object, object]] = []
    body = b"<rss><channel /></rss>"

    async def fetch(*_args: object, **kwargs: object) -> RssFetchResult:
        calls.append((kwargs.get("etag"), kwargs.get("last_modified")))
        return RssFetchResult(
            status_code=200,
            body=body,
            etag="etag-new",
            last_modified="Tue, 11 Aug 2026 00:00:00 GMT",
            cache_control=None,
            papers=[_paper()],
        )

    original_complete = service.complete_rss_response

    def fail_local_write(**_kwargs: object) -> NoReturn:
        raise RuntimeError("checking snapshot local write interrupted")

    _disable_limiter(monkeypatch)
    monkeypatch.setattr("ainrf.literature.work.ArxivRssProvider.fetch", fetch)
    monkeypatch.setattr(service, "complete_rss_response", fail_local_write)
    with pytest.raises(RuntimeError, match="checking snapshot local write interrupted"):
        await execute_work_item(service, first)

    service.retry_work_item(first.work_item_id, "changed validator", delay_seconds=0)
    monkeypatch.setattr(service, "complete_rss_response", original_complete)
    with service._connect() as conn:
        conn.execute(
            "UPDATE literature_check_scopes SET status = 'checking', etag = ?, last_modified = ? WHERE scope_id = ?",
            ("etag-changed", "Wed, 12 Aug 2026 00:00:00 GMT", first.payload["scope_id"]),
        )
    second = _claim(service)
    await execute_work_item(service, second)

    assert calls == [(None, None), ("etag-changed", "Wed, 12 Aug 2026 00:00:00 GMT")]
    attempts = service.list_api_attempts(work_item_id=first.work_item_id)
    assert len(attempts) == 2
    assert attempts[-1].state == "succeeded"


@pytest.mark.asyncio
async def test_rss_checking_snapshot_different_fingerprint_is_not_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A checking scope may recover only the exact request that made its snapshot."""

    service = _service(tmp_path)
    first = _claim(service)
    body = b"<rss><channel /></rss>"
    calls = 0

    async def fetch(*_args: object, **_kwargs: object) -> RssFetchResult:
        nonlocal calls
        calls += 1
        return RssFetchResult(
            status_code=200,
            body=body,
            etag="etag-response",
            last_modified=None,
            cache_control=None,
            papers=[_paper()],
        )

    original_complete = service.complete_rss_response

    def fail_local_write(**_kwargs: object) -> NoReturn:
        raise RuntimeError("checking fingerprint fixture local write interrupted")

    _disable_limiter(monkeypatch)
    monkeypatch.setattr("ainrf.literature.work.ArxivRssProvider.fetch", fetch)
    monkeypatch.setattr(service, "complete_rss_response", fail_local_write)
    with pytest.raises(RuntimeError, match="checking fingerprint fixture"):
        await execute_work_item(service, first)

    service.retry_work_item(first.work_item_id, "checking fingerprint fixture", delay_seconds=0)
    attempt = service.list_api_attempts(work_item_id=first.work_item_id)[0]
    with service._connect() as conn:
        # Keep the snapshot internally consistent while changing the concrete
        # request identity.  The checking scope must still reject it.
        conn.execute(
            "UPDATE literature_api_attempts SET request_fingerprint = ? WHERE attempt_id = ?",
            ("different-request", attempt.attempt_id),
        )
        conn.execute(
            "UPDATE literature_source_snapshots SET request_fingerprint = ? WHERE attempt_id = ?",
            ("different-request", attempt.attempt_id),
        )

    monkeypatch.setattr(service, "complete_rss_response", original_complete)
    second = _claim(service)
    await execute_work_item(service, second)

    attempts = service.list_api_attempts(work_item_id=first.work_item_id)
    assert calls == 2
    assert len(attempts) == 2
    assert attempts[-1].state == "succeeded"


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper_field", ["body", "body_hash"])
async def test_rss_tampered_snapshot_fails_closed_without_recovery_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tamper_field: str
) -> None:
    service = _service(tmp_path)
    first = _claim(service)
    body = b"<rss><channel /></rss>"
    calls = 0

    async def fetch(*_args: object, **_kwargs: object) -> RssFetchResult:
        nonlocal calls
        calls += 1
        return RssFetchResult(
            status_code=200,
            body=body,
            etag="etag-snapshot",
            last_modified=None,
            cache_control=None,
            papers=[_paper()],
        )

    original_complete = service.complete_rss_response

    def fail_local_write(**_kwargs: object) -> NoReturn:
        raise RuntimeError("snapshot tamper fixture local write interrupted")

    _disable_limiter(monkeypatch)
    monkeypatch.setattr("ainrf.literature.work.ArxivRssProvider.fetch", fetch)
    monkeypatch.setattr(service, "complete_rss_response", fail_local_write)
    with pytest.raises(RuntimeError, match="snapshot tamper fixture local write interrupted"):
        await execute_work_item(service, first)

    service.retry_work_item(first.work_item_id, "tampered snapshot", delay_seconds=0)
    monkeypatch.setattr(service, "complete_rss_response", original_complete)
    attempt = service.list_api_attempts(work_item_id=first.work_item_id)[0]
    with service._connect() as conn:
        if tamper_field == "body":
            conn.execute(
                "UPDATE literature_source_snapshots SET body = ? WHERE attempt_id = ?",
                (b"tampered body", attempt.attempt_id),
            )
        else:
            conn.execute(
                "UPDATE literature_source_snapshots SET body_hash = ? WHERE attempt_id = ?",
                ("0" * 64, attempt.attempt_id),
            )

    second = _claim(service)
    with pytest.raises(RuntimeError, match="hash-integrity validation"):
        await execute_work_item(service, second)

    assert calls == 1
    recovered = service.api_attempt(attempt.attempt_id)
    assert recovered is not None
    assert recovered.state == "response_persisted"
    scope = service.check_scope(str(first.payload["scope_id"]))
    assert scope is not None
    assert scope["status"] == "checking"


@pytest.mark.asyncio
async def test_rss_snapshot_fingerprint_tampering_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(tmp_path)
    first = _claim(service)
    body = b"<rss><channel /></rss>"
    calls = 0

    async def fetch(*_args: object, **_kwargs: object) -> RssFetchResult:
        nonlocal calls
        calls += 1
        return RssFetchResult(
            status_code=200,
            body=body,
            etag="etag-snapshot",
            last_modified=None,
            cache_control=None,
            papers=[_paper()],
        )

    original_complete = service.complete_rss_response

    def fail_local_write(**_kwargs: object) -> NoReturn:
        raise RuntimeError("snapshot fingerprint fixture local write interrupted")

    _disable_limiter(monkeypatch)
    monkeypatch.setattr("ainrf.literature.work.ArxivRssProvider.fetch", fetch)
    monkeypatch.setattr(service, "complete_rss_response", fail_local_write)
    with pytest.raises(RuntimeError, match="snapshot fingerprint fixture"):
        await execute_work_item(service, first)

    service.retry_work_item(first.work_item_id, "tampered snapshot fingerprint", delay_seconds=0)
    monkeypatch.setattr(service, "complete_rss_response", original_complete)
    with service._connect() as conn:
        conn.execute(
            "UPDATE literature_source_snapshots SET request_fingerprint = ? WHERE attempt_id = ?",
            (
                "tampered-request",
                service.list_api_attempts(work_item_id=first.work_item_id)[0].attempt_id,
            ),
        )

    second = _claim(service)
    with pytest.raises(RuntimeError, match="snapshot request fingerprint"):
        await execute_work_item(service, second)

    assert calls == 1
    scope = service.check_scope(str(first.payload["scope_id"]))
    assert scope is not None
    assert scope["status"] == "checking"


@pytest.mark.asyncio
async def test_rss_historical_validator_does_not_match_current_request_fingerprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A changed current validator must issue a new request after success."""

    service = _service(tmp_path)
    first = _claim(service)
    body = b"<rss><channel /></rss>"
    calls = 0

    async def fetch(*_args: object, **_kwargs: object) -> RssFetchResult:
        nonlocal calls
        calls += 1
        return RssFetchResult(
            status_code=200,
            body=body,
            etag=f"etag-{calls}",
            last_modified=None,
            cache_control=None,
            papers=[_paper()],
        )

    _disable_limiter(monkeypatch)
    monkeypatch.setattr("ainrf.literature.work.ArxivRssProvider.fetch", fetch)
    await execute_work_item(service, first)
    service.retry_work_item(first.work_item_id, "current validator changed", delay_seconds=0)
    with service._connect() as conn:
        conn.execute(
            "UPDATE literature_check_scopes SET etag = 'etag-new' WHERE scope_id = ?",
            (first.payload["scope_id"],),
        )

    second = _claim(service)
    await execute_work_item(service, second)

    attempts = service.list_api_attempts(work_item_id=first.work_item_id)
    assert calls == 2
    assert len(attempts) == 2
    assert attempts[0].state == "succeeded"
    assert attempts[1].state == "succeeded"


@pytest.mark.asyncio
async def test_rss_category_order_and_duplicates_share_request_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = LiteratureTrackingService(tmp_path)
    service.initialize()
    topic = service.create_topic(
        user_id="owner",
        label="Agents",
        include_terms=[],
        exclude_terms=[],
        categories=["cs.AI", "cs.LG"],
    )
    service.create_check(user_id="owner", topic_ids=[topic["topic_id"]])
    work_item_id = service.pending_outbox_work_ids()[0]
    with service._connect() as conn:
        payload = json.loads(
            conn.execute(
                "SELECT payload_json FROM literature_work_items WHERE work_item_id = ?",
                (work_item_id,),
            ).fetchone()[0]
        )
        payload["categories"] = ["cs.LG", "cs.AI", "cs.LG"]
        conn.execute(
            "UPDATE literature_work_items SET payload_json = ? WHERE work_item_id = ?",
            (json.dumps(payload), work_item_id),
        )

    first = _claim(service)
    provider_categories: list[list[str]] = []
    calls = 0

    async def fetch(_provider: object, categories: list[str], **_kwargs: object) -> RssFetchResult:
        nonlocal calls
        calls += 1
        provider_categories.append(categories)
        return RssFetchResult(
            status_code=200,
            body=b"<rss><channel /></rss>",
            etag=None,
            last_modified=None,
            cache_control=None,
            papers=[_paper()],
        )

    _disable_limiter(monkeypatch)
    monkeypatch.setattr("ainrf.literature.work.ArxivRssProvider.fetch", fetch)
    await execute_work_item(service, first)
    service.retry_work_item(first.work_item_id, "same normalized request", delay_seconds=0)
    with service._connect() as conn:
        payload["categories"] = ["cs.AI", "cs.LG", "cs.AI"]
        conn.execute(
            "UPDATE literature_work_items SET payload_json = ? WHERE work_item_id = ?",
            (json.dumps(payload), first.work_item_id),
        )
    second = _claim(service)
    await execute_work_item(service, second)

    attempts = service.list_api_attempts(work_item_id=first.work_item_id)
    assert calls == 1
    assert provider_categories == [["cs.AI", "cs.LG"]]
    assert len(attempts) == 1
    assert attempts[0].state == "succeeded"


@pytest.mark.asyncio
async def test_anthropic_retryable_failure_creates_retry_attempt_after_retry_after(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _summary_service(tmp_path)
    first = _claim(service)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    rate_limit = anthropic.RateLimitError(
        "rate limited",
        response=httpx.Response(
            429,
            headers={"retry-after": "17"},
            request=httpx.Request("POST", "https://example.test"),
        ),
        body={},
    )

    with patch(
        "anthropic.resources.messages.messages.AsyncMessages.create",
        new=AsyncMock(side_effect=[rate_limit, _summary_message()]),
    ) as mock_create:
        with pytest.raises(ExternalCallFailure, match="rate limited"):
            await execute_work_item(service, first)
        attempts = service.list_api_attempts(work_item_id=first.work_item_id)
        assert len(attempts) == 1
        assert attempts[0].state == "retryable_failure"
        assert attempts[0].retry_after_seconds == 17
        service.retry_work_item(first.work_item_id, "rate limited")
        with service._connect() as conn:
            row = conn.execute(
                "SELECT available_at FROM literature_work_items WHERE work_item_id = ?",
                (first.work_item_id,),
            ).fetchone()
        assert row is not None
        retry_at = datetime.fromisoformat(str(row["available_at"]))
        completed_at = datetime.fromisoformat(attempts[0].completed_at or "")
        assert retry_at >= completed_at + timedelta(seconds=16)

        with service._connect() as conn:
            conn.execute(
                "UPDATE literature_work_items SET available_at = ? WHERE work_item_id = ?",
                (datetime.now(UTC).isoformat(), first.work_item_id),
            )
        second = _claim(service)
        await execute_work_item(service, second)

        attempts = service.list_api_attempts(work_item_id=first.work_item_id)
        assert [attempt.state for attempt in attempts] == ["retryable_failure", "succeeded"]
        assert mock_create.await_count == 2


@pytest.mark.asyncio
async def test_rss_parser_error_reparses_snapshot_without_refetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(tmp_path)
    first = _claim(service)
    body = b"raw parser fixture"
    calls = 0

    async def fetch(*_args: object, **_kwargs: object) -> RssFetchResult:
        nonlocal calls
        calls += 1
        return RssFetchResult(
            status_code=200,
            body=body,
            etag=None,
            last_modified=None,
            cache_control=None,
            papers=[],
        )

    def parse_error(_body: bytes) -> list[DiscoveredPaper]:
        raise ValueError("malformed RSS")

    _disable_limiter(monkeypatch)
    monkeypatch.setattr("ainrf.literature.work.ArxivRssProvider.fetch", fetch)
    monkeypatch.setattr("ainrf.literature.work.parse_rss", parse_error)
    with pytest.raises(ValueError, match="malformed RSS"):
        await execute_work_item(service, first)
    attempt = service.list_api_attempts(work_item_id=first.work_item_id)[0]
    assert attempt.state == "response_persisted"
    assert attempt.error_kind == "parser_error"

    service.retry_work_item(first.work_item_id, "malformed RSS", delay_seconds=0)
    monkeypatch.setattr("ainrf.literature.work.parse_rss", lambda _body: [])
    second = _claim(service)
    await execute_work_item(service, second)
    assert calls == 1
    assert service.list_api_attempts(work_item_id=first.work_item_id)[0].state == "succeeded"


@pytest.mark.asyncio
async def test_rss_keyboard_interrupt_converges_unknown_without_swallowing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(tmp_path)
    item = _claim(service)

    async def interrupt(*_args: object, **_kwargs: object) -> RssFetchResult:
        raise KeyboardInterrupt("worker interrupted")

    _disable_limiter(monkeypatch)
    monkeypatch.setattr("ainrf.literature.work.ArxivRssProvider.fetch", interrupt)
    with pytest.raises(KeyboardInterrupt, match="worker interrupted"):
        await execute_work_item(service, item)
    attempt = service.list_api_attempts(work_item_id=item.work_item_id)[0]
    assert attempt.state == "unknown"
    assert attempt.error_kind == "request_uncertain"


@pytest.mark.asyncio
async def test_rss_provider_failure_secondary_persistence_fault_is_dedicated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(tmp_path)
    item = _claim(service)
    calls = 0

    async def provider_failure(*_args: object, **_kwargs: object) -> RssFetchResult:
        nonlocal calls
        calls += 1
        raise RuntimeError("RSS provider failed")

    def mark_failure(*_args: object, **_kwargs: object) -> NoReturn:
        raise RuntimeError("RSS failure mark unavailable")

    _disable_limiter(monkeypatch)
    monkeypatch.setattr("ainrf.literature.work.ArxivRssProvider.fetch", provider_failure)
    monkeypatch.setattr(service, "mark_api_retryable_failure", mark_failure)
    with pytest.raises(DurableAttemptPersistenceFailure):
        await execute_work_item(service, item)

    assert calls == 1
    attempt = service.list_api_attempts(work_item_id=item.work_item_id)[0]
    assert attempt.state == "started"
    service.retry_work_item(item.work_item_id, "RSS provider failed", delay_seconds=0)
    second = _claim(service)
    with pytest.raises(RuntimeError, match="started without durable response evidence"):
        await execute_work_item(service, second)
    assert calls == 1


@pytest.mark.asyncio
async def test_rss_retry_after_is_durable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(tmp_path)
    item = _claim(service)

    async def rate_limited(*_args: object, **_kwargs: object) -> RssFetchResult:
        return RssFetchResult(
            status_code=429,
            body=None,
            etag=None,
            last_modified=None,
            cache_control=None,
            papers=[],
            retry_after_seconds=17,
        )

    _disable_limiter(monkeypatch)
    monkeypatch.setattr("ainrf.literature.work.ArxivRssProvider.fetch", rate_limited)
    with pytest.raises(RuntimeError, match="HTTP 429"):
        await execute_work_item(service, item)
    attempt = service.list_api_attempts(work_item_id=item.work_item_id)[0]
    assert attempt.state == "retryable_failure"
    assert attempt.retry_after_seconds == 17


def test_stale_started_attempt_and_expired_running_work_are_reconciled(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    item = _claim(service)
    attempt = service.begin_api_attempt(
        provider="arxiv-rss",
        operation="fetch",
        request={"categories": ["cs.AI"]},
        work_item_id=item.work_item_id,
        attempt_number=item.attempt_count,
    )
    with service._connect() as conn:
        conn.execute(
            "UPDATE literature_api_attempts SET started_at = '2020-01-01T00:00:00+00:00' WHERE attempt_id = ?",
            (attempt.attempt_id,),
        )
        conn.execute(
            "UPDATE literature_work_items SET lease_expires_at = '2020-01-01T00:00:00+00:00' WHERE work_item_id = ?",
            (item.work_item_id,),
        )

    assert service.claim_work_item_by_id(item.work_item_id, worker_id="recovery") is None
    recovered = service.api_attempt(attempt.attempt_id)
    assert recovered is not None
    assert recovered.state == "unknown"
    with service._connect() as conn:
        status = conn.execute(
            "SELECT status FROM literature_work_items WHERE work_item_id = ?",
            (item.work_item_id,),
        ).fetchone()[0]
    assert status == "failed"


def test_stale_started_attempt_with_rss_snapshot_crosses_response_boundaries(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    item = _claim(service)
    attempt = service.begin_api_attempt(
        provider="arxiv-rss",
        operation="fetch",
        request={"categories": ["cs.AI"]},
        check_id=str(item.payload["check_id"]),
        work_item_id=item.work_item_id,
        attempt_number=item.attempt_count,
    )
    snapshot = service.persist_rss_snapshot(
        attempt_id=attempt.attempt_id,
        check_id=str(item.payload["check_id"]),
        scope_id=str(item.payload["scope_id"]),
        body=b"raw rss evidence",
        etag=None,
        last_modified=None,
        cache_control=None,
        status_code=200,
    )
    with service._connect() as conn:
        conn.execute(
            "UPDATE literature_api_attempts SET started_at = '2020-01-01T00:00:00+00:00' WHERE attempt_id = ?",
            (attempt.attempt_id,),
        )

    reconciled = service.reconcile_stale_api_attempts(stale_after_seconds=0)
    recovered = service.api_attempt(attempt.attempt_id)
    assert len(reconciled) == 1
    assert recovered is not None
    assert recovered.state == "response_persisted"
    assert recovered.response_received_at is not None
    assert recovered.response_persisted_at is not None
    assert recovered.status_code == 200
    assert recovered.response_hash == snapshot["body_hash"]
    assert service.reconcile_stale_api_attempts(stale_after_seconds=0) == []


def test_expired_started_attempt_with_rss_snapshot_crosses_response_boundaries(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    item = _claim(service)
    attempt = service.begin_api_attempt(
        provider="arxiv-rss",
        operation="fetch",
        request={"categories": ["cs.AI"]},
        check_id=str(item.payload["check_id"]),
        work_item_id=item.work_item_id,
        attempt_number=item.attempt_count,
    )
    snapshot = service.persist_rss_snapshot(
        attempt_id=attempt.attempt_id,
        check_id=str(item.payload["check_id"]),
        scope_id=str(item.payload["scope_id"]),
        body=b"raw rss evidence",
        etag=None,
        last_modified=None,
        cache_control=None,
        status_code=200,
    )
    with service._connect() as conn:
        conn.execute(
            "UPDATE literature_work_items SET lease_expires_at = '2020-01-01T00:00:00+00:00' WHERE work_item_id = ?",
            (item.work_item_id,),
        )

    service.reconcile_expired_work_items()
    recovered = service.api_attempt(attempt.attempt_id)
    assert recovered is not None
    assert recovered.state == "response_persisted"
    assert recovered.response_received_at is not None
    assert recovered.response_persisted_at is not None
    assert recovered.status_code == 200
    assert recovered.response_hash == snapshot["body_hash"]
    with service._connect() as conn:
        status = conn.execute(
            "SELECT status FROM literature_work_items WHERE work_item_id = ?",
            (item.work_item_id,),
        ).fetchone()[0]
    assert status == "retrying"


@pytest.mark.parametrize("tamper_field", ["body", "body_hash"])
def test_stale_tampered_rss_snapshot_is_not_promoted(tmp_path: Path, tamper_field: str) -> None:
    service = _service(tmp_path)
    item = _claim(service)
    attempt = service.begin_api_attempt(
        provider="arxiv-rss",
        operation="fetch",
        request={"categories": ["cs.AI"]},
        check_id=str(item.payload["check_id"]),
        work_item_id=item.work_item_id,
        attempt_number=item.attempt_count,
    )
    snapshot = service.persist_rss_snapshot(
        attempt_id=attempt.attempt_id,
        check_id=str(item.payload["check_id"]),
        scope_id=str(item.payload["scope_id"]),
        body=b"raw rss evidence",
        etag=None,
        last_modified=None,
        cache_control=None,
        status_code=200,
    )
    with service._connect() as conn:
        conn.execute(
            "UPDATE literature_api_attempts SET started_at = '2020-01-01T00:00:00+00:00' WHERE attempt_id = ?",
            (attempt.attempt_id,),
        )
        if tamper_field == "body":
            conn.execute(
                "UPDATE literature_source_snapshots SET body = ? WHERE attempt_id = ?",
                (b"tampered rss evidence", attempt.attempt_id),
            )
        else:
            conn.execute(
                "UPDATE literature_source_snapshots SET body_hash = ? WHERE attempt_id = ?",
                ("0" * 64, attempt.attempt_id),
            )

    reconciled = service.reconcile_stale_api_attempts(stale_after_seconds=0)
    recovered = service.api_attempt(attempt.attempt_id)
    assert len(reconciled) == 1
    assert recovered is not None
    assert recovered.state == "unknown"
    assert recovered.response_received_at is None
    assert recovered.response_persisted_at is None
    assert recovered.response_hash is None
    assert recovered.response_hash != snapshot["body_hash"]


def test_expired_response_received_with_payload_is_promoted_for_recovery(tmp_path: Path) -> None:
    service = _service(tmp_path)
    item = _claim(service)
    attempt = service.begin_api_attempt(
        provider="anthropic",
        operation="summary.batch",
        request={"model": "model", "prompt_hash": "prompt"},
        work_item_id=item.work_item_id,
        attempt_number=item.attempt_count,
    )
    service.record_api_response(
        attempt.attempt_id,
        status_code=200,
        response_hash=hashlib.sha256(b"durable payload").hexdigest(),
        response_payload="durable payload",
    )
    with service._connect() as conn:
        conn.execute(
            "UPDATE literature_work_items SET lease_expires_at = '2020-01-01T00:00:00+00:00' WHERE work_item_id = ?",
            (item.work_item_id,),
        )

    service.reconcile_expired_work_items()
    recovered = service.api_attempt(attempt.attempt_id)
    assert recovered is not None
    assert recovered.state == "response_persisted"
    with service._connect() as conn:
        status = conn.execute(
            "SELECT status FROM literature_work_items WHERE work_item_id = ?",
            (item.work_item_id,),
        ).fetchone()[0]
    assert status == "retrying"
