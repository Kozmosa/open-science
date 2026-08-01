"""Lazy execution Adapter exports."""

from typing import Any
from ainrf._lazy_exports import resolve_export

_EXPORTS = {
    name: ("ainrf.execution.errors", name)
    for name in (
        "BootstrapError",
        "CommandTimeoutError",
        "SSHConnectionError",
        "SSHExecutorError",
        "TransferError",
        "UnsupportedContainerError",
    )
}
_EXPORTS.update(
    {
        name: ("ainrf.execution.models", name)
        for name in ("CommandResult", "ContainerConfig", "ContainerHealth")
    }
)
_EXPORTS["SSHExecutor"] = ("ainrf.execution.ssh", "SSHExecutor")
__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    return resolve_export(name, _EXPORTS, globals())
