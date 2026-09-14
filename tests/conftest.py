"""Configure sys.path so test modules can import the scripts under test."""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

# Create-release scripts
sys.path.insert(0, str(REPO_ROOT / "bootc-build" / "create-release" / "scripts"))

# chunka scripts
sys.path.insert(0, str(REPO_ROOT / "bootc-build" / "chunka"))

# Composite action scripts (accessed via $GITHUB_ACTION_PATH at runtime)
sys.path.insert(0, str(REPO_ROOT / ".github" / "actions" / "render-pr-body"))
sys.path.insert(0, str(REPO_ROOT / ".github" / "actions" / "render-gate-section"))

# Top-level scripts — inserted last so they take precedence. scripts/render_pr_body.py
# and scripts/render_gate_section.py are thin re-export wrappers around the
# .github/actions copies, so coverage lands on the implementation that CI runs.
sys.path.insert(0, str(REPO_ROOT / "scripts"))
