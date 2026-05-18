"""Pytest configuration for tests.

Ensure the repository root is on sys.path so the local `specforge` package
is importable when running `pytest` directly.
"""

from pathlib import Path
import sys

# Insert project root (parent of this tests/ directory) at front of sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if PROJECT_ROOT.name == "tests":
	PROJECT_ROOT = PROJECT_ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Tests configuration
