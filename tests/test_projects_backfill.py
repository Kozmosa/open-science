"""Tests for the per-user default project backfill."""

from __future__ import annotations

from pathlib import Path

import pytest

from ainrf.projects import ProjectRegistryService
from ainrf.projects.backfill import backfill_user_default_projects

pytestmark = [pytest.mark.unit]


class _FakeUser:
    def __init__(self, username: str, uid: str) -> None:
        self.username = username
        self.id = uid


def test_backfill_creates_missing_defaults(tmp_path: Path) -> None:
    service = ProjectRegistryService(tmp_path)
    service.initialize()
    users = [_FakeUser("alice", "u1"), _FakeUser("bob", "u2")]

    created, skipped = backfill_user_default_projects(project_service=service, users=users)

    assert created == 2
    assert skipped == 0
    assert service.get_project("alice_default").owner_user_id == "u1"
    assert service.get_project("bob_default").owner_user_id == "u2"


def test_backfill_is_idempotent(tmp_path: Path) -> None:
    service = ProjectRegistryService(tmp_path)
    service.initialize()
    users = [_FakeUser("alice", "u1")]

    backfill_user_default_projects(project_service=service, users=users)
    created, skipped = backfill_user_default_projects(project_service=service, users=users)

    assert created == 0
    assert skipped == 1


def test_backfill_preserves_seed_default_project(tmp_path: Path) -> None:
    service = ProjectRegistryService(tmp_path)
    service.initialize()
    before = service.get_project("default")

    backfill_user_default_projects(project_service=service, users=[_FakeUser("alice", "u1")])

    assert service.get_project("default") == before
