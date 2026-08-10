"""HTTP Adapter for the canonical Conversation Interface."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from ainrf.api.idempotency import require_idempotency_key
from ainrf.api.schemas import (
    ForkConfirmResponse,
    ForkConfirmRequest,
    ForkPreviewRequest,
    ForkPreviewResponse,
    TurnControlResponse,
    TurnCreateRequest,
    TurnInterruptRequest,
    TurnItemListResponse,
    TurnListResponse,
    TurnSteerRequest,
    TurnSubmissionResponse,
)
from ainrf.auth.permissions import get_current_user
from ainrf.domain import ConversationApplicationService
from ainrf.domain.conversation_contracts import ConversationContractError
from ainrf.domain.conversation_contracts import ForkTransferMode
from ainrf.domain.service import DomainNotFoundError, DomainPermissionError
from ainrf.domain_control import MaintenanceModeError

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _conversation(request: Request) -> ConversationApplicationService:
    module = getattr(request.app.state, "conversation_application_service", None)
    if module is None or not isinstance(module, ConversationApplicationService):
        raise HTTPException(status_code=503, detail="Conversation Module is unavailable")
    if not module.ready():
        raise HTTPException(status_code=503, detail="Conversation Module is not ready")
    return module


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, MaintenanceModeError):
        return HTTPException(status_code=503, detail="Domain writes are paused for maintenance")
    if isinstance(exc, DomainPermissionError):
        return HTTPException(status_code=403, detail="Task permission denied")
    if isinstance(exc, DomainNotFoundError):
        return HTTPException(status_code=404, detail="Conversation resource not found")
    if isinstance(exc, ConversationContractError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "message": str(exc)},
        )
    if isinstance(exc, ValueError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=500, detail="Unexpected Conversation error")


@router.post("/{task_id}/turns", status_code=202, response_model=TurnSubmissionResponse)
async def create_turn(
    task_id: str, payload: TurnCreateRequest, request: Request
) -> TurnSubmissionResponse:
    try:
        result = _conversation(request).create_turn(
            task_id,
            get_current_user(request),
            input={"text": payload.text},
            idempotency_key=require_idempotency_key(request),
            context_snapshot_ref=payload.context_snapshot_ref,
            allow_next_turn=payload.allow_next_turn,
        )
        return TurnSubmissionResponse.model_validate(result)
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/{task_id}/turns", response_model=TurnListResponse)
async def list_turns(task_id: str, request: Request) -> TurnListResponse:
    try:
        return TurnListResponse.model_validate(
            {"items": _conversation(request).list_turns(task_id, get_current_user(request))}
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/{task_id}/turns/{turn_id}/items", response_model=TurnItemListResponse)
async def list_turn_items(task_id: str, turn_id: str, request: Request) -> TurnItemListResponse:
    try:
        items = _conversation(request).list_items(
            task_id, get_current_user(request), turn_id=turn_id
        )
        return TurnItemListResponse.model_validate({"items": items})
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate(exc) from exc


@router.post(
    "/{task_id}/turns/{turn_id}/steer", status_code=202, response_model=TurnControlResponse
)
async def steer_turn(
    task_id: str, turn_id: str, payload: TurnSteerRequest, request: Request
) -> TurnControlResponse:
    if payload.expected_turn_id != turn_id:
        raise HTTPException(status_code=409, detail="expected_turn_id must match the route Turn")
    try:
        result = _conversation(request).request_steer(
            task_id,
            turn_id,
            get_current_user(request),
            input={"text": payload.text},
            idempotency_key=require_idempotency_key(request),
        )
        return TurnControlResponse.model_validate(result)
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate(exc) from exc


@router.post(
    "/{task_id}/turns/{turn_id}/interrupt",
    status_code=202,
    response_model=TurnControlResponse,
)
async def interrupt_turn(
    task_id: str, turn_id: str, payload: TurnInterruptRequest, request: Request
) -> TurnControlResponse:
    if payload.expected_turn_id != turn_id:
        raise HTTPException(status_code=409, detail="expected_turn_id must match the route Turn")
    try:
        result = _conversation(request).request_interrupt(
            task_id,
            turn_id,
            get_current_user(request),
            idempotency_key=require_idempotency_key(request),
        )
        return TurnControlResponse.model_validate(result)
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate(exc) from exc


@router.post(
    "/{task_id}/turns/{turn_id}/retry", status_code=202, response_model=TurnSubmissionResponse
)
async def retry_turn(
    task_id: str, turn_id: str, payload: TurnCreateRequest, request: Request
) -> TurnSubmissionResponse:
    try:
        result = _conversation(request).retry_turn(
            task_id,
            turn_id,
            get_current_user(request),
            input={"text": payload.text},
            idempotency_key=require_idempotency_key(request),
            context_snapshot_ref=payload.context_snapshot_ref,
        )
        return TurnSubmissionResponse.model_validate(result)
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/{task_id}/fork-preview", response_model=ForkPreviewResponse)
async def preview_fork(
    task_id: str, payload: ForkPreviewRequest, request: Request
) -> ForkPreviewResponse:
    try:
        result = _conversation(request).preview_fork(
            task_id,
            get_current_user(request),
            target_engine_family=payload.target_engine_family,
            target_project_id=payload.target_project_id,
            target_workspace_id=payload.target_workspace_id,
            target_harness_engine=payload.target_harness_engine,
            target_title=payload.target_title,
            transfer_mode=ForkTransferMode(payload.transfer_mode),
            transfer_range=payload.transfer_range,
            metrics=payload.metrics,
            disclosure=payload.disclosure,
            idempotency_key=require_idempotency_key(request),
        )
        return ForkPreviewResponse.model_validate(result)
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate(exc) from exc


@router.post(
    "/{task_id}/fork-preview/{preview_id}/confirm",
    response_model=ForkConfirmResponse,
)
async def confirm_fork(
    task_id: str,
    preview_id: str,
    payload: ForkConfirmRequest,
    request: Request,
) -> ForkConfirmResponse:
    try:
        result = _conversation(request).confirm_fork(
            task_id,
            preview_id,
            get_current_user(request),
            preview_hash=payload.preview_hash,
            source_revision=payload.source_revision,
            transfer_mode=ForkTransferMode(payload.transfer_mode),
            truncation_acknowledged=payload.truncation_acknowledged,
            full_transcript_confirmed=payload.full_transcript_confirmed,
            idempotency_key=require_idempotency_key(request),
        )
        return ForkConfirmResponse.model_validate(result)
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate(exc) from exc
