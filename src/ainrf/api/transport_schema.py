"""Build-only assembly for the authoritative HTTP transport schema."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI

from ainrf.api.app import ROUTERS
from ainrf.api.openapi import stable_operation_id
from ainrf.api.routes.metrics import create_metrics_router
from ainrf.runtime.product_config import ApiConfig


def build_transport_openapi() -> dict[str, Any]:
    """Build OpenAPI without constructing runtime or persistence Modules."""

    app = FastAPI(
        title="OpenScience API",
        version="0.1.0",
        generate_unique_id_function=stable_operation_id,
    )
    for router in ROUTERS:
        app.include_router(router, prefix="/api")
    app.include_router(
        create_metrics_router(ApiConfig(api_key_hashes=frozenset(), state_root=Path("/tmp")))
    )
    return app.openapi()
