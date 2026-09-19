#!/usr/bin/env bats
# Tests for bootc-build/setup-runner native-overlay validation, storage setup,
# and podman source selection.
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
# Verbatim from bootc-build/setup-runner/action.yml ("Select podman source" step)
# Note: only the os-release source file is substituted via MOCK_OS_RELEASE.
PODMAN_SOURCE_LOGIC=$(cat <<'EOF'
set -euo pipefail
IDV=$(. "${MOCK_OS_RELEASE:-/usr/lib/os-release}" && echo "${ID}-${VERSION_ID}")
case "${IDV}" in
  ubuntu-24.04)
    # Ubuntu 24.04's podman (4.9.x) does not push layer annotations
    # (ostree.components) needed by the rpm-ostree rechunker and does not
    # support zstd:chunked push. The resolute (26.04) packages install on
    # noble, so pull the whole stack from there.
    if [ "$(dpkg --print-architecture)" = "amd64" ]; then
      mirror="http://azure.archive.ubuntu.com/ubuntu"
    else
      mirror="http://ports.ubuntu.com/ubuntu-ports"
    fi
    echo "deb ${mirror} resolute universe main" | sudo tee /etc/apt/sources.list.d/resolute.list
    echo "install-from-resolute=true" >> "$GITHUB_OUTPUT"
    ;;
  ubuntu-26.04)
    # resolute *is* 26.04: verify the runner's podman is 5.x or newer
    # before skipping the apt source.
    PODMAN_VERSION=$(podman --version 2>/dev/null | awk '{print $3}' || echo "unknown")
    if [[ ! "${PODMAN_VERSION}" =~ ^([0-9]+)\. ]] || (( BASH_REMATCH[1] < 5 )); then
      echo "::error::ubuntu-26.04 runner image has podman '${PODMAN_VERSION}', but version 5.x or newer is required for layer annotations and zstd:chunked push."
      exit 1
    fi
    echo "::notice::${IDV} ships podman ${PODMAN_VERSION}; skipping the resolute apt source."
    echo "install-from-resolute=false" >> "$GITHUB_OUTPUT"
    ;;
  *)
    echo "::error::setup-runner supports ubuntu-24.04 and ubuntu-26.04 runner images; found '${IDV}'. Set update-podman: 'false' to skip the podman upgrade."
    exit 1
    ;;
esac
EOF
)


NATIVE_OVERLAY_LOGIC=$(cat <<'NATIVE_LOGIC_EOF'
set -euo pipefail

# GitHub runners' sudo preserves XDG_RUNTIME_DIR, so a plain
# `sudo podman` drops root-owned state (crun, libpod) into the
# runner user's runtime dir and breaks every later rootless podman
# call with EACCES. Scrub the variable from all rootful calls.
sudo_podman() {
  sudo env -u XDG_RUNTIME_DIR podman "$@"
}

PODMAN_VERSION=$(sudo_podman --version 2>/dev/null | awk '{print $3}')
if [[ ! "${PODMAN_VERSION}" =~ ^([0-9]+)\. ]] || (( BASH_REMATCH[1] < 5 )); then
  echo "::error::native-overlay requires the runner's Podman 5.x or newer; found '${PODMAN_VERSION:-unknown}'."
  exit 1
fi

# Reset while the old configuration is still active. containers/storage
# records mount-program use in overlay/.has-mount-program, so editing the
# configuration alone can leave fuse-overlayfs selected.
sudo_podman system reset --force

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

INFO=$(sudo_podman info --format json)

# Fail-safe: sweep root-owned leftovers out of the user runtime dir
# in case a rootful call still created state there.
if [[ -n "${XDG_RUNTIME_DIR:-}" ]]; then
  sudo find "${XDG_RUNTIME_DIR}" -mindepth 1 -maxdepth 1 -user root -exec rm -rf {} +
fi
DRIVER=$(jq -r '.store.graphDriverName // empty' <<<"${INFO}")
NATIVE_DIFF=$(jq -r '.store.graphStatus["Native Overlay Diff"] // empty' <<<"${INFO}")
GRAPH_OPTIONS=$(jq -c '.store.graphOptions // {}' <<<"${INFO}")

if [[ "${DRIVER}" != "overlay" ]]; then
  echo "::error::Expected rootful Podman storage driver 'overlay', found '${DRIVER:-unknown}'."
  exit 1
fi
if [[ "${GRAPH_OPTIONS}" == *mount_program* ]]; then
  echo "::error::Rootful Podman still reports a mount_program: ${GRAPH_OPTIONS}"
  exit 1
fi
# "Native Overlay Diff" is diagnostic only: containers/storage
# refuses the native diff fast path whenever the kernel's overlay
# module has redirect_dir enabled (the Ubuntu default) and computes
# layer diffs naively instead. Layer mounts still use kernel
# overlayfs (no FUSE), which is what this mode guarantees, so
# report the status without failing.
if [[ "${NATIVE_DIFF}" != "true" ]]; then
  echo "::notice::Rootful Podman computes overlay diffs naively (native diff: '${NATIVE_DIFF:-unknown}'); expected on Ubuntu kernels with CONFIG_OVERLAY_FS_REDIRECT_DIR=y."
fi

echo "Podman ${PODMAN_VERSION}: driver=${DRIVER}, native-diff=${NATIVE_DIFF}, graph-options=${GRAPH_OPTIONS}"
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
  export GITHUB_OUTPUT="${TEST_TMP}/github_output"
  touch "${GITHUB_OUTPUT}"

  cat > "${MOCK_DIR}/sudo" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "${CALL_LOG}"
case "${1:-}" in
  env)
    shift
    while [[ "${1:-}" == "-u" ]]; do shift 2; done
    exec "$@"
    ;;
  podman)
    shift
    exec podman "$@"
    ;;
  install|rm|find)
    exit 0
    ;;
  tee)
    shift
    if [[ "${1:-}" == "/etc/apt/sources.list.d/resolute.list" ]]; then
      cat > "${MOCK_RESOLUTE_LIST}"
    else
      cat > "${MOCK_STORAGE_CONF}"
    fi
    ;;
  *)
    exec "$@"
    ;;
esac
EOF
  chmod +x "${MOCK_DIR}/sudo"
  cat > "${MOCK_DIR}/dpkg" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == "--print-architecture" ]]; then
  echo "${MOCK_DPKG_ARCH:-amd64}"
  exit 0
fi
exit 1
EOF
  chmod +x "${MOCK_DIR}/dpkg"


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
  # Observed GitHub-hosted Ubuntu runners report a non-native diff (their
  # kernels enable the overlay module's redirect_dir); make the default
  # mock match that observation.
  export MOCK_PODMAN_INFO_JSON='{"store":{"graphDriverName":"overlay","graphStatus":{"Native Overlay Diff":"false"},"graphOptions":{}}}'
  export MOCK_RESOLUTE_LIST="${TEST_TMP}/resolute.list"
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
  [[ "${output}" == *"native-diff=false"* ]]
  grep -q '^driver = "overlay"$' "${MOCK_STORAGE_CONF}"
  grep -q '^mountopt = "nodev"$' "${MOCK_STORAGE_CONF}"
  ! grep -q 'mount_program\|fsync=0' "${MOCK_STORAGE_CONF}"
  grep -q '^env -u XDG_RUNTIME_DIR podman system reset --force$' "${CALL_LOG}"
  grep -q '^rm -f /var/lib/containers/storage/overlay/.has-mount-program$' "${CALL_LOG}"
}

@test "native overlay scrubs XDG_RUNTIME_DIR and sweeps root-owned state" {
  export XDG_RUNTIME_DIR="${TEST_TMP}/runtime"
  mkdir -p "${XDG_RUNTIME_DIR}"

  run bash -c "${NATIVE_OVERLAY_LOGIC}"

  [ "${status}" -eq 0 ]
  # Every rootful podman call must go through the env scrub.
  ! grep -qE '^podman ' "${CALL_LOG}"
  grep -q '^env -u XDG_RUNTIME_DIR podman info --format json$' "${CALL_LOG}"
  grep -q "^find ${XDG_RUNTIME_DIR} -mindepth 1 -maxdepth 1 -user root -exec rm -rf {} +$" "${CALL_LOG}"
}

@test "native overlay rejects Podman older than version 5" {
  export MOCK_PODMAN_VERSION="4.9.3"

  run bash -c "${NATIVE_OVERLAY_LOGIC}"

  [ "${status}" -ne 0 ]
  [[ "${output}" == *"requires the runner's Podman 5.x or newer"* ]]
  ! grep -q 'system reset' "${CALL_LOG}"
}

@test "native overlay tolerates a non-native diff with a notice" {
  run bash -c "${NATIVE_OVERLAY_LOGIC}"

  [ "${status}" -eq 0 ]
  [[ "${output}" == *"computes overlay diffs naively"* ]]
}

@test "native overlay stays quiet when the diff is native" {
  export MOCK_PODMAN_INFO_JSON='{"store":{"graphDriverName":"overlay","graphStatus":{"Native Overlay Diff":"true"},"graphOptions":{}}}'

  run bash -c "${NATIVE_OVERLAY_LOGIC}"

  [ "${status}" -eq 0 ]
  [[ "${output}" != *"computes overlay diffs naively"* ]]
  [[ "${output}" == *"native-diff=true"* ]]
}

@test "native overlay fails when a mount program remains configured" {
  export MOCK_PODMAN_INFO_JSON='{"store":{"graphDriverName":"overlay","graphStatus":{"Native Overlay Diff":"false"},"graphOptions":{"overlay.mount_program":"/usr/local/bin/fuse-overlayfs"}}}'

  run bash -c "${NATIVE_OVERLAY_LOGIC}"

  [ "${status}" -ne 0 ]
  [[ "${output}" == *"still reports a mount_program"* ]]
}

@test "podman source selection configures resolute apt repo on ubuntu-24.04 amd64" {
  export MOCK_OS_RELEASE="${TEST_TMP}/os-release"
  cat <<'EOF' > "${MOCK_OS_RELEASE}"
ID=ubuntu
VERSION_ID=24.04
EOF
  export MOCK_DPKG_ARCH="amd64"

  run bash -c "${PODMAN_SOURCE_LOGIC}"

  [ "${status}" -eq 0 ]
  grep -q "^install-from-resolute=true$" "${GITHUB_OUTPUT}"
  grep -q "deb http://azure.archive.ubuntu.com/ubuntu resolute universe main" "${MOCK_RESOLUTE_LIST}"
}

@test "podman source selection configures resolute ports repo on ubuntu-24.04 arm64" {
  export MOCK_OS_RELEASE="${TEST_TMP}/os-release"
  cat <<'EOF' > "${MOCK_OS_RELEASE}"
ID=ubuntu
VERSION_ID=24.04
EOF
  export MOCK_DPKG_ARCH="arm64"

  run bash -c "${PODMAN_SOURCE_LOGIC}"

  [ "${status}" -eq 0 ]
  grep -q "^install-from-resolute=true$" "${GITHUB_OUTPUT}"
  grep -q "deb http://ports.ubuntu.com/ubuntu-ports resolute universe main" "${MOCK_RESOLUTE_LIST}"
}

@test "podman source selection skips apt repo on ubuntu-26.04 when podman >= 5" {
  export MOCK_OS_RELEASE="${TEST_TMP}/os-release"
  cat <<'EOF' > "${MOCK_OS_RELEASE}"
ID=ubuntu
VERSION_ID=26.04
EOF
  export MOCK_PODMAN_VERSION="5.7.0"

  run bash -c "${PODMAN_SOURCE_LOGIC}"

  [ "${status}" -eq 0 ]
  grep -q "^install-from-resolute=false$" "${GITHUB_OUTPUT}"
  [[ "${output}" == *"ships podman 5.7.0; skipping the resolute apt source"* ]]
  [ ! -f "${MOCK_RESOLUTE_LIST}" ]
}

@test "podman source selection rejects ubuntu-26.04 if podman is older than 5" {
  export MOCK_OS_RELEASE="${TEST_TMP}/os-release"
  cat <<'EOF' > "${MOCK_OS_RELEASE}"
ID=ubuntu
VERSION_ID=26.04
EOF
  export MOCK_PODMAN_VERSION="4.9.3"

  run bash -c "${PODMAN_SOURCE_LOGIC}"

  [ "${status}" -ne 0 ]
  [[ "${output}" == *"ubuntu-26.04 runner image has podman '4.9.3', but version 5.x or newer is required"* ]]
  [ ! -f "${MOCK_RESOLUTE_LIST}" ]
}

@test "podman source selection fails fast on unsupported runner image" {
  export MOCK_OS_RELEASE="${TEST_TMP}/os-release"
  cat <<'EOF' > "${MOCK_OS_RELEASE}"
ID=ubuntu
VERSION_ID=22.04
EOF

  run bash -c "${PODMAN_SOURCE_LOGIC}"

  [ "${status}" -ne 0 ]
  [[ "${output}" == *"supports ubuntu-24.04 and ubuntu-26.04 runner images; found 'ubuntu-22.04'"* ]]
}

@test "podman source selection fails fast on non-ubuntu runner image" {
  export MOCK_OS_RELEASE="${TEST_TMP}/os-release"
  cat <<'EOF' > "${MOCK_OS_RELEASE}"
ID=fedora
VERSION_ID=42
EOF

  run bash -c "${PODMAN_SOURCE_LOGIC}"

  [ "${status}" -ne 0 ]
  [[ "${output}" == *"supports ubuntu-24.04 and ubuntu-26.04 runner images; found 'fedora-42'"* ]]
}

@test "setup-runner action.yml contains the verbatim podman source selection logic" {
  ACTION_FILE="${BATS_TEST_DIRNAME}/../../bootc-build/setup-runner/action.yml"
  # Ensure the action.yml contains the expected branch structures and outputs
  grep -q 'case "${IDV}" in' "${ACTION_FILE}"
  grep -q 'ubuntu-24.04)' "${ACTION_FILE}"
  grep -q 'ubuntu-26.04)' "${ACTION_FILE}"
  grep -q 'echo "deb \${mirror} resolute universe main" | sudo tee /etc/apt/sources.list.d/resolute.list' "${ACTION_FILE}"
  grep -q 'install-from-resolute=true' "${ACTION_FILE}"
  grep -q 'install-from-resolute=false' "${ACTION_FILE}"
  grep -q "supports ubuntu-24.04 and ubuntu-26.04 runner images" "${ACTION_FILE}"
}
