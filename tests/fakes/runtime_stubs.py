"""Shared import-time stubs and path setup for tests."""

from __future__ import annotations

import os
import sys
from types import ModuleType
from unittest.mock import MagicMock

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
AIRFLOW_DAGS = os.path.join(PROJECT_ROOT, "airflow", "dags")
STREAMING_DIR = os.path.join(PROJECT_ROOT, "streaming")

_STUB_MODULES = [
    "airflow",
    "airflow.models",
    "airflow.datasets",
    "airflow.operators",
    "airflow.operators.python",
    "airflow.operators.dummy",
    "airflow.utils",
    "airflow.utils.task_group",
    "psycopg2",
    "psycopg2.extras",
    "confluent_kafka",
    "confluent_kafka.schema_registry",
    "confluent_kafka.schema_registry.avro",
    "confluent_kafka.serialization",
    "websocket",
]


def ensure_project_paths() -> None:
    for path in (PROJECT_ROOT, AIRFLOW_DAGS, STREAMING_DIR):
        if path not in sys.path:
            sys.path.insert(0, path)


def _install_requests_stub() -> None:
    try:
        import requests as _requests  # noqa: F401
    except Exception:
        requests_stub = ModuleType("requests")
        requests_stub.adapters = MagicMock()
        requests_stub.get = MagicMock()
        requests_stub.post = MagicMock()
        requests_stub.put = MagicMock()
        requests_stub.delete = MagicMock()
        sys.modules.setdefault("requests", requests_stub)
        sys.modules.setdefault("requests.adapters", requests_stub.adapters)


def install_runtime_stubs() -> None:
    for module_name in _STUB_MODULES:
        sys.modules.setdefault(module_name, MagicMock())
    _install_requests_stub()
