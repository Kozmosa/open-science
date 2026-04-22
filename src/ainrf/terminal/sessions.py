from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import datetime
from getpass import getuser
from pathlib import Path
from uuid import uuid4

from ainrf.environments import EnvironmentNotFoundError, InMemoryEnvironmentService
from ainrf.environments.models import EnvironmentRegistryEntry
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


def current_daemon_user() -> str:
    try:
        resolved = getuser()
    except Exception:
        return "root"
    return resolved or "root"


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


class SessionManager:
    def __init__(
        self,
        *,
        state_root: Path,
        environment_service: InMemoryEnvironmentService,
        tmux_adapter: TmuxAdapter,
        default_shell: str | None,
        user_id: str | None = None,
    ) -> None:
        self._state_root = state_root
        self._runtime_root = state_root / "runtime"
        self._db_path = self._runtime_root / "terminal_state.sqlite3"
        self._environment_service = environment_service
        self._tmux_adapter = tmux_adapter
        self._default_shell = default_shell
        self._legacy_user_id = user_id or current_daemon_user()
        self._initialized = False

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

    def initialize(self) -> None:
        if self._initialized:
            return
        self._runtime_root.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS user_environment_bindings (
                    binding_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    environment_id TEXT NOT NULL,
                    remote_login_user TEXT NOT NULL,
                    default_shell TEXT,
                    default_workdir TEXT,
                    mux_kind TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(user_id, environment_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS user_session_pairs (
                    binding_id TEXT PRIMARY KEY,
                    personal_session_name TEXT NOT NULL,
                    agent_session_name TEXT,
                    personal_status TEXT NOT NULL,
                    agent_status TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    personal_started_at TEXT,
                    personal_closed_at TEXT,
                    last_verified_at TEXT,
                    last_personal_attach_at TEXT,
                    last_agent_attach_at TEXT,
                    detail TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(binding_id) REFERENCES user_environment_bindings(binding_id)
                )
                """
            )
            connection.commit()
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
    ) -> TerminalSessionRecord:
        self.initialize()
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

        refreshed_pair = self._refresh_pair(binding, environment, pair)
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
    ) -> tuple[TerminalSessionRecord, TerminalAttachmentTarget]:
        self.initialize()
        if isinstance(app_user_id, EnvironmentRegistryEntry):
            working_directory = environment if isinstance(environment, str) else None
            environment = app_user_id
            app_user_id = self._legacy_user_id
        assert isinstance(environment, EnvironmentRegistryEntry)
        binding = self._upsert_binding(app_user_id, environment, working_directory)
        pair = self._upsert_pair(app_user_id, binding, environment.id)
        try:
            self._tmux_adapter.ensure_personal_session(
                binding,
                environment,
                pair.personal_session_name,
            )
        except TmuxCommandError as exc:
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
            raise TerminalSessionOperationError(str(exc)) from exc

        success_time = utc_now()
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
            spawn_working_directory=self._state_root,
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
    ) -> tuple[TerminalSessionRecord, TerminalAttachmentTarget]:
        self.initialize()
        if isinstance(app_user_id, EnvironmentRegistryEntry):
            working_directory = environment if isinstance(environment, str) else None
            environment = app_user_id
            app_user_id = self._legacy_user_id
        assert isinstance(environment, EnvironmentRegistryEntry)
        binding = self._upsert_binding(app_user_id, environment, working_directory)
        pair = self._upsert_pair(app_user_id, binding, environment.id)
        try:
            self._tmux_adapter.reset_personal_session(
                binding,
                environment,
                pair.personal_session_name,
            )
        except TmuxCommandError as exc:
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
            raise TerminalSessionOperationError(str(exc)) from exc

        reset_time = utc_now()
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
            spawn_working_directory=self._state_root,
        )
        return record, target

    def record_personal_attach(self, binding_id: str) -> None:
        self._record_attach(binding_id, personal=True)

    def record_agent_attach(self, binding_id: str) -> None:
        self._record_attach(binding_id, personal=False)

    def _record_attach(self, binding_id: str, *, personal: bool) -> None:
        self.initialize()
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
        self._store_pair(updated_pair)

    def get_binding_by_id(self, binding_id: str) -> UserEnvironmentBinding | None:
        self.initialize()
        return self._load_binding_by_id(binding_id)

    def list_session_pairs(
        self,
        app_user_id: str,
        environment_id: str | None = None,
    ) -> list[tuple[UserEnvironmentBinding, UserSessionPair, EnvironmentRegistryEntry | None]]:
        self.initialize()
        bindings = [binding for binding in self._list_bindings() if binding.user_id == app_user_id]
        if environment_id is not None:
            bindings = [binding for binding in bindings if binding.environment_id == environment_id]
        items: list[
            tuple[UserEnvironmentBinding, UserSessionPair, EnvironmentRegistryEntry | None]
        ] = []
        for binding in bindings:
            pair = self._load_pair(binding.binding_id)
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
        for binding in bindings:
            pair = self._load_pair(binding.binding_id)
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
                detail = "Personal tmux session is not running"

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
                    if detail is None:
                        detail = "Agent tmux session is not running"

        if personal_status is TerminalSessionStatus.RUNNING and (
            pair.agent_session_name is None or agent_status is TerminalSessionStatus.RUNNING
        ):
            detail = None

        return self._store_pair(
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

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        return connection
