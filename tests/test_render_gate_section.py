"""Unit tests for render_gate_section.py — gate checklist section updater."""
import sys
import pytest
import render_gate_section

GATE_START = "<!-- gate-section-start -->"
GATE_END   = "<!-- gate-section-end -->"

FULL_BODY = """\
## 🦕 Bluefin testing → stable · 2026-06-11

> **12 days since the last stable release**

<!-- gate-section-start -->
### Release checklist

| Check | Status | Details |
|---|---|---|
| Digest resolution | ⏳ checking… | — |
| Cosign signatures | ⏳ checking… | — |
| E2E | ⏳ checking… | — |
<!-- gate-section-end -->

### Variants being promoted

| Variant | Tag |
|---|---|
| `bluefin` | `:testing` |
"""

ARGS_PASSED = dict(
    resolve_ok="true",   resolve_summary="2 variants resolved.",
    verify_ok="true",    verify_summary="All signatures verified.",
    e2e_state="passed",  e2e_summary="Smoke suite passed.",
    e2e_details="https://github.com/example/runs/99",
    ready="true",
)

ARGS_BLOCKED = dict(
    resolve_ok="true",   resolve_summary="2 variants resolved.",
    verify_ok="false",   verify_summary="Signature verification failed for bluefin-nvidia.",
    e2e_state="skipped", e2e_summary="E2E disabled by caller.",
    e2e_details="",
    ready="false",
)

ARGS_E2E_SKIPPED = dict(
    resolve_ok="true",   resolve_summary="2 variants resolved.",
    verify_ok="true",    verify_summary="All signatures verified.",
    e2e_state="skipped", e2e_summary="E2E disabled by caller.",
    e2e_details="",
    ready="true",
)


class TestBuildGateSection:
    def test_contains_start_marker(self):
        assert GATE_START in render_gate_section.build_gate_section(**ARGS_PASSED)

    def test_contains_end_marker(self):
        assert GATE_END in render_gate_section.build_gate_section(**ARGS_PASSED)

    def test_passed_shows_green_checkmarks(self):
        section = render_gate_section.build_gate_section(**ARGS_PASSED)
        assert "✅" in section

    def test_failed_shows_red_cross(self):
        section = render_gate_section.build_gate_section(**ARGS_BLOCKED)
        assert "❌" in section

    def test_skipped_shows_skip_icon(self):
        section = render_gate_section.build_gate_section(**ARGS_E2E_SKIPPED)
        assert "⏭️" in section

    def test_resolve_summary_present(self):
        assert "2 variants resolved" in render_gate_section.build_gate_section(**ARGS_PASSED)

    def test_verify_summary_present(self):
        assert "All signatures verified" in render_gate_section.build_gate_section(**ARGS_PASSED)

    def test_e2e_summary_present(self):
        assert "Smoke suite passed" in render_gate_section.build_gate_section(**ARGS_PASSED)

    def test_e2e_details_url_linked(self):
        section = render_gate_section.build_gate_section(**ARGS_PASSED)
        assert "https://github.com/example/runs/99" in section

    def test_overall_passed_label(self):
        section = render_gate_section.build_gate_section(**ARGS_PASSED)
        assert "All checks passed" in section

    def test_overall_blocked_label(self):
        section = render_gate_section.build_gate_section(**ARGS_BLOCKED)
        assert "Gate blocked" in section

    def test_e2e_no_details_no_crash(self):
        render_gate_section.build_gate_section(**ARGS_E2E_SKIPPED)  # must not raise


class TestReplaceGateSection:
    def test_replaces_placeholders_with_results(self):
        new_section = render_gate_section.build_gate_section(**ARGS_PASSED)
        result = render_gate_section.replace_gate_section(FULL_BODY, new_section)
        assert "✅" in result
        assert "⏳" not in result

    def test_preserves_content_before_markers(self):
        new_section = render_gate_section.build_gate_section(**ARGS_PASSED)
        result = render_gate_section.replace_gate_section(FULL_BODY, new_section)
        assert "🦕 Bluefin testing → stable" in result

    def test_preserves_content_after_markers(self):
        new_section = render_gate_section.build_gate_section(**ARGS_PASSED)
        result = render_gate_section.replace_gate_section(FULL_BODY, new_section)
        assert "Variants being promoted" in result

    def test_markers_still_present_after_replace(self):
        new_section = render_gate_section.build_gate_section(**ARGS_PASSED)
        result = render_gate_section.replace_gate_section(FULL_BODY, new_section)
        assert GATE_START in result
        assert GATE_END in result

    def test_idempotent_double_replace(self):
        """Replacing the gate section twice should produce the same result."""
        new_section = render_gate_section.build_gate_section(**ARGS_PASSED)
        once  = render_gate_section.replace_gate_section(FULL_BODY, new_section)
        twice = render_gate_section.replace_gate_section(once, new_section)
        assert once == twice

    def test_raises_when_markers_missing(self):
        with pytest.raises(ValueError, match="gate-section"):
            render_gate_section.replace_gate_section("no markers here", "anything")


class TestMain:
    def test_main_writes_updated_body(self, tmp_path):
        body_in  = tmp_path / "body.md"
        body_out = tmp_path / "body-out.md"
        body_in.write_text(FULL_BODY)
        old = sys.argv
        sys.argv = [
            "render_gate_section.py",
            "--body-file",       str(body_in),
            "--output",          str(body_out),
            "--resolve-ok",      "true",
            "--resolve-summary", "2 variants resolved.",
            "--verify-ok",       "true",
            "--verify-summary",  "All signatures verified.",
            "--e2e-state",       "passed",
            "--e2e-summary",     "Smoke suite passed.",
            "--e2e-details",     "https://github.com/example/runs/99",
            "--ready",           "true",
        ]
        try:
            render_gate_section.main()
        finally:
            sys.argv = old
        result = body_out.read_text()
        assert "✅" in result
        assert "⏳" not in result
        assert "🦕 Bluefin" in result  # preserved from original body

    def test_main_missing_markers_exits_nonzero(self, tmp_path):
        body_in  = tmp_path / "body.md"
        body_out = tmp_path / "body-out.md"
        body_in.write_text("no markers here")
        old = sys.argv
        sys.argv = [
            "render_gate_section.py",
            "--body-file",       str(body_in),
            "--output",          str(body_out),
            "--resolve-ok",      "true",
            "--resolve-summary", "ok",
            "--verify-ok",       "true",
            "--verify-summary",  "ok",
            "--e2e-state",       "skipped",
            "--e2e-summary",     "skipped",
            "--ready",           "true",
        ]
        try:
            with pytest.raises(SystemExit) as exc:
                render_gate_section.main()
            assert exc.value.code != 0
        finally:
            sys.argv = old
