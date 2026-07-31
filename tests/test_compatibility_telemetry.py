"""Contract tests for bounded compatibility telemetry."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Generator

import httpx
import pytest
from fastapi import APIRouter, FastAPI

from ainrf.api.http_telemetry import (
    build_http_metrics_middleware,
    frozen_contract_operations,
    frozen_contract_routes,
)
from ainrf.api.config import ApiConfig, hash_api_key
from ainrf.telemetry.compatibility import (
    HttpContractObservation,
    classify_surface,
    durable_http_observations,
    observe_http_contract,
)
from ainrf.telemetry import compatibility as compatibility_telemetry
from ainrf.telemetry.metrics import get_metrics_text, reset_metrics
from tests.testutil import create_v2_test_app, get_jwt_headers

pytestmark = [pytest.mark.api]


@pytest.fixture(autouse=True)
def _clean_metrics() -> Generator[None, None, None]:
    reset_metrics()
    yield
    reset_metrics()


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/api/projects", "canonical"),
        ("/projects", "compat_root"),
        ("/v1/projects", "compat_v1"),
        ("/v1/models", "external_compatible"),
        ("/v1/messages", "external_compatible"),
        ("/health", "non_product"),
    ],
)
def test_surface_classification_has_external_protocol_precedence(path: str, expected: str) -> None:
    assert classify_surface(path) == expected


def test_frozen_contract_inventory_expands_lazy_included_routers() -> None:
    route = APIRouter(prefix="/projects")

    @route.get("")
    async def list_projects() -> dict[str, list[object]]:
        return {"items": []}

    concrete = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    concrete.include_router(route, prefix="/api")
    included = tuple(concrete.routes)
    lazy_app = SimpleNamespace(routes=(SimpleNamespace(effective_route_contexts=lambda: included),))

    frozen_routes = frozen_contract_routes(lazy_app)

    assert {item.path for item in frozen_routes} == {"/api/projects"}
    assert frozen_contract_operations(lazy_app) >= {"get_projects", "unmatched"}


@pytest.mark.anyio
async def test_http_matrix_preserves_prefix_and_shared_operation(tmp_path: Path) -> None:
    router = APIRouter(prefix="/projects")

    @router.get("")
    async def list_projects() -> dict[str, list[object]]:
        return {"items": []}

    app = FastAPI()
    app.state.api_config = SimpleNamespace(state_root=tmp_path)
    app.include_router(router)
    app.include_router(router, prefix="/v1")
    app.include_router(router, prefix="/api")
    operations = frozen_contract_operations(app)
    app.middleware("http")(
        build_http_metrics_middleware(
            allowed_operations=operations,
            contract_routes=frozen_contract_routes(app),
            state_root=tmp_path,
        )
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for path in ("/api/projects", "/projects", "/v1/projects"):
            assert (await client.get(path)).status_code == 200

    text = get_metrics_text()
    for surface in ("canonical", "compat_root", "compat_v1"):
        assert (
            f'ainrf_http_contract_requests_total{{method="GET",operation="get_projects",'
            f'status_class="2xx",surface="{surface}"}} 1.0' in text
        )
    rows = durable_http_observations(tmp_path)
    assert {(row["surface"], row["operation"], row["count"]) for row in rows} == {
        ("canonical", "get_projects", 1),
        ("compat_root", "get_projects", 1),
        ("compat_v1", "get_projects", 1),
    }


@pytest.mark.anyio
async def test_product_resource_matrix_only_exposes_canonical_prefix(tmp_path: Path) -> None:
    app = create_v2_test_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key("telemetry-key")}),
            state_root=tmp_path,
            metrics_enabled=True,
        )
    )
    headers = get_jwt_headers(app)
    resources = {
        "projects": ("/api/domain/projects", "get_domain_projects"),
        "workspaces": ("/api/domain/workspaces", "get_domain_workspaces"),
        "environments": ("/api/domain/environments", "get_domain_environments"),
        "tasks": ("/api/tasks", "get_tasks"),
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for resource, (canonical_path, _) in resources.items():
            canonical = await client.get(canonical_path, headers=headers)
            root_alias = await client.get(f"/{resource}", headers=headers)
            v1_alias = await client.get(f"/v1/{resource}", headers=headers)
            assert canonical.status_code == 200, (resource, canonical.text)
            assert root_alias.status_code == 404, (resource, root_alias.text)
            assert v1_alias.status_code == 404, (resource, v1_alias.text)

    text = get_metrics_text()
    for _, operation in resources.values():
        assert (
            f'ainrf_http_contract_requests_total{{method="GET",operation="{operation}",'
            'status_class="2xx",surface="canonical"} 1.0' in text
        )


@pytest.mark.anyio
async def test_external_compatible_protocol_is_not_product_v1(tmp_path: Path) -> None:
    app = create_v2_test_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key("telemetry-key")}),
            state_root=tmp_path,
            metrics_enabled=True,
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/v1/models")

    assert response.status_code == 404
    text = get_metrics_text()
    assert (
        'ainrf_http_contract_requests_total{method="GET",operation="get_models",'
        'status_class="4xx",surface="external_compatible"} 1.0' in text
    )
    assert 'operation="get_models",status_class="4xx",surface="compat_v1"' not in text


def test_operation_allowlist_rejects_dynamic_values_and_secrets(tmp_path: Path) -> None:
    secret_operation = "get_projects_tenant_42_private_token"
    observe_http_contract(
        HttpContractObservation(
            actual_path="/api/projects/private-resource-id",
            operation=secret_operation,
            method="GET",
            status=200,
            duration_seconds=0.01,
            allowed_operations=frozenset({"get_projects", "unmatched"}),
            state_root=tmp_path,
        )
    )

    text = get_metrics_text()
    assert 'operation="unmatched"' in text
    assert secret_operation not in text
    assert "private-resource-id" not in text


def test_durable_http_aggregate_survives_process_metric_reset(tmp_path: Path) -> None:
    observation = HttpContractObservation(
        actual_path="/v1/tasks",
        operation="get_tasks",
        method="GET",
        status=200,
        duration_seconds=0.01,
        allowed_operations=frozenset({"get_tasks", "unmatched"}),
        state_root=tmp_path,
    )
    observe_http_contract(observation)
    reset_metrics()
    observe_http_contract(observation)

    rows = durable_http_observations(tmp_path)
    assert len(rows) == 1
    assert rows[0]["surface"] == "compat_v1"
    assert rows[0]["operation"] == "get_tasks"
    assert rows[0]["count"] == 2


def test_durable_failure_is_latched_without_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fail(*_args: object, **_kwargs: object) -> None:
        raise sqlite3.OperationalError("simulated")

    import sqlite3

    monkeypatch.setattr(compatibility_telemetry, "_persist_http_observation", _fail)
    observe_http_contract(
        HttpContractObservation(
            actual_path="/api/tasks",
            operation="get_tasks",
            method="GET",
            status=200,
            duration_seconds=0.01,
            allowed_operations=frozenset({"get_tasks", "unmatched"}),
            state_root=tmp_path,
        )
    )

    assert (tmp_path / "runtime" / "compatibility_telemetry_delivery_failure.json").is_file()
    assert "ainrf_http_contract_telemetry_delivery_failure_latched 1.0" in get_metrics_text()


def test_supported_config_alias_remains_available_without_secret_exposure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret_hash = "private-api-key-hash"
    monkeypatch.delenv("AINRF_API_KEY_HASHES", raising=False)
    monkeypatch.setenv("OPENSCIENCE_API_KEY_HASHES", secret_hash)

    config = ApiConfig.from_env(state_root=tmp_path)

    assert config.api_key_hashes == frozenset({secret_hash})
    assert secret_hash not in get_metrics_text()
