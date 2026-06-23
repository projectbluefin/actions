# Release Notes Redesign

**Date:** 2026-06-23  
**Scope:** `bootc-build/create-release`, `reusable-release.yml`, `bluefin-lts/execute-release.yml`  
**Affects:** bluefin, bluefin-lts, dakota

---

## Problem

Current release notes for bluefin-lts, bluefin, and dakota have three defects:

1. **Triple "Variants promoted" tables.** The `post-release-variants` job in `execute-release.yml` fetches the current release body and prepends a variants table. If the workflow runs more than once (dispatch + retries), each run prepends another copy with whatever digests were live at that moment. Three runs = three tables with divergent digests.

2. **Supply chain section dominates.** Four multi-line code blocks (`cosign`, `oras`, `slsa-verifier`) account for roughly 90% of the visible release body. Important for compliance users; invisible wall of text for everyone else.

3. **No story.** The notes are mechanically correct but contain no signal about what changed or why anyone should care. The full 2587-package SPDX inventory is embedded inline, replacing prose with bulk.

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

## Key components                        ← existing, notable packages with changes highlighted
| Kernel | 7.0.9 | 6.x → 7.0.9 |

> N updated, M total.                    ← diff summary

<details> ↑ N updated   </details>       ← collapsed diff blocks
<details> + N added     </details>
<details> − N removed   </details>

## Contributors                          ← NEW, human contributors linked (no @ping)
[castrojo](https://github.com/castrojo) · [aaroneaton](https://github.com/aaroneaton)

<details>                                ← NEW, non-bot PRs grouped by type
<summary>Merged since last release</summary>
**Features** / **Fixes** / **Other**
</details>

[Desktop screenshot]                     ← near bottom

<details>                                ← supply chain: collapsed by default
<summary>Supply chain verification</summary>
[cosign / oras / slsa-verifier commands]
</details>

Full changelog → {docs_url}
```

**Removed from body:** full 2587-package SPDX inventory. The `.spdx.json` file is still attached as a release asset.

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
--variants     _variants.json    (only if file exists)
--github-notes _github_notes.json
```

**Cleanup step** — add `_variants.json _github_notes.json` to `rm -f`.

---

### 3. `.github/workflows/reusable-release.yml`

**New input:**

| Input | Type | Required | Description |
|---|---|---|---|
| `variants_json` | string | no | Forwarded to create-release `variants-json` input |

**Modified "Create release" step** — add:
```yaml
variants-json: ${{ inputs.variants_json }}
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
| `projectbluefin/bluefin-lts` | `.github/workflows/execute-release.yml` | No — deletes a job, adds inputs |
| `projectbluefin/bluefin` | None (uses single-image path, no variants) | No |
| `projectbluefin/dakota` | None | No |

Consumer validation required: open draft PR in `projectbluefin/bluefin-lts` targeting `main` (not bluefin's `testing` branch).

---

## Open Questions / Deferred

- `reusable-execute-release.yml` variant digest outputs: need to check if these are already exposed or need to be added. If not exposed, fallback is to call `skopeo inspect` inside the `release-notes` job instead of passing from `execute`.
- Dakota uses a different release path — verify variants table is not needed there (single-image). No action needed unless confirmed.
