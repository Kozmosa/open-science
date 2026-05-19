"""pytest configuration — ensures test isolation for the cached app singleton."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True, scope="module")
def _reset_cached_app() -> None:
    """Reset cached app instance before each test module.

    ``tests._testutil`` lazily creates and caches an app singleton so multiple
    tests in the same module can share state (/ admin user / project setup).
    Resetting here prevents stale state from leaking between modules.
    """
    from tests._testutil import reset_app_instance

    reset_app_instance()
    yield
    reset_app_instance()
