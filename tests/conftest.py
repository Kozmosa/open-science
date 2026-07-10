"""pytest configuration — anyio backend restriction and shared fixtures."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from ainrf.agentic_researcher.service import AgenticResearcherService
    from ainrf.auth.service import AuthService
    from ainrf.projects.service import ProjectRegistryService
    from ainrf.sessions.service import SessionService
    from ainrf.workspaces.service import WorkspaceRegistryService


# Pytest loads this conftest before importing test modules. Point HOME at a
# worker-local temporary directory first so module-level Path.home() constants
# never bind to the invoking user's real home on the shared server.
_TEST_SESSION_HOME = tempfile.TemporaryDirectory(prefix="openscience-pytest-home-")
os.environ["HOME"] = _TEST_SESSION_HOME.name


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


@pytest.fixture(autouse=True)
def isolated_runtime_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep deterministic L0/L1 tests away from host workspace and tenant paths.

    Real Linux tenant provisioning is a privileged L3 system boundary. The
    deterministic suite uses one isolated HOME and tenant root per test so it
    remains safe inside coding-agent containers as well as GitHub runners.
    """
    home_dir = tmp_path / "home"
    tenant_root = tmp_path / "tenant-homes"
    home_dir.mkdir()
    tenant_root.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setattr("ainrf.auth.jwt_utils._SECRET_PATH", home_dir / ".ainrf" / "jwt_secret")
    monkeypatch.setattr("ainrf.auth.service._TENANT_HOME_ROOT", tenant_root)
    monkeypatch.setattr("ainrf.auth.service._is_container_environment", lambda: False)
    monkeypatch.setattr("ainrf.runtime.paths._TENANT_HOME_ROOT", tenant_root)


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
    from ainrf.auth.service import AuthService

    svc = AuthService(state_root=state_root)
    svc.initialize()
    return svc


@pytest.fixture
def session_service(state_root: Path) -> SessionService:
    """Return an initialized SessionService using the isolated state root."""
    from ainrf.sessions.service import SessionService

    svc = SessionService(state_root=state_root)
    svc.initialize()
    return svc


@pytest.fixture
def agentic_service(state_root: Path) -> AgenticResearcherService:
    """Return an initialized AgenticResearcherService using the isolated state root."""
    from ainrf.agentic_researcher.service import AgenticResearcherService

    svc = AgenticResearcherService(state_root=state_root)
    svc.initialize()
    return svc


@pytest.fixture
def project_service(state_root: Path) -> ProjectRegistryService:
    """Return an initialized ProjectRegistryService using the isolated state root."""
    from ainrf.projects.service import ProjectRegistryService

    svc = ProjectRegistryService(state_root=state_root)
    svc.initialize()
    return svc


@pytest.fixture
def workspace_service(state_root: Path) -> WorkspaceRegistryService:
    """Return an initialized WorkspaceRegistryService using the isolated state root."""
    from ainrf.workspaces.service import WorkspaceRegistryService

    svc = WorkspaceRegistryService(state_root=state_root)
    svc.initialize()
    return svc


@pytest.fixture
def freezer():
    """Yield a freezegun freezer for deterministic time-based tests."""
    from freezegun import freeze_time

    with freeze_time("2026-01-01T00:00:00+00:00") as f:
        yield f
