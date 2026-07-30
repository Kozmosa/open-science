"""Simple, human-gated release workflow contracts."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.cli]


def test_release_staging_reuses_production_images_without_builds_or_source_mounts() -> None:
    root = Path(__file__).resolve().parents[1]
    compose = yaml.safe_load(
        (root / "deploy/docker-compose.release-staging.yml").read_text(encoding="utf-8")
    )
    services = compose["services"]
    assert services["api"]["image"].startswith("${OPENSCIENCE_API_IMAGE")
    assert services["web"]["image"].startswith("${OPENSCIENCE_WEB_IMAGE")
    assert all("build" not in service for service in services.values())
    assert all("container_name" not in service for service in services.values())
    assert services["api"]["environment"]["AINRF_PORT"] == "17000"
    assert services["api"]["environment"]["AINRF_RUNTIME_RECONCILIATION_ENABLED"] == (
        "false"
    )
    assert services["api"]["environment"]["AINRF_DOMAIN_ARTIFACT_SHA"].startswith(
        "${OPENSCIENCE_RELEASE_DOMAIN_ARTIFACT_SHA"
    )
    assert services["api"]["depends_on"]["init"]["condition"] == (
        "service_completed_successfully"
    )
    assert services["init"]["command"][:3] == [
        "openscience",
        "frontend-dev",
        "prepare",
    ]
    assert any(
        value.startswith("${OPENSCIENCE_RELEASE_STAGING_API_KEY")
        for value in services["init"]["command"]
    )
    assert any(
        value.startswith("${OPENSCIENCE_RELEASE_DOMAIN_ARTIFACT_SHA")
        for value in services["init"]["command"]
    )
    assert services["web"]["environment"]["AINRF_WEB_PORT"] == "7192"
    mounted_sources = str(compose)
    assert "src/" not in mounted_sources
    assert "frontend/" not in mounted_sources
    assert "docker.sock" not in mounted_sources


def test_release_manifest_binds_each_image_to_its_local_image_id() -> None:
    root = Path(__file__).resolve().parents[1]
    build = (root / "deploy/build-production.sh").read_text(encoding="utf-8")
    verifier = (root / "deploy/verify-release-manifest.sh").read_text(encoding="utf-8")
    production = (root / "deploy/release-production.sh").read_text(encoding="utf-8")
    for name in ("API", "WEB", "PROMETHEUS", "GRAFANA"):
        assert f"OPENSCIENCE_{name}_IMAGE_ID" in build
        assert f"OPENSCIENCE_{name}_IMAGE_ID" in verifier
    assert "docker image inspect" in verifier
    assert "deploy/verify-release-manifest.sh" in production


def test_release_staging_is_human_gated_and_never_drives_production() -> None:
    root = Path(__file__).resolve().parents[1]
    script = (root / "deploy/release-staging.sh").read_text(encoding="utf-8")
    assert "Human acceptance remains the release authority" in script
    assert "--no-build --wait" in script
    assert "openscience-release-staging" in script
    assert "ainrf-nginx" not in script
    assert "release-production.sh" not in script
    assert "promote-production" not in script
    assert "ledger" not in script
    assert "OPENSCIENCE_RELEASE_STAGING_API_KEY" in script
    assert '"${OPENSCIENCE_API_IMAGE_ID#sha256:}"' in script


def test_web_image_uses_one_port_parameterized_nginx_template() -> None:
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "deploy/Dockerfile").read_text(encoding="utf-8")
    template = (root / "deploy/config/nginx-release.conf.template").read_text(encoding="utf-8")
    production = (root / "deploy/docker-compose.cpu.yml").read_text(encoding="utf-8")
    assert "nginx-release.conf.template" in dockerfile
    assert "NGINX_ENVSUBST_FILTER=^AINRF_" in dockerfile
    assert "listen ${AINRF_WEB_PORT};" in template
    assert "127.0.0.1:${AINRF_BACKEND_PORT}" in template
    assert 'AINRF_WEB_PORT: "8192"' in production


def test_development_and_mutable_staging_remain_separate_paths() -> None:
    root = Path(__file__).resolve().parents[1]
    dev = (root / "scripts/dev.sh").read_text(encoding="utf-8")
    staging = (root / "scripts/staging.sh").read_text(encoding="utf-8")
    release_staging = (root / "deploy/release-staging.sh").read_text(encoding="utf-8")
    assert "uv run python" in dev
    assert "--build" in staging
    assert "Hot-reload is active" in staging
    assert "--no-build" in release_staging
