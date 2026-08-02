#!/usr/bin/env bash
set -euo pipefail

MANIFEST_PATH="${1:-}"
if [[ -z "${MANIFEST_PATH}" || ! -f "${MANIFEST_PATH}" || -L "${MANIFEST_PATH}" ]]; then
  echo "Release manifest must be an existing regular file." >&2
  exit 2
fi

mode="$(stat -c '%a' "${MANIFEST_PATH}")"
if (( (8#${mode}) & 8#077 )); then
  echo "Release manifest must not be group- or world-readable." >&2
  exit 2
fi

set -a
# shellcheck disable=SC1090
source "${MANIFEST_PATH}"
set +a

required=(
  OPENSCIENCE_RELEASE_ID
  OPENSCIENCE_RELEASE_GIT_SHA
  OPENSCIENCE_API_IMAGE OPENSCIENCE_API_IMAGE_ID
  OPENSCIENCE_WEB_IMAGE OPENSCIENCE_WEB_IMAGE_ID
  OPENSCIENCE_PROMETHEUS_IMAGE OPENSCIENCE_PROMETHEUS_IMAGE_ID
  OPENSCIENCE_GRAFANA_IMAGE OPENSCIENCE_GRAFANA_IMAGE_ID
  OPENSCIENCE_GATUS_IMAGE OPENSCIENCE_GATUS_IMAGE_ID
)
for name in "${required[@]}"; do
  [[ -n "${!name:-}" ]] || {
    echo "Release manifest is missing ${name}." >&2
    exit 2
  }
done

verify_image() {
  local label="$1"
  local image="$2"
  local expected_id="$3"
  local actual_id
  actual_id="$(docker image inspect --format '{{.Id}}' "${image}" 2>/dev/null)" || {
    echo "${label} image is not available locally: ${image}" >&2
    exit 2
  }
  [[ "${actual_id}" == "${expected_id}" ]] || {
    echo "${label} image does not match the release manifest." >&2
    exit 2
  }
}

verify_image API "${OPENSCIENCE_API_IMAGE}" "${OPENSCIENCE_API_IMAGE_ID}"
verify_image Web "${OPENSCIENCE_WEB_IMAGE}" "${OPENSCIENCE_WEB_IMAGE_ID}"
verify_image Prometheus "${OPENSCIENCE_PROMETHEUS_IMAGE}" "${OPENSCIENCE_PROMETHEUS_IMAGE_ID}"
verify_image Grafana "${OPENSCIENCE_GRAFANA_IMAGE}" "${OPENSCIENCE_GRAFANA_IMAGE_ID}"
verify_image Gatus "${OPENSCIENCE_GATUS_IMAGE}" "${OPENSCIENCE_GATUS_IMAGE_ID}"

printf 'Release %s verified (%s).\n' "${OPENSCIENCE_RELEASE_ID}" "${OPENSCIENCE_RELEASE_GIT_SHA}"
