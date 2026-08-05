"""Lazy compatibility exports for v2 application Modules."""

from typing import Any

from ainrf._lazy_exports import resolve_export

_EXPORTS = {
    "DomainNotFoundError": ("ainrf.domain.service", "DomainNotFoundError"),
    "DomainPermissionError": ("ainrf.domain.service", "DomainPermissionError"),
    "DomainModules": ("ainrf.domain.service", "DomainModules"),
    "build_domain_modules": ("ainrf.domain.service", "build_domain_modules"),
    "ProjectModule": ("ainrf.domain.interfaces", "ProjectModule"),
    "WorkspaceModule": ("ainrf.domain.interfaces", "WorkspaceModule"),
    "EnvironmentModule": ("ainrf.domain.interfaces", "EnvironmentModule"),
    "ContextModule": ("ainrf.domain.interfaces", "ContextModule"),
    "TaskLifecycleModule": ("ainrf.domain.interfaces", "TaskLifecycleModule"),
    "ConversationModule": ("ainrf.domain.interfaces", "ConversationModule"),
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
    "ConversationApplicationService": (
        "ainrf.domain.conversation_service",
        "ConversationApplicationService",
    ),
    "TaskProjectionService": ("ainrf.domain.task_projection", "TaskProjectionService"),
    "OverviewSnapshotPlanner": ("ainrf.domain.overview", "OverviewSnapshotPlanner"),
    "OverviewSnapshotService": ("ainrf.domain.overview", "OverviewSnapshotService"),
}
__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    return resolve_export(name, _EXPORTS, globals())
