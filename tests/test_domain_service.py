"""V2 Project/Workspace/Environment service and permission tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from ainrf.auth.service import AuthService
from ainrf.domain.service import DomainNotFoundError, DomainPermissionError, DomainService

pytestmark = [pytest.mark.unit, pytest.mark.db_race]


def _admin() -> dict[str, object]:
    return {"id": "admin", "role": "admin"}


def _user(user_id: str) -> dict[str, object]:
    return {"id": user_id, "role": "member"}


def _grant_environment(state_root: Path, environment_id: str, user_id: str) -> None:
    auth = AuthService(state_root=state_root)
    auth.initialize()
    auth.grant_environment(
        env_id=environment_id,
        user_id=user_id,
        max_tasks=None,
        granted_by="admin",
        reason="domain service test",
    )


def test_project_workspace_link_is_idempotent_and_does_not_grant_workspace_access(
    state_root: Path,
) -> None:
    service = DomainService(state_root)
    admin = _admin()
    alice = _user("alice")
    bob = _user("bob")
    environment = service.create_environment(
        admin, alias="host-a", display_name="Host A", connection={"host": "example"}
    )
    _grant_environment(state_root, str(environment["environment_id"]), "alice")
    project = service.create_project(alice, name="Alice project")
    workspace = service.create_workspace(
        alice,
        environment_id=str(environment["environment_id"]),
        canonical_path="/tmp/alice",
        label="Alice",
    )

    first = service.attach_workspace(
        str(project["project_id"]),
        str(workspace["workspace_id"]),
        alice,
        idempotency_key="attach-1",
    )
    second = service.attach_workspace(
        str(project["project_id"]),
        str(workspace["workspace_id"]),
        alice,
        idempotency_key="attach-1",
    )

    assert first == second
    with pytest.raises(DomainNotFoundError):
        service.attach_workspace(
            str(project["project_id"]),
            str(workspace["workspace_id"]),
            bob,
            idempotency_key="attach-2",
        )
    with pytest.raises(DomainPermissionError):
        service.attach_workspace(
            str(project["project_id"]),
            str(workspace["workspace_id"]),
            admin,
            idempotency_key="attach-3",
        )


def test_primary_replacement_and_detach_guard(state_root: Path) -> None:
    service = DomainService(state_root)
    admin, alice = _admin(), _user("alice")
    environment = service.create_environment(
        admin, alias="host-a", display_name="Host A", connection={}
    )
    _grant_environment(state_root, str(environment["environment_id"]), "alice")
    project = service.create_project(alice, name="Project")
    one = service.create_workspace(
        alice,
        environment_id=str(environment["environment_id"]),
        canonical_path="/tmp/one",
        label="one",
    )
    two = service.create_workspace(
        alice,
        environment_id=str(environment["environment_id"]),
        canonical_path="/tmp/two",
        label="two",
    )
    service.set_primary_workspace(
        str(project["project_id"]), str(one["workspace_id"]), alice, idempotency_key="one"
    )
    service.set_primary_workspace(
        str(project["project_id"]), str(two["workspace_id"]), alice, idempotency_key="two"
    )
    with pytest.raises(ValueError):
        service.detach_workspace(
            str(project["project_id"]), str(two["workspace_id"]), alice, idempotency_key="detach"
        )


def test_environment_is_disabled_not_hard_deleted_and_secret_is_redacted(state_root: Path) -> None:
    service = DomainService(state_root)
    environment = service.create_environment(
        _admin(),
        alias="host-a",
        display_name="Host A",
        connection={},
        credential_ref="secret://profile",
    )
    service.disable_environment(str(environment["environment_id"]), _admin())
    returned = service.environment(str(environment["environment_id"]), _admin())
    assert returned["status"] == "disabled"
    assert "credential_ref" not in returned


def test_default_project_cannot_be_archived_and_workspace_can_be_unregistered(
    state_root: Path,
) -> None:
    service = DomainService(state_root)
    admin, alice = _admin(), _user("alice")
    default = service.create_project(alice, name="Default", is_default=True)
    with pytest.raises(ValueError):
        service.archive_project(str(default["project_id"]), alice, reason="test")
    environment = service.create_environment(
        admin, alias="host-a", display_name="Host A", connection={}
    )
    _grant_environment(state_root, str(environment["environment_id"]), "alice")
    workspace = service.create_workspace(
        alice,
        environment_id=str(environment["environment_id"]),
        canonical_path="/tmp/unregister",
        label="unregister",
    )
    service.unregister_workspace(str(workspace["workspace_id"]), alice)
    assert service.workspace(str(workspace["workspace_id"]), alice)["status"] == "unregistered"


def test_link_idempotency_is_actor_scoped_and_rejects_request_hash_conflicts(
    state_root: Path,
) -> None:
    service = DomainService(state_root)
    admin, alice, bob = _admin(), _user("alice"), _user("bob")
    environment = service.create_environment(
        admin, alias="host-a", display_name="Host A", connection={}
    )
    environment_id = str(environment["environment_id"])
    _grant_environment(state_root, environment_id, "alice")
    _grant_environment(state_root, environment_id, "bob")
    alice_project = service.create_project(alice, name="Alice")
    bob_project = service.create_project(bob, name="Bob")
    alice_one = service.create_workspace(
        alice, environment_id=environment_id, canonical_path="/tmp/alice-one", label="Alice one"
    )
    alice_two = service.create_workspace(
        alice, environment_id=environment_id, canonical_path="/tmp/alice-two", label="Alice two"
    )
    bob_workspace = service.create_workspace(
        bob, environment_id=environment_id, canonical_path="/tmp/bob", label="Bob"
    )

    alice_result = service.attach_workspace(
        str(alice_project["project_id"]),
        str(alice_one["workspace_id"]),
        alice,
        idempotency_key="shared-key",
    )
    bob_result = service.attach_workspace(
        str(bob_project["project_id"]),
        str(bob_workspace["workspace_id"]),
        bob,
        idempotency_key="shared-key",
    )

    assert alice_result["workspace_id"] == alice_one["workspace_id"]
    assert bob_result["workspace_id"] == bob_workspace["workspace_id"]
    with pytest.raises(ValueError, match="different request"):
        service.attach_workspace(
            str(alice_project["project_id"]),
            str(alice_two["workspace_id"]),
            alice,
            idempotency_key="shared-key",
        )


def test_project_viewer_visibility_and_primary_replacement_guards(state_root: Path) -> None:
    service = DomainService(state_root)
    admin, alice, viewer, outsider = _admin(), _user("alice"), _user("viewer"), _user("outsider")
    environment = service.create_environment(
        admin, alias="host-a", display_name="Host A", connection={}
    )
    environment_id = str(environment["environment_id"])
    _grant_environment(state_root, environment_id, "alice")
    project = service.create_project(alice, name="Private project")
    project_id = str(project["project_id"])
    service.add_member(project_id, "viewer", "viewer", False, alice)
    assert service.project(project_id, viewer)["project_id"] == project_id
    with pytest.raises(DomainPermissionError):
        service.archive_project(project_id, viewer, reason="not allowed")
    with pytest.raises(DomainNotFoundError):
        service.project(project_id, outsider)

    one = service.create_workspace(
        alice, environment_id=environment_id, canonical_path="/tmp/one", label="one"
    )
    two = service.create_workspace(
        alice, environment_id=environment_id, canonical_path="/tmp/two", label="two"
    )
    service.set_primary_workspace(
        project_id, str(one["workspace_id"]), alice, idempotency_key="one"
    )
    replacement = service.replace_primary_workspace(
        project_id,
        str(one["workspace_id"]),
        str(two["workspace_id"]),
        alice,
        idempotency_key="replace",
    )
    assert replacement["is_primary"] is True
    assert replacement["environment_id"] == environment_id
    assert replacement["can_execute"] is True
    with pytest.raises(ValueError, match="Replace the Primary"):
        service.unregister_workspace(str(two["workspace_id"]), alice)
