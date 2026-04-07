# 🛸 CryptoStream AI — Full Project Context (Updated: April 2026)

## 🎯 Project Vision
**CryptoStream AI** is an enterprise-grade Data Lakehouse and Real-time Analytics platform designed for the **Virtual Banking** sector. It demonstrates high-availability data engineering patterns, regulatory compliance readiness (BOT/AMLO standards), and scalable cloud-native infrastructure using a modern data stack.

---

## 🏗️ System Architecture (Cloud-Native Scale)

### Data Flow (7 Layers):
```
[Binance WebSocket]
       │
       ▼
[1] Ingestion — producer.py
       │  (Kafka topic: trade_stream, 3 partitions)
       ▼
[2] Message Broker — Apache Kafka
       │
       ├──────────────────────────────────────┐
       ▼                                      ▼
[3] Stream Processing — Apache Flink    [3B] Data Lake Writer — lake_writer.py
  ┌──── Validation Gate ────┐                 (Parquet, Hive-partitioned)
  │ VALID → enriched_trades │
  │ VALID → market_metrics  │
  │ INVALID → DLQ (Kafka)   │
  │ INVALID → dq_audit_log  │
  └─────────────────────────┘
       │
       ▼
[4] Storage — PostgreSQL (Hot) + Parquet Data Lake (Cold) + BigQuery (Archive)
       │
       ▼
[5] Orchestration — Apache Airflow (EOD Reports, DLQ Recovery)
       │
       ▼
[6] AI Agent — MCP Server (FastAPI + Model Context Protocol)
       │
       ▼
[7] Monitoring — Prometheus + Grafana + Alertmanager
```

---

## 📦 Infrastructure: Local Dev vs Production

| Component          | Local Dev (Docker Compose)           | Production (Kubernetes / Helm)              |
| :---               | :---                                  | :---                                       |
| **Kafka**          | Single-node, 3 partitions, RF=1       | Multi-node cluster (StatefulSet, RF=3)     |
| **Flink**          | JobManager + TaskManager (2 services) | Kubernetes Operator + HPA auto-scaling     |
| **PostgreSQL**     | Single instance + PVC                 | StatefulSet + PVC + Secrets (K8s)          |
| **Airflow**        | LocalExecutor                         | KubernetesExecutor + RBAC                  |
| **Networking**     | Docker bridge network                 | Zero-Trust NetworkPolicies (K8s)           |
| **Secret Mgmt**    | env vars in compose                   | Kubernetes Secrets                         |
| **Startup**        | `docker compose up -d` (one command)  | `helm install cryptostream ./k8s`          |

---

## ✅ Project Phases & Roadmap

### Phase 1: Data Ingestion ✅ (Completed, Automated)
- **Tech:** `streaming/producer.py` — Python WebSocket → Kafka
- **Service:** `ingestion-producer` Docker Compose service (starts automatically)
- **Key Feature:** High-throughput streaming with Dead Letter Queue for invalid records.
- **Kafka Topics:** `trade_stream` (3 partitions) + `trade_stream_dlq` (1 partition, 30d retention)

### Phase 2: Real-time Processing ✅ (Completed)
- **Tech:** Apache Flink (`streaming/flink_processor.py`)
- **Key Features:**
  - Whale detection (quantity > 0.5 BTC)
  - 1-minute VWAP Tumbling Windows → `market_metrics`
  - Stateful processing with Event Time + 5s Watermark

### Phase 3: Data Quality & Governance ✅ (Completed)
- **Logic:** Automated validation (Null checks, Range checks) via Flink SQL CASE WHEN
- **Valid path:** → `enriched_trades` (PostgreSQL)
- **Invalid path:** → `trade_stream_dlq` (Kafka DLQ) + `data_quality_log` (PostgreSQL audit)
- **Banking Relevance:** Audit trails for every rejected record (Regulatory requirement)

### Phase 3B: Data Lake Writer ✅ (Completed, Automated)
- **Tech:** `streaming/lake_writer.py` — Kafka consumer → Parquet (Hive-partitioned)
- **Service:** `lake-writer` Docker Compose service (starts automatically)
- **Structure:** `datalake/raw/year=YYYY/month=MM/day=DD/trades_*.parquet`
- **Policy:** Micro-batch flush every 1,000 records OR 5 minutes
- **Banking Relevance:** Immutable archive for 5–10 year BOT/AMLO regulatory retention

### Phase 4: Batch Orchestration ✅ (Completed)
- **Tech:** Apache Airflow
- **Key Feature:** Idempotent Daily OHLCV & Whale Summary reports with ShortCircuit logic
- **Banking Relevance:** Mirrors EOD Reconciliation reports submitted to ธปท.

### Phase 5: Data Observability ✅ (Completed, Integrated)
- **Tech:** Prometheus + Grafana + Alertmanager (now integrated into main `docker-compose.yml`)
- **Exporters:** `kafka-exporter` (consumer lag) + `postgres-exporter` (DB health)
- **Alerts:** Critical threshold breaches route to Alertmanager → Webhook/Slack/PagerDuty
- **Banking Relevance:** SLA tracking for data freshness (< 5 min target)

### Phase 6: GenAI Agent Integration ✅ (Completed)
- **Tech:** MCP Server (Model Context Protocol), FastAPI, Python
- **Goal:** "Chat with Data" — LLMs query the Lakehouse via read-only REST API
- **Security:** API Key authentication + Rate limiting (SlowAPI) + SQL injection prevention
- **Audit:** Every query logged to `mcp_audit_log` table (AI Governance requirement)

### Phase 7: Cloud-Native Scaling & Production Hardening ✅ (Completed)
- **Tech:** Kubernetes (K8s), Helm, HPA, NetworkPolicies
- **Location:** `k8s/` directory contains all manifests
- **Features:** StatefulSets (HA), Zero-Trust Network Segmentation, K8s Secrets
- **Banking Relevance:** Meets Virtual Bank RTO/RPO and Penetration Testing requirements

---

## 🏦 Banking/Regulatory Relevance Summary

| Feature | Banking Equivalent |
| :--- | :--- |
| **Kafka DLQ** | Rejection Reports for BOT/AMLO Audits |
| **Kafka 3-Partition Topic** | Load-balanced message routing across broker nodes |
| **Flink Validation Gate** | Pre-settlement validation in Payment Clearing systems |
| **Whale Detection (>0.5 BTC)** | AML Transaction Monitoring thresholds |
| **Flink VWAP Real-time** | Execution Quality Reporting (TWAP/VWAP benchmarks) |
| **Parquet Data Lake (Hive)** | Immutable Transaction Archive (5–10 yr BOT retention) |
| **Airflow Idempotency** | Reliable EOD (End-of-Day) Reconciliation Reports |
| **K8s StatefulSets (HA)** | High Availability (RTO < 15min / RPO < 1min) |
| **Zero-Trust K8s Network** | Network Segmentation (Preventing Lateral Movement) |
| **MCP AI Audit Log** | AI Governance, Access Auditing & LLM query traceability |
| **Prometheus Alertmanager** | Automated SLA breach escalation to on-call team |

---

## 🚀 Quick Start (One Command)

```bash
# Start the entire stack
docker compose up -d

# Submit the Flink streaming job
docker exec -d jobmanager flink run -py /opt/streaming/flink_processor.py

# Run the full E2E test
python test_e2e.py
```

### UI Access:
| Service     | URL                      | Credentials |
| :---        | :---                     | :--- |
| Kafka UI    | http://localhost:8080    | (none) |
| Flink UI    | http://localhost:8081    | (none) |
| Airflow     | http://localhost:8082    | admin / admin |
| Grafana     | http://localhost:3000    | admin / cryptostream_admin |
| Prometheus  | http://localhost:9090    | (none) |
| Alertmgr    | http://localhost:9093    | (none) |

---

## 📁 Directory Structure
```text
crypto-stream-ai/
├── docker-compose.yml      # ✅ Unified: ALL services in one file
├── k8s/                    # Kubernetes Manifests & Helm Charts (Phase 7)
│   ├── kafka/              # Kafka StatefulSet + Service
│   ├── flink/              # Flink JobManager + TaskManager
│   ├── postgres/           # PostgreSQL + PVC + Secrets
│   ├── airflow/            # Airflow KubernetesExecutor + RBAC
│   └── network-policies.yaml  # Zero-Trust Network Segmentation
├── infrastructure/         # Docker image definitions & DB init scripts
│   ├── flink/Dockerfile    # Custom Flink image with PyFlink + connectors
│   ├── init_db.sh          # Creates 'airflow' DB on first boot
│   └── schema.sql          # All PostgreSQL table definitions
├── streaming/              # Core streaming code
│   ├── producer.py         # Binance WebSocket → Kafka
│   ├── lake_writer.py      # Kafka → Parquet Data Lake
│   ├── flink_processor.py  # DQ validation, enrichment, VWAP, DLQ routing
│   └── load_tester.py      # High-throughput test data generator
├── airflow/dags/           # Orchestration DAGs (EOD reports, DLQ recovery)
├── datalake/raw/           # Partitioned Parquet files (immutable archive)
├── schemas/                # Avro Schemas & Schema Registry definitions
├── mcp_server/             # MCP AI Agent (FastAPI + read-only SQL tools)
├── monitoring/             # Prometheus config, Grafana dashboards, alerts
│   ├── prometheus.yml      # Scrape configs (Kafka, Flink, Postgres, Airflow)
│   ├── alertmanager.yml    # Alert routing rules
│   ├── rules/              # Prometheus alerting rules
│   └── grafana/            # Dashboard JSONs + provisioning
├── test_e2e.py             # Full pipeline E2E test (5 phases)
└── test_mcp.py             # MCP Server unit & integration tests
```

---
*Updated: April 2026 — Unified Docker Compose (all services), Kafka 3-partition topics,
env-var-based service configuration, and enriched E2E test suite with DB assertions.*
