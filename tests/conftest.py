"""pytest configuration — anyio backend restriction and shared fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from ainrf.agentic_researcher.service import AgenticResearcherService
from ainrf.auth.service import AuthService
from ainrf.projects.service import ProjectRegistryService
from ainrf.sessions.service import SessionService
from ainrf.workspaces.service import WorkspaceRegistryService


# ---------------------------------------------------------------------------
# anyio backend restriction
# ---------------------------------------------------------------------------
# The codebase uses asyncio.to_thread() and other asyncio-specific primitives
# that are incompatible with the trio event loop.  Override the auto-discovery
# fixture from anyio to restrict parametrization to asyncio only.
#
# Without this, installing trio (a transïtive dependency in some environments)
# causes all @pytest.mark.anyio tests to also run under trio, producing 100+
# spurious failures.
# ---------------------------------------------------------------------------
@pytest.fixture(params=["asyncio"])
def anyio_backend(request: pytest.FixtureRequest) -> str:
    return request.param


# ---------------------------------------------------------------------------
# Shared state fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def state_root(tmp_path: Path) -> Path:
    """Return an isolated state root with runtime subdirectories created."""
    root = tmp_path / "ainrf-state"
    (root / "runtime").mkdir(parents=True, exist_ok=True)
    (root / "session-states").mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture
def auth_service(state_root: Path) -> AuthService:
    """Return an initialized AuthService using the isolated state root."""
    svc = AuthService(state_root=state_root)
    svc.initialize()
    return svc


@pytest.fixture
def session_service(state_root: Path) -> SessionService:
    """Return an initialized SessionService using the isolated state root."""
    svc = SessionService(state_root=state_root)
    svc.initialize()
    return svc


@pytest.fixture
def agentic_service(state_root: Path) -> AgenticResearcherService:
    """Return an initialized AgenticResearcherService using the isolated state root."""
    svc = AgenticResearcherService(state_root=state_root)
    svc.initialize()
    return svc


@pytest.fixture
def project_service(state_root: Path) -> ProjectRegistryService:
    """Return an initialized ProjectRegistryService using the isolated state root."""
    svc = ProjectRegistryService(state_root=state_root)
    svc.initialize()
    return svc


@pytest.fixture
def workspace_service(state_root: Path) -> WorkspaceRegistryService:
    """Return an initialized WorkspaceRegistryService using the isolated state root."""
    svc = WorkspaceRegistryService(state_root=state_root)
    svc.initialize()
    return svc


@pytest.fixture
def freezer():
    """Yield a freezegun freezer for deterministic time-based tests."""
    from freezegun import freeze_time

    with freeze_time("2026-01-01T00:00:00+00:00") as f:
        yield f
