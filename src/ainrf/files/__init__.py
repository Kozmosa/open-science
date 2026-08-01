"""Lazy file browser exports."""

from typing import Any
from ainrf._lazy_exports import resolve_export

_EXPORTS = {"FileTreeCache": ("ainrf.files.cache", "FileTreeCache")}
_EXPORTS.update(
    {
        name: ("ainrf.files.models", name)
        for name in ("DirectoryListing", "FileContent", "FileEntry", "FileUploadResult")
    }
)
_EXPORTS.update(
    {
        name: ("ainrf.files.service", name)
        for name in (
            "FileBrowserError",
            "FileBrowserService",
            "FileTooLargeError",
            "PathNotFoundError",
        )
    }
)
__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    return resolve_export(name, _EXPORTS, globals())
