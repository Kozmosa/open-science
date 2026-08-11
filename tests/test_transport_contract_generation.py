from __future__ import annotations

import hashlib
import json
import re
import ast
from pathlib import Path

import pytest

from ainrf.api.transport_schema import build_transport_openapi

pytestmark = [pytest.mark.unit]

_REPO_ROOT = Path(__file__).resolve().parents[1]
_GENERATED_ROOT = _REPO_ROOT / "frontend" / "src" / "generated" / "transport"


def test_generated_openapi_matches_backend_authority() -> None:
    generated_bytes = (_GENERATED_ROOT / "openapi.json").read_bytes()
    generated_schema = json.loads(generated_bytes)
    assert generated_schema == build_transport_openapi()

    manifest = json.loads((_GENERATED_ROOT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest == {
        "generator": "@hey-api/openapi-ts",
        "generatorVersion": "0.99.0",
        "openapiVersion": generated_schema["openapi"],
        "schemaSha256": hashlib.sha256(generated_bytes).hexdigest(),
    }


def test_task_mutation_response_uses_strict_task_summary_reference() -> None:
    schema = build_transport_openapi()
    mutation = schema["components"]["schemas"]["ConversationTaskMutationResponse"]
    assert mutation["additionalProperties"] is False
    assert mutation["properties"]["task"] == {"$ref": "#/components/schemas/TaskSummaryResponse"}
    assert schema["components"]["schemas"]["TaskSummaryResponse"]["additionalProperties"] is False

    generated_types = (_GENERATED_ROOT / "schema.ts").read_text(encoding="utf-8")
    start = generated_types.index("export type ConversationTaskMutationResponse = {")
    end = generated_types.index("};", start) + 2
    assert "task: TaskSummaryResponse;" in generated_types[start:end]


def test_file_entry_kind_uses_the_domain_union_in_transport() -> None:
    schema = build_transport_openapi()
    kind_schema = schema["components"]["schemas"]["FileEntryResponse"]["properties"]["kind"]
    assert kind_schema["enum"] == ["file", "directory", "symlink"]

    generated_types = (_GENERATED_ROOT / "schema.ts").read_text(encoding="utf-8")
    start = generated_types.index("export type FileEntryResponse = {")
    end = generated_types.index("};", start) + 2
    assert "kind: 'file' | 'directory' | 'symlink';" in generated_types[start:end]


def test_conversation_responses_use_domain_enums_in_transport() -> None:
    schema = build_transport_openapi()
    schemas = schema["components"]["schemas"]
    assert schemas["TurnSubmissionIntent"]["enum"] == ["create", "retry", "next_turn"]
    expected_refs = {
        ("TurnSubmissionResponse", "status"): "TurnSubmissionStatus",
        ("TurnSubmissionResponse", "intent"): "TurnSubmissionIntent",
        ("TurnResponse", "status"): "TurnStatus",
        ("TurnItemResponse", "item_type"): "TurnItemType",
        ("TurnItemResponse", "actor"): "TurnItemActor",
        ("TurnControlResponse", "kind"): "ControlKind",
        ("TurnControlResponse", "status"): "ControlRequestStatus",
        ("TaskHealthResponse", "status"): "ConversationTaskStatus",
    }
    for (response_name, field_name), enum_name in expected_refs.items():
        assert schemas[response_name]["properties"][field_name]["$ref"] == (
            f"#/components/schemas/{enum_name}"
        )

    generated_types = (_GENERATED_ROOT / "schema.ts").read_text(encoding="utf-8")
    expected_types = {
        "TurnSubmissionResponse": (
            "status: TurnSubmissionStatus;",
            "intent: TurnSubmissionIntent;",
        ),
        "TurnResponse": ("status: TurnStatus;",),
        "TurnItemResponse": ("item_type: TurnItemType;", "actor: TurnItemActor;"),
        "TurnControlResponse": ("kind: ControlKind;", "status: ControlRequestStatus;"),
        "TaskHealthResponse": ("status: ConversationTaskStatus;",),
    }
    for response_name, declarations in expected_types.items():
        start = generated_types.index(f"export type {response_name} = {{")
        end = generated_types.index("};", start) + 2
        for declaration in declarations:
            assert declaration in generated_types[start:end]


def test_auth_responses_use_domain_enums_and_typed_user_transport() -> None:
    schema = build_transport_openapi()
    schemas = schema["components"]["schemas"]
    assert schemas["UserRole"]["enum"] == ["admin", "member"]
    assert schemas["UserStatus"]["enum"] == ["pending", "active", "disabled"]
    assert schemas["UserInfoResponse"]["properties"]["role"] == {
        "$ref": "#/components/schemas/UserRole"
    }
    assert schemas["UserInfoResponse"]["properties"]["status"] == {
        "$ref": "#/components/schemas/UserStatus"
    }
    assert schemas["AuthTokenResponse"]["properties"]["user"] == {
        "$ref": "#/components/schemas/UserInfoResponse"
    }
    assert schemas["AdminUserResponse"]["properties"]["role"] == {
        "$ref": "#/components/schemas/UserRole"
    }
    assert schemas["AdminUserResponse"]["properties"]["status"] == {
        "$ref": "#/components/schemas/UserStatus"
    }
    update_status = schemas["AdminUserUpdateRequest"]["properties"]["status"]
    assert update_status["enum"] == ["active", "disabled"]
    assert schemas["AdminUserUpdateRequest"]["required"] == ["status"]

    generated_types = (_GENERATED_ROOT / "schema.ts").read_text(encoding="utf-8")
    expected_types = {
        "UserInfoResponse": ("role: UserRole;", "status: UserStatus;"),
        "AuthTokenResponse": ("user: UserInfoResponse;",),
        "AdminUserResponse": ("role: UserRole;", "status: UserStatus;"),
        "AdminUserUpdateRequest": ("status: 'active' | 'disabled';",),
    }
    for response_name, declarations in expected_types.items():
        start = generated_types.index(f"export type {response_name} = {{")
        end = generated_types.index("};", start) + 2
        for declaration in declarations:
            assert declaration in generated_types[start:end]


def test_operation_ids_are_unique_stable_and_cover_canonical_metadata() -> None:
    schema = build_transport_openapi()
    operations: list[tuple[str, str, str, bool]] = []
    for path, path_item in schema["paths"].items():
        for method, operation in path_item.items():
            if method not in {"delete", "get", "head", "options", "patch", "post", "put"}:
                continue
            operation_id = operation["operationId"]
            normalized_path = re.sub(r"[^a-zA-Z0-9]+", "_", path).strip("_").lower()
            assert operation_id == f"{method}_{normalized_path}"
            operations.append(
                (operation_id, method.upper(), path, operation.get("deprecated", False))
            )

    operation_ids = [operation[0] for operation in operations]
    assert len(operation_ids) == len(set(operation_ids))
    canonical_count = sum(path.startswith("/api/") for _, _, path, _ in operations)
    metadata_source = (_GENERATED_ROOT / "operations.ts").read_text(encoding="utf-8")
    assert metadata_source.count('"canonical": true') == canonical_count
    for operation_id, method, path, deprecated in operations:
        assert f'"{operation_id}"' in metadata_source
        assert f'"method": "{method}"' in metadata_source
        assert f'"path": "{path}"' in metadata_source
        assert f'"deprecated": {str(deprecated).lower()}' in metadata_source

    generated_types = (_GENERATED_ROOT / "schema.ts").read_text(encoding="utf-8")
    assert "export type EnvironmentAuthKind = 'ssh_key' | 'password' | 'agent';" in generated_types
    assert "description?: string | null;" in generated_types
    assert '"deprecated": true' not in metadata_source


def test_route_modules_do_not_own_pydantic_transport_models() -> None:
    routes_root = _REPO_ROOT / "src" / "ainrf" / "api" / "routes"
    for route_path in sorted(routes_root.glob("*.py")):
        tree = ast.parse(route_path.read_text(encoding="utf-8"), filename=str(route_path))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            assert all(
                not (isinstance(base, ast.Name) and base.id == "BaseModel") for base in node.bases
            ), f"move {route_path.name}:{node.name} into the authoritative schema Module"
