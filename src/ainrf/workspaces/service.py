from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from threading import Lock

from ainrf.environments.models import utc_now
from ainrf.workspaces.models import WorkspaceRecord


class WorkspaceNotFoundError(LookupError):
    pass


class WorkspaceDeletionError(ValueError):
    pass


class WorkspaceRegistryService:
    def __init__(self, state_root: Path, default_workspace_dir: Path | None = None) -> None:
        self._state_root = state_root
        self._default_workspace_dir = default_workspace_dir
        self._runtime_root = state_root / "runtime"
        self._registry_path = self._runtime_root / "workspaces.json"
        self._lock = Lock()
        self._workspaces: dict[str, WorkspaceRecord] = {}
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            self._runtime_root.mkdir(parents=True, exist_ok=True)
            if self._registry_path.exists():
                payload = json.loads(self._registry_path.read_text(encoding="utf-8"))
                self._workspaces = {
                    item["workspace_id"]: WorkspaceRecord(
                        workspace_id=item["workspace_id"],
                        label=item["label"],
                        description=item["description"],
                        default_workdir=item["default_workdir"],
                        workspace_prompt=item["workspace_prompt"],
                        created_at=datetime.fromisoformat(item["created_at"]),
                        updated_at=datetime.fromisoformat(item["updated_at"]),
                    )
                    for item in payload.get("items", [])
                }
            if not self._workspaces:
                seed = self._build_seed_workspace()
                self._workspaces[seed.workspace_id] = seed
                self._persist()
            self._initialized = True

    def list_workspaces(self) -> list[WorkspaceRecord]:
        self.initialize()
        return list(self._workspaces.values())

    def get_workspace(self, workspace_id: str) -> WorkspaceRecord:
        self.initialize()
        try:
            return self._workspaces[workspace_id]
        except KeyError as exc:
            raise WorkspaceNotFoundError(workspace_id) from exc

    def create_workspace(
        self,
        *,
        label: str,
        description: str | None,
        default_workdir: str | None,
        workspace_prompt: str,
    ) -> WorkspaceRecord:
        self.initialize()
        with self._lock:
            now = utc_now()
            workspace_id = f"workspace-{uuid.uuid4().hex[:12]}"
            workspace = WorkspaceRecord(
                workspace_id=workspace_id,
                label=label,
                description=description,
                default_workdir=default_workdir,
                workspace_prompt=workspace_prompt,
                created_at=now,
                updated_at=now,
            )
            self._workspaces[workspace_id] = workspace
            self._persist()
            return workspace

    def update_workspace(
        self,
        workspace_id: str,
        *,
        label: str | None = None,
        description: str | None = None,
        default_workdir: str | None = None,
        workspace_prompt: str | None = None,
    ) -> WorkspaceRecord:
        self.initialize()
        with self._lock:
            current = self.get_workspace(workspace_id)
            workspace = WorkspaceRecord(
                workspace_id=current.workspace_id,
                label=current.label if label is None else label,
                description=description,
                default_workdir=default_workdir,
                workspace_prompt=(
                    current.workspace_prompt if workspace_prompt is None else workspace_prompt
                ),
                created_at=current.created_at,
                updated_at=utc_now(),
            )
            self._workspaces[workspace_id] = workspace
            self._persist()
            return workspace

    def delete_workspace(self, workspace_id: str) -> None:
        self.initialize()
        with self._lock:
            self.get_workspace(workspace_id)
            if workspace_id == "workspace-default":
                raise WorkspaceDeletionError("Default workspace cannot be deleted")
            if len(self._workspaces) == 1:
                raise WorkspaceDeletionError("Last workspace cannot be deleted")
            del self._workspaces[workspace_id]
            self._persist()

    def _build_seed_workspace(self) -> WorkspaceRecord:
        now = utc_now()
        default_workdir_path = self._default_workspace_dir or Path.cwd() / "workspace" / "default"
        default_workdir_path.mkdir(parents=True, exist_ok=True)
        default_workdir = str(default_workdir_path)
        return WorkspaceRecord(
            workspace_id="workspace-default",
            label="Repository Default",
            description="Seed workspace bound to the default local workspace directory.",
            default_workdir=default_workdir,
            workspace_prompt=(
                "Treat this workspace as the default local workspace context for the task.\n"
                f"Workspace directory: {default_workdir}"
            ),
            created_at=now,
            updated_at=now,
        )

    def _persist(self) -> None:
        payload = {
            "items": [
                {
                    **asdict(workspace),
                    "created_at": workspace.created_at.isoformat(),
                    "updated_at": workspace.updated_at.isoformat(),
                }
                for workspace in self._workspaces.values()
            ]
        }
        self._registry_path.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )
