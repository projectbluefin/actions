"""Configure sys.path so test modules can import the scripts under test."""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

# Create-release scripts
sys.path.insert(0, str(REPO_ROOT / "bootc-build" / "create-release" / "scripts"))

# chunka scripts
sys.path.insert(0, str(REPO_ROOT / "bootc-build" / "chunka"))

# Top-level scripts (check-consumer-contract, etc.)
sys.path.insert(0, str(REPO_ROOT / "scripts"))

# Composite action scripts (accessed via $GITHUB_ACTION_PATH at runtime)
sys.path.insert(0, str(REPO_ROOT / ".github" / "actions" / "render-pr-body"))
sys.path.insert(0, str(REPO_ROOT / ".github" / "actions" / "render-gate-section"))
