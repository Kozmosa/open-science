#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/deploy/docker-compose.release-staging.yml"
COMMAND="${1:-status}"
MANIFEST_PATH="${OPENSCIENCE_RELEASE_MANIFEST:-}"
ENV_FILE="${OPENSCIENCE_RELEASE_STAGING_ENV_FILE:-}"

require_env_file() {
  [[ -n "${ENV_FILE}" && -f "${ENV_FILE}" ]] || {
    echo "Set OPENSCIENCE_RELEASE_STAGING_ENV_FILE to a staging-only env file outside the repository." >&2
    exit 2
  }
  local resolved_env resolved_repo mode
  resolved_env="$(realpath "${ENV_FILE}")"
  resolved_repo="$(realpath "${REPO_ROOT}")"
  [[ "${resolved_env}" != "${resolved_repo}" && "${resolved_env}" != "${resolved_repo}/"* ]] || {
    echo "Release staging env file must live outside the repository." >&2
    exit 2
  }
  mode="$(stat -c '%a' "${resolved_env}")"
  (( ((8#${mode}) & 8#077) == 0 )) || {
    echo "Release staging env file must not be group- or world-readable." >&2
    exit 2
  }
  ENV_FILE="${resolved_env}"
}

load_release() {
  require_env_file
  [[ -n "${OPENSCIENCE_RELEASE_STAGING_API_KEY:-}" ]] || {
    echo "Set OPENSCIENCE_RELEASE_STAGING_API_KEY to a disposable release-staging API key." >&2
    exit 2
  }
  [[ -n "${MANIFEST_PATH}" ]] || {
    echo "Set OPENSCIENCE_RELEASE_MANIFEST to the manifest produced by build-production.sh." >&2
    exit 2
  }
  set -a
  # shellcheck disable=SC1090
  source "${MANIFEST_PATH}"
  set +a
  "${REPO_ROOT}/deploy/verify-release-manifest.sh" "${MANIFEST_PATH}"
  OPENSCIENCE_RELEASE_DOMAIN_ARTIFACT_SHA="${OPENSCIENCE_API_IMAGE_ID#sha256:}"
  export OPENSCIENCE_RELEASE_DOMAIN_ARTIFACT_SHA
}

compose() {
  docker compose --project-name openscience-release-staging \
    --env-file "${ENV_FILE}" --file "${COMPOSE_FILE}" "$@"
}

case "${COMMAND}" in
  up)
    load_release
    compose up -d --no-build --wait
    echo "Release staging is ready at http://127.0.0.1:7192/"
    echo "Perform the human acceptance pass, then run: bash deploy/release-staging.sh smoke"
    ;;
  smoke)
    curl --fail --silent --show-error http://127.0.0.1:17000/api/health >/dev/null
    curl --fail --silent --show-error http://127.0.0.1:7192/ >/dev/null
    curl --fail --silent --show-error http://127.0.0.1:7192/api/health >/dev/null
    echo "Release staging smoke passed. Human acceptance remains the release authority."
    ;;
  status)
    require_env_file
    compose ps
    ;;
  down)
    require_env_file
    compose down --remove-orphans
    ;;
  purge)
    require_env_file
    [[ "${OPENSCIENCE_RELEASE_STAGING_PURGE_ACK:-}" == "remove-disposable-release-staging-data" ]] || {
      echo "Set OPENSCIENCE_RELEASE_STAGING_PURGE_ACK=remove-disposable-release-staging-data." >&2
      exit 2
    }
    compose down --volumes --remove-orphans
    ;;
  *)
    echo "Usage: bash deploy/release-staging.sh {up|smoke|status|down|purge}" >&2
    exit 2
    ;;
esac
