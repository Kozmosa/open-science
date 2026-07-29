"""Composition Adapter for concrete harness engines."""

from __future__ import annotations

from pathlib import Path

from ainrf.harness_engine.base import HarnessEngine, HarnessEngineType
from ainrf.harness_engine.db_session_store import DbSessionStore
from ainrf.harness_engine.engines import get_engine
from ainrf.harness_engine.engines.agent_sdk import AgentSdkEngine


def create_engine(engine_type: HarnessEngineType, *, state_root: Path) -> HarnessEngine:
    """Construct and configure one concrete engine Adapter."""

    engine = get_engine(engine_type.value)
    if isinstance(engine, AgentSdkEngine):
        engine._session_store = DbSessionStore(
            str(state_root / "runtime" / "agentic_researcher.sqlite3")
        )
    return engine
