#!/usr/bin/env bats
# Tests for bootc-build/setup-runner native-overlay validation and storage setup.
#
# The shell logic lives inline in bootc-build/setup-runner/action.yml. Keep these
# snippets verbatim so action changes must update their regression tests.

VALIDATION_LOGIC=$(cat <<'EOF'
set -euo pipefail
case "${NATIVE_OVERLAY}" in
  true|false) ;;
  *)
    echo "::error::native-overlay must be 'true' or 'false'."
    exit 1
    ;;
esac
EOF
)

NATIVE_OVERLAY_LOGIC=$(cat <<'NATIVE_LOGIC_EOF'
set -euo pipefail

PODMAN_VERSION=$(sudo podman --version 2>/dev/null | awk '{print $3}')
if [[ ! "${PODMAN_VERSION}" =~ ^([0-9]+)\. ]] || (( BASH_REMATCH[1] < 5 )); then
  echo "::error::native-overlay requires the runner's Podman 5.x or newer; found '${PODMAN_VERSION:-unknown}'."
  exit 1
fi

# Reset while the old configuration is still active. containers/storage
# records mount-program use in overlay/.has-mount-program, so editing the
# configuration alone can leave fuse-overlayfs selected.
sudo podman system reset --force

sudo install -d -m 0755 /etc/containers
sudo tee /etc/containers/storage.conf >/dev/null <<'EOF'
[storage]
driver = "overlay"
runroot = "/run/containers/storage"
graphroot = "/var/lib/containers/storage"

[storage.options.overlay]
mountopt = "nodev"
EOF

# podman system reset removes graphroot; remove the marker explicitly as
# a fail-safe for runner-image implementations that preserve the path.
sudo rm -f /var/lib/containers/storage/overlay/.has-mount-program

INFO=$(sudo podman info --format json)
DRIVER=$(jq -r '.store.graphDriverName // empty' <<<"${INFO}")
NATIVE_DIFF=$(jq -r '.store.graphStatus["Native Overlay Diff"] // empty' <<<"${INFO}")
GRAPH_OPTIONS=$(jq -c '.store.graphOptions // {}' <<<"${INFO}")

if [[ "${DRIVER}" != "overlay" ]]; then
  echo "::error::Expected rootful Podman storage driver 'overlay', found '${DRIVER:-unknown}'."
  exit 1
fi
if [[ "${NATIVE_DIFF}" != "true" ]]; then
  echo "::error::Rootful Podman did not enable native overlay diff (reported '${NATIVE_DIFF:-unknown}')."
  exit 1
fi
if [[ "${GRAPH_OPTIONS}" == *mount_program* ]]; then
  echo "::error::Rootful Podman still reports a mount_program: ${GRAPH_OPTIONS}"
  exit 1
fi

echo "Podman ${PODMAN_VERSION}: driver=${DRIVER}, native-overlay=${NATIVE_DIFF}, graph-options=${GRAPH_OPTIONS}"
NATIVE_LOGIC_EOF
)

setup() {
  TEST_TMP=$(mktemp -d)
  export TEST_TMP
  export MOCK_DIR="${TEST_TMP}/bin"
  export CALL_LOG="${TEST_TMP}/calls.log"
  export MOCK_STORAGE_CONF="${TEST_TMP}/storage.conf"
  mkdir -p "${MOCK_DIR}"
  touch "${CALL_LOG}"
  export PATH="${MOCK_DIR}:${PATH}"

  cat > "${MOCK_DIR}/sudo" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "${CALL_LOG}"
case "${1:-}" in
  podman)
    shift
    exec podman "$@"
    ;;
  install|rm)
    exit 0
    ;;
  tee)
    cat > "${MOCK_STORAGE_CONF}"
    ;;
  *)
    exec "$@"
    ;;
esac
EOF
  chmod +x "${MOCK_DIR}/sudo"

  cat > "${MOCK_DIR}/podman" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
case "$*" in
  "--version")
    echo "podman version ${MOCK_PODMAN_VERSION:-5.8.4}"
    ;;
  "system reset --force")
    ;;
  "info --format json")
    printf '%s\n' "${MOCK_PODMAN_INFO_JSON}"
    ;;
  *)
    echo "unexpected podman invocation: $*" >&2
    exit 2
    ;;
esac
EOF
  chmod +x "${MOCK_DIR}/podman"

  export MOCK_PODMAN_VERSION="5.8.4"
  export MOCK_PODMAN_INFO_JSON='{"store":{"graphDriverName":"overlay","graphStatus":{"Native Overlay Diff":"true"},"graphOptions":{}}}'
}

teardown() {
  rm -rf "${TEST_TMP}"
}

@test "native overlay validation accepts the disabled default" {
  export NATIVE_OVERLAY="false"

  run bash -c "${VALIDATION_LOGIC}"

  [ "${status}" -eq 0 ]
}

@test "native overlay validation rejects an invalid boolean" {
  export NATIVE_OVERLAY="yes"

  run bash -c "${VALIDATION_LOGIC}"

  [ "${status}" -ne 0 ]
  [[ "${output}" == *"must be 'true' or 'false'"* ]]
}

@test "native overlay validation accepts the updated Podman stack" {
  export NATIVE_OVERLAY="true"

  run bash -c "${VALIDATION_LOGIC}"

  [ "${status}" -eq 0 ]
}

@test "native overlay resets storage and writes a native configuration" {
  run bash -c "${NATIVE_OVERLAY_LOGIC}"

  [ "${status}" -eq 0 ]
  [[ "${output}" == *"native-overlay=true"* ]]
  grep -q '^driver = "overlay"$' "${MOCK_STORAGE_CONF}"
  grep -q '^mountopt = "nodev"$' "${MOCK_STORAGE_CONF}"
  ! grep -q 'mount_program\|fsync=0' "${MOCK_STORAGE_CONF}"
  grep -q '^podman system reset --force$' "${CALL_LOG}"
  grep -q '^rm -f /var/lib/containers/storage/overlay/.has-mount-program$' "${CALL_LOG}"
}

@test "native overlay rejects Podman older than version 5" {
  export MOCK_PODMAN_VERSION="4.9.3"

  run bash -c "${NATIVE_OVERLAY_LOGIC}"

  [ "${status}" -ne 0 ]
  [[ "${output}" == *"requires the runner's Podman 5.x or newer"* ]]
  ! grep -q 'system reset' "${CALL_LOG}"
}

@test "native overlay fails when Podman reports a non-native diff" {
  export MOCK_PODMAN_INFO_JSON='{"store":{"graphDriverName":"overlay","graphStatus":{"Native Overlay Diff":"false"},"graphOptions":{}}}'

  run bash -c "${NATIVE_OVERLAY_LOGIC}"

  [ "${status}" -ne 0 ]
  [[ "${output}" == *"did not enable native overlay diff"* ]]
}

@test "native overlay fails when a mount program remains configured" {
  export MOCK_PODMAN_INFO_JSON='{"store":{"graphDriverName":"overlay","graphStatus":{"Native Overlay Diff":"true"},"graphOptions":{"overlay.mount_program":"/usr/local/bin/fuse-overlayfs"}}}'

  run bash -c "${NATIVE_OVERLAY_LOGIC}"

  [ "${status}" -ne 0 ]
  [[ "${output}" == *"still reports a mount_program"* ]]
}
