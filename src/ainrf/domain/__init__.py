"""Lazy compatibility exports for v2 application Modules."""

from typing import Any

from ainrf._lazy_exports import resolve_export

_EXPORTS = {
    "DomainAuthorizationService": ("ainrf.domain.service", "DomainAuthorizationService"),
    "DomainNotFoundError": ("ainrf.domain.service", "DomainNotFoundError"),
    "DomainPermissionError": ("ainrf.domain.service", "DomainPermissionError"),
    "DomainService": ("ainrf.domain.service", "DomainService"),
    "PersistentEnvironmentFacade": (
        "ainrf.domain.environment_facade",
        "PersistentEnvironmentFacade",
    ),
    "PersistentWorkspaceFacade": ("ainrf.domain.workspace_facade", "PersistentWorkspaceFacade"),
    "ContextAssembler": ("ainrf.domain.context", "ContextAssembler"),
    "ContextAssembly": ("ainrf.domain.context", "ContextAssembly"),
    "ContextFragment": ("ainrf.domain.context", "ContextFragment"),
    "ContextSource": ("ainrf.domain.context", "ContextSource"),
    "ProjectContextService": ("ainrf.domain.context", "ProjectContextService"),
    "AttemptService": ("ainrf.domain.attempts", "AttemptService"),
    "AttemptProjectionService": ("ainrf.domain.attempt_projection", "AttemptProjectionService"),
    "DispatchClaim": ("ainrf.domain.attempts", "DispatchClaim"),
    "DispatchRunResult": ("ainrf.domain.worker", "DispatchRunResult"),
    "TaskDispatcher": ("ainrf.domain.worker", "TaskDispatcher"),
    "TaskApplicationService": ("ainrf.domain.tasks", "TaskApplicationService"),
    "TaskProjectionService": ("ainrf.domain.task_projection", "TaskProjectionService"),
    "SessionProjectionService": ("ainrf.domain.session_projection", "SessionProjectionService"),
    "OverviewSnapshotPlanner": ("ainrf.domain.overview", "OverviewSnapshotPlanner"),
    "OverviewSnapshotService": ("ainrf.domain.overview", "OverviewSnapshotService"),
}
__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    return resolve_export(name, _EXPORTS, globals())
