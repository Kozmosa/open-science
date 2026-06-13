"""pytest configuration — anyio backend restriction."""

from __future__ import annotations

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
#
# Function-scoped (the anyio default) — keeps each test on an isolated event
# loop so a misbehaving test cannot leak state to the next one.
# ---------------------------------------------------------------------------
@pytest.fixture(params=["asyncio"])
def anyio_backend(request: pytest.FixtureRequest) -> str:
    return request.param
