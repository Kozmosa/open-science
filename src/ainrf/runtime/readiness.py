from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import TypedDict


class DependencyStatusPayload(TypedDict):
    available: bool
    path: str | None
    detail: str | None


class RuntimeReadinessPayload(TypedDict):
    ready: bool
    dependencies: dict[str, DependencyStatusPayload]


@dataclass(frozen=True, slots=True)
class DependencyStatus:
    name: str
    available: bool
    path: str | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class RuntimeReadiness:
    tmux: DependencyStatus
    uv: DependencyStatus

    @property
    def ready(self) -> bool:
        return self.tmux.available and self.uv.available

    def as_public_payload(self) -> RuntimeReadinessPayload:
        return {
            "ready": self.ready,
            "dependencies": {
                "tmux": _dependency_payload(self.tmux),
                "uv": _dependency_payload(self.uv),
            },
        }


def check_runtime_readiness() -> RuntimeReadiness:
    return RuntimeReadiness(
        tmux=_check_binary(
            "tmux", "Install tmux to use localhost terminals and workspace browser."
        ),
        uv=_check_binary("uv", "Install uv to run repository-local Python commands."),
    )


def _check_binary(name: str, missing_detail: str) -> DependencyStatus:
    path = shutil.which(name)
    return DependencyStatus(
        name=name,
        available=path is not None,
        path=path,
        detail=None if path is not None else missing_detail,
    )


def _dependency_payload(status: DependencyStatus) -> DependencyStatusPayload:
    return {
        "available": status.available,
        "path": status.path,
        "detail": status.detail,
    }
