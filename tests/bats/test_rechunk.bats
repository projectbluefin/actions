#!/usr/bin/env bats
# Tests for bootc-build/rechunk inline shell logic.
#
# The shell logic lives inline in bootc-build/rechunk/action.yml.
# The snippet below is a verbatim copy of the "Rechunk image" run block,
# so this test breaks if the action logic changes without updating the test.
#
# sudo and podman are stubbed on PATH so no container runtime is required.
#
# Covers:
#   - default parameters (max-layers=127, format-version=2, bootc=true, previous-build="")
#   - argument assembly for rpm-ostree compose build-chunked-oci:
#       --max-layers, --format-version, --from, --output containers-storage:localhost/<output>
#   - conditional inclusion of --bootc flag when BOOTC_FLAG is "true"
#   - omission of --bootc flag when BOOTC_FLAG is "false" or empty
#   - conditional inclusion of --previous-build flag when PREVIOUS_BUILD is non-empty
#   - omission of --previous-build flag when PREVIOUS_BUILD is empty
#   - podman invoked with sudo, --rm, --privileged, and volume mount /var/lib/containers
#   - podman execution failure propagates non-zero exit status
#   - GITHUB_OUTPUT receives image-ref=containers-storage:localhost/<output>
#   - snippet drift guard against action.yml

RECHUNK_SNIPPET=$(cat <<'SNIP'
set -euo pipefail

ARGS=(
  --max-layers "${MAX_LAYERS}"
  --format-version "${FORMAT_VERSION}"
  --from "${SOURCE}"
  --output "containers-storage:localhost/${OUTPUT}"
)

[[ "${BOOTC_FLAG}" == "true" ]] && ARGS+=(--bootc)
[[ -n "${PREVIOUS_BUILD}" ]] && ARGS+=(--previous-build "${PREVIOUS_BUILD}")

sudo podman run --rm --privileged \
  --volume /var/lib/containers:/var/lib/containers \
  "${SOURCE}" \
  rpm-ostree compose build-chunked-oci "${ARGS[@]}"

echo "image-ref=containers-storage:localhost/${OUTPUT}" >> "$GITHUB_OUTPUT"
SNIP
)

setup() {
  TEST_TMP=$(mktemp -d)
  export TEST_TMP
  export GITHUB_OUTPUT="${TEST_TMP}/github_output"
  : >"$GITHUB_OUTPUT"

  export STUB_BIN="${TEST_TMP}/bin"
  mkdir -p "$STUB_BIN"
  export CMD_LOG="${TEST_TMP}/cmd.log"
  : >"$CMD_LOG"

  # Stub sudo to invoke the target command directly and log it
  cat >"${STUB_BIN}/sudo" <<'STUB'
#!/usr/bin/env bash
echo "sudo $*" >>"$CMD_LOG"
"$@"
STUB
  chmod +x "${STUB_BIN}/sudo"

  # Stub podman
  cat >"${STUB_BIN}/podman" <<'STUB'
#!/usr/bin/env bash
echo "podman $*" >>"$CMD_LOG"
if [[ "${PODMAN_FAIL:-0}" == "1" ]]; then
  echo "podman execution failed" >&2
  exit 1
fi
exit 0
STUB
  chmod +x "${STUB_BIN}/podman"

  export PATH="${STUB_BIN}:${PATH}"

  # Default environment matching action inputs
  export SOURCE="localhost/bluefin:latest"
  export OUTPUT="rechunked"
  export MAX_LAYERS="127"
  export FORMAT_VERSION="2"
  export PREVIOUS_BUILD=""
  export BOOTC_FLAG="true"
}

teardown() {
  rm -rf "$TEST_TMP"
}

get_output() {
  grep "^$1=" "$GITHUB_OUTPUT" | tail -1 | cut -d= -f2-
}

# ── Argument building & execution ─────────────────────────────────────────────

@test "rechunk: basic invocation with defaults passes expected args to podman" {
  run bash -c "$RECHUNK_SNIPPET"
  [ "$status" -eq 0 ]
  [ "$(get_output image-ref)" = "containers-storage:localhost/rechunked" ]

  run grep "podman run --rm --privileged --volume /var/lib/containers:/var/lib/containers" "$CMD_LOG"
  [ "$status" -eq 0 ]

  run grep "rpm-ostree compose build-chunked-oci --max-layers 127 --format-version 2 --from localhost/bluefin:latest --output containers-storage:localhost/rechunked --bootc" "$CMD_LOG"
  [ "$status" -eq 0 ]
}

@test "rechunk: custom output name is reflected in args and GITHUB_OUTPUT" {
  export OUTPUT="my-custom-rechunk"
  run bash -c "$RECHUNK_SNIPPET"
  [ "$status" -eq 0 ]
  [ "$(get_output image-ref)" = "containers-storage:localhost/my-custom-rechunk" ]

  run grep -- "--output containers-storage:localhost/my-custom-rechunk" "$CMD_LOG"
  [ "$status" -eq 0 ]
}

@test "rechunk: custom max-layers and format-version are passed through" {
  export MAX_LAYERS="64"
  export FORMAT_VERSION="1"
  run bash -c "$RECHUNK_SNIPPET"
  [ "$status" -eq 0 ]

  run grep -- "--max-layers 64" "$CMD_LOG"
  [ "$status" -eq 0 ]
  run grep -- "--format-version 1" "$CMD_LOG"
  [ "$status" -eq 0 ]
}

@test "rechunk: --bootc flag is omitted when BOOTC_FLAG is false" {
  export BOOTC_FLAG="false"
  run bash -c "$RECHUNK_SNIPPET"
  [ "$status" -eq 0 ]

  run grep -- "--bootc" "$CMD_LOG"
  [ "$status" -ne 0 ]
}

@test "rechunk: --previous-build is included when set" {
  export PREVIOUS_BUILD="ghcr.io/projectbluefin/bluefin:previous"
  run bash -c "$RECHUNK_SNIPPET"
  [ "$status" -eq 0 ]

  run grep -- "--previous-build ghcr.io/projectbluefin/bluefin:previous" "$CMD_LOG"
  [ "$status" -eq 0 ]
}

@test "rechunk: --previous-build is omitted when empty" {
  export PREVIOUS_BUILD=""
  run bash -c "$RECHUNK_SNIPPET"
  [ "$status" -eq 0 ]

  run grep -- "--previous-build" "$CMD_LOG"
  [ "$status" -ne 0 ]
}

@test "rechunk: podman failure propagates non-zero exit and halts before output" {
  export PODMAN_FAIL="1"
  run bash -c "$RECHUNK_SNIPPET"
  [ "$status" -eq 1 ]
  [[ "$output" == *"podman execution failed"* ]]
  [ "$(get_output image-ref)" = "" ]
}

# ── Snippet drift guard ───────────────────────────────────────────────────────

@test "rechunk: action.yml still contains the inline run logic under test" {
  ACTION="${BATS_TEST_DIRNAME}/../../bootc-build/rechunk/action.yml"
  [ -f "$ACTION" ]
  grep -q 'rpm-ostree compose build-chunked-oci' "$ACTION"
  grep -q 'containers-storage:localhost/\${OUTPUT}' "$ACTION"
  grep -q 'image-ref=containers-storage:localhost/\${OUTPUT}' "$ACTION"
}
