"""
Pytest configuration for unit tests.

Keeps the import environment lightweight by stubbing heavy runtime
dependencies before application modules are imported.
"""

from tests.fakes.runtime_stubs import ensure_project_paths, install_runtime_stubs

ensure_project_paths()
install_runtime_stubs()
