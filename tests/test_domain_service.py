"""V2 Project/Workspace/Environment service and permission tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

import pytest

from ainrf.auth.service import AuthService
from ainrf.api.routes.metrics import get_metrics_text, reset_metrics
from ainrf.db import connect
from ainrf.domain.service import (
    DomainConflictError,
    DomainNotFoundError,
    DomainPermissionError,
    DomainService,
)
from tests.testutil import seed_user

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


def _service(state_root: Path, artifact_sha: str) -> DomainService:
    return DomainService(state_root, artifact_sha=artifact_sha)


def test_project_workspace_link_is_idempotent_and_does_not_grant_workspace_access(
    state_root: Path, committed_v2_state: str
) -> None:
    service = _service(state_root, committed_v2_state)
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
    with pytest.raises(DomainPermissionError, match="Environment access"):
        service.attach_workspace(
            str(project["project_id"]),
            str(workspace["workspace_id"]),
            admin,
            idempotency_key="attach-3",
        )
    admin_link = service.workspace_links(str(project["project_id"]), admin)[0]
    assert admin_link["can_execute"] is False
    assert admin_link["cannot_execute_reason"] == "active Environment grant is required"
    updated = service.update_workspace(
        str(workspace["workspace_id"]),
        admin,
        label="Admin-managed registry label",
        idempotency_key="admin-metadata-update",
    )
    assert updated["label"] == "Admin-managed registry label"


def test_admin_cannot_bypass_environment_execution_grants_for_workspace_operations(
    state_root: Path, committed_v2_state: str
) -> None:
    """Registry administration never implies a tenant's execution authority."""

    reset_metrics()
    service = _service(state_root, committed_v2_state)
    admin, owner = _admin(), _user("workspace-owner")
    environment = service.create_environment(
        admin, alias="grant-guard-host", display_name="Grant guard", connection={}
    )
    environment_id = str(environment["environment_id"])
    _grant_environment(state_root, environment_id, "workspace-owner")
    project_id = str(service.create_project(owner, name="Grant guard project")["project_id"])
    first = service.create_workspace(
        owner,
        environment_id=environment_id,
        canonical_path="/tmp/grant-guard-first",
        label="first",
    )
    first_workspace_id = str(first["workspace_id"])

    with pytest.raises(DomainPermissionError, match="Environment access"):
        service.create_workspace(
            admin,
            environment_id=environment_id,
            canonical_path="/tmp/grant-guard-admin-create",
            label="admin create",
        )
    with pytest.raises(DomainPermissionError, match="Environment access"):
        service.create_workspace_and_attach(
            project_id=project_id,
            user=admin,
            environment_id=environment_id,
            canonical_path="/tmp/grant-guard-admin-create-attach",
            label="admin create and attach",
            idempotency_key="admin-create-and-attach",
        )
    with pytest.raises(DomainPermissionError, match="Environment access"):
        service.attach_workspace(
            project_id,
            first_workspace_id,
            admin,
            idempotency_key="admin-attach-without-grant",
        )

    service.attach_workspace(
        project_id,
        first_workspace_id,
        owner,
        idempotency_key="owner-attach-first",
    )
    service.set_primary_workspace(
        project_id,
        first_workspace_id,
        owner,
        idempotency_key="owner-primary-first",
    )
    second = service.create_workspace(
        owner,
        environment_id=environment_id,
        canonical_path="/tmp/grant-guard-second",
        label="second",
    )
    second_workspace_id = str(second["workspace_id"])
    service.attach_workspace(
        project_id,
        second_workspace_id,
        owner,
        idempotency_key="owner-attach-second",
    )
    with pytest.raises(DomainPermissionError, match="Environment access"):
        service.replace_primary_workspace(
            project_id,
            first_workspace_id,
            second_workspace_id,
            admin,
            idempotency_key="admin-replace-primary-without-grant",
        )

    assert (
        'ainrf_domain_permission_denied_total{reason="environment_grant_required",resource="environment"} 4.0'
        in get_metrics_text()
    )
    reset_metrics()


def test_environment_admin_denial_records_bounded_permission_telemetry(
    state_root: Path, committed_v2_state: str
) -> None:
    reset_metrics()
    service = _service(state_root, committed_v2_state)

    with pytest.raises(DomainPermissionError, match="Only admins"):
        service.create_environment(
            _user("member"), alias="member-host", display_name="Member host", connection={}
        )

    assert (
        'ainrf_domain_permission_denied_total{reason="admin_required",resource="environment"} 1.0'
        in get_metrics_text()
    )
    reset_metrics()


def test_invisible_environment_operations_record_bounded_permission_telemetry(
    state_root: Path, committed_v2_state: str
) -> None:
    """A hidden Environment remains a 404 while observability sees the denial."""

    reset_metrics()
    service = _service(state_root, committed_v2_state)
    environment = service.create_environment(
        _admin(), alias="hidden-host", display_name="Hidden host", connection={}
    )
    environment_id = str(environment["environment_id"])
    outsider = _user("environment-outsider")

    with pytest.raises(DomainNotFoundError):
        service.environment(environment_id, outsider)
    with pytest.raises(DomainNotFoundError):
        service.disable_environment(environment_id, outsider)
    with pytest.raises(DomainNotFoundError):
        service.update_environment(environment_id, outsider, display_name="Not allowed")

    assert (
        'ainrf_domain_permission_denied_total{reason="not_visible",resource="environment"} 3.0'
        in get_metrics_text()
    )

    # An absent Environment is not a permission denial, but has the same
    # public result as the hidden one.
    reset_metrics()
    with pytest.raises(DomainNotFoundError):
        service.environment("env-not-present", outsider)
    assert (
        'ainrf_domain_permission_denied_total{reason="not_visible",resource="environment"}'
        not in get_metrics_text()
    )
    reset_metrics()


def test_primary_replacement_and_detach_guard(state_root: Path, committed_v2_state: str) -> None:
    service = _service(state_root, committed_v2_state)
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
    project_id = str(project["project_id"])
    with pytest.raises(DomainConflictError, match="already be an active"):
        service.set_primary_workspace(
            project_id, str(one["workspace_id"]), alice, idempotency_key="unlinked-primary"
        )
    service.attach_workspace(
        project_id, str(one["workspace_id"]), alice, idempotency_key="one-link"
    )
    service.attach_workspace(
        project_id, str(two["workspace_id"]), alice, idempotency_key="two-link"
    )
    service.set_primary_workspace(
        project_id, str(one["workspace_id"]), alice, idempotency_key="one"
    )
    service.replace_primary_workspace(
        project_id,
        str(one["workspace_id"]),
        str(two["workspace_id"]),
        alice,
        idempotency_key="two",
    )
    with pytest.raises(ValueError):
        service.detach_workspace(
            project_id, str(two["workspace_id"]), alice, idempotency_key="detach"
        )


def test_environment_is_disabled_not_hard_deleted_and_secret_is_redacted(
    state_root: Path, committed_v2_state: str
) -> None:
    service = _service(state_root, committed_v2_state)
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
    state_root: Path, committed_v2_state: str
) -> None:
    service = _service(state_root, committed_v2_state)
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
    state_root: Path, committed_v2_state: str
) -> None:
    service = _service(state_root, committed_v2_state)
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


def test_project_viewer_visibility_and_primary_replacement_guards(
    state_root: Path, committed_v2_state: str
) -> None:
    service = _service(state_root, committed_v2_state)
    admin, alice, viewer, outsider = _admin(), _user("alice"), _user("viewer"), _user("outsider")
    seed_user(
        AuthService(state_root=state_root), username="viewer", role="member", user_id="viewer"
    )
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
    service.attach_workspace(
        project_id, str(one["workspace_id"]), alice, idempotency_key="one-link"
    )
    service.attach_workspace(
        project_id, str(two["workspace_id"]), alice, idempotency_key="two-link"
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


def test_referenced_environment_cannot_change_endpoint_identity(
    state_root: Path, committed_v2_state: str
) -> None:
    service = _service(state_root, committed_v2_state)
    admin, alice = _admin(), _user("alice")
    environment = service.create_environment(
        admin,
        alias="immutable-host",
        display_name="Immutable host",
        connection={"host": "one.example", "port": 22, "user": "researcher"},
    )
    environment_id = str(environment["environment_id"])
    _grant_environment(state_root, environment_id, "alice")
    service.create_workspace(
        alice,
        environment_id=environment_id,
        canonical_path="/tmp/immutable-host",
        label="Immutable",
    )

    updated = service.update_environment(
        environment_id,
        admin,
        display_name="Renamed host",
        connection={
            "host": "one.example",
            "port": 22,
            "user": "researcher",
            "default_workdir": "/workspace/new-default",
        },
    )
    assert updated["display_name"] == "Renamed host"
    with pytest.raises(DomainConflictError, match="cannot be repointed"):
        service.update_environment(
            environment_id,
            admin,
            connection={"host": "two.example", "port": 22, "user": "researcher"},
        )


def test_project_membership_publish_capability_and_owner_transfer_guards(
    state_root: Path, committed_v2_state: str
) -> None:
    service = _service(state_root, committed_v2_state)
    auth = AuthService(state_root=state_root)
    seed_user(auth, username="editor", role="member", user_id="editor")
    seed_user(auth, username="new-owner", role="member", user_id="new-owner")
    owner = _user("owner")
    project = service.create_project(owner, name="Transferable")
    project_id = str(project["project_id"])

    service.add_member(project_id, "editor", "editor", True, owner)
    members = service.list_project_members(project_id, owner)
    assert len(members) == 1
    assert members[0]["user_id"] == "editor"
    assert members[0]["role"] == "editor"
    assert bool(members[0]["can_publish"])
    with pytest.raises(DomainConflictError, match="Only editors"):
        service.add_member(project_id, "editor", "viewer", True, owner)

    service.transfer_project_owner(project_id, "new-owner", owner)
    transferred = service.project(project_id, owner)
    assert transferred["owner_user_id"] == "new-owner"
    old_owner_members = service.list_project_members(project_id, _user("new-owner"))
    assert any(
        member["user_id"] == "owner" and member["role"] == "editor" and bool(member["can_publish"])
        for member in old_owner_members
    )

    default_project = service.create_project(owner, name="Default", is_default=True)
    with pytest.raises(DomainConflictError, match="Default Project"):
        service.transfer_project_owner(str(default_project["project_id"]), "new-owner", owner)


def test_member_write_idempotency_is_concurrent_and_actor_scoped(
    state_root: Path, committed_v2_state: str
) -> None:
    service = _service(state_root, committed_v2_state)
    auth = AuthService(state_root=state_root)
    seed_user(auth, username="member-target", role="member", user_id="member-target")
    owner = _user("owner")
    project_id = str(service.create_project(owner, name="Concurrent members")["project_id"])

    def upsert() -> dict[str, object]:
        return service.add_member(
            project_id,
            "member-target",
            "editor",
            True,
            owner,
            idempotency_key="member-race-key",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(upsert) for _ in range(2)]
        first, second = [future.result() for future in futures]

    assert first == second
    assert first == {
        "project_id": project_id,
        "user_id": "member-target",
        "role": "editor",
        "can_publish": True,
    }
    members = [
        member
        for member in service.list_project_members(project_id, owner)
        if member["user_id"] == "member-target"
    ]
    assert len(members) == 1
    assert members[0]["role"] == "editor"
    assert bool(members[0]["can_publish"])
    with pytest.raises(DomainConflictError, match="different request"):
        service.add_member(
            project_id,
            "member-target",
            "viewer",
            False,
            owner,
            idempotency_key="member-race-key",
        )


def test_primary_race_has_one_winner_and_records_link_audit_metadata(
    state_root: Path, committed_v2_state: str
) -> None:
    service = _service(state_root, committed_v2_state)
    admin, owner = _admin(), _user("primary-race-owner")
    environment = service.create_environment(
        admin, alias="primary-race-host", display_name="Primary race", connection={}
    )
    environment_id = str(environment["environment_id"])
    _grant_environment(state_root, environment_id, "primary-race-owner")
    project_id = str(service.create_project(owner, name="Primary race")["project_id"])
    first_workspace = service.create_workspace(
        owner,
        environment_id=environment_id,
        canonical_path="/tmp/primary-race-one",
        label="one",
    )
    second_workspace = service.create_workspace(
        owner,
        environment_id=environment_id,
        canonical_path="/tmp/primary-race-two",
        label="two",
    )
    first_workspace_id = str(first_workspace["workspace_id"])
    second_workspace_id = str(second_workspace["workspace_id"])
    service.attach_workspace(
        project_id, first_workspace_id, owner, idempotency_key="race-attach-one"
    )
    service.attach_workspace(
        project_id, second_workspace_id, owner, idempotency_key="race-attach-two"
    )

    def set_primary(workspace_id: str, key: str) -> dict[str, object] | Exception:
        try:
            return service.set_primary_workspace(
                project_id,
                workspace_id,
                owner,
                idempotency_key=key,
            )
        except Exception as exc:  # deliberate concurrent outcome capture
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(
            executor.map(
                lambda item: set_primary(*item),
                (
                    (first_workspace_id, "primary-race-one"),
                    (second_workspace_id, "primary-race-two"),
                ),
            )
        )

    successes = [outcome for outcome in outcomes if isinstance(outcome, dict)]
    failures = [outcome for outcome in outcomes if isinstance(outcome, Exception)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], DomainConflictError)
    active_links = [
        link
        for link in service.workspace_links(project_id, owner)
        if link["status"] == "active" and link["is_primary"] is True
    ]
    assert len(active_links) == 1

    with connect(state_root / "runtime" / "agentic_researcher.sqlite3") as conn:
        row = conn.execute(
            """
            SELECT metadata_json FROM domain_audit_events
            WHERE event_type = 'workspace.primary_set' AND subject_id = ?
            """,
            (str(active_links[0]["workspace_id"]),),
        ).fetchone()
    assert row is not None
    metadata = json.loads(str(row["metadata_json"]))
    assert metadata["idempotency_key"] in {"primary-race-one", "primary-race-two"}
    assert metadata["new_link"]["is_primary"] is True


def test_workspace_create_and_attach_is_atomic_and_project_filter_uses_active_links(
    state_root: Path, committed_v2_state: str
) -> None:
    service = _service(state_root, committed_v2_state)
    admin, owner = _admin(), _user("atomic-workspace-owner")
    environment = service.create_environment(
        admin, alias="atomic-workspace-host", display_name="Atomic Workspace", connection={}
    )
    environment_id = str(environment["environment_id"])
    _grant_environment(state_root, environment_id, "atomic-workspace-owner")

    with pytest.raises(DomainNotFoundError):
        service.create_workspace_and_attach(
            project_id="missing-project",
            user=owner,
            environment_id=environment_id,
            canonical_path="/tmp/orphan-must-not-exist",
            label="orphan",
            idempotency_key="missing-project-create",
        )
    assert service.list_workspaces(owner) == []

    project_id = str(service.create_project(owner, name="Atomic workspace project")["project_id"])
    first = service.create_workspace_and_attach(
        project_id=project_id,
        user=owner,
        environment_id=environment_id,
        canonical_path="/tmp/atomic-workspace",
        label="atomic",
        idempotency_key="atomic-create",
    )
    replay = service.create_workspace_and_attach(
        project_id=project_id,
        user=owner,
        environment_id=environment_id,
        canonical_path="/tmp/atomic-workspace",
        label="atomic",
        idempotency_key="atomic-create",
    )
    assert replay == first
    workspace_id = str(first["workspace_id"])
    assert [
        item["workspace_id"] for item in service.list_workspaces(owner, project_id=project_id)
    ] == [workspace_id]

    service.detach_workspace(
        project_id,
        workspace_id,
        owner,
        idempotency_key="atomic-detach",
        allow_no_primary=True,
    )
    assert service.list_workspaces(owner, project_id=project_id) == []
