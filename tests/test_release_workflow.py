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
    assert services["api"]["environment"]["AINRF_RUNTIME_RECONCILIATION_ENABLED"] == ("false")
    assert services["api"]["environment"]["AINRF_DOMAIN_ARTIFACT_SHA"].startswith(
        "${OPENSCIENCE_RELEASE_DOMAIN_ARTIFACT_SHA"
    )
    assert services["api"]["depends_on"]["init"]["condition"] == ("service_completed_successfully")
    expected_workspace_mount = "release-staging-workspaces:/opt/ainrf/state-workspaces"
    assert expected_workspace_mount in services["init"]["volumes"]
    assert expected_workspace_mount in services["api"]["volumes"]
    assert services["init"]["environment"]["AINRF_NO_SSHD"] == "1"
    dockerfile = (root / "deploy/Dockerfile").read_text(encoding="utf-8")
    assert "mkdir -p /opt/ainrf/state /opt/ainrf/state-workspaces" in dockerfile
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
    assert services["web"]["environment"]["AINRF_GATUS_PORT"] == "8080"
    mounted_sources = str(compose)
    assert "src/" not in mounted_sources
    assert "frontend/" not in mounted_sources
    assert "docker.sock" not in mounted_sources


def test_container_tenant_provisioning_uses_stable_auth_row_order() -> None:
    root = Path(__file__).resolve().parents[1]
    entrypoint = (root / "deploy/config/entrypoint.py").read_text(encoding="utf-8")
    assert "SELECT username FROM users ORDER BY rowid" in entrypoint


def test_release_manifest_binds_each_image_to_its_local_image_id() -> None:
    root = Path(__file__).resolve().parents[1]
    build = (root / "deploy/build-production.sh").read_text(encoding="utf-8")
    verifier = (root / "deploy/verify-release-manifest.sh").read_text(encoding="utf-8")
    production = (root / "deploy/release-production.sh").read_text(encoding="utf-8")
    for name in ("API", "WEB", "PROMETHEUS", "GRAFANA", "GATUS"):
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
    assert "RUN chmod -R a+rX /usr/share/nginx/html" in dockerfile
    assert "RUN chmod -R a+rX /opt/ainrf/frontend/dist" in dockerfile


def test_production_monitoring_services_use_runtime_ports_and_readable_config() -> None:
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "deploy/Dockerfile").read_text(encoding="utf-8")
    compose = yaml.safe_load((root / "deploy/docker-compose.cpu.yml").read_text(encoding="utf-8"))

    redis = compose["services"]["literature-redis"]
    domain_worker = compose["services"]["domain-worker"]
    literature_worker = compose["services"]["literature-worker"]
    assert redis["command"][redis["command"].index("--port") + 1] == "16379"
    assert "redis-cli -p 16379" in redis["healthcheck"]["test"][1]
    assert domain_worker["healthcheck"] == {"disable": True}
    assert literature_worker["command"][:3] == ["python", "-m", "dramatiq"]
    assert literature_worker["healthcheck"] == {"disable": True}
    assert "FROM docker.1ms.run/prom/prometheus:v3.3.1 AS prometheus\nUSER root" in dockerfile
    assert "RUN chmod -R a+rX /etc/prometheus" in dockerfile
    assert "RUN chmod -R a+rX /etc/prometheus\nUSER nobody" in dockerfile


def test_development_and_mutable_staging_remain_separate_paths() -> None:
    root = Path(__file__).resolve().parents[1]
    dev = (root / "scripts/dev.sh").read_text(encoding="utf-8")
    staging = (root / "scripts/staging.sh").read_text(encoding="utf-8")
    release_staging = (root / "deploy/release-staging.sh").read_text(encoding="utf-8")
    assert "uv run python" in dev
    assert "--build" in staging
    assert "Hot-reload is active" in staging
    assert "--no-build" in release_staging


def test_gatus_is_an_immutable_public_uptime_service_with_isolated_routes() -> None:
    root = Path(__file__).resolve().parents[1]
    compose = yaml.safe_load((root / "deploy/docker-compose.cpu.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    gatus = services["gatus"]
    nginx = services["nginx"]
    config = yaml.safe_load((root / "deploy/config/gatus.yaml").read_text(encoding="utf-8"))

    assert gatus["image"].startswith("${OPENSCIENCE_GATUS_IMAGE")
    assert gatus["network_mode"] == "host"
    assert gatus["environment"]["GATUS_WEB_ADDRESS"] == "127.0.0.1"
    assert gatus["environment"]["GATUS_WEB_PORT"] == "8080"
    assert "ports" not in gatus
    assert "gatus-data:/data" in gatus["volumes"]
    assert nginx["environment"]["AINRF_GATUS_PORT"] == "8080"
    assert nginx["depends_on"]["gatus"]["condition"] == "service_started"

    assert config["metrics"] is True
    assert config["storage"]["type"] == "sqlite"
    assert config["ui"]["title"] == "OpenScience Status"
    assert config["ui"]["logo"].startswith("data:image/svg+xml,")
    assert config["ui"]["buttons"] == [{"name": "OpenScience", "link": "/"}]
    assert "--osci-shadow-card" in config["ui"]["custom-css"]
    assert ".endpoint-group" in config["ui"]["custom-css"]
    assert [endpoint["group"] for endpoint in config["endpoints"]] == [
        "Production",
        "Staging",
        "Development",
    ]
    assert config["endpoints"][2]["enabled"] == "${GATUS_DEVELOPMENT_ENABLED}"
    assert all(endpoint["ui"]["hide-hostname"] for endpoint in config["endpoints"])
    dockerfile = (root / "deploy/Dockerfile").read_text(encoding="utf-8")
    assert "twinproduction/gatus:v5.36.0 AS gatus" in dockerfile

    for relative_path in (
        "deploy/config/nginx-release.conf.template",
        "deploy/config/nginx-host.conf",
        "deploy/config/nginx-staging.conf",
        "deploy/config/nginx-bridge.conf",
        "deploy/nginx-docker.conf",
    ):
        nginx_config = (root / relative_path).read_text(encoding="utf-8")
        assert "location = /uptime" in nginx_config
        assert "location /uptime/" in nginx_config
        assert "sub_filter '\"/api/v1' '\"/uptime/api/v1';" in nginx_config
        assert "sub_filter '`/api/v1' '`/uptime/api/v1';" in nginx_config
        assert "'(0,i.PO)(\"/\")' '(0,i.PO)(\"/uptime/\")'" in nginx_config
        assert nginx_config.index("location /uptime/") < nginx_config.index("location /api/")
