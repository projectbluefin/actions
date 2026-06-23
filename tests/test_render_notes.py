"""
Unit tests for render_notes.py — Markdown release notes generation.
"""
import pytest
import render_notes


# Shared fixture data
NOTABLE_NO_PREV = [
    {"name": "Kernel",     "version": "6.10.0", "prev": None,    "changed": False},
    {"name": "GNOME Shell","version": "47.1",   "prev": None,    "changed": False},
]

NOTABLE_WITH_PREV = [
    {"name": "Kernel",     "version": "6.10.0", "prev": "6.9.14","changed": True},
    {"name": "GNOME Shell","version": "47.1",   "prev": "47.0",  "changed": True},
    {"name": "Firefox",    "version": "131.0",  "prev": "131.0", "changed": False},
]

DIFF_EMPTY = {
    "changed_count": 0, "added_count": 0, "removed_count": 0,
    "changed": [], "added": [], "removed": [],
}

DIFF_FULL = {
    "changed_count": 2,
    "added_count":   1,
    "removed_count": 1,
    "changed": [
        {"name": "linux",      "prev": "6.9.14", "curr": "6.10.0"},
        {"name": "gnome-shell","prev": "47.0",   "curr": "47.1"},
    ],
    "added":   [{"name": "podman",      "version": "5.2.0"}],
    "removed": [{"name": "old-package", "version": "9.9.9"}],
}


# ── _section_notable ──────────────────────────────────────────────────────────

class TestSectionNotable:
    def test_contains_package_names(self):
        md = render_notes._section_notable(NOTABLE_NO_PREV)
        assert "Kernel" in md
        assert "GNOME Shell" in md

    def test_contains_versions(self):
        md = render_notes._section_notable(NOTABLE_NO_PREV)
        assert "6.10.0" in md
        assert "47.1" in md

    def test_changed_package_shows_prev(self):
        md = render_notes._section_notable(NOTABLE_WITH_PREV)
        assert "6.9.14" in md  # previous version for Kernel

    def test_empty_notable_produces_empty(self):
        md = render_notes._section_notable([])
        assert md == ""


# ── _section_diff_summary ─────────────────────────────────────────────────────

class TestSectionDiffSummary:
    def test_no_prev_shows_baseline_message(self):
        md = render_notes._section_diff_summary(DIFF_EMPTY, has_prev=False, total=100)
        assert "100" in md
        assert "No previous release baseline" in md

    def test_with_prev_shows_total(self):
        md = render_notes._section_diff_summary(DIFF_FULL, has_prev=True, total=423)
        assert "423" in md

    def test_with_prev_shows_changed_count(self):
        md = render_notes._section_diff_summary(DIFF_FULL, has_prev=True, total=423)
        assert "2" in md  # 2 changed

    def test_no_changes_still_generates_section(self):
        md = render_notes._section_diff_summary(DIFF_EMPTY, has_prev=True, total=100)
        assert md != ""
        assert "100" in md


# ── _section_diff_details ─────────────────────────────────────────────────────

class TestSectionDiffDetails:
    def test_no_prev_returns_empty(self):
        md = render_notes._section_diff_details(DIFF_FULL, has_prev=False)
        assert md == ""

    def test_changed_packages_appear(self):
        md = render_notes._section_diff_details(DIFF_FULL, has_prev=True)
        assert "linux" in md
        assert "gnome-shell" in md
        assert "6.9.14" in md
        assert "6.10.0" in md

    def test_added_packages_appear(self):
        md = render_notes._section_diff_details(DIFF_FULL, has_prev=True)
        assert "podman" in md
        assert "5.2.0" in md

    def test_removed_packages_appear(self):
        md = render_notes._section_diff_details(DIFF_FULL, has_prev=True)
        assert "old-package" in md

    def test_empty_diff_returns_empty(self):
        md = render_notes._section_diff_details(DIFF_EMPTY, has_prev=True)
        assert md == ""


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


# ── _section_supply_chain ─────────────────────────────────────────────────────

# ── overflow / body-size guard ────────────────────────────────────────────────

class TestOverflowGuard:
    """Tests for the 125k-char GitHub limit guard."""

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


class TestSectionSupplyChain:
    def _call(self, **kwargs):
        defaults = dict(
            image="ghcr.io/projectbluefin/bluefin",
            digest="sha256:abc123def456",
            repo="projectbluefin/bluefin",
            tag="2026-05-14-abc1234",
            cert_regexp="^https://github\\.com/projectbluefin/",
            sbom_filename="bluefin.spdx.json",
            docs_url="https://docs.projectbluefin.io/changelogs",
        )
        defaults.update(kwargs)
        return render_notes._section_supply_chain(**defaults)

    def test_contains_image_reference(self):
        md = self._call()
        assert "ghcr.io/projectbluefin/bluefin" in md

    def test_contains_digest(self):
        md = self._call()
        assert "sha256:abc123def456" in md

    def test_contains_cosign_command(self):
        md = self._call()
        assert "cosign verify" in md

    def test_contains_oras_command(self):
        md = self._call()
        assert "oras discover" in md

    def test_contains_slsa_verifier(self):
        md = self._call()
        assert "slsa-verifier" in md

    def test_cert_regexp_injected(self):
        md = self._call(cert_regexp="^https://github.com/myorg/")
        assert "myorg" in md

    def test_sbom_filename_injected(self):
        md = self._call(sbom_filename="custom.spdx.json")
        assert "custom.spdx.json" in md


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
        # Full inventory would produce hundreds of table rows; supply chain has ~3
        # This catches regression if the full SPDX package inventory is reintroduced
        assert md.count("\n|") < 7, "Too many table rows; full inventory may have been introduced"
        # Also verify specific inventory section headers are absent
        assert "## SPDX Packages" not in md
        assert "## Full package inventory" not in md

    def test_supply_chain_is_collapsed(self, tmp_path):
        md = self._run_main(tmp_path)
        assert "<details>" in md
        assert "Supply chain verification" in md
        # cosign commands should be inside a details block
        details_start = md.find("<details>")
        cosign_pos = md.find("cosign verify")
        assert cosign_pos > details_start
