#!/usr/bin/env python3
"""
render_pr_body.py — repository-root entry point for promotion PR body rendering.

The implementation is a single source of truth that lives in
`.github/actions/render-pr-body/render_pr_body.py`, because that is the copy the
`render-pr-body` composite action executes via `$GITHUB_ACTION_PATH` at runtime.
This module re-exports that implementation so the root entry point and the
shipped action cannot drift, and so the tests exercise the code that actually
runs in CI.
"""
import importlib.util
import sys
from pathlib import Path

_IMPL_PATH = (
    Path(__file__).resolve().parent.parent
    / ".github"
    / "actions"
    / "render-pr-body"
    / "render_pr_body.py"
)
_IMPL_NAME = "_render_pr_body_impl"

_spec = importlib.util.spec_from_file_location(_IMPL_NAME, _IMPL_PATH)
if _spec is None or _spec.loader is None:  # pragma: no cover - defensive
    raise ImportError(f"cannot load implementation from {_IMPL_PATH}")
_impl = importlib.util.module_from_spec(_spec)
sys.modules[_IMPL_NAME] = _impl
_spec.loader.exec_module(_impl)

globals().update({k: v for k, v in vars(_impl).items() if not k.startswith("__")})

if __name__ == "__main__":
    main()  # noqa: F821 - re-exported from the implementation module
