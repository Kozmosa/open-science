from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from threading import Lock

from ainrf.environments.models import utc_now
from ainrf.projects.models import ProjectRecord, TaskEdgeRecord


class ProjectNotFoundError(LookupError):
    pass


class TaskEdgeNotFoundError(LookupError):
    pass


class ProjectRegistryService:
    def __init__(self, state_root: Path) -> None:
        self._state_root = state_root
        self._runtime_root = state_root / "runtime"
        self._registry_path = self._runtime_root / "projects.json"
        self._task_edges_path = self._runtime_root / "task_edges.json"
        self._lock = Lock()
        self._projects: dict[str, ProjectRecord] = {}
        self._task_edges: dict[str, TaskEdgeRecord] = {}
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
                self._projects = {
                    item["project_id"]: ProjectRecord(
                        project_id=item["project_id"],
                        name=item["name"],
                        description=item.get("description"),
                        default_workspace_id=item.get("default_workspace_id"),
                        default_environment_id=item.get("default_environment_id"),
                        created_at=datetime.fromisoformat(item["created_at"]),
                        updated_at=datetime.fromisoformat(item["updated_at"]),
                        owner_user_id=item.get("owner_user_id"),
                    )
                    for item in payload.get("items", [])
                }
            if self._task_edges_path.exists():
                edge_payload = json.loads(self._task_edges_path.read_text(encoding="utf-8"))
                self._task_edges = {
                    item["edge_id"]: TaskEdgeRecord(
                        edge_id=item["edge_id"],
                        project_id=item["project_id"],
                        source_task_id=item["source_task_id"],
                        target_task_id=item["target_task_id"],
                        created_at=datetime.fromisoformat(item["created_at"]),
                    )
                    for item in edge_payload.get("items", [])
                }
            if not self._projects:
                seed = self._build_seed_project()
                self._projects[seed.project_id] = seed
                self._persist()
            self._initialized = True

    def list_projects(
        self,
        *,
        owner_user_id: str | None = None,
        collaborator_project_ids: list[str] | None = None,
    ) -> list[ProjectRecord]:
        self.initialize()
        projects = list(self._projects.values())
        if owner_user_id is not None or collaborator_project_ids:
            collaborator_ids = set(collaborator_project_ids or [])
            projects = [
                p
                for p in projects
                if p.owner_user_id == owner_user_id or p.project_id in collaborator_ids
            ]
        return projects

    def get_project(self, project_id: str) -> ProjectRecord:
        self.initialize()
        try:
            return self._projects[project_id]
        except KeyError as exc:
            raise ProjectNotFoundError(project_id) from exc

    def create_project(
        self,
        *,
        name: str,
        description: str | None,
        owner_user_id: str | None = None,
    ) -> ProjectRecord:
        self.initialize()
        with self._lock:
            now = utc_now()
            project_id = f"project-{uuid.uuid4().hex[:12]}"
            project = ProjectRecord(
                project_id=project_id,
                name=name,
                description=description,
                default_workspace_id=None,
                default_environment_id=None,
                created_at=now,
                updated_at=now,
                owner_user_id=owner_user_id,
            )
            self._projects[project_id] = project
            self._persist()
            return project

    def update_project(
        self,
        project_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        default_workspace_id: str | None = None,
        default_environment_id: str | None = None,
    ) -> ProjectRecord:
        self.initialize()
        with self._lock:
            current = self.get_project(project_id)
            project = ProjectRecord(
                project_id=current.project_id,
                name=current.name if name is None else name,
                description=description if description is not None else current.description,
                default_workspace_id=default_workspace_id
                if default_workspace_id is not None
                else current.default_workspace_id,
                default_environment_id=default_environment_id
                if default_environment_id is not None
                else current.default_environment_id,
                created_at=current.created_at,
                updated_at=utc_now(),
                owner_user_id=current.owner_user_id,
            )
            self._projects[project_id] = project
            self._persist()
            return project

    def delete_project(self, project_id: str) -> None:
        self.initialize()
        with self._lock:
            self.get_project(project_id)
            if project_id == "default":
                raise ValueError("Default project cannot be deleted")
            if len(self._projects) == 1:
                raise ValueError("Last project cannot be deleted")
            del self._projects[project_id]
            self._persist()
            self._task_edges = {
                edge_id: edge
                for edge_id, edge in self._task_edges.items()
                if edge.project_id != project_id
            }
            self._persist_task_edges()

    def list_task_edges(self, project_id: str) -> list[TaskEdgeRecord]:
        self.initialize()
        self.get_project(project_id)
        return [
            edge
            for edge in self._task_edges.values()
            if edge.project_id == project_id
        ]

    def create_task_edge(
        self,
        project_id: str,
        *,
        source_task_id: str,
        target_task_id: str,
    ) -> TaskEdgeRecord:
        self.initialize()
        self.get_project(project_id)
        with self._lock:
            for edge in self._task_edges.values():
                if (
                    edge.project_id == project_id
                    and edge.source_task_id == source_task_id
                    and edge.target_task_id == target_task_id
                ):
                    return edge
            edge = TaskEdgeRecord(
                edge_id=f"edge-{uuid.uuid4().hex[:12]}",
                project_id=project_id,
                source_task_id=source_task_id,
                target_task_id=target_task_id,
                created_at=utc_now(),
            )
            self._task_edges[edge.edge_id] = edge
            self._persist_task_edges()
            return edge

    def delete_task_edge(self, edge_id: str) -> None:
        self.initialize()
        with self._lock:
            if edge_id not in self._task_edges:
                raise TaskEdgeNotFoundError(edge_id)
            del self._task_edges[edge_id]
            self._persist_task_edges()

    def _build_seed_project(self) -> ProjectRecord:
        now = utc_now()
        return ProjectRecord(
            project_id="default",
            name="Default Project",
            description="Default project for existing workspaces and tasks.",
            default_workspace_id=None,
            default_environment_id=None,
            created_at=now,
            updated_at=now,
        )

    def _persist(self) -> None:
        payload = {
            "items": [
                {
                    **asdict(project),
                    "created_at": project.created_at.isoformat(),
                    "updated_at": project.updated_at.isoformat(),
                }
                for project in self._projects.values()
            ]
        }
        self._registry_path.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )

    def _persist_task_edges(self) -> None:
        payload = {
            "items": [
                {
                    **asdict(edge),
                    "created_at": edge.created_at.isoformat(),
                }
                for edge in self._task_edges.values()
            ]
        }
        self._task_edges_path.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )