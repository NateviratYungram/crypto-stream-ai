"""
Pytest configuration for unit tests.

Stubs out all heavy runtime dependencies (Airflow, psycopg2, Kafka, requests,
websocket) before any test file is imported. This lets us test pure business
logic without a live Postgres, Kafka, or Airflow installation.
"""
import os
import sys
from unittest.mock import MagicMock

# ── Path setup ──────────────────────────────────────────────────────────────
_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
_DAGS = os.path.join(_ROOT, "airflow", "dags")
_STREAMING = os.path.join(_ROOT, "streaming")

for _path in (_ROOT, _DAGS, _STREAMING):
    if _path not in sys.path:
        sys.path.insert(0, _path)

# ── Module stubs ─────────────────────────────────────────────────────────────
_STUBS = [
    # Airflow
    "airflow",
    "airflow.models",
    "airflow.operators",
    "airflow.operators.python",
    "airflow.operators.dummy",
    "airflow.utils",
    "airflow.utils.task_group",
    # Database
    "psycopg2",
    "psycopg2.extras",
    # Kafka / Schema Registry
    "confluent_kafka",
    "confluent_kafka.schema_registry",
    "confluent_kafka.schema_registry.avro",
    "confluent_kafka.serialization",
    # HTTP / WebSocket
    "requests",
    "websocket",
]

for _mod in _STUBS:
    sys.modules.setdefault(_mod, MagicMock())
