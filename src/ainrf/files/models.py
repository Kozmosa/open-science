from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


FileKind = Literal["file", "directory", "symlink"]


@dataclass(slots=True)
class FileEntry:
    name: str
    path: str
    kind: FileKind
    size: int | None = None
    modified_at: str | None = None


@dataclass(slots=True)
class DirectoryListing:
    path: str
    entries: list[FileEntry]


@dataclass(slots=True)
class FileContent:
    path: str
    content: str
    is_binary: bool
    size: int
    language: str | None = None
    mime_type: str | None = None
