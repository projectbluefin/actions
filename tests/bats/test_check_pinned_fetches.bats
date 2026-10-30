#!/usr/bin/env bats
# Tests for scripts/check-pinned-fetches.sh — the "pinned fetches" supply-chain
# gate (projectbluefin/utah#902, Option A).
#
# Each test writes fixture files into a temp root and runs the script against it
# with --root, so the rules are exercised in isolation from the repo under test.
# Covers:
#   - a clean, fully-pinned tree reports nothing and exits 0
#   - each rule fires on its unsafe shape in fail mode (exit 1)
#   - warn mode never blocks (exit 0) even when findings are present
#   - the allowlist suppresses a whole rule by id and a single finding by text
#   - only the intended file types are scanned
#   - comment lines are not reported as real fetches
#   - bad usage exits 2; --help exits 0

SCRIPT="$BATS_TEST_DIRNAME/../../scripts/check-pinned-fetches.sh"
setup() {
  ROOT="$(mktemp -d)"
  mkdir -p "$ROOT/.github/workflows"
}
teardown() {
  rm -rf "$ROOT"
}

# --- positive: a clean tree is clean -----------------------------------------

@test "clean tree reports nothing and exits 0" {
  cat > "$ROOT/.github/workflows/build.yml" <<'YAML'
name: build
on: pull_request
jobs:
  build:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - name: pinned download
        run: |
          curl -fsSL "https://example.com/dl/1.2.3/tool.tar.gz" -o tool.tgz
          echo "$SHA256  tool.tgz" | sha256sum -c -
      - name: pinned clone
        run: git clone --branch abc123def456abc123def456abc123def456abc123 https://git.sr.ht/x
      - name: pinned image
        run: podman pull ghcr.io/projectbluefin/img@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
YAML
  printf 'FROM fedora@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n' > "$ROOT/Containerfile"

  run bash "$SCRIPT" --root "$ROOT" --mode fail
  [ "$status" -eq 0 ]
  [[ $output == *"clean"* ]]
}

# --- each rule fires in fail mode --------------------------------------------

@test "mutable-url rule flags a :latest / releases/latest URL" {
  printf 'curl -sL https://example.com/releases/latest/download/t.gz -o t\n' > "$ROOT/.github/workflows/w.yml"
  run bash "$SCRIPT" --root "$ROOT" --mode fail
  [ "$status" -eq 1 ]
  [[ $output == *"mutable-url"* ]]
}

@test "pipe-download rule flags curl piped to bash with no verify" {
  printf 'curl -fsSL https://get.example.com | bash\n' > "$ROOT/install.sh"
  run bash "$SCRIPT" --root "$ROOT" --mode fail
  [ "$status" -eq 1 ]
  [[ $output == *"pipe-download"* ]]
}

@test "pipe-download rule does NOT flag a curl download verified with sha256sum -c" {
  printf 'curl -fsSL https://get.example.com -o t.tgz\n' > "$ROOT/install.sh"
  printf 'echo "$SHA  t.tgz" | sha256sum -c -\n' >> "$ROOT/install.sh"
  run bash "$SCRIPT" --root "$ROOT" --mode fail
  [ "$status" -eq 0 ]
}

@test "unpinned-clone rule flags a git clone with no commit SHA" {
  printf 'git clone https://git.sr.ht/~emersion/grim\n' > "$ROOT/.github/workflows/w.yml"
  run bash "$SCRIPT" --root "$ROOT" --mode fail
  [ "$status" -eq 1 ]
  [[ $output == *"unpinned-clone"* ]]
}

@test "unpinned-clone rule does NOT flag a clone with a 40-hex branch" {
  printf 'git clone --branch abc123def456abc123def456abc123def456abc1 https://x/y\n' > "$ROOT/.github/workflows/w.yml"
  run bash "$SCRIPT" --root "$ROOT" --mode fail
  [ "$status" -eq 0 ]
}

@test "unpinned-image rule flags a FROM line by tag with no digest" {
  printf 'FROM fedora:41 AS build\n' > "$ROOT/Containerfile"
  run bash "$SCRIPT" --root "$ROOT" --mode fail
  [ "$status" -eq 1 ]
  [[ $output == *"unpinned-image"* ]]
}

@test "unpinned-image rule does NOT flag a FROM line pinned by digest" {
  printf 'FROM ghcr.io/x/y@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n' > "$ROOT/Containerfile"
  run bash "$SCRIPT" --root "$ROOT" --mode fail
  [ "$status" -eq 0 ]
}

@test "unpinned-ostree rule flags a bootc switch to a tag without sigpolicy" {
  printf 'bootc switch ghcr.io/projectbluefin/bluefin:testing\n' > "$ROOT/40-update.sh"
  run bash "$SCRIPT" --root "$ROOT" --mode fail
  [ "$status" -eq 1 ]
  [[ $output == *"unpinned-ostree"* ]]
}

# --- warn mode never blocks ---------------------------------------------------

@test "warn mode exits 0 even when findings are present" {
  printf 'curl -fsSL https://get.example.com | bash\n' > "$ROOT/install.sh"
  run bash "$SCRIPT" --root "$ROOT" --mode warn
  [ "$status" -eq 0 ]
  [[ $output == *"pipe-download"* ]]
  [[ $output == *"WARN"* ]]
}

# --- allowlist ----------------------------------------------------------------

@test "allowlist suppresses a whole rule by id" {
  printf 'FROM fedora:41 AS build\n' > "$ROOT/Containerfile"
  printf 'unpinned-image\n' > "$ROOT/allow.txt"
  run bash "$SCRIPT" --root "$ROOT" --mode fail --allowlist "$ROOT/allow.txt"
  [ "$status" -eq 0 ]
  [[ $output == *"clean"* ]]
}

@test "allowlist suppresses a single finding by substring" {
  printf 'git clone https://git.sr.ht/~emersion/grim\n' > "$ROOT/.github/workflows/w.yml"
  printf 'git clone https://git.sr.ht/someother/tool\n' >> "$ROOT/.github/workflows/w.yml"
  printf '~emersion/grim\n' > "$ROOT/allow.txt"
  run bash "$SCRIPT" --root "$ROOT" --mode fail --allowlist "$ROOT/allow.txt"
  [ "$status" -eq 1 ]
  [[ $output == *"someother/tool"* ]]
  [[ $output != *"~emersion/grim"* ]]
}

# --- file-type filtering ------------------------------------------------------

@test "non-scanned file types are ignored" {
  printf 'curl -fsSL https://get.example.com | bash\n' > "$ROOT/notes.txt"
  run bash "$SCRIPT" --root "$ROOT" --mode fail
  [ "$status" -eq 0 ]
  [[ $output == *"clean"* ]]
}

# --- comment handling ---------------------------------------------------------

@test "comment lines mentioning a mutable ref are not flagged" {
  cat > "$ROOT/.github/workflows/w.yml" <<'YAML'
name: w
on: pull_request
jobs:
  w:
    steps:
      # example only: curl -fsSL https://example.com/releases/latest/download/t -o t
      # and a bare git clone https://git.sr.ht/x is documentation, not a fetch
      - run: echo hi
YAML
  run bash "$SCRIPT" --root "$ROOT" --mode fail
  [ "$status" -eq 0 ]
  [[ $output == *"clean"* ]]
}

@test "a real fetch on a non-comment line is still flagged beside comments" {
  cat > "$ROOT/.github/workflows/w.yml" <<'YAML'
name: w
on: pull_request
jobs:
  w:
    steps:
      # this is just a comment
      - run: curl -fsSL https://example.com/releases/latest/download/t -o t
YAML
  run bash "$SCRIPT" --root "$ROOT" --mode fail
  [ "$status" -eq 1 ]
  [[ $output == *"mutable-url"* ]]
}

# --- usage --------------------------------------------------------------------

@test "unknown mode exits 2" {
  run bash "$SCRIPT" --root "$ROOT" --mode sideways
  [ "$status" -eq 2 ]
}

@test "--help exits 0 and prints usage" {
  run bash "$SCRIPT" --help
  [ "$status" -eq 0 ]
  [[ $output == *"Usage"* ]]
}
