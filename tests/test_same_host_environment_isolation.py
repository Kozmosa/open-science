from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
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
    nginx = _mapping(services["nginx-staging"])
    nginx_healthcheck = _mapping(nginx["healthcheck"])
    nginx_health_command = nginx_healthcheck["test"]

    assert limits["cpus"] == "8.0"
    assert environment["OPENSCIENCE_PRODUCTION"] == "1"
    assert environment["OPENSCIENCE_AUTH_COOKIE_NAMESPACE"] == "staging"
    assert "STAGING_OPENSCIENCE_NO_SSHD" in str(environment["OPENSCIENCE_NO_SSHD"])
    assert "STAGING_OPENSCIENCE_INTERACTIVE_AUTH_ENABLED" in str(
        environment["OPENSCIENCE_INTERACTIVE_AUTH_ENABLED"]
    )
    assert "STAGING_PUBLIC_REGISTRATION:-false" in str(
        environment["AINRF_PUBLIC_REGISTRATION_ENABLED"]
    )
    assert "STAGING_OPENSCIENCE_STATE_ROOT" in str(environment["OPENSCIENCE_STATE_ROOT"])
    assert environment["OPENSCIENCE_STATE_ROOT"] == environment["AINRF_STATE_ROOT"]
    assert "STAGING_OPENSCIENCE_RUNTIME_RECONCILIATION_ENABLED" in str(
        environment["OPENSCIENCE_RUNTIME_RECONCILIATION_ENABLED"]
    )
    assert isinstance(nginx_health_command, list)
    assert "http://127.0.0.1:7192/api/health" in nginx_health_command
    observability_enabled = environment["AINRF_OBSERVABILITY_ENABLED"]
    assert isinstance(observability_enabled, str)
    assert "STAGING_AINRF_OBSERVABILITY_ENABLED" in observability_enabled


def test_every_deployment_mounts_the_authoritative_prometheus_alert_rules() -> None:
    repo_root = Path(__file__).resolve().parent.parent

    for compose_name in (
        "docker-compose.yml",
        "docker-compose.cpu.yml",
        "docker-compose.gpu.yml",
        "docker-compose.staging.yml",
    ):
        compose = _load_compose(repo_root, compose_name)
        services = _mapping(compose["services"])
        service_name = (
            "prometheus-staging" if compose_name.endswith("staging.yml") else "prometheus"
        )
        prometheus = _mapping(services[service_name])
        volumes = prometheus["volumes"]
        assert isinstance(volumes, list)
        assert (
            "./config/prometheus/rules/ainrf-alerts.yml:/etc/prometheus/rules/ainrf.yml:ro"
            in volumes
        )


def test_staging_prometheus_matches_the_nginx_subpath_contract() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    staging = _load_compose(repo_root, "docker-compose.staging.yml")
    services = _mapping(staging["services"])
    prometheus = _mapping(services["prometheus-staging"])
    command = prometheus["command"]

    assert isinstance(command, list)
    assert "--web.listen-address=127.0.0.1:9092" in command
    assert "--web.external-url=/prometheus" in command
    assert "--web.route-prefix=/prometheus" in command


def test_direct_redeploy_scripts_refuse_to_bypass_staging_isolation() -> None:
    repo_root = Path(__file__).resolve().parent.parent

    for script_name in ("redeploy-backend.sh", "redeploy-frontend.sh"):
        script = (repo_root / "deploy" / script_name).read_text(encoding="utf-8")
        assert "Direct staging redeploy is disabled" in script
        assert "OPENSCIENCE_STAGING_ENV_FILE" in script


def test_staging_lifecycle_publishes_only_explicit_read_only_bind_mounts() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    script = (repo_root / "scripts" / "staging.sh").read_text(encoding="utf-8")

    for path in (
        "src/ainrf",
        "frontend/${STAGING_FRONTEND_OUT_DIR}",
        "deploy/config/nginx-staging.conf",
        "deploy/config/prometheus-staging.yml",
        "deploy/config/prometheus/rules/ainrf-alerts.yml",
        "deploy/config/grafana/provisioning-staging/datasources",
        "deploy/config/grafana/provisioning-staging/dashboards",
        "deploy/config/grafana/dashboards",
    ):
        assert f'"${{REPO_ROOT}}/{path}"' in script
    assert 'chmod -R a+rX "${path}"' in script
    assert script.count("_publish_staging_bind_mounts") == 3


def test_staging_health_poll_uses_the_explicit_env_file() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    staging = (repo_root / "scripts" / "staging.sh").read_text(encoding="utf-8")
    health = (repo_root / "deploy" / "lib" / "health.sh").read_text(encoding="utf-8")

    assert '60 2 "${STAGING_ENV_FILE}"' in staging
    assert 'local env_file="${5:-}"' in health
    assert 'compose_args+=(--env-file "${env_file}")' in health


def test_staging_grafana_preserves_optional_image_provisioning_directories() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    staging = _load_compose(repo_root, "docker-compose.staging.yml")
    services = _mapping(staging["services"])
    grafana = _mapping(services["grafana-staging"])
    volumes = grafana["volumes"]

    assert isinstance(volumes, list)
    assert (
        "./config/grafana/provisioning-staging/datasources:/etc/grafana/provisioning/datasources:ro"
    ) in volumes
    assert (
        "./config/grafana/provisioning-staging/dashboards:/etc/grafana/provisioning/dashboards:ro"
    ) in volumes
    assert "./config/grafana/provisioning-staging:/etc/grafana/provisioning:ro" not in volumes


def test_default_frontend_build_preserves_target_specific_bundles(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    source = repo_root / "frontend" / "scripts" / "prepare-build-output.mjs"
    frontend_root = tmp_path / "frontend"
    script_target = frontend_root / "scripts" / source.name
    script_target.parent.mkdir(parents=True)
    shutil.copy2(source, script_target)

    dist = frontend_root / "dist"
    for target in ("production", "staging", "gpu"):
        target_root = dist / target
        target_root.mkdir(parents=True)
        (target_root / "build-info.json").write_text(target, encoding="utf-8")
    (dist / "assets").mkdir()
    (dist / "assets" / "stale.js").write_text("stale", encoding="utf-8")
    (dist / "index.html").write_text("stale", encoding="utf-8")

    env = os.environ.copy()
    env["OPENSCIENCE_FRONTEND_OUT_DIR"] = "dist"
    result = subprocess.run(
        ["node", str(script_target)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert not (dist / "assets").exists()
    assert not (dist / "index.html").exists()
    for target in ("production", "staging", "gpu"):
        assert (dist / target / "build-info.json").read_text(encoding="utf-8") == target

    package = (repo_root / "frontend" / "package.json").read_text(encoding="utf-8")
    vite_config = (repo_root / "frontend" / "vite.config.ts").read_text(encoding="utf-8")
    assert "node scripts/prepare-build-output.mjs" in package
    assert "emptyOutDir: FRONTEND_OUT_PATH !== SHARED_DIST_ROOT" in vite_config


def test_staging_up_rebuilds_and_remounts_the_current_frontend_bundle() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    script = (repo_root / "scripts" / "staging.sh").read_text(encoding="utf-8")

    assert 'OPENSCIENCE_FRONTEND_OUT_DIR="${STAGING_FRONTEND_OUT_DIR}"' in script
    assert 'if [[ ! -d "${REPO_ROOT}/frontend/${STAGING_FRONTEND_OUT_DIR}" ]]' not in script
    assert "up -d --no-deps --force-recreate nginx-staging" in script
    assert '"nginx-staging" 60 2 "${STAGING_ENV_FILE}"' in script
    assert 'wait_for_url "http://localhost:7192/api/health" 60 2' in script


def test_staging_nginx_exposes_machine_readable_identity() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    nginx_config = (repo_root / "deploy" / "config" / "nginx-staging.conf").read_text(
        encoding="utf-8"
    )

    assert "location = /staging-identity.json" in nginx_config
    assert '\'{"environment":"staging"}\'' in nginx_config


def test_runtime_image_contains_primary_and_compatibility_cli_entrypoints() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    dockerfile = (repo_root / "deploy" / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY --from=backend-build /usr/local/bin/ainrf /usr/local/bin/ainrf" in dockerfile
    assert (
        "COPY --from=backend-build /usr/local/bin/openscience /usr/local/bin/openscience"
        in dockerfile
    )


def test_deploy_scripts_reuse_runtime_env_and_publish_readable_assets() -> None:
    repo_root = Path(__file__).resolve().parent.parent

    for script_name in ("redeploy-backend.sh", "redeploy-frontend.sh"):
        script = (repo_root / "deploy" / script_name).read_text(encoding="utf-8")
        assert 'load_runtime_env_from_container "${RUNTIME_CONTAINER}"' in script
        assert 'chmod -R a+rX "${REPO_ROOT}/frontend/${FRONTEND_OUT_DIR}"' in script
