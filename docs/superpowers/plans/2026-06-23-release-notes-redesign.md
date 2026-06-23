# Release Notes Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign release notes for bluefin, bluefin-lts, and dakota to be user-readable: richer key components, proper screenshots, contributors, collapsed supply chain, no full inventory in body, and fix the triple-table variant duplication bug.

**Architecture:** All rendering changes live in `render_notes.py` (new functions + reordered sections). New CLI args (`--variants`, `--extra-components`, `--github-notes`) feed new data in. `action.yml` adds two new inputs and a generate-notes fetch step. `reusable-release.yml` passes them through. The `post-release-variants` hack in `bluefin-lts/execute-release.yml` is deleted; variants render inline from the start.

**Tech Stack:** Python 3.10+ (stdlib only), pytest, GitHub Actions composite actions, `gh` CLI, `skopeo`, GitHub generate-notes REST API.

## Global Constraints

- No new Python dependencies — stdlib only in render_notes.py
- All new `action.yml` inputs are optional (no breaking changes to callers)
- Tests run with: `python3 -m pytest tests/test_render_notes.py -v`
- Pre-commit validation: `pre-commit run --files <changed files>`
- Consumer PR targets `main` in bluefin-lts, `testing` in bluefin — never the other way
- Commit format: `feat(create-release): ...` / `fix(create-release): ...` with AI trailer
- `_screenshot_slug()` must strip `-hwe`, `-hwe-nvidia`, `-nvidia` suffixes
- `_section_supply_chain()` content is unchanged — only wrapping changes
- `_section_full_inventory()` is deleted; its tests are deleted with it

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `bootc-build/create-release/scripts/render_notes.py` | Modify | All rendering logic changes |
| `tests/test_render_notes.py` | Modify | Tests for all render_notes changes |
| `bootc-build/create-release/action.yml` | Modify | New inputs + steps |
| `.github/workflows/reusable-release.yml` | Modify | Pass-through new inputs |
| `projectbluefin/bluefin-lts` (consumer PR) | Consumer PR | Wire variants + base kernel, delete post-release-variants, add .github/release.yml |
| `projectbluefin/bluefin` (consumer PR) | Consumer PR | Add .github/release.yml, update notable_packages |
| `projectbluefin/dakota` (consumer PR) | Consumer PR | Add .github/release.yml |

---

## Task 1: Fix screenshot slug and rendering

**Files:**
- Modify: `bootc-build/create-release/scripts/render_notes.py` — `_screenshot_slug()`, `_section_screenshot()`
- Modify: `tests/test_render_notes.py` — `TestSectionScreenshot`

**Context:** `_screenshot_slug("ghcr.io/projectbluefin/bluefin-lts-hwe")` currently returns `"bluefin-lts-hwe-testing"` → URL 404. Actual testsuite slugs are per family: `bluefin-lts-testing-smoke-latest.png`, `bluefin-testing-smoke-latest.png`, `dakota-testing-smoke-latest.png`. Also `_section_screenshot()` signature is `(image, label)` where label is the raw tag — needs `project_name` for better alt text. GitHub release bodies render HTML `<img>` tags correctly.

**Interfaces:**
- Produces: `_screenshot_slug(image: str) -> str`, `_section_screenshot(image: str, tag: str, project_name: str) -> str`

- [ ] **Step 1: Write failing tests**

Replace the `TestSectionScreenshot` class in `tests/test_render_notes.py`:

```python
class TestSectionScreenshot:
    def test_strips_registry_prefix(self):
        assert render_notes._screenshot_slug("ghcr.io/projectbluefin/bluefin") == "bluefin"

    def test_strips_tag(self):
        assert render_notes._screenshot_slug("ghcr.io/projectbluefin/bluefin:stable") == "bluefin"

    def test_strips_hwe_suffix(self):
        assert render_notes._screenshot_slug("ghcr.io/projectbluefin/bluefin-lts-hwe") == "bluefin-lts"

    def test_strips_hwe_nvidia_suffix(self):
        assert render_notes._screenshot_slug("ghcr.io/projectbluefin/bluefin-lts-hwe-nvidia") == "bluefin-lts"

    def test_strips_nvidia_suffix(self):
        assert render_notes._screenshot_slug("ghcr.io/projectbluefin/bluefin-nvidia") == "bluefin"

    def test_dakota_unchanged(self):
        assert render_notes._screenshot_slug("ghcr.io/projectbluefin/dakota") == "dakota"

    def test_renders_html_img_tag(self):
        md = render_notes._section_screenshot(
            "ghcr.io/projectbluefin/bluefin-lts-hwe", "stable-20260621", "Bluefin LTS"
        )
        assert '<img src=' in md
        assert 'width="100%"' in md

    def test_correct_url_for_hwe(self):
        md = render_notes._section_screenshot(
            "ghcr.io/projectbluefin/bluefin-lts-hwe", "stable-20260621", "Bluefin LTS"
        )
        assert "bluefin-lts-testing-smoke-latest.png" in md
        assert "bluefin-lts-hwe" not in md.split("screenshots/")[1].split(".png")[0]

    def test_alt_text_uses_project_name(self):
        md = render_notes._section_screenshot(
            "ghcr.io/projectbluefin/bluefin", "stable-20260621", "Bluefin"
        )
        assert "Bluefin desktop" in md

    def test_caption_identifies_image(self):
        md = render_notes._section_screenshot(
            "ghcr.io/projectbluefin/bluefin-lts-hwe", "stable-20260621", "Bluefin LTS"
        )
        assert "bluefin-lts-hwe:testing" in md

    def test_testsuite_link_present(self):
        md = render_notes._section_screenshot(
            "ghcr.io/projectbluefin/bluefin", "stable-20260621", "Bluefin"
        )
        assert "github.com/projectbluefin/testsuite" in md
```

- [ ] **Step 2: Run tests to confirm failures**

```bash
cd /var/home/jorge/src/actions
python3 -m pytest tests/test_render_notes.py::TestSectionScreenshot -v
```

Expected: multiple failures (`AssertionError` on slug and rendering)

- [ ] **Step 3: Replace `_screenshot_slug()` and `_section_screenshot()` in render_notes.py**

Replace the existing `_screenshot_slug` and `_section_screenshot` functions (lines ~79–98):

```python
def _screenshot_slug(image: str) -> str:
    """Derive testsuite screenshot family slug from an image ref.

    Screenshots live at: {slug}-testing-smoke-latest.png
    One screenshot per image family — strip registry, tag, and variant suffixes.

    Examples:
        ghcr.io/projectbluefin/bluefin-lts-hwe  → bluefin-lts
        ghcr.io/projectbluefin/bluefin:stable    → bluefin
        ghcr.io/projectbluefin/dakota            → dakota
    """
    slug = re.sub(r"^[^/]+/[^/]+/", "", image)               # strip registry/org prefix
    slug = re.sub(r":.*$", "", slug)                           # strip tag
    slug = re.sub(r"-(hwe-nvidia|hwe|nvidia)$", "", slug)     # strip variant suffix
    return slug


def _section_screenshot(image: str, tag: str, project_name: str) -> str:
    """Render desktop screenshot section with HTML img tag and caption."""
    slug = _screenshot_slug(image)
    url = (
        f"https://projectbluefin.github.io/testsuite/screenshots/"
        f"{slug}-testing-smoke-latest.png"
    )
    base_image = re.sub(r"^[^/]+/[^/]+/", "", image)
    return (
        "## Desktop Screenshot\n\n"
        f'<img src="{url}" alt="{project_name} desktop \u2014 {tag}" width="100%">\n\n'
        f"*Captured from `{base_image}:testing` during automated e2e validation \u2014 "
        f"[testsuite](https://github.com/projectbluefin/testsuite)*\n"
    )
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
python3 -m pytest tests/test_render_notes.py::TestSectionScreenshot -v
```

Expected: 11 tests pass

- [ ] **Step 5: Commit**

```bash
git add bootc-build/create-release/scripts/render_notes.py tests/test_render_notes.py
git commit -m "fix(create-release): fix screenshot slug for HWE variants, use HTML img tag

- Strip -hwe/-hwe-nvidia/-nvidia suffixes from image slug
  (bluefin-lts-hwe-testing-smoke-latest.png was 404; now bluefin-lts)
- Replace bare markdown image with <img width=100%> for proper sizing
- Add descriptive alt text with project_name
- Add testsuite link in caption
- Update and expand TestSectionScreenshot

Assisted-by: Claude Sonnet 4.6 via GitHub Copilot
Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 2: Add variants section, extra-components, collapse supply chain, remove inventory

**Files:**
- Modify: `bootc-build/create-release/scripts/render_notes.py`
- Modify: `tests/test_render_notes.py`

**Context:** Add `_section_variants()` for the multi-variant digest table. Add `_load_extra_components()` to parse `--extra-components` JSON. Wrap `_section_supply_chain()` in a `<details>` block. Delete `_section_full_inventory()` and its `_load_full_inventory()` helper (no longer needed — inventory stays in SPDX asset). Delete `TestSectionFullInventory` tests.

**Interfaces:**
- Consumes: `_screenshot_slug()` (Task 1)
- Produces:
  - `_section_variants(variants: list[dict] | None) -> str`
  - `_load_extra_components(path: str | None) -> list[dict]` — returns `[{"name": label, "version": version, "prev": None, "changed": False}]`
  - `_section_supply_chain(...)` — same signature, now returns `<details>` wrapped output

- [ ] **Step 1: Write failing tests**

Add these classes to `tests/test_render_notes.py` (append after existing tests):

```python
class TestSectionVariants:
    def test_empty_returns_empty_string(self):
        assert render_notes._section_variants(None) == ""
        assert render_notes._section_variants([]) == ""

    def test_single_variant_appears_in_table(self):
        variants = [{"name": "bluefin-lts", "tag": ":stable", "digest": "sha256:abc123"}]
        md = render_notes._section_variants(variants)
        assert "bluefin-lts" in md
        assert ":stable" in md
        assert "sha256:abc123" in md

    def test_multiple_variants_all_appear(self):
        variants = [
            {"name": "bluefin-lts", "tag": ":stable", "digest": "sha256:aaa"},
            {"name": "bluefin-lts-hwe", "tag": ":stable", "digest": "sha256:bbb"},
            {"name": "bluefin-lts-hwe-nvidia", "tag": ":stable", "digest": "sha256:ccc"},
        ]
        md = render_notes._section_variants(variants)
        assert "bluefin-lts" in md
        assert "bluefin-lts-hwe" in md
        assert "bluefin-lts-hwe-nvidia" in md
        assert "sha256:aaa" in md
        assert "sha256:bbb" in md
        assert "sha256:ccc" in md

    def test_optional_note_appears(self):
        variants = [{"name": "img", "tag": ":stable", "digest": "sha256:x",
                     "note": "Uses HWE kernel"}]
        md = render_notes._section_variants(variants)
        assert "Uses HWE kernel" in md

    def test_has_variants_promoted_heading(self):
        variants = [{"name": "img", "tag": ":stable", "digest": "sha256:x"}]
        md = render_notes._section_variants(variants)
        assert "## Variants promoted" in md

    def test_is_markdown_table(self):
        variants = [{"name": "img", "tag": ":stable", "digest": "sha256:x"}]
        md = render_notes._section_variants(variants)
        assert "|" in md


class TestLoadExtraComponents:
    def test_none_path_returns_empty(self):
        assert render_notes._load_extra_components(None) == []

    def test_missing_file_returns_empty(self):
        assert render_notes._load_extra_components("/nonexistent/path.json") == []

    def test_parses_label_version(self, tmp_path):
        f = tmp_path / "extra.json"
        f.write_text('[{"label": "Kernel (Base)", "version": "6.12.0-22.el10"}]')
        result = render_notes._load_extra_components(str(f))
        assert len(result) == 1
        assert result[0]["name"] == "Kernel (Base)"
        assert result[0]["version"] == "6.12.0-22.el10"
        assert result[0]["prev"] is None
        assert result[0]["changed"] is False

    def test_multiple_components(self, tmp_path):
        f = tmp_path / "extra.json"
        f.write_text('[{"label": "A", "version": "1.0"}, {"label": "B", "version": "2.0"}]')
        result = render_notes._load_extra_components(str(f))
        assert len(result) == 2


class TestSupplyChainCollapsed:
    def test_wrapped_in_details_block(self):
        md = render_notes._section_supply_chain(
            image="ghcr.io/projectbluefin/bluefin",
            digest="sha256:abc123",
            repo="projectbluefin/bluefin",
            tag="2026-05-14-abc1234",
            cert_regexp="^https://github.com/",
            sbom_filename="bluefin.spdx.json",
            docs_url="https://docs.projectbluefin.io/changelogs",
        )
        assert "<details>" in md
        assert "</details>" in md
        assert "<summary>Supply chain verification</summary>" in md

    def test_commands_still_present(self):
        md = render_notes._section_supply_chain(
            image="ghcr.io/projectbluefin/bluefin",
            digest="sha256:abc123",
            repo="projectbluefin/bluefin",
            tag="2026-05-14-abc1234",
            cert_regexp="^https://github.com/",
            sbom_filename="bluefin.spdx.json",
            docs_url="https://docs.projectbluefin.io/changelogs",
        )
        assert "cosign verify" in md
        assert "oras discover" in md
        assert "slsa-verifier" in md
```

Also **delete** the `TestSectionFullInventory` class entirely from the test file.

- [ ] **Step 2: Run tests to confirm failures**

```bash
python3 -m pytest tests/test_render_notes.py::TestSectionVariants \
  tests/test_render_notes.py::TestLoadExtraComponents \
  tests/test_render_notes.py::TestSupplyChainCollapsed -v
```

Expected: failures for all three new classes

- [ ] **Step 3: Implement in render_notes.py**

**3a. Add `_section_variants()` after `_section_card()`:**

```python
def _section_variants(variants: list[dict] | None) -> str:
    """Render promoted variants table. Returns '' when variants is None or empty."""
    if not variants:
        return ""
    rows = []
    notes = []
    for v in variants:
        rows.append(f"| `{v['name']}` | `{v['tag']}` | `{v['digest']}` |")
        if v.get("note"):
            notes.append(v["note"])
    table = (
        "## Variants promoted\n\n"
        "| Variant | Tag | Digest |\n"
        "|---|---|---|\n"
        + "\n".join(rows)
    )
    if notes:
        table += "\n\n" + "\n\n".join(f"> {n}" for n in notes)
    return table + "\n"
```

**3b. Add `_load_extra_components()` in the helpers section:**

```python
def _load_extra_components(path: str | None) -> list[dict]:
    """Load extra key-component rows from a JSON file.

    File format: [{"label": "Kernel (Base)", "version": "6.12.0"}]
    Returns rows in the same shape as notable package dicts so they can be
    appended directly to the notable list and rendered by _section_notable().
    Returns [] when path is None or file does not exist.
    """
    if not path or not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return [
        {"name": item["label"], "version": item["version"], "prev": None, "changed": False}
        for item in data
    ]
```

**3c. Wrap `_section_supply_chain()` return value in `<details>`:**

Find the `return f"""\` at the end of `_section_supply_chain()`. Wrap the entire returned string:

```python
    body = f"""\
## Supply chain

This image is signed, attested, and ships a full SPDX-JSON SBOM.
Every artifact below is verifiable without trusting this release page.

**Tools required** — install via Homebrew or see links in each section:

```bash
brew install cosign oras slsa-verifier
```

---

### 1 — Verify the image signature
...
[rest of existing supply chain content, unchanged]
...

Full changelog and verification guide → {docs_url}
"""
    return f"<details>\n<summary>Supply chain verification</summary>\n\n{body}\n</details>\n"
```

The exact body content is unchanged from the current implementation — only the outer `<details>` wrapper is new. Find the existing `return f"""` and change it to `body = f"""`, then add the return line with `<details>` wrapping after the triple-quote block closes.

**3d. Delete `_load_full_inventory()` and `_section_full_inventory()` functions entirely.**

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/test_render_notes.py -v
```

Expected: all tests pass. `TestSectionFullInventory` should no longer exist. `TestSectionSupplyChain` existing tests (test_contains_cosign_command etc.) must still pass since commands are unchanged.

- [ ] **Step 5: Commit**

```bash
git add bootc-build/create-release/scripts/render_notes.py tests/test_render_notes.py
git commit -m "feat(create-release): add variants table, extra-components, collapse supply chain

- Add _section_variants() for multi-image digest table
- Add _load_extra_components() for LTS dual-kernel injection
- Wrap _section_supply_chain() in <details> block (commands unchanged)
- Delete _section_full_inventory() and _load_full_inventory()
  (SPDX asset remains attached; body no longer includes 2500+ package table)

Assisted-by: Claude Sonnet 4.6 via GitHub Copilot
Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 3: Add contributors and PR changelog sections

**Files:**
- Modify: `bootc-build/create-release/scripts/render_notes.py`
- Modify: `tests/test_render_notes.py`

**Context:** GitHub's `generate-notes` API returns markdown with `## What's Changed` (list of PRs) and `## New Contributors` (first-time contributors). We parse this to extract human-only contributors (no `[bot]`) and group non-bot PRs by type (feat/fix/other). Both sections return `""` when empty so no section appears in purely-agentic releases.

**Interfaces:**
- Produces:
  - `_parse_github_notes(body: str) -> dict` — returns `{"contributors": list[str], "prs": list[dict]}`
  - `_section_contributors(contributors: list[str]) -> str`
  - `_section_pr_changelog(prs: list[dict]) -> str`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_render_notes.py`:

```python
GITHUB_NOTES_BODY = """\
## What's Changed
* feat: add X feature by @castrojo in https://github.com/projectbluefin/bluefin-lts/pull/101
* fix: fix Y bug by @aaroneaton in https://github.com/projectbluefin/bluefin-lts/pull/102
* chore(deps): bump foo by @renovate[bot] in https://github.com/projectbluefin/bluefin-lts/pull/103
* chore: update image by @github-actions[bot] in https://github.com/projectbluefin/bluefin-lts/pull/104

## New Contributors
* @castrojo made their first contribution in https://github.com/projectbluefin/bluefin-lts/pull/101
* @aaroneaton made their first contribution in https://github.com/projectbluefin/bluefin-lts/pull/102

**Full Changelog**: https://github.com/projectbluefin/bluefin-lts/compare/prev...new
"""

BOT_ONLY_BODY = """\
## What's Changed
* chore(deps): bump foo by @renovate[bot] in https://github.com/org/repo/pull/1
* chore: build image by @github-actions[bot] in https://github.com/org/repo/pull/2
"""


class TestParseGithubNotes:
    def test_extracts_human_contributors(self):
        result = render_notes._parse_github_notes(GITHUB_NOTES_BODY)
        assert "castrojo" in result["contributors"]
        assert "aaroneaton" in result["contributors"]

    def test_filters_bot_contributors(self):
        result = render_notes._parse_github_notes(GITHUB_NOTES_BODY)
        for c in result["contributors"]:
            assert "[bot]" not in c
            assert c != "github-actions"

    def test_extracts_human_prs(self):
        result = render_notes._parse_github_notes(GITHUB_NOTES_BODY)
        titles = [pr["title"] for pr in result["prs"]]
        assert any("feat: add X feature" in t for t in titles)
        assert any("fix: fix Y bug" in t for t in titles)

    def test_filters_bot_prs(self):
        result = render_notes._parse_github_notes(GITHUB_NOTES_BODY)
        for pr in result["prs"]:
            assert "renovate" not in pr.get("author", "")
            assert "github-actions" not in pr.get("author", "")

    def test_captures_pr_number(self):
        result = render_notes._parse_github_notes(GITHUB_NOTES_BODY)
        numbers = [pr["number"] for pr in result["prs"]]
        assert "101" in numbers
        assert "102" in numbers

    def test_captures_pr_type(self):
        result = render_notes._parse_github_notes(GITHUB_NOTES_BODY)
        types = {pr["number"]: pr["type"] for pr in result["prs"]}
        assert types["101"] == "feat"
        assert types["102"] == "fix"

    def test_empty_body_returns_empty_lists(self):
        result = render_notes._parse_github_notes("")
        assert result["contributors"] == []
        assert result["prs"] == []

    def test_bot_only_body_returns_empty_prs(self):
        result = render_notes._parse_github_notes(BOT_ONLY_BODY)
        assert result["prs"] == []


class TestSectionContributors:
    def test_empty_list_returns_empty_string(self):
        assert render_notes._section_contributors([]) == ""

    def test_single_contributor_linked(self):
        md = render_notes._section_contributors(["castrojo"])
        assert "[castrojo](https://github.com/castrojo)" in md

    def test_multiple_contributors_separated(self):
        md = render_notes._section_contributors(["castrojo", "aaroneaton"])
        assert "castrojo" in md
        assert "aaroneaton" in md

    def test_no_at_sign_in_output(self):
        md = render_notes._section_contributors(["castrojo"])
        assert "@castrojo" not in md

    def test_has_contributors_heading(self):
        md = render_notes._section_contributors(["castrojo"])
        assert "## Contributors" in md


class TestSectionPrChangelog:
    FEAT_PRS = [
        {"title": "feat: add something", "number": "1", "type": "feat", "author": "castrojo"},
    ]
    FIX_PRS = [
        {"title": "fix: fix something", "number": "2", "type": "fix", "author": "aaroneaton"},
    ]
    MIXED_PRS = FEAT_PRS + FIX_PRS + [
        {"title": "docs: update readme", "number": "3", "type": "other", "author": "user3"},
    ]

    def test_empty_list_returns_empty_string(self):
        assert render_notes._section_pr_changelog([]) == ""

    def test_wrapped_in_details(self):
        md = render_notes._section_pr_changelog(self.FEAT_PRS)
        assert "<details>" in md
        assert "</details>" in md

    def test_feat_prs_in_features_group(self):
        md = render_notes._section_pr_changelog(self.MIXED_PRS)
        assert "Features" in md
        assert "add something" in md

    def test_fix_prs_in_fixes_group(self):
        md = render_notes._section_pr_changelog(self.MIXED_PRS)
        assert "Fixes" in md
        assert "fix something" in md

    def test_other_prs_in_other_group(self):
        md = render_notes._section_pr_changelog(self.MIXED_PRS)
        assert "Other" in md
        assert "update readme" in md

    def test_pr_number_appears(self):
        md = render_notes._section_pr_changelog(self.FEAT_PRS)
        assert "#1" in md
```

- [ ] **Step 2: Run tests to confirm failures**

```bash
python3 -m pytest tests/test_render_notes.py::TestParseGithubNotes \
  tests/test_render_notes.py::TestSectionContributors \
  tests/test_render_notes.py::TestSectionPrChangelog -v
```

Expected: all fail with `AttributeError: module 'render_notes' has no attribute ...`

- [ ] **Step 3: Implement in render_notes.py**

Add after the existing section-builder helpers, before `_section_supply_chain`:

```python
# ── GitHub generate-notes parsing ─────────────────────────────────────────────

_BOT_PATTERN = re.compile(r"\[bot\]$|^github-actions$|^renovate$|^dependabot$")


def _parse_github_notes(body: str) -> dict:
    """Parse GitHub generate-notes API response body.

    Returns {"contributors": list[str], "prs": list[dict]}
    where prs are non-bot entries with keys: title, number, author, type.
    type is one of: "feat", "fix", "other".
    """
    contributors: list[str] = []
    prs: list[dict] = []

    # ── Extract contributors from ## New Contributors section ─────────────
    contrib_section = re.search(
        r"## New Contributors\n(.*?)(?:\n## |\n\*\*Full Changelog|$)",
        body, re.DOTALL
    )
    if contrib_section:
        for m in re.finditer(r"@([A-Za-z0-9_-]+(?:\[bot\])?)", contrib_section.group(1)):
            username = m.group(1)
            if not _BOT_PATTERN.search(username):
                contributors.append(username)

    # ── Extract PRs from ## What's Changed section ────────────────────────
    changed_section = re.search(
        r"## What's Changed\n(.*?)(?:\n## |\n\*\*Full Changelog|$)",
        body, re.DOTALL
    )
    if changed_section:
        # Each line: "* {title} by @{author} in https://.../{number}"
        pr_pattern = re.compile(
            r"^\* (.+?) by @([A-Za-z0-9_-]+(?:\[bot\])?) in https://[^\s]+/(\d+)\s*$",
            re.MULTILINE,
        )
        for m in pr_pattern.finditer(changed_section.group(1)):
            title, author, number = m.group(1), m.group(2), m.group(3)
            if _BOT_PATTERN.search(author):
                continue
            pr_type = "other"
            if title.startswith("feat"):
                pr_type = "feat"
            elif title.startswith("fix"):
                pr_type = "fix"
            prs.append({"title": title, "number": number, "author": author, "type": pr_type})

    return {"contributors": contributors, "prs": prs}


def _section_contributors(contributors: list[str]) -> str:
    """Render human contributors as linked names (no @-ping)."""
    if not contributors:
        return ""
    links = " \u00b7 ".join(
        f"[{u}](https://github.com/{u})" for u in contributors
    )
    return f"## Contributors\n\n{links}\n"


def _section_pr_changelog(prs: list[dict]) -> str:
    """Render non-bot PRs grouped by type in a collapsible details block."""
    if not prs:
        return ""

    groups: dict[str, list[dict]] = {"feat": [], "fix": [], "other": []}
    for pr in prs:
        groups.setdefault(pr.get("type", "other"), []).append(pr)

    group_titles = {"feat": "Features", "fix": "Fixes", "other": "Other Changes"}
    blocks: list[str] = []
    for key in ("feat", "fix", "other"):
        if not groups[key]:
            continue
        lines = "\n".join(f"- {pr['title']} (#{pr['number']})" for pr in groups[key])
        blocks.append(f"**{group_titles[key]}**\n\n{lines}")

    body = "\n\n".join(blocks)
    return (
        "<details>\n"
        "<summary>Merged since last release</summary>\n\n"
        f"{body}\n\n"
        "</details>\n"
    )
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/test_render_notes.py -v
```

Expected: all tests pass (including existing 29 + new tests)

- [ ] **Step 5: Commit**

```bash
git add bootc-build/create-release/scripts/render_notes.py tests/test_render_notes.py
git commit -m "feat(create-release): add contributors and PR changelog sections

- _parse_github_notes(): extract humans from generate-notes API response
- _section_contributors(): linked names without @ping
- _section_pr_changelog(): non-bot PRs grouped feat/fix/other in <details>
- Both sections return '' when empty (agentic-heavy releases stay clean)

Assisted-by: Claude Sonnet 4.6 via GitHub Copilot
Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 4: New section order in main() + update CLI args

**Files:**
- Modify: `bootc-build/create-release/scripts/render_notes.py` — `main()`, argparse, docstring
- Modify: `tests/test_render_notes.py` — `TestOverflowGuard._make_args()` + `_make_argv()`

**Context:** Wire everything together. New section order: card → variants → key components (notable + extra) → diff summary → diff details → contributors → PR changelog → screenshot → supply chain (collapsed) → footer. Remove `--sbom` from driving inventory (still needed for diff). Add `--variants`, `--extra-components`, `--github-notes` args. Update the compact overflow path to also omit the inventory (it's already removed from the full path). Update docstring.

**Interfaces:**
- Consumes: all functions from Tasks 1–3
- Produces: updated `main()` with new arg surface

- [ ] **Step 1: Update `_make_args` in TestOverflowGuard and add integration test for new sections**

In `tests/test_render_notes.py`, update `_make_args()` in `TestOverflowGuard` to add the missing new args to the Namespace and update the argv list used in the test:

```python
def _make_argv(self, tmp_path, max_chars=120_000, extra_sbom_pkgs=10):
    """Build argv list for render_notes.main() with the new arg surface."""
    import json

    sbom = {
        "spdxVersion": "SPDX-2.3",
        "packages": [
            {"name": f"pkg-{i}", "versionInfo": f"1.{i}"}
            for i in range(extra_sbom_pkgs)
        ],
    }
    sbom_path = tmp_path / "test.sbom.json"
    sbom_path.write_text(json.dumps(sbom))

    versions = {
        "notable": [],
        "diff": {"changed_count": 0, "added_count": 0, "removed_count": 0,
                 "changed": [], "added": [], "removed": []},
        "has_prev": False,
        "total_packages": extra_sbom_pkgs,
    }
    versions_path = tmp_path / "versions.json"
    versions_path.write_text(json.dumps(versions))

    output_path   = tmp_path / "release-notes.md"
    overflow_path = tmp_path / "release-notes-full.md"

    return (
        [
            "render_notes.py",
            "--versions", str(versions_path),
            "--sbom",     str(sbom_path),
            "--tag",      "2026-06-01-abc1234",
            "--title",    "Test Stable 2026-06-01",
            "--image",    "ghcr.io/example/img",
            "--digest",   "sha256:deadbeef",
            "--repo",     "example/img",
            "--cert-regexp", "^https://github.com/example/",
            "--overflow-file", str(overflow_path),
            "--output",   str(output_path),
            "--max-chars", str(max_chars),
        ],
        str(output_path),
        str(overflow_path),
    )
```

Replace the three `TestOverflowGuard` test methods to use `_make_argv` instead of `_make_args`:

```python
def test_no_overflow_when_under_limit(self, tmp_path):
    import os, sys
    argv, output_path, overflow_path = self._make_argv(tmp_path, max_chars=120_000)
    old_argv = sys.argv
    sys.argv = argv
    try:
        render_notes.main()
    finally:
        sys.argv = old_argv
    assert os.path.exists(output_path)
    assert not os.path.exists(overflow_path), \
        "Overflow file should NOT be created when notes are within limits"

def test_overflow_file_created_when_over_limit(self, tmp_path):
    import os, sys
    argv, output_path, overflow_path = self._make_argv(tmp_path, max_chars=500)
    old_argv = sys.argv
    sys.argv = argv
    try:
        render_notes.main()
    finally:
        sys.argv = old_argv
    assert os.path.exists(output_path), "Trimmed output must still be created"
    assert os.path.exists(overflow_path), \
        "Overflow file must be created when notes exceed max_chars"
    body = open(output_path).read()
    full = open(overflow_path).read()
    assert len(body) <= 520, f"Trimmed body must be within max_chars (got {len(body)})"
    assert len(full) > len(body), "Full notes must be longer than the trimmed body"

def test_overflow_body_stays_under_github_limit(self, tmp_path):
    import os, sys
    argv, output_path, overflow_path = self._make_argv(tmp_path, extra_sbom_pkgs=3000)
    old_argv = sys.argv
    sys.argv = argv
    try:
        render_notes.main()
    finally:
        sys.argv = old_argv
    assert os.path.exists(output_path)
    body = open(output_path).read()
    # With inventory removed from body, even 3000 packages won't overflow
    assert len(body) <= 120_000, \
        f"Release body must stay <= 120 000 chars (got {len(body)})"
```

Also add an integration test for section ordering:

```python
class TestSectionOrder:
    def _run_main(self, tmp_path, variants=None, extra_components=None):
        import json, sys
        sbom = {"spdxVersion": "SPDX-2.3", "packages": [
            {"name": "kernel", "versionInfo": "6.10.0"}
        ]}
        versions = {
            "notable": [{"name": "Kernel", "version": "6.10.0", "prev": None, "changed": False}],
            "diff": {"changed_count": 0, "added_count": 0, "removed_count": 0,
                     "changed": [], "added": [], "removed": []},
            "has_prev": False,
            "total_packages": 1,
        }
        sbom_path = tmp_path / "s.sbom.json"
        sbom_path.write_text(json.dumps(sbom))
        versions_path = tmp_path / "versions.json"
        versions_path.write_text(json.dumps(versions))
        output_path = tmp_path / "notes.md"

        argv = [
            "render_notes.py",
            "--versions", str(versions_path),
            "--sbom", str(sbom_path),
            "--tag", "stable-20260621",
            "--title", "Test",
            "--image", "ghcr.io/example/img",
            "--digest", "sha256:abc",
            "--repo", "example/img",
            "--cert-regexp", "^https://",
            "--output", str(output_path),
        ]
        if variants:
            v_path = tmp_path / "variants.json"
            v_path.write_text(json.dumps(variants))
            argv += ["--variants", str(v_path)]
        if extra_components:
            e_path = tmp_path / "extra.json"
            e_path.write_text(json.dumps(extra_components))
            argv += ["--extra-components", str(e_path)]

        old_argv = sys.argv
        sys.argv = argv
        try:
            render_notes.main()
        finally:
            sys.argv = old_argv
        return output_path.read_text()

    def test_card_appears_before_key_components(self, tmp_path):
        md = self._run_main(tmp_path)
        card_pos = md.find("release-card.png")
        components_pos = md.find("## Key components")
        assert card_pos < components_pos, "Card must appear before key components"

    def test_key_components_appears_before_screenshot(self, tmp_path):
        md = self._run_main(tmp_path)
        components_pos = md.find("## Key components")
        screenshot_pos = md.find("## Desktop Screenshot")
        assert components_pos < screenshot_pos

    def test_screenshot_appears_before_supply_chain(self, tmp_path):
        md = self._run_main(tmp_path)
        screenshot_pos = md.find("## Desktop Screenshot")
        supply_pos = md.find("Supply chain verification")
        assert screenshot_pos < supply_pos

    def test_variants_appear_after_card(self, tmp_path):
        variants = [{"name": "img", "tag": ":stable", "digest": "sha256:x"}]
        md = self._run_main(tmp_path, variants=variants)
        card_pos = md.find("release-card.png")
        variants_pos = md.find("## Variants promoted")
        assert card_pos < variants_pos

    def test_extra_components_in_key_components_table(self, tmp_path):
        extra = [{"label": "Kernel (Base)", "version": "6.12.0-22.el10"}]
        md = self._run_main(tmp_path, extra_components=extra)
        assert "Kernel (Base)" in md
        assert "6.12.0-22.el10" in md

    def test_full_inventory_not_in_body(self, tmp_path):
        md = self._run_main(tmp_path)
        # Should not contain the full SPDX inventory marker
        assert "Full SPDX package inventory" not in md
        assert "📦" not in md

    def test_supply_chain_is_collapsed(self, tmp_path):
        md = self._run_main(tmp_path)
        assert "<details>" in md
        assert "Supply chain verification" in md
        # cosign commands should be inside a details block
        details_start = md.find("<details>")
        cosign_pos = md.find("cosign verify")
        assert cosign_pos > details_start
```

- [ ] **Step 2: Run tests to confirm failures**

```bash
python3 -m pytest tests/test_render_notes.py::TestSectionOrder \
  tests/test_render_notes.py::TestOverflowGuard -v
```

Expected: `TestSectionOrder` fails (functions exist but `main()` not yet updated). `TestOverflowGuard` may fail due to missing `_make_argv`.

- [ ] **Step 3: Update `main()` in render_notes.py**

Replace the `main()` function. Key changes: add new args, load variants/extra/github-notes, reorder sections, remove inventory from both full and compact paths.

```python
def main() -> None:
    ap = argparse.ArgumentParser(description="Generate release notes markdown.")
    ap.add_argument("--versions",         required=True,
                    help="Path to versions.json (from sbom_diff.py)")
    ap.add_argument("--sbom",             required=True,
                    help="Path to current SPDX-JSON SBOM")
    ap.add_argument("--tag",              required=True)
    ap.add_argument("--title",            required=True)
    ap.add_argument("--image",            required=True,
                    help="Full image ref without tag (e.g. ghcr.io/projectbluefin/bluefin)")
    ap.add_argument("--digest",           required=True,
                    help="Image digest (sha256:...)")
    ap.add_argument("--repo",             required=True,
                    help="GitHub repo slug (org/repo)")
    ap.add_argument("--project-name",     default="Bluefin")
    ap.add_argument("--cert-regexp",      required=True,
                    help="cosign --certificate-identity-regexp value")
    ap.add_argument("--docs-url",
                    default="https://docs.projectbluefin.io/changelogs")
    ap.add_argument("--sbom-filename",    default="",
                    help="Filename of the SBOM release asset")
    ap.add_argument("--variants",         default=None,
                    help="Path to variants JSON file (optional)")
    ap.add_argument("--extra-components", default=None,
                    help="Path to extra key-component rows JSON (optional)")
    ap.add_argument("--github-notes",     default=None,
                    help="Path to GitHub generate-notes API JSON response (optional)")
    ap.add_argument("--output",           default="release-notes.md")
    ap.add_argument("--max-chars",        type=int, default=120_000,
                    help="Hard cap on release body (GitHub limit is 125 000)")
    ap.add_argument("--overflow-file",    default="release-notes-full.md",
                    help="Path to write full notes when truncation occurs")
    args = ap.parse_args()

    for path, label in [(args.versions, "--versions"), (args.sbom, "--sbom")]:
        if not os.path.isfile(path):
            print(f"ERROR: {label} file not found: {path}", file=sys.stderr)
            sys.exit(1)

    with open(args.versions, encoding="utf-8") as f:
        versions = json.load(f)

    sbom_filename = args.sbom_filename or os.path.basename(args.sbom)

    # Load optional inputs
    variants       = _load_variants(args.variants)
    extra_comps    = _load_extra_components(args.extra_components)
    github_parsed  = _parse_github_notes(
        json.load(open(args.github_notes, encoding="utf-8")).get("body", "")
        if args.github_notes and os.path.isfile(args.github_notes)
        else ""
    )

    notable_all = versions["notable"] + extra_comps
    total       = versions.get("total_packages", 0)

    sections = [
        _section_card(args.tag, args.repo),
        "",
        _section_variants(variants),
        "",
        _section_notable(notable_all),
        "",
        _section_diff_summary(versions["diff"], versions["has_prev"], total),
        "",
        _section_diff_details(versions["diff"], versions["has_prev"]),
        "",
        _section_contributors(github_parsed["contributors"]),
        "",
        _section_pr_changelog(github_parsed["prs"]),
        "",
        _section_screenshot(args.image, args.tag, args.project_name),
        "",
        _section_supply_chain(
            image=args.image,
            digest=args.digest,
            repo=args.repo,
            tag=args.tag,
            cert_regexp=args.cert_regexp,
            sbom_filename=sbom_filename,
            docs_url=args.docs_url,
        ),
        "",
        f"Full changelog \u2192 {args.docs_url}\n",
    ]

    notes = "\n".join(s for s in sections if s is not None)

    if len(notes) > args.max_chars:
        with open(args.overflow_file, "w", encoding="utf-8") as f:
            f.write(notes)
        print(
            f"::warning::Release notes are {len(notes):,} chars "
            f"(limit {args.max_chars:,}). Full notes written to "
            f"'{args.overflow_file}' — it will be attached as a release asset.",
            file=sys.stderr,
        )

        asset_ref = os.path.basename(args.overflow_file)
        overflow_note = (
            f"_The full package diff details exceed GitHub's release-body limit. "
            f"They are attached as [`{asset_ref}`]({asset_ref})._\n"
        )
        compact_sections = [
            _section_card(args.tag, args.repo),
            "",
            _section_variants(variants),
            "",
            _section_notable(notable_all),
            "",
            _section_diff_summary(versions["diff"], versions["has_prev"], total),
            "",
            overflow_note,
            "",
            _section_contributors(github_parsed["contributors"]),
            "",
            _section_pr_changelog(github_parsed["prs"]),
            "",
            _section_screenshot(args.image, args.tag, args.project_name),
            "",
            _section_supply_chain(
                image=args.image,
                digest=args.digest,
                repo=args.repo,
                tag=args.tag,
                cert_regexp=args.cert_regexp,
                sbom_filename=sbom_filename,
                docs_url=args.docs_url,
            ),
            "",
            f"Full changelog \u2192 {args.docs_url}\n",
        ]
        notes = "\n".join(s for s in compact_sections if s is not None)

        if len(notes) > args.max_chars:
            notes = notes[: args.max_chars - 12] + "\n\n\u2026*(truncated)*"
            print(
                "::warning::Compact release notes still exceeded the limit \u2014 "
                "hard-truncated.",
                file=sys.stderr,
            )

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(notes)
    print(f"Release notes written: {args.output} ({len(notes):,} chars)")
```

Also add `_load_variants()` helper near the other loaders:

```python
def _load_variants(path: str | None) -> list[dict] | None:
    """Load variants JSON from disk. Returns None when path is absent."""
    if not path or not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)
```

Update the module docstring to reflect the new section order:

```python
"""
render_notes.py — Generate release notes markdown.

Section order:
  1. Release card image
  2. Variants promoted table (optional, multi-image releases)
  3. Key components (notable packages from SBOM + extra-components)
  4. Package diff summary and details (collapsible)
  5. Contributors (human only, linked, no @ping)
  6. PR changelog (non-bot, grouped by type, collapsible)
  7. Desktop screenshot
  8. Supply chain verification (collapsible)
  9. Changelog link
"""
```

- [ ] **Step 4: Run all tests**

```bash
python3 -m pytest tests/test_render_notes.py -v
```

Expected: all tests pass. Count should be higher than original 29.

- [ ] **Step 5: Commit**

```bash
git add bootc-build/create-release/scripts/render_notes.py tests/test_render_notes.py
git commit -m "feat(create-release): new section order in main(), add --variants/--extra-components/--github-notes

- New section order: card → variants → key components → diff → contributors → PRs → screenshot → supply chain → footer
- Remove full package inventory from release body
- --variants: optional path to variants JSON
- --extra-components: optional path to extra key-component rows
- --github-notes: optional path to generate-notes API response
- Update overflow compact path (no inventory there either)
- Update docstring

Assisted-by: Claude Sonnet 4.6 via GitHub Copilot
Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 5: Update action.yml — new inputs and steps

**Files:**
- Modify: `bootc-build/create-release/action.yml`

**Context:** Add two new optional inputs (`variants-json`, `extra-components-json`). Add a step to write them to disk. Add a step to fetch GitHub generate-notes. Pass the new file paths to render_notes.py. Update cleanup step. The `generate-notes` step uses `steps.prev-sbom.outputs.tag` which is already emitted by the existing "Fetch previous SBOM" step.

**Interfaces:**
- Consumes: `--variants`, `--extra-components`, `--github-notes` args from Task 4

- [ ] **Step 1: Add new inputs after `sbom-filename`**

In `bootc-build/create-release/action.yml`, after the `sbom-filename` input block, add:

```yaml
  variants-json:
    description: >
      Optional JSON array of promoted variants for the release notes table.
      Each element: {"name":"bluefin-lts","tag":":stable","digest":"sha256:...","note":"..."}
    required: false
    default: ""
  extra-components-json:
    description: >
      Optional JSON array of extra key-component rows not derivable from the primary SBOM.
      Each element: {"label":"Kernel (Base)","version":"6.12.0-22.el10"}
      Appended to the Key Components table after SBOM-derived notable packages.
    required: false
    default: ""
```

- [ ] **Step 2: Add "Write optional inputs to disk" step**

Add this step after the "Write notable-packages spec" step (which writes `_notable_packages.json`):

```yaml
    - name: Write optional inputs to disk
      shell: bash
      env:
        VARIANTS_JSON:          ${{ inputs.variants-json }}
        EXTRA_COMPONENTS_JSON:  ${{ inputs.extra-components-json }}
      run: |
        set -euo pipefail
        [[ -n "${VARIANTS_JSON:-}" ]]         && echo "${VARIANTS_JSON}"         > _variants.json
        [[ -n "${EXTRA_COMPONENTS_JSON:-}" ]] && echo "${EXTRA_COMPONENTS_JSON}" > _extra_components.json
        true
```

- [ ] **Step 3: Add "Fetch GitHub generate-notes" step**

Add this step after "Write optional inputs to disk" and before "Install Playwright and Chromium":

```yaml
    - name: Fetch GitHub generate-notes
      shell: bash
      env:
        GH_TOKEN:  ${{ inputs.github-token }}
        REPO:      ${{ inputs.repo }}
        TAG:       ${{ inputs.tag }}
        PREV_TAG:  ${{ steps.prev-sbom.outputs.tag }}
      run: |
        set -euo pipefail
        PREV_ARGS=()
        if [[ -n "${PREV_TAG:-}" ]]; then
          PREV_ARGS=(--field "previous_tag_name=${PREV_TAG}")
        fi
        gh api "repos/${REPO}/releases/generate-notes" \
          --method POST \
          --field "tag_name=${TAG}" \
          "${PREV_ARGS[@]}" \
          > _github_notes.json 2>/dev/null \
          || echo '{"name":"","body":""}' > _github_notes.json
```

- [ ] **Step 4: Update "Render release notes" step**

Find the `python3 "${ACTION_PATH}/scripts/render_notes.py" \` invocation in the "Render release notes" step. Add the three new optional args:

```yaml
      run: |
        set -euo pipefail
        VARIANTS_ARG=()
        [[ -f "_variants.json" ]]          && VARIANTS_ARG=(--variants _variants.json)
        EXTRA_ARG=()
        [[ -f "_extra_components.json" ]]  && EXTRA_ARG=(--extra-components _extra_components.json)
        GITHUB_NOTES_ARG=()
        [[ -f "_github_notes.json" ]]      && GITHUB_NOTES_ARG=(--github-notes _github_notes.json)

        python3 "${ACTION_PATH}/scripts/render_notes.py" \
          --versions       _versions.json \
          --sbom           "${SBOM_PATH}" \
          --tag            "${TAG}" \
          --title          "${TITLE}" \
          --image          "${IMAGE}" \
          --digest         "${DIGEST}" \
          --repo           "${REPO}" \
          --project-name   "${PROJECT_NAME}" \
          --cert-regexp    "${CERT_REGEXP}" \
          --docs-url       "${DOCS_URL}" \
          --sbom-filename  "${SBOM_FILENAME}" \
          --overflow-file  release-notes-full.md \
          --output         release-notes.md \
          "${VARIANTS_ARG[@]}" \
          "${EXTRA_ARG[@]}" \
          "${GITHUB_NOTES_ARG[@]}"
```

- [ ] **Step 5: Update Cleanup step**

Find the `rm -f _versions.json _notable_packages.json release-notes-full.md` line in the Cleanup step. Add the new temp files:

```bash
rm -f _versions.json _notable_packages.json _variants.json _extra_components.json _github_notes.json release-notes-full.md
```

- [ ] **Step 6: Validate with actionlint**

```bash
cd /var/home/jorge/src/actions
pre-commit run --files bootc-build/create-release/action.yml
```

Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add bootc-build/create-release/action.yml
git commit -m "feat(create-release): add variants-json, extra-components-json inputs; fetch generate-notes

- variants-json: optional multi-variant digest table for release notes
- extra-components-json: optional extra key-component rows (e.g. LTS base kernel)
- New step fetches GitHub generate-notes API for contributors + PR changelog
- Render step passes optional files conditionally
- Cleanup step removes new temp files

Assisted-by: Claude Sonnet 4.6 via GitHub Copilot
Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 6: Update reusable-release.yml — pass-through new inputs

**Files:**
- Modify: `.github/workflows/reusable-release.yml`

**Context:** The reusable workflow wraps `bootc-build/create-release`. It needs to accept `variants_json` and `extra_components_json` as new optional workflow inputs and forward them to the `create-release` action step.

- [ ] **Step 1: Add new workflow inputs**

In `.github/workflows/reusable-release.yml`, under `workflow_call.inputs`, add after the last existing input:

```yaml
      variants_json:
        description: >
          Optional JSON array of promoted variants passed to create-release variants-json input.
          Each element: {"name":"image","tag":":stable","digest":"sha256:...","note":"..."}
        required: false
        default: ""
        type: string
      extra_components_json:
        description: >
          Optional JSON array of extra key-component rows passed to create-release
          extra-components-json input. Each element: {"label":"Kernel (Base)","version":"..."}
        required: false
        default: ""
        type: string
```

- [ ] **Step 2: Forward inputs to the create-release action step**

Find the `- name: Create release` step (around line 309). Add two lines to the `with:` block:

```yaml
          variants-json:         ${{ inputs.variants_json }}
          extra-components-json: ${{ inputs.extra_components_json }}
```

- [ ] **Step 3: Validate**

```bash
pre-commit run --files .github/workflows/reusable-release.yml
```

Expected: no errors

- [ ] **Step 4: Run full test suite to confirm nothing broken**

```bash
python3 -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/reusable-release.yml
git commit -m "feat(reusable-release): add variants_json and extra_components_json inputs

Pass-through to create-release action. Both optional; no breaking change
for existing callers (bluefin, dakota) which omit them.

Assisted-by: Claude Sonnet 4.6 via GitHub Copilot
Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 7: Consumer PR — bluefin-lts (wire variants + base kernel, delete post-release-variants)

**Files (in bluefin-lts repo):**
- Modify: `.github/workflows/execute-release.yml`
- Create: `.github/release.yml`

**Context:** `reusable-execute-release.yml` already exposes `promoted_digests` as a JSON map output: `{"bluefin-lts":"sha256:...","bluefin-lts-hwe":"sha256:...","bluefin-lts-hwe-nvidia":"sha256:..."}`. The `execute` job exposes this as `needs.execute.outputs.promoted_digests`. We parse that map to build `variants_json`. Base kernel extracted via `skopeo inspect` on `bluefin-lts:stable`. The `post-release-variants` job is deleted entirely.

- [ ] **Step 1: Open a working branch in bluefin-lts**

```bash
gh repo clone projectbluefin/bluefin-lts /tmp/bluefin-lts-relnotes 2>/dev/null \
  || (cd /tmp/bluefin-lts-relnotes && git fetch origin && git checkout main && git pull)
cd /tmp/bluefin-lts-relnotes
git checkout -b release-notes-redesign
```

- [ ] **Step 2: Create `.github/release.yml`**

Create `/tmp/bluefin-lts-relnotes/.github/release.yml`:

```yaml
# Configure GitHub's automated release notes generation.
# This file is read by the generate-notes API called in create-release action.
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

- [ ] **Step 3: Update execute-release.yml — add base-kernel-resolve job**

Add a new job `resolve-base-kernel` that runs after `execute` and before `release-notes`:

```yaml
  resolve-base-kernel:
    needs: [execute]
    if: always() && needs.execute.result == 'success'
    runs-on: ubuntu-latest
    outputs:
      extra_components_json: ${{ steps.kernel.outputs.extra_components_json }}
    steps:
      - name: Resolve base kernel version
        id: kernel
        env:
          REGISTRY: ghcr.io/projectbluefin
        run: |
          set -euo pipefail
          BASE_KERNEL=$(skopeo inspect --no-tags \
            "docker://${REGISTRY}/bluefin-lts:stable" \
            | jq -r '.Labels["ostree.linux"] // empty' \
            | grep -oP '[\d\.\-]+el\d+' | head -1 || true)
          if [[ -n "${BASE_KERNEL:-}" ]]; then
            echo "extra_components_json=[{\"label\":\"Kernel (Base)\",\"version\":\"${BASE_KERNEL}\"}]" \
              >> "$GITHUB_OUTPUT"
          else
            echo "extra_components_json=[]" >> "$GITHUB_OUTPUT"
          fi
```

- [ ] **Step 4: Update release-notes job — add variants_json and extra_components_json**

The `release-notes` job currently `needs: [execute]`. Change to `needs: [execute, resolve-base-kernel]`. Add new `with:` inputs:

```yaml
  release-notes:
    needs: [execute, resolve-base-kernel]
    if: always() && needs.execute.result == 'success'
    ...
    uses: projectbluefin/actions/.github/workflows/reusable-release.yml@v1
    with:
      ...existing inputs...
      notable_packages: >-
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
      variants_json: >-
        ${{ format('[
          {{"name":"bluefin-lts","tag":":stable","digest":"{0}"}},
          {{"name":"bluefin-lts-hwe","tag":":stable","digest":"{1}","note":"Uses Fedora CoreOS stable kernel"}},
          {{"name":"bluefin-lts-hwe-nvidia","tag":":stable","digest":"{2}","note":"Uses Fedora CoreOS stable kernel"}}
        ]',
          fromJson(needs.execute.outputs.promoted_digests)['bluefin-lts'],
          fromJson(needs.execute.outputs.promoted_digests)['bluefin-lts-hwe'],
          fromJson(needs.execute.outputs.promoted_digests)['bluefin-lts-hwe-nvidia']
        ) }}
      extra_components_json: ${{ needs.resolve-base-kernel.outputs.extra_components_json }}
    secrets: inherit
```

**Note on `format()`:** GitHub Actions `format()` does not support `fromJson()` as arguments. Use an intermediate step instead. Add this job step to `resolve-base-kernel` to build the `variants_json`:

```yaml
      - name: Build variants JSON
        id: variants
        env:
          DIGESTS: ${{ needs.execute.outputs.promoted_digests }}
        run: |
          set -euo pipefail
          LTS=$(echo "$DIGESTS" | jq -r '.["bluefin-lts"]')
          HWE=$(echo "$DIGESTS" | jq -r '.["bluefin-lts-hwe"]')
          NVIDIA=$(echo "$DIGESTS" | jq -r '.["bluefin-lts-hwe-nvidia"]')
          VARIANTS=$(jq -cn \
            --arg lts "$LTS" --arg hwe "$HWE" --arg nv "$NVIDIA" \
            '[
              {"name":"bluefin-lts","tag":":stable","digest":$lts},
              {"name":"bluefin-lts-hwe","tag":":stable","digest":$hwe,"note":"Uses Fedora CoreOS stable kernel"},
              {"name":"bluefin-lts-hwe-nvidia","tag":":stable","digest":$nv,"note":"Uses Fedora CoreOS stable kernel"}
            ]')
          echo "variants_json=${VARIANTS}" >> "$GITHUB_OUTPUT"
```

Then in `release-notes` job use: `variants_json: ${{ needs.resolve-base-kernel.outputs.variants_json }}`

Also expose `variants_json` as an output of `resolve-base-kernel`:
```yaml
    outputs:
      extra_components_json: ${{ steps.kernel.outputs.extra_components_json }}
      variants_json: ${{ steps.variants.outputs.variants_json }}
```

- [ ] **Step 5: Delete post-release-variants job**

Remove the entire `post-release-variants` job from `execute-release.yml` (approximately 45 lines including the job definition, `needs`, `permissions`, `env`, and both steps).

- [ ] **Step 6: Commit and push**

```bash
cd /tmp/bluefin-lts-relnotes
git add .github/workflows/execute-release.yml .github/release.yml
git commit -m "feat: wire release notes redesign — variants table, dual kernel, delete post-release-variants

- Delete post-release-variants job (triple-table bug eliminated)
- Add resolve-base-kernel job: extract CentOS base kernel via skopeo inspect
- Build variants_json from promoted_digests output (all 3 images with digests)
- Pass variants_json + extra_components_json to release-notes job
- Expand notable_packages: add podman, distrobox, systemd, mesa, pipewire
- Add .github/release.yml for bot exclusion and PR label categorization

Assisted-by: Claude Sonnet 4.6 via GitHub Copilot
Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
git push origin release-notes-redesign
```

- [ ] **Step 7: Open draft PR targeting main**

```bash
gh pr create \
  --repo projectbluefin/bluefin-lts \
  --base main \
  --head release-notes-redesign \
  --title "feat: release notes redesign — variants table, dual kernel, richer components" \
  --body "Consumer validation PR for projectbluefin/actions release-notes redesign.

Changes:
- Triple-variant-table bug fixed: delete post-release-variants job
- Both kernel versions shown (HWE + base CentOS via skopeo inspect)
- Expanded notable_packages (podman, distrobox, systemd, mesa, pipewire)
- Variants with digests rendered inline in release notes
- .github/release.yml: exclude bots, group PRs by label

Depends on: projectbluefin/actions#{ACTIONS_PR_NUMBER}

Consumer CI run: (link after CI starts)" \
  --draft
```

---

## Task 8: Consumer PRs — bluefin and dakota .github/release.yml

**Context:** These are simpler consumer PRs that only add `.github/release.yml` and update `notable_packages`. Open a draft PR in each repo after actions PR is merged.

- [ ] **Step 1: bluefin — add .github/release.yml and update notable_packages**

```bash
gh repo clone projectbluefin/bluefin /tmp/bluefin-relnotes 2>/dev/null \
  || (cd /tmp/bluefin-relnotes && git fetch && git checkout testing && git pull)
cd /tmp/bluefin-relnotes
git checkout -b release-notes-redesign
```

Create `/tmp/bluefin-relnotes/.github/release.yml` with the same content as in Task 7 Step 2.

Find the `notable_packages` input in the bluefin caller workflow (likely `.github/workflows/build.yml` or similar — check with `grep -r notable_packages .github/`). Update it to:

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

Commit and open draft PR targeting `testing` (not `main`):

```bash
git add .github/release.yml
git commit -m "feat: add .github/release.yml and expand notable_packages

Assisted-by: Claude Sonnet 4.6 via GitHub Copilot
Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
git push origin release-notes-redesign
gh pr create \
  --repo projectbluefin/bluefin \
  --base testing \
  --head release-notes-redesign \
  --title "feat: release notes redesign — richer key components" \
  --body "Consumer validation PR. Adds .github/release.yml for PR categorization. Expands notable_packages." \
  --draft
```

- [ ] **Step 2: dakota — add .github/release.yml**

```bash
gh repo clone projectbluefin/dakota /tmp/dakota-relnotes 2>/dev/null \
  || (cd /tmp/dakota-relnotes && git fetch && git checkout main && git pull)
cd /tmp/dakota-relnotes
git checkout -b release-notes-redesign
```

Create `/tmp/dakota-relnotes/.github/release.yml` (same content). Commit and open draft PR targeting `main`.

```bash
git add .github/release.yml
git commit -m "feat: add .github/release.yml for PR categorization in release notes

Assisted-by: Claude Sonnet 4.6 via GitHub Copilot
Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
git push origin release-notes-redesign
gh pr create \
  --repo projectbluefin/dakota \
  --base main \
  --head release-notes-redesign \
  --title "feat: add .github/release.yml for release notes categorization" \
  --body "Consumer validation PR. Adds .github/release.yml to categorize PRs in release notes (GitHub generate-notes API)." \
  --draft
```

---

## Final: merge and advance @v1

After CI passes on the actions PR and both consumer PRs show green:

```bash
# Merge actions PR (in projectbluefin/actions repo)
gh pr merge --squash --repo projectbluefin/actions

# Advance @v1 tag
cd /var/home/jorge/src/actions
git fetch origin
git tag -f v1 origin/main
git push --force origin v1

# Verify
git ls-remote origin v1
# Should match: git rev-parse origin/main
```

Consumer repos pick up new behavior on their next workflow run (they reference `@v1`).
