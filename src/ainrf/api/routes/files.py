from __future__ import annotations

import logging
import tempfile
from pathlib import Path

import mimetypes
import shlex

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse

from ainrf.api.schemas import (
    FileEntryResponse,
    FileListResponse,
    FileReadResponse,
    FileUploadResponse,
)
from ainrf.auth.permissions import check_resource_ownership, get_current_user
from ainrf.execution.ssh import SSHExecutor
from ainrf.files import FileBrowserError, FileBrowserService, FileTooLargeError, PathNotFoundError
from ainrf.files.service import _build_container_config
from ainrf.workspaces.service import WorkspaceNotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["files"])


def _get_file_browser_service(request: Request) -> FileBrowserService:
    service = getattr(request.app.state, "file_browser_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="file browser service not initialized")
    return service


def _get_workspace_service(request: Request):
    service = getattr(request.app.state, "workspace_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="workspace service not initialized")
    return service


def _check_workspace_access(request: Request, workspace_id: str | None) -> str | None:
    """Validate workspace ownership. Returns the workspace default_workdir if access is allowed.

    Returns None if no workspace_id was given (caller should use environment default).
    Raises 403 if the user does not own the workspace.
    """
    if workspace_id is None:
        return None
    user = get_current_user(request)
    ws_service = _get_workspace_service(request)
    try:
        workspace = ws_service.get_workspace(workspace_id)
    except WorkspaceNotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found") from None
    check_resource_ownership(user, workspace.owner_user_id)
    return workspace.default_workdir


def _resolve_tenant_user(request: Request) -> str | None:
    """Resolve the current user to a tenant Linux username (container-only).

    Returns None if the Linux user has not been provisioned yet.
    """
    user = get_current_user(request)
    auth_service = getattr(request.app.state, "auth_service", None)
    if auth_service is None:
        return None
    from ainrf.auth.service import (
        _is_container_environment,
        _linux_user_exists,
        tenant_linux_username,
    )

    if not _is_container_environment():
        return None
    try:
        user_record = auth_service.get_user(user["id"])
    except Exception:
        return None
    linux_user = tenant_linux_username(user_record.username)
    if not _linux_user_exists(linux_user):
        return None
    return linux_user


def _translate_file_browser_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PathNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, FileTooLargeError):
        return HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=str(exc))
    if isinstance(exc, FileBrowserError):
        return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"Unexpected file browser error: {type(exc).__name__}: {exc}",
    )


@router.get("/list", response_model=FileListResponse)
async def list_files(
    request: Request,
    environment_id: str = Query(..., description="Target environment ID"),
    path: str = Query(default="", description="Directory path relative to workspace root"),
    workspace_id: str | None = Query(
        default=None, description="Optional workspace ID to override workdir"
    ),
) -> FileListResponse:
    get_current_user(request)
    _check_workspace_access(request, workspace_id)
    service = _get_file_browser_service(request)
    try:
        listing = await service.list_directory(environment_id, path, workspace_id)
    except Exception as exc:
        raise _translate_file_browser_error(exc) from exc
    return FileListResponse(
        path=listing.path,
        entries=[
            FileEntryResponse(
                name=e.name,
                path=e.path,
                kind=e.kind,
                size=e.size,
                modified_at=e.modified_at,
            )
            for e in listing.entries
        ],
    )


@router.get("/read", response_model=FileReadResponse)
async def read_file(
    request: Request,
    environment_id: str = Query(..., description="Target environment ID"),
    path: str = Query(..., description="File path relative to workspace root"),
    workspace_id: str | None = Query(
        default=None, description="Optional workspace ID to override workdir"
    ),
) -> FileReadResponse:
    get_current_user(request)
    _check_workspace_access(request, workspace_id)
    service = _get_file_browser_service(request)
    try:
        content = await service.read_file(environment_id, path, workspace_id)
    except Exception as exc:
        raise _translate_file_browser_error(exc) from exc
    return FileReadResponse(
        path=content.path,
        content=content.content,
        is_binary=content.is_binary,
        size=content.size,
        language=content.language,
        mime_type=content.mime_type,
    )


@router.get("/stream")
async def stream_file(
    request: Request,
    environment_id: str = Query(..., description="Target environment ID"),
    path: str = Query(..., description="File path relative to workspace root"),
    workspace_id: str | None = Query(
        default=None, description="Optional workspace ID to override workdir"
    ),
):
    get_current_user(request)
    _check_workspace_access(request, workspace_id)
    service = _get_file_browser_service(request)
    try:
        is_local, resolved_path, environment = await service.resolve_stream_target(
            environment_id, path, workspace_id
        )
    except Exception as exc:
        raise _translate_file_browser_error(exc) from exc

    media_type, _ = mimetypes.guess_type(resolved_path)
    if media_type is None:
        media_type = "application/octet-stream"

    if is_local:
        return FileResponse(
            resolved_path,
            media_type=media_type,
            headers={"X-Frame-Options": "SAMEORIGIN"},
        )

    # Remote file: stream via SSH
    container_config = _build_container_config(environment)
    executor = SSHExecutor(container_config)

    # Check file size before streaming (default 100MB limit)
    MAX_REMOTE_FILE_SIZE = 100 * 1024 * 1024
    try:
        size_result = await executor.run_command(
            f"stat -c %s {shlex.quote(resolved_path)} 2>/dev/null || stat -f %z {shlex.quote(resolved_path)}",
            timeout=10,
        )
        if size_result.exit_code == 0 and size_result.stdout:
            file_size = int(size_result.stdout.strip())
            if file_size > MAX_REMOTE_FILE_SIZE:
                await executor.close()
                raise HTTPException(
                    status_code=413,
                    detail=f"File size {file_size} exceeds maximum allowed size of {MAX_REMOTE_FILE_SIZE} bytes",
                )
    except (ValueError, HTTPException):
        await executor.close()
        raise
    except Exception:
        # If size check fails, proceed with caution but still stream
        pass

    async def _stream():
        try:
            result = await executor.run_command(
                f"base64 -w0 {shlex.quote(resolved_path)}",
                timeout=60,
            )
            if result.exit_code == 0 and result.stdout:
                import base64

                yield base64.b64decode(result.stdout.strip())
        finally:
            await executor.close()

    return StreamingResponse(
        _stream(),
        media_type=media_type,
        headers={"X-Frame-Options": "SAMEORIGIN"},
    )


@router.post("/upload", response_model=FileUploadResponse)
async def upload_file(
    request: Request,
    environment_id: str = Form(...),
    path: str = Form(...),
    workspace_id: str | None = Form(default=None),
    file: UploadFile = File(...),
) -> FileUploadResponse:
    get_current_user(request)
    _check_workspace_access(request, workspace_id)
    tenant_user = _resolve_tenant_user(request)
    service = _get_file_browser_service(request)

    # Check file size limit (default 100MB)
    MAX_UPLOAD_SIZE = 100 * 1024 * 1024
    total_size = 0

    suffix = Path(path).suffix or ""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = Path(tmp.name)
            while chunk := await file.read(8192):
                total_size += len(chunk)
                if total_size > MAX_UPLOAD_SIZE:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File size exceeds maximum allowed size of {MAX_UPLOAD_SIZE} bytes",
                    )
                tmp.write(chunk)

        result = await service.upload_file(
            environment_id=environment_id,
            path=path,
            local_temp_path=tmp_path,
            workspace_id=workspace_id,
        )
        # Chown uploaded file to tenant user so agent processes can access it
        if tenant_user is not None:
            import subprocess as _sp

            _sp.run(
                ["chown", f"{tenant_user}:ainrf_tenants", result.path],
                check=False,
                capture_output=True,
            )
        return FileUploadResponse(path=result.path, size=result.size)
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate_file_browser_error(exc) from exc
    finally:
        if tmp_path:
            tmp_path.unlink(missing_ok=True)
