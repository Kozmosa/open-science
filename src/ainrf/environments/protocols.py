"""Small read-only protocols shared by legacy and durable environment adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ainrf.environments.models import EnvironmentRegistryEntry


class EnvironmentRuntimeReader(Protocol):
    """The Environment operations needed by terminal and file consumers."""

    def get_environment(self, environment_id: str) -> EnvironmentRegistryEntry:
        """Return one runtime Environment entry."""

    def resolve_effective_workdir(
        self,
        project_id: str,
        environment_id: str,
        state_root: Path,
        /,
    ) -> str | None:
        """Resolve a non-mutating working-directory projection."""
