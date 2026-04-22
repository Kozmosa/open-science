from __future__ import annotations

from ainrf.tasks.models import (
    ManagedTask,
    ManagedTaskStatus,
    TaskAgentWriteState,
    TaskTakeoverLease,
    TaskTakeoverLeaseStatus,
    TaskTerminalBinding,
    TaskTerminalBindingStatus,
)

__all__ = [
    "ManagedTask",
    "ManagedTaskStatus",
    "TaskAgentWriteState",
    "TaskTakeoverLease",
    "TaskTakeoverLeaseStatus",
    "TaskTerminalBinding",
    "TaskTerminalBindingStatus",
    "TaskManager",
    "TaskOperationError",
]


def __getattr__(name: str) -> object:
    if name in {"TaskManager", "TaskOperationError"}:
        from ainrf.tasks.service import TaskManager, TaskOperationError

        return {"TaskManager": TaskManager, "TaskOperationError": TaskOperationError}[name]
    raise AttributeError(name)
