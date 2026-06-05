from __future__ import annotations

import re
from pathlib import Path

from ainrf.security.audit import audit_event

_SENSITIVE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (".env files", re.compile(r"\.env(?:\.|$|\W)")),
    ("*.pem", re.compile(r"\.pem(?:\W|$)")),
    ("*.key", re.compile(r"\.key(?:\W|$)")),
    ("id_rsa", re.compile(r"id_rsa(?:\W|$)")),
    ("id_ed25519", re.compile(r"id_ed25519(?:\W|$)")),
    ("authorized_keys", re.compile(r"authorized_keys(?:\W|$)")),
    (
        "admin_initial_password.txt",
        re.compile(r"admin_initial_password\.txt(?:\W|$)"),
    ),
    ("*.sqlite", re.compile(r"\.sqlite(?:\W|$)")),
    ("*.db", re.compile(r"\.db(?:\W|$)")),
    ("/etc/passwd", re.compile(r"/etc/passwd(?:\W|$)")),
    ("/etc/shadow", re.compile(r"/etc/shadow(?:\W|$)")),
    ("~/.ssh/*", re.compile(r"(?:^|/)\.ssh/")),
    ("/root/*", re.compile(r"/root/")),
    ("/proc/*", re.compile(r"/proc/")),
]

SENSITIVE_PATTERNS: list[re.Pattern[str]] = [pattern for _, pattern in _SENSITIVE_PATTERNS]


def is_sensitive_path(path: str) -> tuple[bool, str | None]:
    """Return whether ``path`` matches a sensitive path pattern.

    Returns ``(True, pattern_name)`` on a match or ``(False, None)``.
    """
    for name, pattern in _SENSITIVE_PATTERNS:
        if pattern.search(path):
            return True, name
    return False, None


def check_path_access(
    path: str,
    user_id: str | None = None,
    environment_id: str | None = None,
) -> None:
    """Audit access to ``path`` when it matches a sensitive pattern.

    The audited ``path`` field is the basename only. The full path is never
    logged.
    """
    sensitive, pattern_name = is_sensitive_path(path)
    if sensitive:
        audit_event(
            "files.sensitive_path_access",
            severity="high",
            path=Path(path).name,
            pattern=pattern_name,
            user_id=user_id,
            environment_id=environment_id,
        )
