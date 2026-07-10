from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
import yaml

pytestmark = [pytest.mark.cli]


def _mapping(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def _load_compose(repo_root: Path, name: str) -> dict[str, object]:
    path = repo_root / "deploy" / name
    payload: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    return _mapping(payload)


def test_production_and_staging_use_separate_compose_projects_and_frontends() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    production = _load_compose(repo_root, "docker-compose.cpu.yml")
    staging = _load_compose(repo_root, "docker-compose.staging.yml")

    assert production["name"] == "deploy"
    assert staging["name"] == "openscience-staging"

    production_services = _mapping(production["services"])
    staging_services = _mapping(staging["services"])

    production_nginx = _mapping(production_services["nginx"])
    staging_nginx = _mapping(staging_services["nginx-staging"])
    production_volumes = production_nginx["volumes"]
    staging_volumes = staging_nginx["volumes"]
    assert isinstance(production_volumes, list)
    assert isinstance(staging_volumes, list)
    assert "../frontend/dist/production:/usr/share/nginx/html:ro" in production_volumes
    assert "../frontend/dist/staging:/usr/share/nginx/html:ro" in staging_volumes


def test_staging_uses_separate_cookie_and_observability_configuration() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    staging = _load_compose(repo_root, "docker-compose.staging.yml")
    services = _mapping(staging["services"])
    backend = _mapping(services["ainrf-staging"])
    environment = _mapping(backend["environment"])
    deploy = _mapping(backend["deploy"])
    resources = _mapping(deploy["resources"])
    limits = _mapping(resources["limits"])

    assert limits["cpus"] == "8.0"
    assert environment["OPENSCIENCE_AUTH_COOKIE_NAMESPACE"] == "staging"
    observability_enabled = environment["AINRF_OBSERVABILITY_ENABLED"]
    assert isinstance(observability_enabled, str)
    assert "STAGING_AINRF_OBSERVABILITY_ENABLED" in observability_enabled


def test_runtime_image_contains_primary_and_compatibility_cli_entrypoints() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    dockerfile = (repo_root / "deploy" / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY --from=backend-build /usr/local/bin/ainrf /usr/local/bin/ainrf" in dockerfile
    assert (
        "COPY --from=backend-build /usr/local/bin/openscience /usr/local/bin/openscience"
        in dockerfile
    )
