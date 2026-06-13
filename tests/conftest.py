"""pytest configuration — ensures test isolation for the cached app singleton."""

from __future__ import annotations

from collections.abc import Iterator

import pytest


# ---------------------------------------------------------------------------
# anyio backend restriction
# ---------------------------------------------------------------------------
# The codebase uses asyncio.to_thread() and other asyncio-specific primitives
# that are incompatible with the trio event loop.  Override the auto-discovery
# fixture from anyio to restrict parametrization to asyncio only.
#
# Without this, installing trio (a transitive dependency in some environments)
# causes all @pytest.mark.anyio tests to also run under trio, producing 100+
# spurious failures.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module", params=["asyncio"])
def anyio_backend(request: pytest.FixtureRequest) -> str:
    return request.param


# ---------------------------------------------------------------------------
# Test isolation
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True, scope="module")
def _reset_cached_app() -> Iterator[None]:
    """Reset cached app singleton before each test module.

    ``tests._testutil`` lazily creates and caches an app singleton so multiple
    tests in the same module can share state (/ admin user / project setup).
    Resetting here prevents stale state from leaking between modules.
    """
    from tests._testutil import reset_app_instance

    reset_app_instance()
    yield
    reset_app_instance()
