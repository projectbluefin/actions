"""
Unit tests for inject-xattrs.py — xattr injection from a fakecap TSV manifest.

Tests cover:
- Happy path: TSV parsed and xattrs set on all present files
- Missing file handling: OSError on missing path increments skip counter
- Malformed lines: empty lines and comment lines are skipped
- Insufficient columns (<2 fields): line skipped silently
- Default interval: 'weekly' used when third column omitted
- Usage error: non-zero exit when argument count is wrong
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch
import pytest

import importlib
inject_xattrs = importlib.import_module("inject-xattrs")


# ── helpers ───────────────────────────────────────────────────────────────────

def write_manifest(tmp_path: Path, lines: list[str]) -> Path:
    manifest = tmp_path / "manifest.tsv"
    manifest.write_text("\n".join(lines) + "\n")
    return manifest


# ── happy path ────────────────────────────────────────────────────────────────

class TestHappyPath:
    def test_sets_component_and_interval_xattrs(self, tmp_path):
        manifest = write_manifest(tmp_path, [
            "/usr/bin/foo\telement/foo.bst\tweekly",
            "/usr/lib/bar.so\telement/bar.bst\tmonthly",
        ])
        rootfs = str(tmp_path)

        with patch("os.setxattr") as mock_setxattr:
            rc = _call_main(inject_xattrs, str(manifest), rootfs)

        assert rc == 0
        assert mock_setxattr.call_count == 4  # 2 files × 2 xattrs each

    def test_xattr_values_correct(self, tmp_path):
        manifest = write_manifest(tmp_path, [
            "/usr/bin/foo\telement/foo.bst\tweekly",
        ])
        rootfs = str(tmp_path)
        expected_target = rootfs + "/usr/bin/foo"

        with patch("os.setxattr") as mock_setxattr:
            rc = _call_main(inject_xattrs, str(manifest), rootfs)

        assert rc == 0
        mock_setxattr.assert_any_call(
            expected_target,
            b"user.component",
            b"element/foo.bst",
            follow_symlinks=False,
        )
        mock_setxattr.assert_any_call(
            expected_target,
            b"user.update-interval",
            b"weekly",
            follow_symlinks=False,
        )

    def test_returns_zero_on_success(self, tmp_path):
        manifest = write_manifest(tmp_path, ["/usr/bin/foo\telement/foo.bst\tweekly"])
        with patch("os.setxattr"):
            rc = _call_main(inject_xattrs, str(manifest), str(tmp_path))
        assert rc == 0


# ── missing file handling ─────────────────────────────────────────────────────

class TestMissingFile:
    def test_oserror_increments_skip_not_ok(self, tmp_path, capsys):
        manifest = write_manifest(tmp_path, [
            "/usr/bin/present\telement/present.bst\tweekly",
            "/usr/bin/missing\telement/missing.bst\tweekly",
        ])
        rootfs = str(tmp_path)

        def fake_setxattr(path, name, value, follow_symlinks=True):
            if "missing" in path:
                raise OSError(2, "No such file or directory", path)

        with patch("os.setxattr", side_effect=fake_setxattr):
            rc = _call_main(inject_xattrs, str(manifest), rootfs)

        assert rc == 0
        captured = capsys.readouterr()
        assert "1 set" in captured.err
        assert "1 skipped" in captured.err

    def test_all_missing_still_returns_zero(self, tmp_path, capsys):
        manifest = write_manifest(tmp_path, [
            "/usr/bin/gone\telement/gone.bst\tweekly",
        ])
        with patch("os.setxattr", side_effect=OSError("no such file")):
            rc = _call_main(inject_xattrs, str(manifest), str(tmp_path))
        assert rc == 0
        captured = capsys.readouterr()
        assert "0 set" in captured.err
        assert "1 skipped" in captured.err


# ── malformed manifest lines ──────────────────────────────────────────────────

class TestMalformedLines:
    def test_empty_lines_skipped(self, tmp_path):
        manifest = write_manifest(tmp_path, [
            "",
            "/usr/bin/foo\telement/foo.bst\tweekly",
            "",
        ])
        with patch("os.setxattr") as mock_setxattr:
            rc = _call_main(inject_xattrs, str(manifest), str(tmp_path))
        assert rc == 0
        assert mock_setxattr.call_count == 2  # only the valid line → 2 xattrs

    def test_comment_lines_skipped(self, tmp_path):
        manifest = write_manifest(tmp_path, [
            "# this is a comment",
            "/usr/bin/foo\telement/foo.bst\tweekly",
        ])
        with patch("os.setxattr") as mock_setxattr:
            rc = _call_main(inject_xattrs, str(manifest), str(tmp_path))
        assert rc == 0
        assert mock_setxattr.call_count == 2

    def test_insufficient_columns_skipped(self, tmp_path):
        """Lines with fewer than 2 tab-separated fields are silently ignored."""
        manifest = write_manifest(tmp_path, [
            "/usr/bin/only-path",
            "/usr/bin/foo\telement/foo.bst\tweekly",
        ])
        with patch("os.setxattr") as mock_setxattr:
            rc = _call_main(inject_xattrs, str(manifest), str(tmp_path))
        assert rc == 0
        assert mock_setxattr.call_count == 2


# ── default interval ──────────────────────────────────────────────────────────

class TestDefaultInterval:
    def test_two_column_line_uses_weekly_interval(self, tmp_path):
        """When the third column is absent, interval defaults to 'weekly'."""
        manifest = write_manifest(tmp_path, [
            "/usr/bin/foo\telement/foo.bst",
        ])
        rootfs = str(tmp_path)

        with patch("os.setxattr") as mock_setxattr:
            rc = _call_main(inject_xattrs, str(manifest), rootfs)

        assert rc == 0
        mock_setxattr.assert_any_call(
            rootfs + "/usr/bin/foo",
            b"user.update-interval",
            b"weekly",
            follow_symlinks=False,
        )


# ── usage error ───────────────────────────────────────────────────────────────

class TestUsageError:
    def test_no_args_returns_nonzero(self):
        orig_argv = sys.argv
        try:
            sys.argv = ["inject-xattrs.py"]
            rc = inject_xattrs.main()
        finally:
            sys.argv = orig_argv
        assert rc != 0

    def test_one_arg_returns_nonzero(self):
        orig_argv = sys.argv
        try:
            sys.argv = ["inject-xattrs.py", "manifest.tsv"]
            rc = inject_xattrs.main()
        finally:
            sys.argv = orig_argv
        assert rc != 0

    def test_extra_args_returns_nonzero(self):
        orig_argv = sys.argv
        try:
            sys.argv = ["inject-xattrs.py", "a", "b", "c"]
            rc = inject_xattrs.main()
        finally:
            sys.argv = orig_argv
        assert rc != 0


# ── internal helper ───────────────────────────────────────────────────────────

def _call_main(module, manifest_path: str, rootfs: str) -> int:
    """Call module.main() with sys.argv patched to the given arguments."""
    orig_argv = sys.argv
    try:
        sys.argv = ["inject-xattrs.py", manifest_path, rootfs]
        return module.main()
    finally:
        sys.argv = orig_argv
