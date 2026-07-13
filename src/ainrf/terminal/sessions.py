from __future__ import annotations

import pwd
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from getpass import getuser
from pathlib import Path
from uuid import uuid4

from ainrf.auth.service import AuthService
from ainrf.environments import EnvironmentNotFoundError
from ainrf.environments.models import EnvironmentRegistryEntry
from ainrf.environments.protocols import EnvironmentRuntimeReader
from ainrf.terminal.models import (
    TerminalAttachmentTarget,
    TerminalMuxKind,
    TerminalSessionRecord,
    TerminalSessionStatus,
    UserEnvironmentBinding,
    UserSessionPair,
    utc_now,
)
from ainrf.terminal.pty import TERMINAL_IDLE_TARGET_KIND, TERMINAL_PROVIDER
from ainrf.terminal.tmux import TmuxAdapter, TmuxCommandError


class TerminalSessionOperationError(RuntimeError):
    pass


MaintenanceCheck = Callable[[], None]
PersonalSessionCleanup = Callable[[], None]
PersonalSessionCreated = Callable[[PersonalSessionCleanup], None]


def _check_maintenance(check: MaintenanceCheck | None) -> None:
    if check is not None:
        check()


def current_daemon_user() -> str:
    try:
        resolved = getuser()
    except Exception:
        return "root"
    return resolved or "root"


def _tenant_home_directory(username: str) -> Path | None:
    """Resolve the Linux home directory for a tenant user."""
    try:
        return Path(pwd.getpwnam(username).pw_dir)
    except KeyError:
        return None


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


@dataclass(frozen=True, slots=True)
class _SessionLifecycleKey:
    app_user_id: str
    environment_id: str
    kind: str


@dataclass(slots=True)
class _SessionLifecycleLockState:
    lock: threading.Lock
    holders: int = 0


class SessionManager:
    def __init__(
        self,
        *,
        state_root: Path,
        environment_service: EnvironmentRuntimeReader,
        tmux_adapter: TmuxAdapter,
        default_shell: str | None,
        user_id: str | None = None,
        auth_service: AuthService | None = None,
    ) -> None:
        self._state_root = state_root
        self._environment_service = environment_service
        self._runtime_root = state_root / "runtime"
        self._db_path = self._runtime_root / "terminal_state.sqlite3"
        self._tmux_adapter = tmux_adapter
        self._default_shell = default_shell
        self._legacy_user_id = user_id or current_daemon_user()
        self._auth_service = auth_service
        self._initialized = False
        self._session_lifecycle_locks: dict[_SessionLifecycleKey, _SessionLifecycleLockState] = {}
        self._session_lifecycle_lock_guard = threading.Lock()

    def _resolve_tenant_user(self, app_user_id: str) -> str | None:
        """Resolve app_user_id to a Linux tenant username.

        Returns None if the Linux user has not been provisioned yet.
        """
        if self._auth_service is None:
            return None
        try:
            user = self._auth_service.get_user(app_user_id)
        except Exception:
            return None
        from ainrf.auth.service import (
            _is_container_environment,
            _linux_user_exists,
            tenant_linux_username,
        )

        if not _is_container_environment():
            return None
        linux_user = tenant_linux_username(user.username)
        if not _linux_user_exists(linux_user):
            return None
        return linux_user

    def _resolve_spawn_directory(self, app_user_id: str) -> Path:
        """Resolve the working directory for spawning a terminal bridge.

        When a tenant user exists, use their home directory.
        Otherwise fall back to the state root.
        """
        tenant_user = self._resolve_tenant_user(app_user_id)
        if tenant_user is not None:
            home = _tenant_home_directory(tenant_user)
            if home is not None:
                return home
        return self._state_root

    @contextmanager
    def _as_tenant(self, app_user_id: str) -> Iterator[None]:
        """Context manager: set tmux adapter run_as_user for the duration."""
        tenant = self._resolve_tenant_user(app_user_id)
        prev = self._tmux_adapter.run_as_user
        try:
            self._tmux_adapter.run_as_user = tenant
            yield
        finally:
            self._tmux_adapter.run_as_user = prev

    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def user_id(self) -> str:
        return self._legacy_user_id

    @property
    def legacy_user_id(self) -> str:
        return self._legacy_user_id

    @property
    def tmux_adapter(self) -> TmuxAdapter:
        return self._tmux_adapter

    @contextmanager
    def _as_tenant(self, app_user_id: str) -> Iterator[None]:
        """Context manager: set tmux adapter run_as_user for the duration."""
        tenant = self._resolve_tenant_user(app_user_id)
        adapter = self._tmux_adapter
        prev = getattr(adapter, "run_as_user", None)
        try:
            if hasattr(adapter, "run_as_user"):
                adapter.run_as_user = tenant
            yield
        finally:
            if hasattr(adapter, "run_as_user"):
                adapter.run_as_user = prev

    def initialize(self) -> None:
        if self._initialized:
            return
        self._runtime_root.mkdir(parents=True, exist_ok=True)
        from ainrf.db.migration import run_pending

        with self._connect() as conn:
            run_pending(conn, "terminal")
        self._initialized = True

    def session_name_for(self, app_user_id: str, environment_id: str | None = None) -> str:
        if environment_id is None:
            environment_id = app_user_id
            app_user_id = self._legacy_user_id
        return self._tmux_adapter.session_name_for(app_user_id, environment_id, kind="personal")

    def agent_session_name_for(self, app_user_id: str, environment_id: str | None = None) -> str:
        if environment_id is None:
            environment_id = app_user_id
            app_user_id = self._legacy_user_id
        return self._tmux_adapter.session_name_for(app_user_id, environment_id, kind="agent")

    def get_session_record(
        self,
        app_user_id: str | EnvironmentRegistryEntry | None,
        environment: EnvironmentRegistryEntry | str | None = None,
        working_directory: str | None = None,
        *,
        maintenance_check: MaintenanceCheck | None = None,
    ) -> TerminalSessionRecord:
        _check_maintenance(maintenance_check)
        self.initialize()
        _check_maintenance(maintenance_check)
        if isinstance(app_user_id, EnvironmentRegistryEntry):
            working_directory = environment if isinstance(environment, str) else None
            environment = app_user_id
            app_user_id = self._legacy_user_id
        elif app_user_id is None:
            app_user_id = self._legacy_user_id
        assert environment is None or isinstance(environment, EnvironmentRegistryEntry)
        if environment is None:
            return TerminalSessionRecord(
                session_id=None,
                provider=TERMINAL_PROVIDER,
                target_kind=TERMINAL_IDLE_TARGET_KIND,
                status=TerminalSessionStatus.IDLE,
            )

        binding = self._load_binding(app_user_id, environment.id)
        predicted_session_name = self.session_name_for(app_user_id, environment.id)
        if binding is None:
            return self._build_record(
                environment=environment,
                working_directory=working_directory,
                binding=None,
                pair=None,
                session_name=predicted_session_name,
            )

        pair = self._load_pair(binding.binding_id)
        if pair is None:
            return self._build_record(
                environment=environment,
                working_directory=working_directory,
                binding=binding,
                pair=None,
                session_name=predicted_session_name,
            )

        refreshed_pair = self._refresh_pair(
            binding,
            environment,
            pair,
            maintenance_check=maintenance_check,
        )
        return self._build_record(
            environment=environment,
            working_directory=working_directory,
            binding=binding,
            pair=refreshed_pair,
            session_name=refreshed_pair.personal_session_name,
        )

    def ensure_personal_session(
        self,
        app_user_id: str | EnvironmentRegistryEntry,
        environment: EnvironmentRegistryEntry | str | None = None,
        working_directory: str | None = None,
        *,
        maintenance_check: MaintenanceCheck | None = None,
        on_personal_session_created: PersonalSessionCreated | None = None,
    ) -> tuple[TerminalSessionRecord, TerminalAttachmentTarget]:
        _check_maintenance(maintenance_check)
        self.initialize()
        _check_maintenance(maintenance_check)
        if isinstance(app_user_id, EnvironmentRegistryEntry):
            working_directory = environment if isinstance(environment, str) else None
            environment = app_user_id
            app_user_id = self._legacy_user_id
        assert isinstance(environment, EnvironmentRegistryEntry)
        with (
            self._as_tenant(app_user_id),
            self._session_lifecycle_guard(app_user_id, environment.id, kind="personal"),
        ):
            _check_maintenance(maintenance_check)
            binding = self._upsert_binding(app_user_id, environment, working_directory)
            _check_maintenance(maintenance_check)
            pair = self._upsert_pair(app_user_id, binding, environment.id)
            _check_maintenance(maintenance_check)
            cleanup: PersonalSessionCleanup | None = None
            try:
                created = bool(
                    self._tmux_adapter.ensure_personal_session(
                        binding,
                        environment,
                        pair.personal_session_name,
                    )
                )
                if created:
                    cleanup_completed = False

                    def cleanup() -> None:
                        nonlocal cleanup_completed
                        if cleanup_completed:
                            return
                        cleanup_completed = True
                        self._cleanup_new_personal_session(
                            binding,
                            environment,
                            pair.personal_session_name,
                        )

                    if on_personal_session_created is not None:
                        on_personal_session_created(cleanup)
                _check_maintenance(maintenance_check)
            except TmuxCommandError as exc:
                _check_maintenance(maintenance_check)
                failure_time = utc_now()
                self._store_pair(
                    replace(
                        pair,
                        personal_status=TerminalSessionStatus.FAILED,
                        personal_closed_at=failure_time,
                        last_verified_at=failure_time,
                        detail=str(exc),
                    )
                )
                _check_maintenance(maintenance_check)
                raise TerminalSessionOperationError(str(exc)) from exc
            except Exception:
                if cleanup is not None:
                    cleanup()
                raise

            success_time = utc_now()
            try:
                _check_maintenance(maintenance_check)
                running_pair = self._store_pair(
                    replace(
                        pair,
                        personal_status=TerminalSessionStatus.RUNNING,
                        personal_started_at=pair.personal_started_at or success_time,
                        personal_closed_at=None,
                        last_verified_at=success_time,
                        updated_at=success_time,
                        detail=None,
                    )
                )
                _check_maintenance(maintenance_check)
            except Exception:
                if cleanup is not None:
                    cleanup()
                raise
            record = self._build_record(
                environment=environment,
                working_directory=working_directory,
                binding=binding,
                pair=running_pair,
                session_name=running_pair.personal_session_name,
            )
            target = TerminalAttachmentTarget(
                binding_id=binding.binding_id,
                session_id=record.session_id or running_pair.personal_session_name,
                session_name=running_pair.personal_session_name,
                user_id=binding.user_id,
                environment_id=environment.id,
                environment_alias=environment.alias,
                target_kind=record.target_kind,
                working_directory=working_directory,
                attach_command=self._tmux_adapter.build_attach_command(
                    binding,
                    environment,
                    running_pair.personal_session_name,
                ),
                spawn_working_directory=self._resolve_spawn_directory(app_user_id),
                tenant_user=self._resolve_tenant_user(app_user_id),
            )
            return record, target

    def ensure_agent_session(
        self,
        app_user_id: str | EnvironmentRegistryEntry,
        environment: EnvironmentRegistryEntry | str | None = None,
        working_directory: str | None = None,
    ) -> tuple[UserEnvironmentBinding, UserSessionPair]:
        self.initialize()
        if isinstance(app_user_id, EnvironmentRegistryEntry):
            working_directory = environment if isinstance(environment, str) else None
            environment = app_user_id
            app_user_id = self._legacy_user_id
        assert isinstance(environment, EnvironmentRegistryEntry)
        with (
            self._as_tenant(app_user_id),
            self._session_lifecycle_guard(app_user_id, environment.id, kind="agent"),
        ):
            binding = self._upsert_binding(app_user_id, environment, working_directory)
            pair = self._upsert_pair(app_user_id, binding, environment.id)
            agent_session_name = pair.agent_session_name or self.agent_session_name_for(
                app_user_id,
                environment.id,
            )
            try:
                self._tmux_adapter.ensure_agent_session(
                    binding,
                    environment,
                    agent_session_name,
                )
            except TmuxCommandError as exc:
                failure_time = utc_now()
                self._store_pair(
                    replace(
                        pair,
                        agent_session_name=agent_session_name,
                        agent_status=TerminalSessionStatus.FAILED,
                        last_verified_at=failure_time,
                        updated_at=failure_time,
                        detail=str(exc),
                    )
                )
                raise TerminalSessionOperationError(str(exc)) from exc

            success_time = utc_now()
            running_pair = self._store_pair(
                replace(
                    pair,
                    agent_session_name=agent_session_name,
                    agent_status=TerminalSessionStatus.RUNNING,
                    last_verified_at=success_time,
                    updated_at=success_time,
                    detail=None,
                )
            )
            return binding, running_pair

    def reset_personal_session(
        self,
        app_user_id: str | EnvironmentRegistryEntry,
        environment: EnvironmentRegistryEntry | str | None = None,
        working_directory: str | None = None,
        *,
        maintenance_check: MaintenanceCheck | None = None,
        on_personal_session_created: PersonalSessionCreated | None = None,
    ) -> tuple[TerminalSessionRecord, TerminalAttachmentTarget]:
        _check_maintenance(maintenance_check)
        self.initialize()
        _check_maintenance(maintenance_check)
        if isinstance(app_user_id, EnvironmentRegistryEntry):
            working_directory = environment if isinstance(environment, str) else None
            environment = app_user_id
            app_user_id = self._legacy_user_id
        assert isinstance(environment, EnvironmentRegistryEntry)
        with (
            self._as_tenant(app_user_id),
            self._session_lifecycle_guard(app_user_id, environment.id, kind="personal"),
        ):
            _check_maintenance(maintenance_check)
            binding = self._upsert_binding(app_user_id, environment, working_directory)
            _check_maintenance(maintenance_check)
            pair = self._upsert_pair(app_user_id, binding, environment.id)
            _check_maintenance(maintenance_check)
            cleanup: PersonalSessionCleanup | None = None
            try:
                created = bool(
                    self._tmux_adapter.reset_personal_session(
                        binding,
                        environment,
                        pair.personal_session_name,
                    )
                )
                if created:
                    cleanup_completed = False

                    def cleanup() -> None:
                        nonlocal cleanup_completed
                        if cleanup_completed:
                            return
                        cleanup_completed = True
                        self._cleanup_new_personal_session(
                            binding,
                            environment,
                            pair.personal_session_name,
                        )

                    if on_personal_session_created is not None:
                        on_personal_session_created(cleanup)
                _check_maintenance(maintenance_check)
            except TmuxCommandError as exc:
                _check_maintenance(maintenance_check)
                failure_time = utc_now()
                self._store_pair(
                    replace(
                        pair,
                        personal_status=TerminalSessionStatus.FAILED,
                        personal_closed_at=failure_time,
                        last_verified_at=failure_time,
                        detail=str(exc),
                    )
                )
                _check_maintenance(maintenance_check)
                raise TerminalSessionOperationError(str(exc)) from exc
            except Exception:
                if cleanup is not None:
                    cleanup()
                raise

            reset_time = utc_now()
            try:
                _check_maintenance(maintenance_check)
                reset_pair = self._store_pair(
                    replace(
                        pair,
                        personal_status=TerminalSessionStatus.RUNNING,
                        personal_started_at=reset_time,
                        personal_closed_at=None,
                        last_verified_at=reset_time,
                        updated_at=reset_time,
                        detail=None,
                    )
                )
                _check_maintenance(maintenance_check)
            except Exception:
                if cleanup is not None:
                    cleanup()
                raise
            record = self._build_record(
                environment=environment,
                working_directory=working_directory,
                binding=binding,
                pair=reset_pair,
                session_name=reset_pair.personal_session_name,
            )
            target = TerminalAttachmentTarget(
                binding_id=binding.binding_id,
                session_id=record.session_id or reset_pair.personal_session_name,
                session_name=reset_pair.personal_session_name,
                user_id=binding.user_id,
                environment_id=environment.id,
                environment_alias=environment.alias,
                target_kind=record.target_kind,
                working_directory=working_directory,
                attach_command=self._tmux_adapter.build_attach_command(
                    binding,
                    environment,
                    reset_pair.personal_session_name,
                ),
                spawn_working_directory=self._resolve_spawn_directory(app_user_id),
                tenant_user=self._resolve_tenant_user(app_user_id),
            )
            return record, target

    def _cleanup_new_personal_session(
        self,
        binding: UserEnvironmentBinding,
        environment: EnvironmentRegistryEntry,
        session_name: str,
    ) -> None:
        """Best-effort cleanup for a Session opened across a maintenance epoch."""

        try:
            self._tmux_adapter.kill_session(binding, environment, session_name)
        except Exception:
            # The original maintenance error is the actionable result.  A
            # failed cleanup is surfaced later by normal reconciliation rather
            # than being allowed to masquerade as a successful terminal start.
            return

    def record_personal_attach(
        self,
        binding_id: str,
        *,
        maintenance_check: MaintenanceCheck | None = None,
    ) -> None:
        self._record_attach(
            binding_id,
            personal=True,
            maintenance_check=maintenance_check,
        )

    def record_agent_attach(self, binding_id: str) -> None:
        self._record_attach(binding_id, personal=False)

    def _record_attach(
        self,
        binding_id: str,
        *,
        personal: bool,
        maintenance_check: MaintenanceCheck | None = None,
    ) -> None:
        _check_maintenance(maintenance_check)
        self.initialize()
        _check_maintenance(maintenance_check)
        pair = self._load_pair(binding_id)
        if pair is None:
            return
        attach_time = utc_now()
        updated_pair = replace(
            pair,
            last_personal_attach_at=attach_time if personal else pair.last_personal_attach_at,
            last_agent_attach_at=attach_time if not personal else pair.last_agent_attach_at,
            updated_at=attach_time,
        )
        _check_maintenance(maintenance_check)
        self._store_pair(updated_pair)
        _check_maintenance(maintenance_check)

    def get_binding_by_id(self, binding_id: str) -> UserEnvironmentBinding | None:
        self.initialize()
        return self._load_binding_by_id(binding_id)

    def list_session_pairs(
        self,
        app_user_id: str,
        environment_id: str | None = None,
        environment_visible: Callable[[str], bool] | None = None,
    ) -> list[tuple[UserEnvironmentBinding, UserSessionPair, EnvironmentRegistryEntry | None]]:
        self.initialize()
        bindings = [binding for binding in self._list_bindings() if binding.user_id == app_user_id]
        if environment_id is not None:
            bindings = [binding for binding in bindings if binding.environment_id == environment_id]
        binding_ids = [b.binding_id for b in bindings]
        pairs_map = self._load_pairs_batch(binding_ids)
        items: list[
            tuple[UserEnvironmentBinding, UserSessionPair, EnvironmentRegistryEntry | None]
        ] = []
        for binding in bindings:
            if environment_visible is not None and not environment_visible(binding.environment_id):
                continue
            pair = pairs_map.get(binding.binding_id)
            if pair is None:
                continue
            environment: EnvironmentRegistryEntry | None
            try:
                environment = self._environment_service.get_environment(binding.environment_id)
            except EnvironmentNotFoundError:
                environment = None
            else:
                pair = self._refresh_pair(binding, environment, pair)
            items.append((binding, pair, environment))
        return items

    def reconcile(self) -> None:
        self.initialize()
        bindings = self._list_bindings()
        binding_ids = [b.binding_id for b in bindings]
        pairs_map = self._load_pairs_batch(binding_ids)
        for binding in bindings:
            pair = pairs_map.get(binding.binding_id)
            if pair is None:
                continue
            try:
                environment = self._environment_service.get_environment(binding.environment_id)
            except EnvironmentNotFoundError:
                reconcile_time = utc_now()
                self._store_pair(
                    replace(
                        pair,
                        personal_status=TerminalSessionStatus.IDLE,
                        agent_status=TerminalSessionStatus.IDLE,
                        personal_closed_at=reconcile_time,
                        last_verified_at=reconcile_time,
                        updated_at=reconcile_time,
                        detail="Environment not found during terminal reconcile",
                    )
                )
                continue
            self._refresh_pair(binding, environment, pair)

    def _refresh_pair(
        self,
        binding: UserEnvironmentBinding,
        environment: EnvironmentRegistryEntry,
        pair: UserSessionPair,
        *,
        maintenance_check: MaintenanceCheck | None = None,
    ) -> UserSessionPair:
        verify_time = utc_now()
        detail: str | None = None

        try:
            personal_exists = self._tmux_adapter.has_session(
                binding,
                environment,
                pair.personal_session_name,
            )
        except TmuxCommandError as exc:
            personal_status = TerminalSessionStatus.FAILED
            personal_started_at = pair.personal_started_at
            personal_closed_at = verify_time
            detail = str(exc)
        else:
            if personal_exists:
                personal_status = TerminalSessionStatus.RUNNING
                personal_started_at = pair.personal_started_at or verify_time
                personal_closed_at = None
            else:
                personal_status = TerminalSessionStatus.IDLE
                personal_started_at = pair.personal_started_at
                personal_closed_at = verify_time
                # No detail needed — IDLE status already communicates that
                # the session doesn't exist; attach will create a new one.

        agent_status = pair.agent_status
        if pair.agent_session_name:
            try:
                agent_exists = self._tmux_adapter.has_session(
                    binding,
                    environment,
                    pair.agent_session_name,
                )
            except TmuxCommandError as exc:
                agent_status = TerminalSessionStatus.FAILED
                if detail is None:
                    detail = str(exc)
            else:
                if agent_exists:
                    agent_status = TerminalSessionStatus.RUNNING
                else:
                    agent_status = TerminalSessionStatus.IDLE

        # Personal session running means the terminal is usable; a missing
        # agent session is normal outside of task execution, so never let it
        # override the detail when personal is healthy.
        if personal_status is TerminalSessionStatus.RUNNING:
            detail = None

        _check_maintenance(maintenance_check)
        refreshed = self._store_pair(
            replace(
                pair,
                personal_status=personal_status,
                agent_status=agent_status,
                personal_started_at=personal_started_at,
                personal_closed_at=personal_closed_at,
                last_verified_at=verify_time,
                updated_at=verify_time,
                detail=detail,
            )
        )
        _check_maintenance(maintenance_check)
        return refreshed

    def _upsert_binding(
        self,
        app_user_id: str,
        environment: EnvironmentRegistryEntry,
        working_directory: str | None,
    ) -> UserEnvironmentBinding:
        existing = self._load_binding(app_user_id, environment.id)
        if existing is None:
            existing = self._claim_legacy_binding(app_user_id, environment.id)

        now = utc_now()
        if existing is None:
            binding = UserEnvironmentBinding(
                binding_id=str(uuid4()),
                user_id=app_user_id,
                environment_id=environment.id,
                remote_login_user=environment.user,
                default_shell=self._default_shell,
                default_workdir=working_directory,
                mux_kind=TerminalMuxKind.TMUX,
                created_at=now,
                updated_at=now,
            )
        else:
            binding = replace(
                existing,
                user_id=app_user_id,
                remote_login_user=environment.user,
                default_shell=self._default_shell,
                default_workdir=working_directory,
                updated_at=now,
            )
        return self._store_binding(binding)

    def _claim_legacy_binding(
        self,
        app_user_id: str,
        environment_id: str,
    ) -> UserEnvironmentBinding | None:
        if app_user_id == self._legacy_user_id:
            return None
        with self._connect() as connection:
            legacy_row = connection.execute(
                """
                SELECT binding_id, user_id, environment_id, remote_login_user, default_shell,
                       default_workdir, mux_kind, created_at, updated_at
                FROM user_environment_bindings
                WHERE user_id = ? AND environment_id = ?
                """,
                (self._legacy_user_id, environment_id),
            ).fetchone()
            if legacy_row is None:
                return None

            non_legacy_count = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM user_environment_bindings
                WHERE environment_id = ? AND user_id != ?
                """,
                (environment_id, self._legacy_user_id),
            ).fetchone()
            if non_legacy_count is not None and int(non_legacy_count["count"]) > 0:
                return None

            connection.execute(
                """
                UPDATE user_environment_bindings
                SET user_id = ?, updated_at = ?
                WHERE binding_id = ?
                """,
                (app_user_id, utc_now().isoformat(), legacy_row["binding_id"]),
            )
            connection.commit()

        return self._load_binding(app_user_id, environment_id)

    def _upsert_pair(
        self,
        app_user_id: str,
        binding: UserEnvironmentBinding,
        environment_id: str,
    ) -> UserSessionPair:
        existing = self._load_pair(binding.binding_id)
        now = utc_now()
        if existing is None:
            pair = UserSessionPair(
                binding_id=binding.binding_id,
                personal_session_name=self.session_name_for(app_user_id, environment_id),
                agent_session_name=self.agent_session_name_for(app_user_id, environment_id),
                personal_status=TerminalSessionStatus.IDLE,
                agent_status=TerminalSessionStatus.IDLE,
                created_at=now,
                updated_at=now,
            )
        else:
            pair = replace(
                existing,
                personal_session_name=self.session_name_for(app_user_id, environment_id),
                agent_session_name=self.agent_session_name_for(app_user_id, environment_id),
                agent_status=existing.agent_status or TerminalSessionStatus.IDLE,
                updated_at=now,
            )
        return self._store_pair(pair)

    @contextmanager
    def _session_lifecycle_guard(
        self,
        app_user_id: str,
        environment_id: str,
        *,
        kind: str,
    ) -> Iterator[None]:
        key = _SessionLifecycleKey(
            app_user_id=app_user_id,
            environment_id=environment_id,
            kind=kind,
        )
        with self._session_lifecycle_lock_guard:
            state = self._session_lifecycle_locks.get(key)
            if state is None:
                state = _SessionLifecycleLockState(lock=threading.Lock())
                self._session_lifecycle_locks[key] = state
            state.holders += 1
            lifecycle_lock = state.lock

        lifecycle_lock.acquire()
        try:
            yield
        finally:
            lifecycle_lock.release()
            with self._session_lifecycle_lock_guard:
                state = self._session_lifecycle_locks.get(key)
                if state is not None:
                    state.holders -= 1
                    if state.holders == 0:
                        self._session_lifecycle_locks.pop(key, None)

    def _build_record(
        self,
        *,
        environment: EnvironmentRegistryEntry,
        working_directory: str | None,
        binding: UserEnvironmentBinding | None,
        pair: UserSessionPair | None,
        session_name: str,
    ) -> TerminalSessionRecord:
        return TerminalSessionRecord(
            session_id=session_name if pair is not None else None,
            provider=TERMINAL_PROVIDER,
            target_kind=self._tmux_adapter.target_kind_for(environment),
            environment_id=environment.id,
            environment_alias=environment.alias,
            working_directory=working_directory,
            status=pair.personal_status if pair is not None else TerminalSessionStatus.IDLE,
            created_at=pair.created_at if pair is not None else None,
            started_at=pair.personal_started_at if pair is not None else None,
            closed_at=pair.personal_closed_at if pair is not None else None,
            detail=pair.detail if pair is not None else None,
            binding_id=binding.binding_id if binding is not None else None,
            session_name=session_name,
        )

    def _list_bindings(self) -> list[UserEnvironmentBinding]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT binding_id, user_id, environment_id, remote_login_user, default_shell,
                       default_workdir, mux_kind, created_at, updated_at
                FROM user_environment_bindings
                ORDER BY created_at ASC
                """
            ).fetchall()
        return [self._row_to_binding(row) for row in rows]

    def _load_binding(
        self,
        app_user_id: str,
        environment_id: str | None = None,
    ) -> UserEnvironmentBinding | None:
        if environment_id is None:
            environment_id = app_user_id
            app_user_id = self._legacy_user_id
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT binding_id, user_id, environment_id, remote_login_user, default_shell,
                       default_workdir, mux_kind, created_at, updated_at
                FROM user_environment_bindings
                WHERE user_id = ? AND environment_id = ?
                """,
                (app_user_id, environment_id),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_binding(row)

    def _load_binding_by_id(self, binding_id: str) -> UserEnvironmentBinding | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT binding_id, user_id, environment_id, remote_login_user, default_shell,
                       default_workdir, mux_kind, created_at, updated_at
                FROM user_environment_bindings
                WHERE binding_id = ?
                """,
                (binding_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_binding(row)

    def _load_pair(self, binding_id: str) -> UserSessionPair | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT binding_id, personal_session_name, agent_session_name, personal_status,
                       agent_status, created_at, updated_at, personal_started_at,
                       personal_closed_at, last_verified_at, last_personal_attach_at,
                       last_agent_attach_at, detail
                FROM user_session_pairs
                WHERE binding_id = ?
                """,
                (binding_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_pair(row)

    def _load_pairs_batch(self, binding_ids: list[str]) -> dict[str, UserSessionPair]:
        """Batch load pairs for multiple binding IDs using chunked IN queries."""
        result: dict[str, UserSessionPair] = {}
        if not binding_ids:
            return result
        with self._connect() as conn:
            # Chunk to stay under SQLite's SQLITE_MAX_VARIABLE_NUMBER (default 999)
            CHUNK = 500
            for i in range(0, len(binding_ids), CHUNK):
                chunk = binding_ids[i : i + CHUNK]
                placeholders = ",".join("?" * len(chunk))
                rows = conn.execute(
                    f"SELECT * FROM user_session_pairs WHERE binding_id IN ({placeholders})",
                    chunk,
                ).fetchall()
                for row in rows:
                    pair = self._row_to_pair(row)
                    result[pair.binding_id] = pair
        return result

    def _store_binding(self, binding: UserEnvironmentBinding) -> UserEnvironmentBinding:
        created_at = binding.created_at or utc_now()
        updated_at = binding.updated_at or created_at
        stored = replace(binding, created_at=created_at, updated_at=updated_at)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO user_environment_bindings (
                    binding_id, user_id, environment_id, remote_login_user,
                    default_shell, default_workdir, mux_kind, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(binding_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    remote_login_user = excluded.remote_login_user,
                    default_shell = excluded.default_shell,
                    default_workdir = excluded.default_workdir,
                    mux_kind = excluded.mux_kind,
                    updated_at = excluded.updated_at
                """,
                (
                    stored.binding_id,
                    stored.user_id,
                    stored.environment_id,
                    stored.remote_login_user,
                    stored.default_shell,
                    stored.default_workdir,
                    stored.mux_kind.value,
                    created_at.isoformat(),
                    updated_at.isoformat(),
                ),
            )
            connection.commit()
        return stored

    def _store_pair(self, pair: UserSessionPair) -> UserSessionPair:
        created_at = pair.created_at or utc_now()
        updated_at = pair.updated_at or created_at
        stored = replace(pair, created_at=created_at, updated_at=updated_at)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO user_session_pairs (
                    binding_id, personal_session_name, agent_session_name, personal_status,
                    agent_status, created_at, updated_at, personal_started_at,
                    personal_closed_at, last_verified_at, last_personal_attach_at,
                    last_agent_attach_at, detail
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(binding_id) DO UPDATE SET
                    personal_session_name = excluded.personal_session_name,
                    agent_session_name = excluded.agent_session_name,
                    personal_status = excluded.personal_status,
                    agent_status = excluded.agent_status,
                    updated_at = excluded.updated_at,
                    personal_started_at = excluded.personal_started_at,
                    personal_closed_at = excluded.personal_closed_at,
                    last_verified_at = excluded.last_verified_at,
                    last_personal_attach_at = excluded.last_personal_attach_at,
                    last_agent_attach_at = excluded.last_agent_attach_at,
                    detail = excluded.detail
                """,
                (
                    stored.binding_id,
                    stored.personal_session_name,
                    stored.agent_session_name,
                    stored.personal_status.value,
                    stored.agent_status.value if stored.agent_status is not None else None,
                    created_at.isoformat(),
                    updated_at.isoformat(),
                    stored.personal_started_at.isoformat()
                    if stored.personal_started_at is not None
                    else None,
                    stored.personal_closed_at.isoformat()
                    if stored.personal_closed_at is not None
                    else None,
                    stored.last_verified_at.isoformat()
                    if stored.last_verified_at is not None
                    else None,
                    stored.last_personal_attach_at.isoformat()
                    if stored.last_personal_attach_at is not None
                    else None,
                    stored.last_agent_attach_at.isoformat()
                    if stored.last_agent_attach_at is not None
                    else None,
                    stored.detail or "",
                ),
            )
            connection.commit()
        return stored

    @staticmethod
    def _row_to_binding(row: sqlite3.Row) -> UserEnvironmentBinding:
        return UserEnvironmentBinding(
            binding_id=row["binding_id"],
            user_id=row["user_id"],
            environment_id=row["environment_id"],
            remote_login_user=row["remote_login_user"],
            default_shell=row["default_shell"],
            default_workdir=row["default_workdir"],
            mux_kind=TerminalMuxKind(row["mux_kind"]),
            created_at=_parse_datetime(row["created_at"]),
            updated_at=_parse_datetime(row["updated_at"]),
        )

    @staticmethod
    def _row_to_pair(row: sqlite3.Row) -> UserSessionPair:
        detail = row["detail"] or None
        agent_status_raw = row["agent_status"]
        return UserSessionPair(
            binding_id=row["binding_id"],
            personal_session_name=row["personal_session_name"],
            agent_session_name=row["agent_session_name"],
            personal_status=TerminalSessionStatus(row["personal_status"]),
            agent_status=TerminalSessionStatus(agent_status_raw) if agent_status_raw else None,
            created_at=_parse_datetime(row["created_at"]),
            updated_at=_parse_datetime(row["updated_at"]),
            personal_started_at=_parse_datetime(row["personal_started_at"]),
            personal_closed_at=_parse_datetime(row["personal_closed_at"]),
            last_verified_at=_parse_datetime(row["last_verified_at"]),
            last_personal_attach_at=_parse_datetime(row["last_personal_attach_at"]),
            last_agent_attach_at=_parse_datetime(row["last_agent_attach_at"]),
            detail=detail,
        )

    def resize_tmux_window(self, *, session_name: str, cols: int, rows: int) -> None:
        """Resize the tmux window dimensions."""
        self._tmux_adapter.resize_window(session_name=session_name, cols=cols, rows=rows)

    def _connect(self) -> sqlite3.Connection:
        from ainrf.db.connection import connect

        return connect(self._db_path)
