"""Canonical OpenScience username policy for Linux tenant identities."""

from __future__ import annotations

import re
from typing import Final


USERNAME_MIN_LENGTH: Final = 2
USERNAME_MAX_LENGTH: Final = 31
USERNAME_PATTERN: Final = r"^[a-z0-9][a-z0-9_-]{1,30}$"
USERNAME_DESCRIPTION: Final = (
    "2-31 characters; start with a lowercase letter or digit; "
    "use only lowercase letters, digits, underscores, or hyphens"
)
USERNAME_REQUIREMENT: Final = "Username must be " + USERNAME_DESCRIPTION

_USERNAME_RE: Final[re.Pattern[str]] = re.compile(USERNAME_PATTERN)


def is_valid_username(value: str) -> bool:
    """Return whether *value* maps safely to the canonical tenant Linux identity."""

    return _USERNAME_RE.fullmatch(value) is not None
