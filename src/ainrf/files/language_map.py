from __future__ import annotations

from pathlib import Path

_EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".json": "json",
    ".md": "markdown",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".rs": "rust",
    ".go": "go",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".java": "java",
    ".rb": "ruby",
    ".php": "php",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".sql": "sql",
    ".dockerfile": "dockerfile",
    ".xml": "xml",
    ".ini": "ini",
    ".cfg": "ini",
    ".log": "log",
    ".lua": "lua",
    ".swift": "swift",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".r": "r",
    ".scala": "scala",
    ".dart": "dart",
    ".ex": "elixir",
    ".exs": "elixir",
    ".clj": "clojure",
    ".cljs": "clojure",
    ".erl": "erlang",
    ".hrl": "erlang",
    ".vim": "vim",
    ".ps1": "powershell",
    ".pl": "perl",
    ".pm": "perl",
    ".groovy": "groovy",
    ".gradle": "groovy",
    ".makefile": "makefile",
    ".mk": "makefile",
    ".cmake": "cmake",
    ".graphql": "graphql",
    ".proto": "protobuf",
}

_IMAGE_EXTENSIONS: set[str] = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".svg",
}


def language_from_path(path: str) -> str | None:
    ext = Path(path).suffix.lower()
    return _EXTENSION_TO_LANGUAGE.get(ext)


def is_image_file(path: str) -> bool:
    ext = Path(path).suffix.lower()
    return ext in _IMAGE_EXTENSIONS


def mime_type_from_path(path: str) -> str | None:
    ext = Path(path).suffix.lower()
    mapping: dict[str, str] = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".svg": "image/svg+xml",
    }
    return mapping.get(ext)
