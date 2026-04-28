from __future__ import annotations

import inspect
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from starlette.datastructures import Headers

from ainrf.api.schemas import (
    CodeServerLifecycleStatus,
    CodeServerSessionRequest,
    CodeServerStatusResponse,
)
from ainrf.code_server import (
    CodeServerState,
    EnvironmentCodeServerManager,
    SessionManagerLike,
    UnsupportedWorkspaceEnvironmentError,
)
from ainrf.environments import EnvironmentNotFoundError

router = APIRouter(prefix="/code", tags=["code"])
_HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}


def _get_code_server_manager(request: Request) -> EnvironmentCodeServerManager | None:
    manager = getattr(request.app.state, "code_server_manager", None)
    if manager is not None:
        return manager
    return getattr(request.app.state, "code_server_supervisor", None)


def _translate_code_server_error(exc: Exception) -> HTTPException:
    if isinstance(exc, EnvironmentNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Environment not found")
    if isinstance(exc, UnsupportedWorkspaceEnvironmentError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


def _serialize_code_server_state(state: CodeServerState) -> CodeServerStatusResponse:
    return CodeServerStatusResponse.model_validate(
        {
            "status": state.status,
            "environment_id": state.environment_id,
            "environment_alias": state.environment_alias,
            "workspace_dir": state.workspace_dir,
            "detail": state.detail,
            "managed": state.managed,
        }
    )


async def _call_manager_status(
    manager: EnvironmentCodeServerManager,
    environment_id: str | None = None,
) -> CodeServerState:
    if environment_id is None:
        result = manager.status()
    else:
        result = manager.status(environment_id)
    if inspect.isawaitable(result):
        return await result
    return result


async def _call_manager_ensure(
    manager: EnvironmentCodeServerManager,
    environment_id: str,
    *,
    app_user_id: str | None = None,
    terminal_session_manager: SessionManagerLike | None = None,
) -> CodeServerState:
    result = manager.ensure(
        environment_id,
        app_user_id=app_user_id,
        terminal_session_manager=terminal_session_manager,
    )
    if inspect.isawaitable(result):
        return await result
    return result


async def _call_manager_stop(manager: EnvironmentCodeServerManager) -> CodeServerState:
    result = manager.stop()
    if inspect.isawaitable(result):
        return await result
    return result


@router.get("/status", response_model=CodeServerStatusResponse)
async def read_code_server_status(
    request: Request,
    environment_id: str | None = Query(default=None),
) -> CodeServerStatusResponse:
    manager = _get_code_server_manager(request)
    if manager is None:
        return CodeServerStatusResponse(
            status=CodeServerLifecycleStatus.UNAVAILABLE,
            environment_id=None,
            environment_alias=None,
            workspace_dir=None,
            detail="code-server supervisor not initialized",
            managed=True,
        )

    try:
        state = await _call_manager_status(manager, environment_id)
    except Exception as exc:
        raise _translate_code_server_error(exc) from exc
    return _serialize_code_server_state(state)


@router.post("/session", response_model=CodeServerStatusResponse)
async def ensure_code_server_session(
    payload: CodeServerSessionRequest,
    request: Request,
) -> CodeServerStatusResponse:
    manager = _get_code_server_manager(request)
    if manager is None:
        raise HTTPException(status_code=500, detail="code-server supervisor not initialized")

    try:
        state = await _call_manager_ensure(
            manager,
            payload.environment_id,
            app_user_id=request.headers.get("X-AINRF-User-Id"),
            terminal_session_manager=getattr(request.app.state, "terminal_session_manager", None),
        )
    except Exception as exc:
        raise _translate_code_server_error(exc) from exc
    return _serialize_code_server_state(state)


@router.delete("/session", response_model=CodeServerStatusResponse)
async def delete_code_server_session(request: Request) -> CodeServerStatusResponse:
    manager = _get_code_server_manager(request)
    if manager is None:
        return CodeServerStatusResponse(
            status=CodeServerLifecycleStatus.UNAVAILABLE,
            environment_id=None,
            environment_alias=None,
            workspace_dir=None,
            detail="code-server supervisor not initialized",
            managed=True,
        )

    state = await _call_manager_stop(manager)
    return _serialize_code_server_state(state)


def _filter_request_headers(headers: Headers) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in _HOP_BY_HOP_HEADERS and key.lower() != "x-api-key"
    }


def _filter_response_headers(headers: httpx.Headers) -> dict[str, str]:
    return {key: value for key, value in headers.items() if key.lower() not in _HOP_BY_HOP_HEADERS}


def _build_upstream_url(base_url: str, request: Request, path: str) -> str:
    base = base_url.rstrip("/")
    upstream_path = f"/{path}" if path else "/"
    split = urlsplit(str(request.url))
    return urlunsplit(("http", urlsplit(base).netloc, upstream_path, split.query, ""))


@router.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    include_in_schema=False,
)
async def proxy_code_server(request: Request, path: str) -> Response:
    manager = _get_code_server_manager(request)
    if manager is None:
        raise HTTPException(status_code=503, detail="code-server is unavailable")

    state = await _call_manager_status(manager)
    base_url = manager.base_url
    if state.status != CodeServerLifecycleStatus.READY or base_url is None:
        raise HTTPException(status_code=503, detail="code-server is unavailable")

    upstream_url = _build_upstream_url(base_url, request, path)
    request_headers = _filter_request_headers(request.headers)
    request_body = await request.body()

    try:
        async with httpx.AsyncClient() as client:
            upstream_response = await client.request(
                request.method,
                upstream_url,
                headers=request_headers,
                content=request_body,
                follow_redirects=False,
            )
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=503, detail="code-server upstream timed out") from exc
    except (httpx.RequestError, httpx.TransportError) as exc:
        raise HTTPException(status_code=502, detail="code-server upstream request failed") from exc

    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=_filter_response_headers(upstream_response.headers),
        media_type=upstream_response.headers.get("content-type"),
    )
