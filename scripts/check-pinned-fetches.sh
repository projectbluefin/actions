#!/usr/bin/env bash
# Pinned-fetches gate (issue projectbluefin/utah#902, Option A).
#
# Scans a repository for tools and source downloaded at build/CI time by a
# mutable reference with no fixed version or checksum. A download that arrives
# from a place that could have been tampered with, and then runs inside the
# build or gets signed into a release, is a supply-chain hole. This gate flags
# those shapes so a pull request fails instead of the instance being fixed one
# repo at a time.
#
# It is intentionally a grep gate, not a full parser: it looks at the common
# download shapes (curl|sh, git clone, image refs, bootc/ostree rebases) and
# reports the ones that carry no immutable marker on the same line. Multi-line
# steps are not cross-checked line to line, so a verified download split across
# several lines can still be reported; the allowlist covers deliberate cases,
# and this is the known limit until a real YAML/AST parser is wanted.
#
# Files scanned: *.yml / *.yaml under .github, plus *.sh, Justfile*,
# Containerfile*, *.container.in and *.toml. Comment lines (first
# non-whitespace char '#') are dropped before matching, so docs/examples
# mentioning a mutable ref are not reported as real fetches.
#
# Modes:
#   warn   always exits 0; findings are printed for the baseline cycle.
#   fail   exits 1 when any non-allowlisted finding exists.
#
# Allowlist (plain text, one entry per line):
#   * a bare rule id (e.g. "unpinned-image") disables that rule entirely;
#   * any other line suppresses a finding whose printed text contains it.
# Lines starting with '#' are comments.
#
# Exit codes: 0 = clean (or warn mode), 1 = findings in fail mode, 2 = bad usage.

set -euo pipefail

ROOT="."
MODE="warn"
ALLOWLIST=""

usage() {
  cat <<'EOF'
Usage: check-pinned-fetches.sh [--root DIR] [--mode warn|fail] [--allowlist FILE]

  --root DIR          Repository root to scan (default: current directory).
  --mode warn|fail    warn prints findings and exits 0; fail exits 1 on any
                      finding that is not allowlisted (default: warn).
  --allowlist FILE    Plain-text allowlist of rule ids or substrings to skip.
  -h, --help          Show this help and exit.
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --root) ROOT="$2"; shift 2 ;;
    --mode) MODE="$2"; shift 2 ;;
    --allowlist) ALLOWLIST="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "error: unknown option: $1" >&2; echo >&2; usage >&2; exit 2 ;;
  esac
done

if [ "$MODE" != "warn" ] && [ "$MODE" != "fail" ]; then
  echo "error: --mode must be 'warn' or 'fail' (got '$MODE')" >&2
  exit 2
fi

# --- rule ids and severities -------------------------------------------------
# mutable-url       a download URL pinned to a moving target (latest / branch)
# pipe-download     curl|wget piped straight into an interpreter
# unpinned-clone    git clone with no immutable commit reference
# unpinned-image    container image referenced by tag with no digest
# unpinned-ostree   bootc switch / ostree rebase to a tag without sigpolicy

declare -A SEVERITY=(
  [mutable-url]=high
  [pipe-download]=high
  [unpinned-clone]=medium
  [unpinned-image]=medium
  [unpinned-ostree]=high
)

# --- allowlist ----------------------------------------------------------------
rule_deny=()
sub_deny=()
if [ -n "$ALLOWLIST" ] && [ -f "$ALLOWLIST" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    # strip trailing CR (files edited on Windows) and leading/trailing space
    line="${line%$'\r'}"
    # skip blanks and comments
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ "$line" =~ ^[[:space:]]*$ ]] && continue
    trimmed="${line#"${line%%[![:space:]]*}"}"
    trimmed="${trimmed%"${trimmed##*[![:space:]]}"}"
    # a known rule id disables that rule; anything else is a suppression string
    if [ -n "${SEVERITY[$trimmed]:-}" ]; then
      rule_deny+=("$trimmed")
    else
      sub_deny+=("$trimmed")
    fi
  done < "$ALLOWLIST"
fi

is_deny_rule() {
  local rule="$1" d
  for d in "${rule_deny[@]+"${rule_deny[@]}"}"; do
    [ "$d" = "$rule" ] && return 0
  done
  return 1
}

is_deny_substring() {
  local text="$1" s
  for s in "${sub_deny[@]+"${sub_deny[@]}"}"; do
    case "$text" in
      *"$s"*) return 0 ;;
    esac
  done
  return 1
}

# --- output -------------------------------------------------------------------
findings=()
record() {
  # $1 rule  $2 severity  $3 file:line  $4 message  $5 detail line
  local rule="$1" sev="$2" loc="$3" msg="$4" detail="$5"
  local text="${rule} (${sev}) ${loc}: ${msg}"
  # a deny-listed rule id suppresses every finding of that rule
  if is_deny_rule "$rule"; then
    return
  fi
  # a suppression string may name the file/ref, so match the whole finding
  local full
  full="${text}"$'\n'"$(printf '%s' "$detail")"
  if is_deny_substring "$full"; then
    return
  fi
  findings+=("${text}"$'\n'"$(printf '%s' "$detail" | sed 's/^/      /')")
}

# --- file discovery -----------------------------------------------------------
scanned=0
while IFS= read -r f; do
  [ -n "$f" ] || continue
  scanned=$((scanned + 1))

  # Every type we scan treats a line whose first non-whitespace char is '#'
  # as a comment, so the rules above filter those out before matching. That
  # keeps documentation and examples that merely mention a mutable URL or a bare
  # command from being reported as real, unverified fetches.

  # mutable-url: URLs pinned to a moving target -------------------------------
  while IFS= read -r match; do
    [ -n "$match" ] || continue
    lineno="${match%%:*}"; content="${match#*:}"
    record mutable-url "${SEVERITY[mutable-url]}" "$f:$lineno" \
      "download URL is pinned to a moving target" "$content"
  done < <(grep -nE '/releases/latest/download/|@[Mm]ain/?|@[Mm]aster/?|@[Ss]table/?|:latest[^a-zA-Z]' "$f" 2>/dev/null | grep -vE '^[0-9]+:[[:space:]]*#' || true)

  # pipe-download: curl|wget piped into an interpreter ------------------------
  while IFS= read -r match; do
    [ -n "$match" ] || continue
    lineno="${match%%:*}"; content="${match#*:}"
    if grep -qiE 'sha256sum|sha512sum|--checksum|cosign|gpg ' <<<"$content"; then
      continue
    fi
    record pipe-download "${SEVERITY[pipe-download]}" "$f:$lineno" \
      "download is piped into an interpreter with no checksum/verify on this line" "$content"
  done < <(grep -nE '(curl|wget)[^|]*\|[[:space:]]*(sudo[[:space:]]+)?(ba)?sh\b|(curl|wget)[^|]*\|[[:space:]]*(sudo[[:space:]]+)?python[0-9.]*\b|(curl|wget)[^|]*\|[[:space:]]*(sudo[[:space:]]+)?tar\b' "$f" 2>/dev/null | grep -vE '^[0-9]+:[[:space:]]*#' || true)

  # unpinned-clone: git clone with no immutable commit ------------------------
  while IFS= read -r match; do
    [ -n "$match" ] || continue
    lineno="${match%%:*}"; content="${match#*:}"
    if grep -qE '[0-9a-f]{40}' <<<"$content"; then
      continue
    fi
    record unpinned-clone "${SEVERITY[unpinned-clone]}" "$f:$lineno" \
      "git clone has no immutable commit SHA" "$content"
  done < <(grep -nE '\bgit[[:space:]]+clone\b' "$f" 2>/dev/null | grep -vE '^[0-9]+:[[:space:]]*#' || true)

  # unpinned-image: container ref by tag with no digest -----------------------
  while IFS= read -r match; do
    [ -n "$match" ] || continue
    lineno="${match%%:*}"; content="${match#*:}"
    if grep -q '@sha256:' <<<"$content"; then
      continue
    fi
    # drop http(s):// and docker:// schemes, then look for name:tag
    stripped=$(printf '%s' "$content" | sed -E 's#https?://##g; s#docker://##g')
    if grep -qE '[a-z0-9._/-]+:[a-z0-9._-]+' <<<"$stripped"; then
      record unpinned-image "${SEVERITY[unpinned-image]}" "$f:$lineno" \
        "container image is referenced by tag with no @sha256 digest" "$content"
    fi
  done < <(grep -nE '^[[:space:]]*(FROM\b)|(^|[[:space:]])Image=|^([[:space:]]*)image:|([[:space:]])podman[[:space:]]+run|([[:space:]])skopeo[[:space:]]+copy' "$f" 2>/dev/null | grep -vE '^[0-9]+:[[:space:]]*#' || true)

  # unpinned-ostree: bootc switch / ostree rebase without sigpolicy -----------
  while IFS= read -r match; do
    [ -n "$match" ] || continue
    lineno="${match%%:*}"; content="${match#*:}"
    if grep -qiE 'enforce-container-sigpolicy|sigstore|policy\.json' <<<"$content"; then
      continue
    fi
    record unpinned-ostree "${SEVERITY[unpinned-ostree]}" "$f:$lineno" \
      "bootc/ostree rebase to a tag has no container signature policy" "$content"
  done < <(grep -nE 'bootc[[:space:]]+switch|([[:space:]])ostree[[:space:]]+(--repo[^[:space:]]+[[:space:]]+)?rebase|rpm-ostree[[:space:]]+rebase' "$f" 2>/dev/null | grep -vE '^[0-9]+:[[:space:]]*#' || true)
done < <(find "$ROOT" -type f \
    \( -path '*/.github/*.yml' -o -path '*/.github/*.yaml' -o \
       -name '*.sh' -o \
       -name 'Justfile*' -o \
       -name 'Containerfile*' -o \
       -name '*.container.in' -o \
       -name '*.toml' \) \
    -not -path '*/.git/*' \
    -not -path '*/node_modules/*' \
    2>/dev/null | sort)

# --- report -------------------------------------------------------------------
if [ "${#findings[@]}" -eq 0 ]; then
  echo "pinned-fetches (${MODE}): clean — no unpinned or unverified fetches found."
  exit 0
fi

printf 'pinned-fetches (%s): %d finding(s) across %d file(s):\n\n' \
  "$MODE" "${#findings[@]}" "$scanned"
printf '%s\n' "${findings[@]}"

if [ "$MODE" = "fail" ]; then
  echo "pinned-fetches: FAILED — fix the fetches above or add them to the allowlist."
  exit 1
fi

echo "pinned-fetches: WARN — findings above are recorded but not blocking this cycle."
echo "pinned-fetches: set --mode fail (or add them to the allowlist) once reviewed."
exit 0
