from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from threading import Lock

from ainrf.environments.models import utc_now
from ainrf.workspaces.models import WorkspaceRecord


class WorkspaceNotFoundError(LookupError):
    pass


class WorkspaceRegistryService:
    def __init__(self, state_root: Path) -> None:
        self._state_root = state_root
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

    def _build_seed_workspace(self) -> WorkspaceRecord:
        now = utc_now()
        # The seed workspace intentionally binds new state roots to the process checkout.
        default_workdir = str(Path.cwd())
        return WorkspaceRecord(
            workspace_id="workspace-default",
            label="Repository Default",
            description="Seed workspace bound to the current repository checkout.",
            default_workdir=default_workdir,
            workspace_prompt=(
                "Treat this workspace as the default repository context for the task.\n"
                f"Repository root: {default_workdir}"
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
