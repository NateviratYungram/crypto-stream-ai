"""
Pytest configuration for unit tests.

Keeps the import environment lightweight by stubbing heavy runtime
dependencies before application modules are imported.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fakes.runtime_stubs import ensure_project_paths, install_runtime_stubs

ensure_project_paths()
install_runtime_stubs()
