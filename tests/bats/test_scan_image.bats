#!/usr/bin/env bats
# Tests for the scan-image action's summarize-cves shell step.
#
# The shell logic lives inline in bootc-build/scan-image/action.yml.
# We extract it here verbatim (SUMMARIZE_LOGIC) so any edit to the action
# that changes testable behavior must also update this file.
#
# Covers:
#   - Missing trivy-results.json → exit 1 (fail-closed, the core fix for bluefin-lts#510)
#   - Empty results (no CVEs) → "No CVEs detected"
#   - Results with CRITICAL CVEs → critical-cves-found=true
#   - Results with only HIGH CVEs → critical-cves-found=false
#   - Duplicate CVEs are deduplicated
#   - Non-CVE entries (GHSA-*) are skipped
#   - Severity normalization from CVSS numeric scores
#   - Empty vulnerabilities array
#   - Multiple Result blocks are merged

# ── Shared summarize logic (verbatim from action.yml summarize-cves step) ────

SUMMARIZE_LOGIC='
set -euo pipefail
python3 <<'"'"'PY'"'"'
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, UTC
from pathlib import Path

severity_order = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"]

def normalize_severity(value):
    text = str(value or "").strip().upper()
    if text in severity_order:
        return text
    try:
        score = float(text)
    except ValueError:
        return "UNKNOWN"
    if score >= 9.0:
        return "CRITICAL"
    if score >= 7.0:
        return "HIGH"
    if score >= 4.0:
        return "MEDIUM"
    if score > 0:
        return "LOW"
    return "UNKNOWN"

findings_path = Path(os.environ["FINDINGS_FILE"])
display_ref = os.environ.get("IMAGE_REF") or os.environ.get("INPUT_PATH") or "unknown-image"
repo = os.environ.get("REPOSITORY", "")
run_url = os.environ.get("RUN_URL", "")
threshold = os.environ.get("SEVERITY_THRESHOLD", "CRITICAL")
ref_name = os.environ.get("REF_NAME", "") or "unknown-ref"
scan_date = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

counts = defaultdict(int)
trivy_results_path = Path("trivy-results.json")
if not trivy_results_path.exists():
    print(
        "::error::Trivy scan failed — trivy-results.json not found. "
        "The scan likely crashed (e.g. DB missing CPE indices for this OS). "
        "CVE status is UNKNOWN, not clean. "
        "See https://github.com/aquasecurity/trivy-db/issues/435"
    )
    sys.exit(1)
else:
    trivy = json.loads(trivy_results_path.read_text(encoding="utf-8"))
seen = set()
critical_entries = []
for result in trivy.get("Results", []) or []:
    target = result.get("Target", "")
    for vuln in result.get("Vulnerabilities", []) or []:
        cve_id = vuln.get("VulnerabilityID", "")
        if not cve_id.startswith("CVE-"):
            continue
        severity = normalize_severity(vuln.get("Severity"))
        counts[severity] += 1
        entry = {
            "package": vuln.get("PkgName", ""),
            "cve": cve_id,
            "severity": severity,
            "installed": vuln.get("InstalledVersion", ""),
            "fixed": vuln.get("FixedVersion", ""),
            "target": target,
        }
        if severity != "CRITICAL":
            continue
        key = (entry["package"], entry["cve"], entry["installed"], entry["fixed"])
        if key in seen:
            continue
        seen.add(key)
        critical_entries.append(entry)

total_cves = sum(counts.values())
highest_severity = next((name for name in severity_order if counts.get(name, 0) > 0), threshold)
issue_title = f"fix(security): critical CVE detected in {ref_name} build"
critical_entries.sort(key=lambda entry: (entry["cve"], entry["package"], entry["installed"]))
findings_path.write_text(
    json.dumps(
        {
            "image": display_ref,
            "repository": repo,
            "run_url": run_url,
            "scan_date": scan_date,
            "severity_threshold": threshold,
            "highest_severity": highest_severity,
            "total_cves": total_cves,
            "ref_name": ref_name,
            "critical_entries": critical_entries,
        },
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)

with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
    output.write(f"cves-found={"true" if total_cves else "false"}\n")
    output.write(f"critical-cves-found={"true" if critical_entries else "false"}\n")
    output.write(f"issue-title={issue_title}\n")
    output.write(f"findings-file={findings_path}\n")

if total_cves:
    print(f"::warning::{total_cves} CVE(s) detected in {display_ref}")
else:
    print(f"No CVEs detected in {display_ref}")
PY
'

# ── Helpers ──────────────────────────────────────────────────────────────────

setup() {
  TEST_TMP=$(mktemp -d)
  export GITHUB_OUTPUT="${TEST_TMP}/github_output"
  touch "$GITHUB_OUTPUT"
  export FINDINGS_FILE="${TEST_TMP}/scan-image-critical-findings.json"
  export IMAGE_REF="localhost/test-image:latest"
  export INPUT_PATH=""
  export SEVERITY_THRESHOLD="CRITICAL"
  export REPOSITORY="projectbluefin/test"
  export RUN_URL="https://github.com/projectbluefin/test/actions/runs/12345"
  export REF_NAME="testing"
  # Run in a temp dir so trivy-results.json doesn't leak between tests
  cd "$TEST_TMP"
}

teardown() {
  rm -rf "$TEST_TMP"
}

get_output() {
  local key="$1"
  grep "^${key}=" "$GITHUB_OUTPUT" | head -1 | cut -d= -f2-
}

# ── Tests ────────────────────────────────────────────────────────────────────

@test "missing trivy-results.json → exit 1 (fail-closed)" {
  rm -f trivy-results.json
  run bash -c "$SUMMARIZE_LOGIC"
  [ "$status" -ne 0 ]
  [[ "$output" == *"Trivy scan failed"* ]]
  [[ "$output" == *"trivy-results.json not found"* ]]
  [[ "$output" == *"::error::"* ]]
}

@test "empty results (no CVEs) → exit 0, No CVEs detected" {
  cat > trivy-results.json <<'EOF'
{"Results": []}
EOF
  run bash -c "$SUMMARIZE_LOGIC"
  [ "$status" -eq 0 ]
  [[ "$output" == *"No CVEs detected"* ]]
  [ "$(get_output cves-found)" = "false" ]
  [ "$(get_output critical-cves-found)" = "false" ]
}

@test "null Results field → exit 0, No CVEs detected" {
  cat > trivy-results.json <<'EOF'
{"Results": null}
EOF
  run bash -c "$SUMMARIZE_LOGIC"
  [ "$status" -eq 0 ]
  [[ "$output" == *"No CVEs detected"* ]]
  [ "$(get_output cves-found)" = "false" ]
}

@test "CRITICAL CVE → critical-cves-found=true" {
  cat > trivy-results.json <<'EOF'
{
  "Results": [
    {
      "Target": "os",
      "Vulnerabilities": [
        {
          "VulnerabilityID": "CVE-2026-1234",
          "PkgName": "openssl",
          "InstalledVersion": "1.0.1",
          "FixedVersion": "1.0.2",
          "Severity": "CRITICAL"
        }
      ]
    }
  ]
}
EOF
  run bash -c "$SUMMARIZE_LOGIC"
  [ "$status" -eq 0 ]
  [[ "$output" == *"1 CVE(s) detected"* ]]
  [ "$(get_output cves-found)" = "true" ]
  [ "$(get_output critical-cves-found)" = "true" ]

  # Verify findings file content
  local findings
  findings=$(cat "$FINDINGS_FILE")
  [[ "$(echo "$findings" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['total_cves'])")" = "1" ]]
  [[ "$(echo "$findings" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['critical_entries'][0]['cve'])")" = "CVE-2026-1234" ]]
  [[ "$(echo "$findings" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['critical_entries'][0]['package'])")" = "openssl" ]]
}

@test "only HIGH CVEs → critical-cves-found=false" {
  cat > trivy-results.json <<'EOF'
{
  "Results": [
    {
      "Target": "os",
      "Vulnerabilities": [
        {
          "VulnerabilityID": "CVE-2026-5678",
          "PkgName": "libxml2",
          "InstalledVersion": "2.9.0",
          "FixedVersion": "2.9.1",
          "Severity": "HIGH"
        }
      ]
    }
  ]
}
EOF
  run bash -c "$SUMMARIZE_LOGIC"
  [ "$status" -eq 0 ]
  [[ "$output" == *"1 CVE(s) detected"* ]]
  [ "$(get_output cves-found)" = "true" ]
  [ "$(get_output critical-cves-found)" = "false" ]

  local findings
  findings=$(cat "$FINDINGS_FILE")
  [[ "$(echo "$findings" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['highest_severity'])")" = "HIGH" ]]
  [[ "$(echo "$findings" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d['critical_entries']))")" = "0" ]]
}

@test "duplicate CRITICAL CVEs are deduplicated" {
  cat > trivy-results.json <<'EOF'
{
  "Results": [
    {
      "Target": "os",
      "Vulnerabilities": [
        {
          "VulnerabilityID": "CVE-2026-1234",
          "PkgName": "openssl",
          "InstalledVersion": "1.0.1",
          "FixedVersion": "1.0.2",
          "Severity": "CRITICAL"
        },
        {
          "VulnerabilityID": "CVE-2026-1234",
          "PkgName": "openssl",
          "InstalledVersion": "1.0.1",
          "FixedVersion": "1.0.2",
          "Severity": "CRITICAL"
        }
      ]
    }
  ]
}
EOF
  run bash -c "$SUMMARIZE_LOGIC"
  [ "$status" -eq 0 ]
  # Total count includes both, but critical_entries is deduplicated
  [ "$(get_output cves-found)" = "true" ]
  [ "$(get_output critical-cves-found)" = "true" ]

  local findings
  findings=$(cat "$FINDINGS_FILE")
  [[ "$(echo "$findings" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['total_cves'])")" = "2" ]]
  [[ "$(echo "$findings" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d['critical_entries']))")" = "1" ]]
}

@test "non-CVE entries (GHSA-*) are skipped" {
  cat > trivy-results.json <<'EOF'
{
  "Results": [
    {
      "Target": "os",
      "Vulnerabilities": [
        {
          "VulnerabilityID": "GHSA-1234-5678",
          "PkgName": "foo",
          "InstalledVersion": "1.0",
          "FixedVersion": "1.1",
          "Severity": "CRITICAL"
        },
        {
          "VulnerabilityID": "CVE-2026-9999",
          "PkgName": "bar",
          "InstalledVersion": "2.0",
          "FixedVersion": "2.1",
          "Severity": "HIGH"
        }
      ]
    }
  ]
}
EOF
  run bash -c "$SUMMARIZE_LOGIC"
  [ "$status" -eq 0 ]
  # Only the CVE entry counts
  [ "$(get_output cves-found)" = "true" ]
  [ "$(get_output critical-cves-found)" = "false" ]

  local findings
  findings=$(cat "$FINDINGS_FILE")
  [[ "$(echo "$findings" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['total_cves'])")" = "1" ]]
}

@test "severity normalization from CVSS numeric score" {
  cat > trivy-results.json <<'EOF'
{
  "Results": [
    {
      "Target": "os",
      "Vulnerabilities": [
        {
          "VulnerabilityID": "CVE-2026-0001",
          "PkgName": "a",
          "InstalledVersion": "1.0",
          "FixedVersion": "1.1",
          "Severity": "9.5"
        },
        {
          "VulnerabilityID": "CVE-2026-0002",
          "PkgName": "b",
          "InstalledVersion": "1.0",
          "FixedVersion": "1.1",
          "Severity": "7.5"
        },
        {
          "VulnerabilityID": "CVE-2026-0003",
          "PkgName": "c",
          "InstalledVersion": "1.0",
          "FixedVersion": "1.1",
          "Severity": "5.0"
        }
      ]
    }
  ]
}
EOF
  run bash -c "$SUMMARIZE_LOGIC"
  [ "$status" -eq 0 ]
  [ "$(get_output cves-found)" = "true" ]
  [ "$(get_output critical-cves-found)" = "true" ]

  local findings
  findings=$(cat "$FINDINGS_FILE")
  # 9.5 → CRITICAL, 7.5 → HIGH, 5.0 → MEDIUM = 3 total
  [[ "$(echo "$findings" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['total_cves'])")" = "3" ]]
  [[ "$(echo "$findings" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['highest_severity'])")" = "CRITICAL" ]]
}

@test "empty Vulnerabilities array → No CVEs detected" {
  cat > trivy-results.json <<'EOF'
{
  "Results": [
    {
      "Target": "os",
      "Vulnerabilities": []
    }
  ]
}
EOF
  run bash -c "$SUMMARIZE_LOGIC"
  [ "$status" -eq 0 ]
  [[ "$output" == *"No CVEs detected"* ]]
  [ "$(get_output cves-found)" = "false" ]
}

@test "multiple Result blocks are merged" {
  cat > trivy-results.json <<'EOF'
{
  "Results": [
    {
      "Target": "os",
      "Vulnerabilities": [
        {
          "VulnerabilityID": "CVE-2026-1111",
          "PkgName": "pkg-a",
          "InstalledVersion": "1.0",
          "FixedVersion": "1.1",
          "Severity": "CRITICAL"
        }
      ]
    },
    {
      "Target": "lib",
      "Vulnerabilities": [
        {
          "VulnerabilityID": "CVE-2026-2222",
          "PkgName": "pkg-b",
          "InstalledVersion": "2.0",
          "FixedVersion": "2.1",
          "Severity": "HIGH"
        }
      ]
    }
  ]
}
EOF
  run bash -c "$SUMMARIZE_LOGIC"
  [ "$status" -eq 0 ]
  [ "$(get_output cves-found)" = "true" ]
  [ "$(get_output critical-cves-found)" = "true" ]

  local findings
  findings=$(cat "$FINDINGS_FILE")
  [[ "$(echo "$findings" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['total_cves'])")" = "2" ]]
  [[ "$(echo "$findings" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d['critical_entries']))")" = "1" ]]
}

@test "missing fixed version shows as empty string in findings" {
  cat > trivy-results.json <<'EOF'
{
  "Results": [
    {
      "Target": "os",
      "Vulnerabilities": [
        {
          "VulnerabilityID": "CVE-2026-3333",
          "PkgName": "unfixed-pkg",
          "InstalledVersion": "1.0",
          "FixedVersion": "",
          "Severity": "CRITICAL"
        }
      ]
    }
  ]
}
EOF
  run bash -c "$SUMMARIZE_LOGIC"
  [ "$status" -eq 0 ]
  [ "$(get_output critical-cves-found)" = "true" ]

  local findings
  findings=$(cat "$FINDINGS_FILE")
  [[ "$(echo "$findings" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['critical_entries'][0]['fixed'])")" = "" ]]
}

@test "IMAGE_REF fallback to INPUT_PATH when IMAGE_REF is empty" {
  export IMAGE_REF=""
  export INPUT_PATH="/tmp/scan-image.tar"
  cat > trivy-results.json <<'EOF'
{"Results": []}
EOF
  run bash -c "$SUMMARIZE_LOGIC"
  [ "$status" -eq 0 ]

  local findings
  findings=$(cat "$FINDINGS_FILE")
  [[ "$(echo "$findings" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['image'])")" = "/tmp/scan-image.tar" ]]
}

@test "REF_NAME defaults to unknown-ref when empty" {
  export REF_NAME=""
  cat > trivy-results.json <<'EOF'
{"Results": []}
EOF
  run bash -c "$SUMMARIZE_LOGIC"
  [ "$status" -eq 0 ]

  local findings
  findings=$(cat "$FINDINGS_FILE")
  [[ "$(echo "$findings" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['ref_name'])")" = "unknown-ref" ]]
}
