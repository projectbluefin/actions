# Release Notes Redesign

**Date:** 2026-06-23  
**Scope:** `bootc-build/create-release`, `reusable-release.yml`, `bluefin-lts/execute-release.yml`  
**Affects:** bluefin, bluefin-lts, dakota

---

## Problem

Current release notes for bluefin-lts, bluefin, and dakota have five defects:

1. **Triple "Variants promoted" tables.** The `post-release-variants` job in `execute-release.yml` fetches the current release body and prepends a variants table. If the workflow runs more than once (dispatch + retries), each run prepends another copy with whatever digests were live at that moment. Three runs = three tables with divergent digests.

2. **Supply chain section dominates.** Four multi-line code blocks (`cosign`, `oras`, `slsa-verifier`) account for roughly 90% of the visible release body. Important for compliance users; invisible wall of text for everyone else.

3. **No story.** The notes are mechanically correct but contain no signal about what changed or why anyone should care. The full 2587-package SPDX inventory is embedded inline, replacing prose with bulk.

4. **LTS shows only one kernel.** The `bluefin-lts` variant uses the CentOS Stream 10 stock kernel; `bluefin-lts-hwe` / `bluefin-lts-hwe-nvidia` use the HWE (Fedora CoreOS stable) kernel. Currently only the HWE kernel appears because the SBOM comes from `bluefin-lts-hwe`. Users on the base variant cannot see their kernel version.

5. **Key components too sparse.** Only 4 packages (kernel, GNOME, flatpak, bootc). Missing components users care about: container runtime, audio stack, GPU stack, display protocol.

---

## Design

### Approach: Absorb variants into render_notes.py, kill post-release-variants

Move the variants table from a post-hoc `gh release edit` hack into `render_notes.py`. The table renders as part of the initial release creation. The `post-release-variants` job is deleted. The triple-table class of bug cannot recur.

---

## New Section Order (render_notes.py)

```
[Release card image]                     ← card PNG, very top

## Variants promoted                     ← NEW, only if --variants supplied
| image | :tag | sha256:... |

## Key components                        ← richer package set (see below)
| Kernel (HWE) | 7.0.9 | 6.x → 7.0.9 |
| Kernel (Base)| 6.12.x |              |  ← LTS only, from extra-components-json
| GNOME Shell  | 50.0   |              |
| Podman       | 5.x    |              |
| Distrobox    | 1.x    |              |
| systemd      | 257.x  |              |
| Mesa         | 25.x   |              |
| PipeWire     | 1.x    |              |
| Flatpak      | 1.18.x |              |
| bootc        | 1.15.x |              |

> N updated, M total.                    ← diff summary

<details> ↑ N updated   </details>       ← collapsed diff blocks
<details> + N added     </details>
<details> − N removed   </details>

## Contributors                          ← NEW, human contributors linked (no @ping)
[castrojo](https://github.com/castrojo) · [aaroneaton](https://github.com/aaroneaton)

<details>                                ← NEW, non-bot PRs, respects .github/release.yml labels
<summary>Merged since last release</summary>
**Features** / **Fixes** / **Other**
</details>

[Desktop screenshot]                     ← always included, URL from testsuite gh-pages

<details>                                ← supply chain: collapsed by default
<summary>Supply chain verification</summary>
[cosign / oras / slsa-verifier commands]
</details>

Full changelog → {docs_url}
```

**Removed from body:** full 2587-package SPDX inventory. The `.spdx.json` file is still attached as a release asset.

### Desktop screenshot

**Current implementation is broken for HWE variants.** `_screenshot_slug()` produces `bluefin-lts-hwe-testing-smoke-latest.png` → 404. Actual testsuite slugs are per image family:

```
bluefin-lts-testing-smoke-latest.png
bluefin-testing-smoke-latest.png
bluefin-testing-vanilla-gnome-latest.png
dakota-testing-smoke-latest.png
```

**Fix `_screenshot_slug()`:** strip variant suffixes before building the URL.

```python
def _screenshot_slug(image: str) -> str:
    slug = re.sub(r"^[^/]+/[^/]+/", "", image)        # strip registry prefix
    slug = re.sub(r":[^-]+$", "", slug)                 # strip tag
    slug = re.sub(r"-(hwe-nvidia|hwe|nvidia)$", "", slug)  # strip variant suffix
    return slug
```

`bluefin-lts-hwe` → `bluefin-lts` → `bluefin-lts-testing-smoke-latest.png` ✓

**Fix rendering:** use HTML `<img>` with width and descriptive alt text. GitHub release bodies render HTML.

```python
def _section_screenshot(image: str, tag: str, project_name: str) -> str:
    slug = _screenshot_slug(image)
    url = f"https://projectbluefin.github.io/testsuite/screenshots/{slug}-testing-smoke-latest.png"
    base_image = re.sub(r"^[^/]+/[^/]+/", "", image)
    return (
        "## Desktop Screenshot\n\n"
        f'<img src="{url}" alt="{project_name} desktop — {tag}" width="100%">\n\n'
        f"*Captured from `{base_image}:testing` during automated e2e validation — "
        f"[testsuite](https://github.com/projectbluefin/testsuite)*\n"
    )
```

Screenshot is **always included** — if the URL returns 404, the broken image is visible evidence of a test gap, not release bloat.

---

## LTS: Both Kernel Versions

**Problem:** Create-release is invoked with a single SBOM (from `bluefin-lts-hwe`). The base CentOS kernel lives in `bluefin-lts`, which has a different package set and no SBOM currently passed to create-release.

**Solution: `extra-components-json` input**

New optional input to `create-release/action.yml`:
```
extra-components-json: '[{"label":"Kernel (Base)","version":"6.12.0-22.el10"}]'
```

These rows inject directly into the Key Components table alongside the SBOM-derived notable packages. No second SBOM needed.

**How the LTS workflow extracts the base kernel version:**

In `execute-release.yml`, before the `release-notes` job:
```bash
BASE_KERNEL=$(skopeo inspect --no-tags \
  docker://ghcr.io/projectbluefin/bluefin-lts:stable \
  | jq -r '.Labels["ostree.linux"] // empty' \
  | grep -oP '[\d\.\-]+el\d+' | head -1)
```

If the label isn't present, fall back to running `rpm -q kernel` inside the container or omit the row gracefully.

The resolved version is passed as an output from a pre-release-notes job step into the `release-notes` job's `extra_components_json` input.

---

## Richer Notable Packages

### bluefin-lts `notable_packages`

```json
[
  {"sbom_name": "kernel", "label": "Kernel (HWE)"},
  {"sbom_name": "gnome-shell", "label": "GNOME Shell"},
  {"sbom_name": "podman", "label": "Podman"},
  {"sbom_name": "distrobox", "label": "Distrobox"},
  {"sbom_name": "systemd", "label": "systemd"},
  {"sbom_name": "mesa-vulkan-drivers", "label": "Mesa"},
  {"sbom_name": "pipewire", "label": "PipeWire"},
  {"sbom_name": "flatpak", "label": "Flatpak"},
  {"sbom_name": "bootc", "label": "bootc"}
]
```

### bluefin `notable_packages` (Fedora base)

```json
[
  {"sbom_name": "kernel", "label": "Kernel"},
  {"sbom_name": "gnome-shell", "label": "GNOME Shell"},
  {"sbom_name": "podman", "label": "Podman"},
  {"sbom_name": "distrobox", "label": "Distrobox"},
  {"sbom_name": "systemd", "label": "systemd"},
  {"sbom_name": "mesa-vulkan-drivers", "label": "Mesa"},
  {"sbom_name": "pipewire", "label": "PipeWire"},
  {"sbom_name": "flatpak", "label": "Flatpak"},
  {"sbom_name": "bootc", "label": "bootc"}
]
```

Notable packages that are absent from the SBOM are silently skipped by `sbom_diff.py` — no error. Safe to include speculatively.

---

## .github/release.yml (GitHub PR categorization)

Add to `projectbluefin/bluefin`, `projectbluefin/bluefin-lts`, and `projectbluefin/dakota`:

```yaml
# .github/release.yml
changelog:
  exclude:
    authors:
      - github-actions
      - renovate
      - dependabot
    labels:
      - dependencies
      - skip-changelog
  categories:
    - title: Features
      labels:
        - enhancement
        - feature
    - title: Fixes
      labels:
        - bug
        - fix
    - title: Other Changes
      labels:
        - "*"
```

This configures GitHub's `generate-notes` API (which `create-release` already calls) to exclude bot PRs and group by label. Our Python parser falls back to conventional-commit prefix parsing when labels are absent.

The `render_notes.py` PR changelog section uses the output from `generate-notes` — which respects this config automatically.

---

## Changes by File

### 1. `bootc-build/create-release/scripts/render_notes.py`

**New functions:**

- `_section_variants(variants: list[dict] | None) -> str`  
  Renders a markdown table from `[{"name": "bluefin-lts", "tag": ":stable", "digest": "sha256:...", "note": "..."}]`.  
  Returns `""` when `variants` is `None` or empty.

- `_section_contributors(contributors: list[str]) -> str`  
  Converts `["castrojo", "aaroneaton"]` to linked names: `[castrojo](https://github.com/castrojo) · [aaroneaton](...)`.  
  Returns `""` when list is empty.

- `_section_pr_changelog(prs: list[dict]) -> str`  
  Groups non-bot PRs by conventional-commit type (`feat`, `fix`, other).  
  Each PR: `- {title} (#{number})`.  
  Wrapped in a `<details>` block.  
  Returns `""` when list is empty.

**Modified functions:**

- `_section_supply_chain(...)` → wrapped in `<details><summary>Supply chain verification</summary>...</details>`. Commands unchanged.

**Removed functions:**

- `_section_full_inventory()` — deleted. Inventory stays in the SPDX asset only.

**New CLI args:**

| Arg | Type | Description |
|---|---|---|
| `--variants` | optional str | Path to JSON file: `[{"name":..., "tag":..., "digest":..., "note":...}]` |
| `--github-notes` | optional str | Path to JSON file from GitHub generate-notes API: `{"body": "..."}` |
| `--extra-components` | optional str | Path to JSON file: `[{"label":"Kernel (Base)","version":"6.12.x"}]` — injected into Key Components table |

**New main() section order:**
```python
sections = [
    _section_card(args.tag, args.repo),
    _section_variants(_load_variants(args.variants)),
    _section_notable(versions["notable"]),
    _section_diff_summary(versions["diff"], versions["has_prev"], total),
    _section_diff_details(versions["diff"], versions["has_prev"]),
    _section_contributors(contributors),
    _section_pr_changelog(prs),
    _section_screenshot(args.image, args.tag),
    _section_supply_chain(...),
    f"Full changelog → {args.docs_url}\n",
]
```

Where `contributors` and `prs` are parsed from the GitHub generate-notes JSON (see below).

---

### 2. `bootc-build/create-release/action.yml`

**New inputs:**

| Input | Required | Description |
|---|---|---|
| `variants-json` | no | JSON array of variant objects: `[{"name":"bluefin-lts","tag":":stable","digest":"sha256:...","note":"..."}]` |
| `extra-components-json` | no | JSON array of extra key component rows not in SBOM: `[{"label":"Kernel (Base)","version":"6.12.x"}]` |

**New step: Fetch GitHub generate-notes** (runs before "Render release notes"):
```yaml
- name: Fetch GitHub generate-notes
  id: gh-notes
  shell: bash
  env:
    GH_TOKEN: ${{ inputs.github-token }}
    REPO: ${{ inputs.repo }}
    TAG: ${{ inputs.tag }}
    PREV_TAG: ${{ steps.prev-sbom.outputs.tag }}
  run: |
    set -euo pipefail
    PREV_ARGS=()
    if [[ -n "${PREV_TAG:-}" ]]; then
      PREV_ARGS=(--field "previous_tag_name=${PREV_TAG}")
    fi
    gh api repos/"${REPO}"/releases/generate-notes \
      --method POST \
      --field "tag_name=${TAG}" \
      "${PREV_ARGS[@]}" \
      > _github_notes.json 2>/dev/null || echo '{"body":""}' > _github_notes.json
```

**Modified step: "Write notable-packages spec"** — also writes variants to disk:
```yaml
- name: Write variants spec
  shell: bash
  env:
    VARIANTS_JSON: ${{ inputs.variants-json }}
  run: |
    set -euo pipefail
    if [[ -n "${VARIANTS_JSON:-}" ]]; then
      echo "${VARIANTS_JSON}" > _variants.json
    fi
```

**Modified step: "Render release notes"** — passes new args:
```
--variants         _variants.json         (only if file exists)
--extra-components _extra_components.json (only if file exists)
--github-notes     _github_notes.json
```

**Cleanup step** — add `_variants.json _extra_components.json _github_notes.json` to `rm -f`.

---

### 3. `.github/workflows/reusable-release.yml`

**New input:**

| Input | Type | Required | Description |
|---|---|---|---|
| `variants_json` | string | no | Forwarded to create-release `variants-json` input |
| `extra_components_json` | string | no | Forwarded to create-release `extra-components-json` input |

**Modified "Create release" step** — add:
```yaml
variants-json:         ${{ inputs.variants_json }}
extra-components-json: ${{ inputs.extra_components_json }}
```

---

### 4. `projectbluefin/bluefin-lts/.github/workflows/execute-release.yml`

**Modified `release-notes` job** — add:
```yaml
with:
  variants_json: >-
    [
      {"name":"bluefin-lts","tag":":stable","digest":"${{ needs.execute.outputs.digest_lts }}"},
      {"name":"bluefin-lts-hwe","tag":":stable","digest":"${{ needs.execute.outputs.digest_hwe }}"},
      {"name":"bluefin-lts-hwe-nvidia","tag":":stable","digest":"${{ needs.execute.outputs.digest_nvidia }}"}
    ]
```

This requires `execute` job to expose per-variant digests as outputs. The `reusable-execute-release.yml` workflow needs to surface these.

**Deleted:** `post-release-variants` job — entirely removed.

---

## GitHub generate-notes Parsing (in render_notes.py)

The API returns:
```json
{
  "name": "...",
  "body": "## What's Changed\n* feat: X by @user1 in https://...#123\n\n## New Contributors\n* @user1 made their first contribution in #99\n\n**Full Changelog**: ..."
}
```

**Contributor extraction:**
- Parse `## New Contributors` section
- Regex: `@([A-Za-z0-9_-]+)` → username
- Filter: skip usernames ending in `[bot]` or equal to `github-actions`
- Format: `[username](https://github.com/username)` (link, not @mention — no ping)

**PR changelog extraction:**
- Parse `## What's Changed` section
- Each line: `* {title} by @{author} in https://...#{number}`
- Filter: skip lines where author ends in `[bot]`
- Conventional commit grouping: title starts with `feat:` → Features, `fix:` → Fixes, else Other
- Format: `- {title} (#{number})`
- Wrap in `<details><summary>Merged since last release</summary>...</details>`
- If all PRs are from bots, skip section entirely

---

## Scope of Changes

| Repo | Files | Breaking? |
|---|---|---|
| `projectbluefin/actions` | `create-release/scripts/render_notes.py`, `create-release/action.yml`, `.github/workflows/reusable-release.yml` | No — new inputs are optional |
| `projectbluefin/bluefin-lts` | `.github/workflows/execute-release.yml`, `.github/release.yml` (new) | No — deletes a job, adds inputs |
| `projectbluefin/bluefin` | `.github/release.yml` (new), update `notable_packages` in caller workflow | No |
| `projectbluefin/dakota` | `.github/release.yml` (new) | No |

Consumer validation: open draft PR in `projectbluefin/bluefin-lts` targeting `main`.

---

## Open Questions / Deferred

- `reusable-execute-release.yml` variant digest outputs: need to check if exposed. Fallback: `skopeo inspect` inside `release-notes` job to resolve digests.
- The base kernel version extraction via `ostree.linux` label may not always be present in the container image metadata. Fallback: run `rpm -q kernel` inside a temporary container, or omit the row if unavailable.
- Dakota single-image path: variants table not needed. `.github/release.yml` still applies.
- `notable_packages` in bluefin and bluefin-lts caller workflows: the exact SBOM package names (`mesa-vulkan-drivers`, `distrobox`, etc.) need to be verified against actual SBOMs before wiring up. `sbom_diff.py` silently skips missing names so incorrect names won't break releases, but the rows won't appear.
