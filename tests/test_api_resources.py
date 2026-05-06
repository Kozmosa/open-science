from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from ainrf.api.app import create_app
from ainrf.api.config import ApiConfig, hash_api_key
from ainrf.execution import ContainerConfig


@pytest.mark.anyio
async def test_get_resources_returns_list(tmp_path: Path) -> None:
    app = create_app(
        ApiConfig(
            api_key_hashes=frozenset({hash_api_key("secret-key")}),
            state_root=tmp_path,
            container_config=ContainerConfig(host="gpu-server-01", user="root"),
        )
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers={"X-API-Key": "secret-key"},
    ) as client:
        response = await client.get("/resources")

    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert isinstance(data["items"], list)
