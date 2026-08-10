"""Interfaces for durable Literature external-call attempts.

The SQLite-backed tracking service owns the implementation.  Providers and
workers receive the small adapter defined here so they cannot write the
``literature_api_attempts`` table directly or substitute process metrics for
durable state.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Protocol


_ATTEMPT_STATES = frozenset(
    {
        "started",
        "response_received",
        "response_persisted",
        "succeeded",
        "retryable_failure",
        "definitive_failure",
        "unknown",
    }
)


def request_fingerprint(provider: str, operation: str, request: object) -> str:
    """Return the canonical identity for one concrete external request.

    Adapters use the same identity as the SQLite store when deciding whether
    a durable response can be replayed.  Matching only provider/operation is
    unsafe: a changed model, prompt, or request identity must create a new
    external attempt.
    """

    canonical = json.dumps(
        {"provider": provider, "operation": operation, "request": request},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ExternalCallAttempt:
    """Durable state for one concrete provider or LLM request."""

    attempt_id: str
    provider: str
    operation: str
    request_fingerprint: str
    attempt_number: int
    state: str
    check_id: str | None
    work_item_id: str | None
    status_code: int | None
    retry_after_seconds: int | None
    error_kind: str | None
    error_message: str | None
    started_at: str
    response_received_at: str | None
    response_persisted_at: str | None
    completed_at: str | None
    response_hash: str | None
    response_payload: str | None
    legacy_state: str | None

    @property
    def is_terminal(self) -> bool:
        return self.state in {
            "succeeded",
            "retryable_failure",
            "definitive_failure",
            "unknown",
        }


class ExternalCallAttemptStore(Protocol):
    """The narrow repository seam used by external-call adapters."""

    def begin_api_attempt(
        self,
        *,
        provider: str,
        operation: str,
        request: object,
        check_id: str | None = None,
        work_item_id: str | None = None,
        attempt_number: int = 1,
    ) -> ExternalCallAttempt: ...

    def record_api_response(
        self,
        attempt_id: str,
        *,
        status_code: int | None,
        response_hash: str | None,
        response_payload: str | None = None,
        retry_after_seconds: int | None = None,
    ) -> ExternalCallAttempt: ...

    def mark_api_response_persisted(
        self,
        attempt_id: str,
        *,
        error_kind: str | None = None,
        error_message: str | None = None,
    ) -> ExternalCallAttempt: ...

    def mark_api_succeeded(
        self,
        attempt_id: str,
        *,
        response_hash: str | None = None,
        status_code: int | None = None,
    ) -> ExternalCallAttempt: ...

    def mark_api_retryable_failure(
        self,
        attempt_id: str,
        *,
        error_kind: str,
        error_message: str,
        retry_after_seconds: int | None = None,
        status_code: int | None = None,
    ) -> ExternalCallAttempt: ...

    def mark_api_definitive_failure(
        self,
        attempt_id: str,
        *,
        error_kind: str,
        error_message: str,
        status_code: int | None = None,
    ) -> ExternalCallAttempt: ...

    def mark_api_unknown(
        self,
        attempt_id: str,
        *,
        error_kind: str,
        error_message: str,
        retry_after_seconds: int | None = None,
    ) -> ExternalCallAttempt: ...


class ExternalCallRecoveryBlocked(RuntimeError):
    """A matching durable attempt has no raw response that can be replayed."""


@dataclass(slots=True)
class LiteratureExternalCallAdapter:
    """Bind a repository to one durable work-item attempt context."""

    store: ExternalCallAttemptStore
    work_item_id: str | None
    attempt_number: int
    recovery_attempt: ExternalCallAttempt | None = None
    _attempts: list[ExternalCallAttempt] = field(default_factory=list, init=False, repr=False)
    _replayed: bool = field(default=False, init=False, repr=False)

    def begin(
        self,
        *,
        provider: str,
        operation: str,
        request: object,
    ) -> ExternalCallAttempt:
        attempt = self.recovery_attempt
        expected_fingerprint = request_fingerprint(provider, operation, request)
        if (
            attempt is not None
            and attempt.provider == provider
            and attempt.operation == operation
            and attempt.request_fingerprint == expected_fingerprint
        ):
            if attempt.state == "retryable_failure":
                # A retryable provider failure has no response to replay.  The
                # queue's available_at gate (which persists Retry-After) owns
                # when this call may run again; once the work item is claimed,
                # always allocate a fresh durable attempt instead of treating
                # the failed row as a recovery fence.
                attempt = self.store.begin_api_attempt(
                    provider=provider,
                    operation=operation,
                    request=request,
                    work_item_id=self.work_item_id,
                    attempt_number=max(self.attempt_number, attempt.attempt_number + 1),
                )
            elif (
                not isinstance(attempt.response_payload, str)
                or not attempt.response_payload.strip()
                or not isinstance(attempt.response_hash, str)
                or hashlib.sha256(attempt.response_payload.encode()).hexdigest()
                != attempt.response_hash
            ):
                raise ExternalCallRecoveryBlocked(
                    "matching Literature external attempt lacks replayable response evidence"
                )
            else:
                self._replayed = True
                self.recovery_attempt = None
        else:
            attempt = self.store.begin_api_attempt(
                provider=provider,
                operation=operation,
                request=request,
                work_item_id=self.work_item_id,
                attempt_number=self.attempt_number,
            )
        self._attempts.append(attempt)
        return attempt

    def fence_response_boundary(
        self,
        attempt: ExternalCallAttempt | None,
        *,
        error_kind: str,
        error_message: str,
    ) -> ExternalCallAttempt | None:
        """Fence a failed durable-record transition without masking its error.

        A provider response payload committed before a wrapper raised is safe
        to replay, so it remains at ``response_received``.  If no payload is
        visible, transition the attempt to ``unknown`` before the worker can
        schedule another provider call.
        """

        if attempt is None:
            return None
        current_reader = getattr(self.store, "api_attempt", None)
        try:
            current = current_reader(attempt.attempt_id) if callable(current_reader) else None
        except BaseException:
            # The caller owns the primary provider/processing exception.  A
            # failed diagnostic read cannot replace it or reopen the call.
            current = attempt
        if current is None:
            current = attempt
        if current.state not in {"started", "response_received"}:
            return current
        if isinstance(current.response_payload, str) and bool(current.response_payload.strip()):
            return current
        try:
            return self.store.mark_api_unknown(
                current.attempt_id,
                error_kind=error_kind,
                error_message=error_message,
            )
        except BaseException:
            # The caller owns the original exception; this method never
            # substitutes a secondary persistence failure for it.
            return current

    @property
    def attempts(self) -> tuple[ExternalCallAttempt, ...]:
        """Return calls begun by this worker invocation in call order."""

        return tuple(self._attempts)

    @property
    def replaying(self) -> bool:
        """Whether the next call is being reconciled from durable evidence."""

        return self._replayed


def is_attempt_state(value: str) -> bool:
    """Return whether *value* is one of the persisted lifecycle states."""

    return value in _ATTEMPT_STATES
