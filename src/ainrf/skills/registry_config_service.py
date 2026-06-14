from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any

from ainrf.db.connection import atomic_write_json
from ainrf.environments.models import utc_now
from ainrf.skills.registry_models import DEFAULT_REGISTRIES, SkillRegistryConfig


class SkillRegistryNotFoundError(LookupError):
    """Raised when a requested skill registry is not configured."""

    def __init__(self, registry_id: str) -> None:
        super().__init__(f"Skill registry not found: {registry_id}")
        self.registry_id = registry_id


class SkillRegistryConfigService:
    """Persistent configuration for skill registries.

    Registries are stored in ``<state_root>/runtime/skill_registries.json``.
    On initialization, persisted registries are merged with ``DEFAULT_REGISTRIES``
    so built-in registries such as ARIS are always present and cannot be
    permanently deleted.  Custom registries added by admins are persisted across
    restarts.

    This service follows the same JSON-registry pattern used by
    ``WorkspaceRegistryService`` and ``ProjectRegistryService``.
    """

    def __init__(self, state_root: Path) -> None:
        self._state_root = state_root
        self._runtime_root = state_root / "runtime"
        self._registry_path = self._runtime_root / "skill_registries.json"
        self._lock = Lock()
        self._registries: dict[str, SkillRegistryConfig] = {}
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            self._runtime_root.mkdir(parents=True, exist_ok=True)
            if self._registry_path.exists():
                raw = self._registry_path.read_text(encoding="utf-8")
                try:
                    payload = json.loads(raw) if raw.strip() else {}
                except json.JSONDecodeError:
                    raise
                self._registries = {
                    item["registry_id"]: SkillRegistryConfig.from_dict(item)
                    for item in payload.get("items", [])
                }
            # Always merge defaults so built-in registries survive deletion and
            # new default registries are picked up automatically.
            for default in DEFAULT_REGISTRIES:
                if default.registry_id not in self._registries:
                    self._registries[default.registry_id] = default
            self._persist()
            self._initialized = True

    def list_registries(self) -> list[SkillRegistryConfig]:
        self.initialize()
        return list(self._registries.values())

    def get_registry(self, registry_id: str) -> SkillRegistryConfig:
        self.initialize()
        try:
            return self._registries[registry_id]
        except KeyError as exc:
            raise SkillRegistryNotFoundError(registry_id) from exc

    def add_registry(self, config: SkillRegistryConfig) -> SkillRegistryConfig:
        """Add a new registry configuration. Raises if registry_id already exists."""
        self.initialize()
        with self._lock:
            if config.registry_id in self._registries:
                raise ValueError(f"Registry '{config.registry_id}' already exists")
            self._registries[config.registry_id] = config
            self._persist()
            return config

    def update_registry(
        self,
        registry_id: str,
        display_name: str | None = None,
        git_url: str | None = None,
        git_ref: str | None = None,
        source_skills_path: str | None = None,
        core_skill_ids: list[str] | None = None,
        install_mode: str | None = None,
        enabled: bool | None = None,
    ) -> SkillRegistryConfig:
        """Update an existing registry. Built-in registries may be edited but not deleted."""
        self.initialize()
        with self._lock:
            existing = self._registries.get(registry_id)
            if existing is None:
                raise SkillRegistryNotFoundError(registry_id)

            updated = SkillRegistryConfig(
                registry_id=registry_id,
                display_name=display_name if display_name is not None else existing.display_name,
                git_url=git_url if git_url is not None else existing.git_url,
                git_ref=git_ref if git_ref is not None else existing.git_ref,
                source_skills_path=source_skills_path
                if source_skills_path is not None
                else existing.source_skills_path,
                core_skill_ids=core_skill_ids if core_skill_ids is not None else existing.core_skill_ids,
                install_mode=install_mode if install_mode is not None else existing.install_mode,
                enabled=enabled if enabled is not None else existing.enabled,
            )
            self._registries[registry_id] = updated
            self._persist()
            return updated

    def delete_registry(self, registry_id: str) -> None:
        """Delete a custom registry. Built-in registries cannot be deleted."""
        self.initialize()
        with self._lock:
            if registry_id not in self._registries:
                raise SkillRegistryNotFoundError(registry_id)
            if any(registry_id == default.registry_id for default in DEFAULT_REGISTRIES):
                raise ValueError(f"Built-in registry '{registry_id}' cannot be deleted")
            del self._registries[registry_id]
            self._persist()

    def reset_to_defaults(self) -> None:
        """Restore all default registries and remove any custom registries."""
        self.initialize()
        with self._lock:
            self._registries = {d.registry_id: d for d in DEFAULT_REGISTRIES}
            self._persist()

    def _persist(self) -> None:
        payload: dict[str, Any] = {
            "items": [r.to_dict() for r in self._registries.values()],
            "updated_at": utc_now().isoformat(),
        }
        atomic_write_json(self._registry_path, payload)
