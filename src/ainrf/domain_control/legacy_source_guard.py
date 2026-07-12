"""Read-only inventory and drift guard for legacy cutover sources.

The v2 control-plane database is intentionally excluded.  It is the target
of the shadow import and changes while reconciliation records its evidence;
including it would make a correctly prepared cutover look stale.  The guard
instead watches only the legacy JSON registries/checkpoints and the legacy
``sessions.sqlite3`` store.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import cast


class LegacySourceGuardError(RuntimeError):
    """Raised when a legacy source cannot be observed safely."""


class LegacySourceDriftError(LegacySourceGuardError):
    """Raised when a prepared legacy source set has changed."""


@dataclass(frozen=True, slots=True)
class LegacySourceFile:
    """One state-relative legacy source observation."""

    relative_path: str
    source_kind: str
    size: int
    sha256: str
    inode: int
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class LegacySourceInventory:
    """A portable, immutable snapshot of legacy source identity."""

    version: int
    state_root: str
    files: tuple[LegacySourceFile, ...]
    excluded_paths: tuple[str, ...]
    observed_at: str

    def canonical_dict(self) -> dict[str, object]:
        """Return the complete state-relative source identity for hashing."""

        return {
            "version": self.version,
            "files": [
                {
                    "relative_path": item.relative_path,
                    "source_kind": item.source_kind,
                    "size": item.size,
                    "sha256": item.sha256,
                    "inode": item.inode,
                    "mtime_ns": item.mtime_ns,
                }
                for item in sorted(self.files, key=lambda item: item.relative_path)
            ],
            "excluded_paths": list(sorted(self.excluded_paths)),
        }

    @property
    def digest(self) -> str:
        encoded = json.dumps(
            self.canonical_dict(), ensure_ascii=True, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def as_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["digest"] = self.digest
        return result

    @classmethod
    def from_dict(cls, value: object) -> LegacySourceInventory:
        """Parse persisted inventory data without accepting arbitrary paths."""

        if not isinstance(value, Mapping):
            raise ValueError("legacy source inventory must be an object")
        payload = cast(Mapping[str, object], value)
        raw_files = payload.get("files")
        raw_excluded = payload.get("excluded_paths")
        if not isinstance(raw_files, (list, tuple)) or not isinstance(raw_excluded, (list, tuple)):
            raise ValueError("legacy source inventory is missing files or excluded paths")
        files: list[LegacySourceFile] = []
        for raw_file in raw_files:
            if not isinstance(raw_file, Mapping):
                raise ValueError("legacy source inventory file must be an object")
            file_payload = cast(Mapping[str, object], raw_file)
            relative_path = file_payload.get("relative_path")
            source_kind = file_payload.get("source_kind")
            size = file_payload.get("size")
            sha256 = file_payload.get("sha256")
            inode = file_payload.get("inode")
            mtime_ns = file_payload.get("mtime_ns")
            if (
                not isinstance(relative_path, str)
                or not _is_safe_relative_path(relative_path)
                or not isinstance(source_kind, str)
                or source_kind not in {"json", "sessions_sqlite"}
                or not isinstance(size, int)
                or size < 0
                or not isinstance(sha256, str)
                or not _is_sha256(sha256)
                or not isinstance(inode, int)
                or inode < 0
                or not isinstance(mtime_ns, int)
                or mtime_ns < 0
            ):
                raise ValueError("legacy source inventory contains an invalid file entry")
            files.append(
                LegacySourceFile(
                    relative_path=relative_path,
                    source_kind=source_kind,
                    size=size,
                    sha256=sha256,
                    inode=inode,
                    mtime_ns=mtime_ns,
                )
            )
        excluded_paths = tuple(str(item) for item in raw_excluded if isinstance(item, str))
        if len(excluded_paths) != len(raw_excluded) or any(
            not _is_safe_relative_path(item) for item in excluded_paths
        ):
            raise ValueError("legacy source inventory contains an invalid excluded path")
        version = payload.get("version")
        state_root = payload.get("state_root")
        observed_at = payload.get("observed_at")
        if (
            not isinstance(version, int)
            or version != 1
            or not isinstance(state_root, str)
            or not isinstance(observed_at, str)
        ):
            raise ValueError("legacy source inventory has an unsupported version")
        inventory = cls(
            version=version,
            state_root=state_root,
            files=tuple(sorted(files, key=lambda item: item.relative_path)),
            excluded_paths=tuple(sorted(excluded_paths)),
            observed_at=observed_at,
        )
        expected_digest = payload.get("digest")
        if expected_digest is not None and expected_digest != inventory.digest:
            raise ValueError("legacy source inventory digest does not match its contents")
        return inventory


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value.lower())


def _is_safe_relative_path(value: str) -> bool:
    candidate = Path(value)
    return not candidate.is_absolute() and ".." not in candidate.parts and value != ""


class LegacySourceGuard:
    """Capture and verify only legacy sources without changing their modes.

    The guard never writes or chmods a source.  SQLite data is copied into a
    temporary backup solely to hash its WAL-consistent contents; that avoids
    treating the main ``.sqlite3`` file as authoritative while a WAL exists.
    """

    _AGENTIC_RESEARCHER_PATH = "runtime/agentic_researcher.sqlite3"
    _SESSION_DATABASE_PATH = "runtime/sessions.sqlite3"
    _LEGACY_RUNTIME_JSON_PATHS = (
        "runtime/projects.json",
        "runtime/workspaces.json",
        "runtime/task_edges.json",
        "runtime/sessions.json",
    )

    def __init__(self, state_root: Path) -> None:
        self._state_root = state_root.resolve()

    def capture(self) -> LegacySourceInventory:
        """Inventory legacy JSON and session data after stable observations."""

        files: list[LegacySourceFile] = []
        for path in self._json_sources():
            files.append(self._capture_json(path))
        session_database = self._state_root / self._SESSION_DATABASE_PATH
        if session_database.exists():
            files.append(self._capture_sessions_sqlite(session_database))
        return LegacySourceInventory(
            version=1,
            state_root=self._state_root.name,
            files=tuple(sorted(files, key=lambda item: item.relative_path)),
            excluded_paths=(self._AGENTIC_RESEARCHER_PATH,),
            observed_at=datetime.now(timezone.utc).isoformat(),
        )

    def verify(self, expected: LegacySourceInventory) -> LegacySourceInventory:
        """Re-observe legacy sources and reject any content or metadata drift."""

        if self._AGENTIC_RESEARCHER_PATH not in expected.excluded_paths:
            raise LegacySourceGuardError("legacy inventory must exclude agentic_researcher.sqlite3")
        observed = self.capture()
        if expected.canonical_dict() != observed.canonical_dict():
            raise LegacySourceDriftError(self._drift_detail(expected, observed))
        return observed

    def _json_sources(self) -> tuple[Path, ...]:
        paths: list[Path] = []
        for relative_path in self._LEGACY_RUNTIME_JSON_PATHS:
            path = self._state_root / relative_path
            if path.is_file():
                paths.append(path)

        session_states_root = self._state_root / "session-states"
        if session_states_root.is_dir():
            for path in session_states_root.rglob("*.json"):
                if not path.is_file():
                    continue
                state_relative_path = path.relative_to(session_states_root)
                if any(part.startswith("attempt-") for part in state_relative_path.parts[:-1]):
                    continue
                paths.append(path)
        return tuple(sorted(paths, key=self._relative_path))

    def _capture_json(self, path: Path) -> LegacySourceFile:
        self._reject_symlink(path)
        relative_path = self._relative_path(path)
        before = self._stat(path, relative_path)
        try:
            payload = path.read_bytes()
        except FileNotFoundError as exc:
            raise LegacySourceDriftError(
                f"legacy JSON source disappeared: {relative_path}"
            ) from exc
        after = self._stat(path, relative_path)
        if before != after or len(payload) != before[2]:
            raise LegacySourceDriftError(
                f"legacy JSON source changed while being read: {relative_path}"
            )
        return LegacySourceFile(
            relative_path=relative_path,
            source_kind="json",
            size=before[2],
            sha256=hashlib.sha256(payload).hexdigest(),
            inode=before[0],
            mtime_ns=before[1],
        )

    def _capture_sessions_sqlite(self, path: Path) -> LegacySourceFile:
        self._reject_symlink(path)
        relative_path = self._relative_path(path)
        before = self._stat(path, relative_path)
        with tempfile.TemporaryDirectory(
            prefix="openscience-legacy-session-"
        ) as temporary_directory:
            snapshot = Path(temporary_directory) / "sessions.sqlite3"
            source_uri = f"{path.resolve().as_uri()}?mode=ro"
            try:
                source_connection = sqlite3.connect(source_uri, uri=True)
                snapshot_connection = sqlite3.connect(snapshot)
                try:
                    source_connection.backup(snapshot_connection)
                finally:
                    snapshot_connection.close()
                    source_connection.close()
            except sqlite3.Error as exc:
                raise LegacySourceGuardError(
                    f"cannot snapshot legacy sessions database: {relative_path}"
                ) from exc
            digest = self._sha256(snapshot)
        after = self._stat(path, relative_path)
        if before != after:
            raise LegacySourceDriftError(
                f"legacy sessions database changed while being snapshotted: {relative_path}"
            )
        return LegacySourceFile(
            relative_path=relative_path,
            source_kind="sessions_sqlite",
            size=before[2],
            sha256=digest,
            inode=before[0],
            mtime_ns=before[1],
        )

    def _relative_path(self, path: Path) -> str:
        try:
            return path.relative_to(self._state_root).as_posix()
        except ValueError as exc:
            raise LegacySourceGuardError("legacy source escaped state root") from exc

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1 << 16), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _stat(path: Path, relative_path: str) -> tuple[int, int, int]:
        try:
            stat = path.stat()
        except FileNotFoundError as exc:
            raise LegacySourceDriftError(f"legacy source disappeared: {relative_path}") from exc
        return stat.st_ino, stat.st_mtime_ns, stat.st_size

    @staticmethod
    def _reject_symlink(path: Path) -> None:
        if path.is_symlink():
            raise LegacySourceGuardError(f"legacy source cannot be a symlink: {path.name}")

    @staticmethod
    def _drift_detail(expected: LegacySourceInventory, observed: LegacySourceInventory) -> str:
        expected_files = {item.relative_path: item for item in expected.files}
        observed_files = {item.relative_path: item for item in observed.files}
        changed = sorted(
            path
            for path in set(expected_files).union(observed_files)
            if expected_files.get(path) != observed_files.get(path)
        )
        return "legacy source inventory changed" + (f": {', '.join(changed)}" if changed else "")
