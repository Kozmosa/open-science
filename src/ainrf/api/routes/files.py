from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile, status

from ainrf.api.schemas import (
    FileEntryResponse,
    FileListResponse,
    FileReadResponse,
    FileUploadResponse,
)
from ainrf.files import FileBrowserError, FileBrowserService, FileTooLargeError, PathNotFoundError

router = APIRouter(prefix="/files", tags=["files"])


def _get_file_browser_service(request: Request) -> FileBrowserService:
    service = getattr(request.app.state, "file_browser_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="file browser service not initialized")
    return service


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
    workspace_id: str | None = Query(default=None, description="Optional workspace ID to override workdir"),
) -> FileListResponse:
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
    workspace_id: str | None = Query(default=None, description="Optional workspace ID to override workdir"),
) -> FileReadResponse:
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


@router.post("/upload", response_model=FileUploadResponse)
async def upload_file(
    request: Request,
    environment_id: str = Form(...),
    path: str = Form(...),
    workspace_id: str | None = Form(default=None),
    file: UploadFile = File(...),
) -> FileUploadResponse:
    service = _get_file_browser_service(request)
    suffix = Path(path).suffix or ""
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_path = Path(tmp.name)
        while chunk := await file.read(8192):
            tmp.write(chunk)
    try:
        result = await service.upload_file(
            environment_id=environment_id,
            path=path,
            local_temp_path=tmp_path,
            workspace_id=workspace_id,
        )
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        raise _translate_file_browser_error(exc) from exc
    tmp_path.unlink(missing_ok=True)
    return FileUploadResponse(path=result.path, size=result.size)
