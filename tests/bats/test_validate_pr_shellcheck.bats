#!/usr/bin/env bats
# Tests for the "Install shellcheck" step of bootc-build/validate-pr/action.yml.
#
# The shell logic lives inline in the action. Keep this snippet verbatim so a
# change to the step must update its regression test. Only the os-release path
# is substituted (MOCK_OS_RELEASE), as in test_setup_runner.bats.
#
# Regression: the step pinned shellcheck=0.9.0-1, which exists only on Ubuntu
# 24.04. When ubuntu-latest moved to 26.04 every consumer's PR validation failed
# with "Version '0.9.0-1' for 'shellcheck' was not found".

INSTALL_LOGIC=$(cat <<'EOF'
set -euo pipefail
# Pin the exact shellcheck package of the runner image's Ubuntu
# release: a 24.04 version does not exist on 26.04, so a single pin
# broke every consumer when ubuntu-latest moved to 26.04.
IDV=$(. "${MOCK_OS_RELEASE:-/usr/lib/os-release}" && echo "${ID}-${VERSION_ID}")
case "${IDV}" in
  ubuntu-24.04) version="0.9.0-1" ;;   # noble
  ubuntu-26.04) version="0.11.0-2" ;;  # resolute
  *)
    echo "::error::validate-pr pins shellcheck for ubuntu-24.04 and ubuntu-26.04 runner images; found '${IDV}'. Add that release's package version to this step."
    exit 1
    ;;
esac
echo "Installing shellcheck ${version} for ${IDV}"
sudo apt-get update -y
sudo apt-get install -y "shellcheck=${version}"
EOF
)

setup() {
  TEST_TMP=$(mktemp -d)
  export TEST_TMP
  export CALL_LOG="${TEST_TMP}/calls.log"
  export MOCK_OS_RELEASE="${TEST_TMP}/os-release"
  mkdir -p "${TEST_TMP}/bin"
  touch "${CALL_LOG}"
  cat > "${TEST_TMP}/bin/sudo" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "${CALL_LOG}"
EOF
  chmod +x "${TEST_TMP}/bin/sudo"
  export PATH="${TEST_TMP}/bin:${PATH}"
}

teardown() {
  rm -rf "${TEST_TMP}"
}

write_os_release() {
  printf 'ID=%s\nVERSION_ID=%s\n' "$1" "$2" > "${MOCK_OS_RELEASE}"
}

@test "installs the noble shellcheck package on ubuntu-24.04" {
  write_os_release ubuntu 24.04
  run bash -c "${INSTALL_LOGIC}"
  [ "${status}" -eq 0 ]
  grep -qx 'apt-get install -y shellcheck=0.9.0-1' "${CALL_LOG}"
}

@test "installs the resolute shellcheck package on ubuntu-26.04" {
  write_os_release ubuntu 26.04
  run bash -c "${INSTALL_LOGIC}"
  [ "${status}" -eq 0 ]
  grep -qx 'apt-get install -y shellcheck=0.11.0-2' "${CALL_LOG}"
}

@test "fails with a clear error on an unpinned release instead of installing an unpinned version" {
  write_os_release ubuntu 22.04
  run bash -c "${INSTALL_LOGIC}"
  [ "${status}" -eq 1 ]
  [[ "${output}" == *"found 'ubuntu-22.04'"* ]]
  ! grep -q 'apt-get install' "${CALL_LOG}"
}

@test "the snippet matches the action's step apart from the os-release path" {
  action="${BATS_TEST_DIRNAME}/../../bootc-build/validate-pr/action.yml"
  expected=$(printf '%s\n' "${INSTALL_LOGIC}" | sed 's|"${MOCK_OS_RELEASE:-/usr/lib/os-release}"|/usr/lib/os-release|')
  actual=$(python3 -c 'import sys, yaml; steps = yaml.safe_load(open(sys.argv[1]))["runs"]["steps"]; print(next(s["run"] for s in steps if s.get("name") == "Install shellcheck"), end="")' "${action}")
  [ "${expected}" = "${actual%$'\n'}" ]
}
