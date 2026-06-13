from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from threading import Lock

from ainrf.db.connection import atomic_write_json
from ainrf.environments.models import utc_now
from ainrf.runtime.paths import RuntimePathConfig
from ainrf.workspaces.models import WorkspaceRecord


class WorkspaceNotFoundError(LookupError):
    pass


class WorkspaceDeletionError(ValueError):
    pass


class WorkspaceDirectoryError(ValueError):
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
                        project_id=item.get("project_id", "default"),
                        label=item["label"],
                        description=item["description"],
                        default_workdir=item["default_workdir"],
                        workspace_prompt=item["workspace_prompt"],
                        created_at=datetime.fromisoformat(item["created_at"]),
                        updated_at=datetime.fromisoformat(item["updated_at"]),
                        owner_user_id=item.get("owner_user_id"),
                    )
                    for item in payload.get("items", [])
                }
                # Migration: persist if any workspace was missing project_id
                if any("project_id" not in item for item in payload.get("items", [])):
                    self._persist()
            if not self._workspaces:
                seed = self._build_seed_workspace()
                self._workspaces[seed.workspace_id] = seed
                self._persist()
            self._initialized = True

    def list_workspaces(
        self,
        project_id: str | None = None,
        owner_user_id: str | None = None,
    ) -> list[WorkspaceRecord]:
        self.initialize()
        workspaces = list(self._workspaces.values())
        if project_id is not None:
            workspaces = [w for w in workspaces if w.project_id == project_id]
        if owner_user_id is not None:
            workspaces = [w for w in workspaces if w.owner_user_id == owner_user_id]
        return workspaces

    def get_workspace(self, workspace_id: str) -> WorkspaceRecord:
        self.initialize()
        try:
            return self._workspaces[workspace_id]
        except KeyError as exc:
            raise WorkspaceNotFoundError(workspace_id) from exc

    def create_workspace(
        self,
        *,
        project_id: str = "default",
        label: str,
        description: str | None,
        default_workdir: str | None,
        workspace_prompt: str,
        owner_user_id: str | None = None,
    ) -> WorkspaceRecord:
        self.initialize()
        with self._lock:
            now = utc_now()
            workspace_id = f"workspace-{uuid.uuid4().hex[:12]}"
            if default_workdir:
                workdir_path = Path(default_workdir).expanduser().resolve()
                default_workdir = str(workdir_path)
                try:
                    workdir_path.mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    raise WorkspaceDirectoryError(
                        f"Failed to create workspace directory {default_workdir}: {exc}"
                    ) from exc
            workspace = WorkspaceRecord(
                workspace_id=workspace_id,
                project_id=project_id,
                label=label,
                description=description,
                default_workdir=default_workdir,
                workspace_prompt=workspace_prompt,
                created_at=now,
                updated_at=now,
                owner_user_id=owner_user_id,
            )
            self._workspaces[workspace_id] = workspace
            self._persist()
            return workspace

    def update_workspace(
        self,
        workspace_id: str,
        *,
        project_id: str | None = None,
        label: str | None = None,
        description: str | None = None,
        default_workdir: str | None = None,
        workspace_prompt: str | None = None,
    ) -> WorkspaceRecord:
        self.initialize()
        with self._lock:
            current = self.get_workspace(workspace_id)
            if default_workdir:
                default_workdir = str(Path(default_workdir).expanduser().resolve())
            workspace = WorkspaceRecord(
                workspace_id=current.workspace_id,
                project_id=current.project_id if project_id is None else project_id,
                label=current.label if label is None else label,
                description=description,
                default_workdir=default_workdir,
                workspace_prompt=(
                    current.workspace_prompt if workspace_prompt is None else workspace_prompt
                ),
                created_at=current.created_at,
                updated_at=utc_now(),
                owner_user_id=current.owner_user_id,
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


    def ensure_tenant_workspace(
        self,
        *,
        username: str,
        label: str = "default",
    ) -> WorkspaceRecord:
        """Return the workspace for a tenant user, creating it if needed.

        The default_workdir is set to ``/home/ainrf_tenants/<username>/workspaces/<label>/``.
        """
        self.initialize()
        existing = [
            ws
            for ws in self._workspaces.values()
            if ws.owner_user_id == username and ws.label == label
        ]
        if existing:
            return existing[0]
        rpc = RuntimePathConfig(startup_cwd=Path.cwd())
        default_workdir = rpc.tenant_workspace_dir(username, label)
        # Create workspace dir via sudo -u <tenant> so the directory is
        # owned by the tenant user (ainrf cannot write to tenant homes).
        linux_user = f"ainrf_{username}"
        if not default_workdir.exists():
            import subprocess
            subprocess.run(
                ["sudo", "-u", linux_user, "mkdir", "-p", str(default_workdir)],
                check=False, capture_output=True,
            )
        return self.create_workspace(
            label=label,
            description=f"Default workspace for tenant {username}",
            default_workdir=str(default_workdir),
            workspace_prompt=(
                "Treat this workspace as the default local workspace context for the task.\n"
                f"Workspace directory: {default_workdir}"
            ),
            owner_user_id=username,
        )

    def _build_seed_workspace(self) -> WorkspaceRecord:
        now = utc_now()
        default_workdir_path = self._default_workspace_dir or Path.cwd() / "workspace" / "default"
        default_workdir_path.mkdir(parents=True, exist_ok=True)
        default_workdir = str(default_workdir_path)
        return WorkspaceRecord(
            workspace_id="workspace-default",
            project_id="default",
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
        atomic_write_json(self._registry_path, payload)
