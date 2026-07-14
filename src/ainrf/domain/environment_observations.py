"""Persistent, non-authoritative Environment detection observations for v2.

The Environment registry remains the control-plane source of truth in SQLite.
Detection is deliberately a separate observation stream: probing never edits
the registry and a read never starts a probe.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ainrf.domain.environment_facade import PersistentEnvironmentFacade
from ainrf.environments.models import (
    AnthropicEnvStatus,
    DetectionSnapshot,
    DetectionStatus,
    EnvironmentRegistryEntry,
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


class PersistentEnvironmentObservationService:
    """Probe durable Environment entries and persist only observation payloads."""

    def __init__(self, state_root: Path, environment_service: PersistentEnvironmentFacade) -> None:
        self._state_root = state_root
        self._environment_service = environment_service
        self._detections_dir = state_root / "detections"

    async def detect_environment(
        self,
        environment_id: str,
        *,
        app_user_id: str | None = None,
        terminal_session_manager: SessionManager | None = None,
    ) -> DetectionSnapshot:
        environment = self._environment_service.get_environment(environment_id)
        try:
            outcome = await probe_with_ssh(environment)
            snapshot = outcome.snapshot
        except SSHConnectionError:
            snapshot = await self._fallback_or_failure(
                environment,
                app_user_id=app_user_id,
                terminal_session_manager=terminal_session_manager,
            )
        except (RuntimeError, ValueError) as exc:
            snapshot = self._failed_configuration_snapshot(environment, exc)
        self._persist(snapshot)
        return snapshot

    async def _fallback_or_failure(
        self,
        environment: EnvironmentRegistryEntry,
        *,
        app_user_id: str | None,
        terminal_session_manager: SessionManager | None,
    ) -> DetectionSnapshot:
        if app_user_id is None or terminal_session_manager is None:
            return failed_missing_user_snapshot(environment)
        try:
            return (
                await probe_with_personal_tmux(
                    environment=environment,
                    app_user_id=app_user_id,
                    session_manager=terminal_session_manager,
                )
            ).snapshot
        except (RuntimeError, TmuxCommandError) as exc:
            return failed_tmux_snapshot(environment, exc)

    def get_latest_detection(self, environment_id: str) -> DetectionSnapshot | None:
        """Read the last durable observation after verifying the registry entry exists."""

        self._environment_service.get_environment(environment_id)
        if not self._safe_environment_id(environment_id):
            return None
        path = self._detections_dir / f"{environment_id}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict) or payload.get("environment_id") != environment_id:
            return None
        try:
            return self._snapshot_from_payload(payload)
        except (KeyError, TypeError, ValueError):
            return None

    def _persist(self, snapshot: DetectionSnapshot) -> None:
        if not self._safe_environment_id(snapshot.environment_id):
            raise ValueError("Environment ID is not safe for persistent observation storage")
        self._detections_dir.mkdir(parents=True, exist_ok=True)
        target = self._detections_dir / f"{snapshot.environment_id}.json"
        payload = self._snapshot_payload(snapshot)
        encoded = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self._detections_dir,
            prefix=f".{snapshot.environment_id}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            stream.write(encoded)
            stream.write("\n")
        try:
            os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, target)
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _safe_environment_id(environment_id: str) -> bool:
        return (
            bool(environment_id)
            and environment_id not in {".", ".."}
            and "/" not in environment_id
            and "\\" not in environment_id
            and "\x00" not in environment_id
        )

    @staticmethod
    def _failed_configuration_snapshot(
        environment: EnvironmentRegistryEntry, exc: Exception
    ) -> DetectionSnapshot:
        return DetectionSnapshot(
            environment_id=environment.id,
            detected_at=utc_now(),
            status=DetectionStatus.FAILED,
            summary=f"Detection failed for {environment.alias} because its configuration is invalid.",
            errors=["environment_configuration_invalid"],
            hostname=environment.host,
            os_info=type(exc).__name__,
        )

    @staticmethod
    def _snapshot_payload(snapshot: DetectionSnapshot) -> dict[str, object]:
        return {
            "environment_id": snapshot.environment_id,
            "detected_at": snapshot.detected_at.isoformat(),
            "status": snapshot.status.value,
            "summary": snapshot.summary,
            "errors": list(snapshot.errors),
            "warnings": list(snapshot.warnings),
            "ssh_ok": snapshot.ssh_ok,
            "tmux_ok": snapshot.tmux_ok,
            "hostname": snapshot.hostname,
            "os_info": snapshot.os_info,
            "arch": snapshot.arch,
            "workdir_exists": snapshot.workdir_exists,
            "python": PersistentEnvironmentObservationService._tool_payload(snapshot.python),
            "conda": PersistentEnvironmentObservationService._tool_payload(snapshot.conda),
            "uv": PersistentEnvironmentObservationService._tool_payload(snapshot.uv),
            "pixi": PersistentEnvironmentObservationService._tool_payload(snapshot.pixi),
            "codex": PersistentEnvironmentObservationService._tool_payload(snapshot.codex),
            "torch": PersistentEnvironmentObservationService._tool_payload(snapshot.torch),
            "cuda": PersistentEnvironmentObservationService._tool_payload(snapshot.cuda),
            "gpu_models": list(snapshot.gpu_models),
            "gpu_count": snapshot.gpu_count,
            "claude_cli": PersistentEnvironmentObservationService._tool_payload(
                snapshot.claude_cli
            ),
            "anthropic_env": snapshot.anthropic_env.value,
        }

    @staticmethod
    def _tool_payload(tool: ToolStatus) -> dict[str, object]:
        return {"available": tool.available, "version": tool.version, "path": tool.path}

    @staticmethod
    def _snapshot_from_payload(payload: dict[str, object]) -> DetectionSnapshot:
        detected_at = payload["detected_at"]
        if not isinstance(detected_at, str):
            raise ValueError("Detection timestamp is invalid")
        environment_id = payload["environment_id"]
        status = payload["status"]
        summary = payload["summary"]
        if (
            not isinstance(environment_id, str)
            or not isinstance(status, str)
            or not isinstance(summary, str)
        ):
            raise ValueError("Detection payload is invalid")
        return DetectionSnapshot(
            environment_id=environment_id,
            detected_at=datetime.fromisoformat(detected_at),
            status=DetectionStatus(status),
            summary=summary,
            errors=PersistentEnvironmentObservationService._strings(payload.get("errors")),
            warnings=PersistentEnvironmentObservationService._strings(payload.get("warnings")),
            ssh_ok=bool(payload.get("ssh_ok", False)),
            tmux_ok=bool(payload.get("tmux_ok", False)),
            hostname=PersistentEnvironmentObservationService._optional_text(
                payload.get("hostname")
            ),
            os_info=PersistentEnvironmentObservationService._optional_text(payload.get("os_info")),
            arch=PersistentEnvironmentObservationService._optional_text(payload.get("arch")),
            workdir_exists=PersistentEnvironmentObservationService._optional_bool(
                payload.get("workdir_exists")
            ),
            python=PersistentEnvironmentObservationService._tool(payload.get("python")),
            conda=PersistentEnvironmentObservationService._tool(payload.get("conda")),
            uv=PersistentEnvironmentObservationService._tool(payload.get("uv")),
            pixi=PersistentEnvironmentObservationService._tool(payload.get("pixi")),
            codex=PersistentEnvironmentObservationService._tool(payload.get("codex")),
            torch=PersistentEnvironmentObservationService._tool(payload.get("torch")),
            cuda=PersistentEnvironmentObservationService._tool(payload.get("cuda")),
            gpu_models=PersistentEnvironmentObservationService._strings(payload.get("gpu_models")),
            gpu_count=PersistentEnvironmentObservationService._nonnegative_int(
                payload.get("gpu_count")
            ),
            claude_cli=PersistentEnvironmentObservationService._tool(payload.get("claude_cli")),
            anthropic_env=AnthropicEnvStatus(
                payload.get("anthropic_env", AnthropicEnvStatus.UNKNOWN.value)
            ),
        )

    @staticmethod
    def _tool(value: object) -> ToolStatus:
        if not isinstance(value, dict):
            return ToolStatus(available=False)
        mapping = {str(key): item for key, item in value.items()}
        return ToolStatus(
            available=bool(mapping.get("available", False)),
            version=PersistentEnvironmentObservationService._optional_text(mapping.get("version")),
            path=PersistentEnvironmentObservationService._optional_text(mapping.get("path")),
        )

    @staticmethod
    def _strings(value: object) -> list[str]:
        return [str(item) for item in value] if isinstance(value, list) else []

    @staticmethod
    def _optional_text(value: object) -> str | None:
        return value if isinstance(value, str) and value else None

    @staticmethod
    def _optional_bool(value: object) -> bool | None:
        return value if isinstance(value, bool) else None

    @staticmethod
    def _nonnegative_int(value: object) -> int:
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
