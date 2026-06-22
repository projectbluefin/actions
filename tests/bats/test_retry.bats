#!/usr/bin/env bats
# Tests for actions/retry/retry.sh
# Covers: success on first attempt, retry on failure, pattern-filtered retry,
# max-attempts exhaustion, exponential backoff doubling.

setup() {
  SCRIPT="${BATS_TEST_DIRNAME}/../../actions/retry/retry.sh"
  TEST_TMP=$(mktemp -d)
  export GITHUB_OUTPUT="${TEST_TMP}/github_output"
  touch "$GITHUB_OUTPUT"

  export MOCK_DIR="${TEST_TMP}/bin"
  mkdir -p "$MOCK_DIR"
  export PATH="${MOCK_DIR}:${PATH}"

  # Default env vars
  export RETRY_COMMAND="true"
  export MAX_ATTEMPTS="3"
  export INITIAL_WAIT_SECONDS="0"   # 0 to keep tests fast
  export RETRY_ON=""
}

teardown() {
  rm -rf "$TEST_TMP"
}

# ── Success paths ─────────────────────────────────────────────────────────────

@test "succeeds immediately when command exits 0" {
  export RETRY_COMMAND="true"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "success=true" "$GITHUB_OUTPUT"
  grep -q "attempts=1" "$GITHUB_OUTPUT"
}

@test "outputs attempts=1 on first-attempt success" {
  export RETRY_COMMAND="echo hello"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "attempts=1" "$GITHUB_OUTPUT"
}

# ── Retry paths ───────────────────────────────────────────────────────────────

@test "retries and succeeds on second attempt" {
  COUNTER_FILE="${TEST_TMP}/counter"
  echo "0" > "$COUNTER_FILE"
  # Use 'test' not 'exit' so eval doesn't kill the retry loop
  export RETRY_COMMAND="
    count=\$(cat ${COUNTER_FILE})
    count=\$((count + 1))
    echo \$count > ${COUNTER_FILE}
    test \$count -ge 2
  "
  export MAX_ATTEMPTS="3"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "success=true" "$GITHUB_OUTPUT"
  grep -q "attempts=2" "$GITHUB_OUTPUT"
}

@test "exits 1 and sets success=false after exhausting all attempts" {
  export RETRY_COMMAND="false"
  export MAX_ATTEMPTS="3"
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
  grep -q "success=false" "$GITHUB_OUTPUT"
  grep -q "attempts=3" "$GITHUB_OUTPUT"
}

@test "max_attempts=1 means no retry on failure" {
  export RETRY_COMMAND="false"
  export MAX_ATTEMPTS="1"
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
  grep -q "success=false" "$GITHUB_OUTPUT"
  grep -q "attempts=1" "$GITHUB_OUTPUT"
}

# ── Pattern-filtered retry ────────────────────────────────────────────────────

@test "retries when stderr matches retry_on pattern" {
  COUNTER_FILE="${TEST_TMP}/counter"
  echo "0" > "$COUNTER_FILE"
  # Write to stderr and use 'test' (not exit) so eval returns non-zero without killing script
  export RETRY_COMMAND="
    count=\$(cat ${COUNTER_FILE})
    count=\$((count + 1))
    echo \$count > ${COUNTER_FILE}
    echo 'rate limit exceeded' >&2
    test \$count -ge 2
  "
  export RETRY_ON="rate limit"
  export MAX_ATTEMPTS="3"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "success=true" "$GITHUB_OUTPUT"
}

@test "does NOT retry when stderr does not match retry_on pattern" {
  export RETRY_COMMAND="
    echo 'permission denied' >&2
    false
  "
  export RETRY_ON="rate limit|timeout"
  export MAX_ATTEMPTS="3"
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
  grep -q "success=false" "$GITHUB_OUTPUT"
  # Should fail on attempt 1 without retrying
  grep -q "attempts=1" "$GITHUB_OUTPUT"
  [[ "$output" == *"non-retryable error"* ]]
}

@test "retries on any failure when retry_on is empty" {
  COUNTER_FILE="${TEST_TMP}/counter"
  echo "0" > "$COUNTER_FILE"
  export RETRY_COMMAND="
    count=\$(cat ${COUNTER_FILE})
    count=\$((count + 1))
    echo \$count > ${COUNTER_FILE}
    test \$count -ge 2
  "
  export RETRY_ON=""
  export MAX_ATTEMPTS="3"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "success=true" "$GITHUB_OUTPUT"
}

@test "retry_on pattern match is case-insensitive" {
  COUNTER_FILE="${TEST_TMP}/counter"
  echo "0" > "$COUNTER_FILE"
  export RETRY_COMMAND="
    count=\$(cat ${COUNTER_FILE})
    count=\$((count + 1))
    echo \$count > ${COUNTER_FILE}
    echo 'RATE LIMIT EXCEEDED' >&2
    test \$count -ge 2
  "
  export RETRY_ON="rate limit"
  export MAX_ATTEMPTS="3"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "success=true" "$GITHUB_OUTPUT"
}

# ── Backoff doubling ──────────────────────────────────────────────────────────

@test "wait doubles between attempts" {
  SLEEP_LOG="${TEST_TMP}/sleep_log"
  touch "$SLEEP_LOG"

  # Create a mock sleep that logs its argument to SLEEP_LOG.
  # Unquoted heredoc: ${SLEEP_LOG} expands at write-time; \$1 is literal in the script.
  cat > "${MOCK_DIR}/sleep" <<SLEEPEOF
#!/usr/bin/env bash
echo "\$1" >> ${SLEEP_LOG}
SLEEPEOF
  chmod +x "${MOCK_DIR}/sleep"

  COUNTER_FILE="${TEST_TMP}/counter"
  echo "0" > "$COUNTER_FILE"
  export RETRY_COMMAND="
    count=\$(cat ${COUNTER_FILE})
    count=\$((count + 1))
    echo \$count > ${COUNTER_FILE}
    test \$count -ge 3
  "
  export MAX_ATTEMPTS="3"
  export INITIAL_WAIT_SECONDS="5"

  run bash "$SCRIPT"
  [ "$status" -eq 0 ]

  # Should have slept 5 then 10
  waits=$(cat "$SLEEP_LOG")
  [[ "$waits" == *"5"* ]]
  [[ "$waits" == *"10"* ]]
}
