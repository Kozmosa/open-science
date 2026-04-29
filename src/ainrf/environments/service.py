from __future__ import annotations

from collections import defaultdict
from getpass import getuser
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from ainrf.environments.local import is_localhost_environment
from ainrf.environments.models import (
    DetectionSnapshot,
    DetectionStatus,
    EnvironmentAuthKind,
    EnvironmentRegistryEntry,
    ProjectEnvironmentReference,
    ToolStatus,
    utc_now,
)
from ainrf.environments.probing import (
    failed_missing_user_snapshot,
    failed_tmux_snapshot,
    probe_with_personal_tmux,
    probe_with_ssh,
)
from ainrf.execution.errors import SSHConnectionError
from ainrf.terminal.tmux import TmuxCommandError

if TYPE_CHECKING:
    from ainrf.terminal.sessions import SessionManager


class EnvironmentNotFoundError(LookupError):
    pass


class AliasConflictError(ValueError):
    pass


class DeleteReferencedEnvironmentError(ValueError):
    pass


class DeleteSeedEnvironmentError(ValueError):
    pass


class ProjectReferenceNotFoundError(LookupError):
    pass


class ProjectReferenceConflictError(ValueError):
    pass


def _detected_env_manager(uv: ToolStatus, pixi: ToolStatus, conda: ToolStatus) -> str | None:
    if uv.available:
        return "uv"
    if pixi.available:
        return "pixi"
    if conda.available:
        return "conda"
    return None


def _current_system_user() -> str:
    try:
        user = getuser()
    except Exception:
        return "root"
    return user or "root"


def _build_seed_environment(default_workdir: str | None = None) -> EnvironmentRegistryEntry:
    now = utc_now()
    return EnvironmentRegistryEntry(
        id="env-localhost",
        alias="localhost",
        display_name="Localhost",
        description="Seed SSH profile for the current machine.",
        is_seed=True,
        tags=["seed", "default"],
        host="127.0.0.1",
        port=22,
        user=_current_system_user(),
        auth_kind=EnvironmentAuthKind.SSH_KEY,
        ssh_options={},
        default_workdir=default_workdir,
        task_harness_profile=(
            "You are running in the default localhost task harness environment.\n"
            "Prefer repository-local tools and keep changes scoped to the requested task."
        ),
        created_at=now,
        updated_at=now,
    )


class InMemoryEnvironmentService:
    def __init__(self, default_local_workdir: str | None = None) -> None:
        self._default_local_workdir = default_local_workdir
        self._environments: dict[str, EnvironmentRegistryEntry] = {}
        self._detections: dict[str, list[DetectionSnapshot]] = defaultdict(list)
        self._project_refs: dict[str, dict[str, ProjectEnvironmentReference]] = defaultdict(dict)
        seed = _build_seed_environment(default_local_workdir)
        self._environments[seed.id] = seed

    def list_environments(self) -> list[EnvironmentRegistryEntry]:
        return list(self._environments.values())

    def get_environment(self, environment_id: str) -> EnvironmentRegistryEntry:
        try:
            return self._environments[environment_id]
        except KeyError as exc:
            raise EnvironmentNotFoundError(environment_id) from exc

    def create_environment(
        self,
        *,
        alias: str,
        display_name: str,
        host: str,
        description: str | None = None,
        tags: list[str] | None = None,
        port: int = 22,
        user: str = "root",
        auth_kind: EnvironmentAuthKind = EnvironmentAuthKind.SSH_KEY,
        identity_file: str | None = None,
        proxy_jump: str | None = None,
        proxy_command: str | None = None,
        ssh_options: dict[str, str] | None = None,
        default_workdir: str | None = None,
        preferred_python: str | None = None,
        preferred_env_manager: str | None = None,
        preferred_runtime_notes: str | None = None,
        task_harness_profile: str | None = None,
        code_server_path: str | None = None,
    ) -> EnvironmentRegistryEntry:
        self._ensure_alias_available(alias)
        now = utc_now()
        environment = EnvironmentRegistryEntry(
            id=f"env-{uuid4().hex}",
            alias=alias,
            display_name=display_name,
            description=description,
            is_seed=False,
            tags=list(tags or []),
            host=host,
            port=port,
            user=user,
            auth_kind=auth_kind,
            identity_file=identity_file,
            proxy_jump=proxy_jump,
            proxy_command=proxy_command,
            ssh_options=dict(ssh_options or {}),
            default_workdir=default_workdir,
            preferred_python=preferred_python,
            preferred_env_manager=preferred_env_manager,
            preferred_runtime_notes=preferred_runtime_notes,
            task_harness_profile=task_harness_profile,
            code_server_path=code_server_path,
            created_at=now,
            updated_at=now,
        )
        self._environments[environment.id] = environment
        return environment

    def update_environment(
        self,
        environment_id: str,
        *,
        alias: str | None = None,
        display_name: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        auth_kind: EnvironmentAuthKind | None = None,
        identity_file: str | None = None,
        proxy_jump: str | None = None,
        proxy_command: str | None = None,
        ssh_options: dict[str, str] | None = None,
        default_workdir: str | None = None,
        preferred_python: str | None = None,
        preferred_env_manager: str | None = None,
        preferred_runtime_notes: str | None = None,
        task_harness_profile: str | None = None,
        code_server_path: str | None = None,
    ) -> EnvironmentRegistryEntry:
        environment = self.get_environment(environment_id)
        if alias is not None and alias != environment.alias:
            self._ensure_alias_available(alias)
            environment.alias = alias
        if display_name is not None:
            environment.display_name = display_name
        if description is not None:
            environment.description = description
        if tags is not None:
            environment.tags = list(tags)
        if host is not None:
            environment.host = host
        if port is not None:
            environment.port = port
        if user is not None:
            environment.user = user
        if auth_kind is not None:
            environment.auth_kind = auth_kind
        if identity_file is not None:
            environment.identity_file = identity_file
        if proxy_jump is not None:
            environment.proxy_jump = proxy_jump
        if proxy_command is not None:
            environment.proxy_command = proxy_command
        if ssh_options is not None:
            environment.ssh_options = dict(ssh_options)
        if default_workdir is not None:
            environment.default_workdir = default_workdir
        if preferred_python is not None:
            environment.preferred_python = preferred_python
        if preferred_env_manager is not None:
            environment.preferred_env_manager = preferred_env_manager
        if preferred_runtime_notes is not None:
            environment.preferred_runtime_notes = preferred_runtime_notes
        if task_harness_profile is not None:
            environment.task_harness_profile = task_harness_profile
        if code_server_path is not None:
            environment.code_server_path = code_server_path
        environment.updated_at = utc_now()
        return environment

    def delete_environment(self, environment_id: str) -> None:
        environment = self.get_environment(environment_id)
        if environment.is_seed:
            raise DeleteSeedEnvironmentError(environment_id)
        refs = self.list_environment_references(environment.id)
        if refs:
            raise DeleteReferencedEnvironmentError(environment_id)
        del self._environments[environment.id]
        self._detections.pop(environment.id, None)

    async def detect_environment(
        self,
        environment_id: str,
        *,
        app_user_id: str | None = None,
        terminal_session_manager: SessionManager | None = None,
    ) -> DetectionSnapshot:
        environment = self.get_environment(environment_id)
        if is_localhost_environment(environment):
            if app_user_id is None or terminal_session_manager is None:
                snapshot = failed_missing_user_snapshot(environment)
            else:
                try:
                    outcome = await probe_with_personal_tmux(
                        environment=environment,
                        app_user_id=app_user_id,
                        session_manager=terminal_session_manager,
                    )
                    snapshot = outcome.snapshot
                except (RuntimeError, TmuxCommandError) as exc:
                    snapshot = failed_tmux_snapshot(environment, exc)
            self._detections[environment.id].append(snapshot)
            self._write_back_detected_runtime_config(environment, snapshot)
            return snapshot

        try:
            outcome = await probe_with_ssh(environment)
            snapshot = outcome.snapshot
        except SSHConnectionError:
            if app_user_id is None or terminal_session_manager is None:
                snapshot = failed_missing_user_snapshot(environment)
            else:
                try:
                    outcome = await probe_with_personal_tmux(
                        environment=environment,
                        app_user_id=app_user_id,
                        session_manager=terminal_session_manager,
                    )
                    snapshot = outcome.snapshot
                except (RuntimeError, TmuxCommandError) as exc:
                    snapshot = failed_tmux_snapshot(environment, exc)
        self._detections[environment.id].append(snapshot)
        self._write_back_detected_runtime_config(environment, snapshot)
        return snapshot

    def get_latest_detection(self, environment_id: str) -> DetectionSnapshot | None:
        self.get_environment(environment_id)
        snapshots = self._detections.get(environment_id)
        if not snapshots:
            return None
        return snapshots[-1]

    def create_project_reference(
        self,
        *,
        project_id: str,
        environment_id: str,
        is_default: bool = False,
        override_workdir: str | None = None,
        override_env_name: str | None = None,
        override_env_manager: str | None = None,
        override_runtime_notes: str | None = None,
    ) -> ProjectEnvironmentReference:
        if environment_id in self._project_refs[project_id]:
            raise ProjectReferenceConflictError(environment_id)
        return self.upsert_project_reference(
            project_id=project_id,
            environment_id=environment_id,
            is_default=is_default,
            override_workdir=override_workdir,
            override_env_name=override_env_name,
            override_env_manager=override_env_manager,
            override_runtime_notes=override_runtime_notes,
        )

    def upsert_project_reference(
        self,
        *,
        project_id: str,
        environment_id: str,
        is_default: bool = False,
        override_workdir: str | None = None,
        override_env_name: str | None = None,
        override_env_manager: str | None = None,
        override_runtime_notes: str | None = None,
    ) -> ProjectEnvironmentReference:
        self.get_environment(environment_id)
        if is_default:
            for ref in self._project_refs[project_id].values():
                ref.is_default = False
        reference = ProjectEnvironmentReference(
            project_id=project_id,
            environment_id=environment_id,
            is_default=is_default,
            override_workdir=override_workdir,
            override_env_name=override_env_name,
            override_env_manager=override_env_manager,
            override_runtime_notes=override_runtime_notes,
            updated_at=utc_now(),
        )
        self._project_refs[project_id][environment_id] = reference
        return reference

    def get_project_reference(
        self,
        project_id: str,
        environment_id: str,
    ) -> ProjectEnvironmentReference:
        try:
            return self._project_refs[project_id][environment_id]
        except KeyError as exc:
            raise ProjectReferenceNotFoundError(environment_id) from exc

    def list_project_references(self, project_id: str) -> list[ProjectEnvironmentReference]:
        return list(self._project_refs[project_id].values())

    def list_environment_references(self, environment_id: str) -> list[ProjectEnvironmentReference]:
        refs: list[ProjectEnvironmentReference] = []
        for project_refs in self._project_refs.values():
            reference = project_refs.get(environment_id)
            if reference is not None:
                refs.append(reference)
        return refs

    def delete_project_reference(self, project_id: str, environment_id: str) -> None:
        self.get_project_reference(project_id, environment_id)
        del self._project_refs[project_id][environment_id]

    def resolve_effective_workdir(
        self,
        project_id: str,
        environment_id: str,
        fallback_root: Path,
    ) -> str:
        reference = self._project_refs.get(project_id, {}).get(environment_id)
        if reference is not None and reference.override_workdir:
            return reference.override_workdir
        environment = self.get_environment(environment_id)
        if environment.default_workdir:
            return environment.default_workdir
        if is_localhost_environment(environment) and self._default_local_workdir is not None:
            return self._default_local_workdir
        return str(fallback_root)

    def _write_back_detected_runtime_config(
        self,
        environment: EnvironmentRegistryEntry,
        snapshot: DetectionSnapshot,
    ) -> None:
        if snapshot.status is not DetectionStatus.SUCCESS:
            return

        updated = False
        if environment.preferred_python is None and snapshot.python.available:
            environment.preferred_python = snapshot.python.path or "python3"
            updated = True

        if environment.preferred_env_manager is None:
            env_manager = _detected_env_manager(snapshot.uv, snapshot.pixi, snapshot.conda)
            if env_manager is not None:
                environment.preferred_env_manager = env_manager
                updated = True

        if snapshot.code_server.available and snapshot.code_server.path is not None:
            if (
                not environment.code_server_path
                or environment.code_server_path != snapshot.code_server.path
            ):
                environment.code_server_path = snapshot.code_server.path
                updated = True

        if updated:
            environment.updated_at = utc_now()

    def _ensure_alias_available(self, alias: str) -> None:
        for environment in self._environments.values():
            if environment.alias == alias:
                raise AliasConflictError(alias)
