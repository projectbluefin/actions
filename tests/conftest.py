"""Configure sys.path so test modules can import the scripts under test."""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

# Create-release scripts
sys.path.insert(0, str(REPO_ROOT / "bootc-build" / "create-release" / "scripts"))

# Top-level scripts (check-consumer-contract, etc.)
sys.path.insert(0, str(REPO_ROOT / "scripts"))
