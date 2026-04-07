# 🌊 CryptoStream AI 

![Architecture](https://img.shields.io/badge/Architecture-Data%20Lakehouse-blue)
![Tech Stack](https://img.shields.io/badge/Tech-Kafka%20%7C%20Flink%20%7C%20Postgres-orange)
![AI Ready](https://img.shields.io/badge/AI-MCP%20Server-green)
![Status](https://img.shields.io/badge/Status-Production%20Ready-success)

A highly scalable, distributed **Data Lakehouse Architecture** designed from the ground up for generative AI integrations under strict Virtual Banking regulatory standards (BOT/AMLO).

This platform ingests, processes, and persists high-throughput cryptocurrency trading data (1,000+ TPS) in real-time. It provides a hardened security layer via the **Model Context Protocol (MCP)**, allowing AI Agents (Current generation LLMs) to query the aggregated financial data autonomously while maintaining a full zero-trust audit trail.

---

## 🏗️ System Architecture

### 1. Ingestion Layer (Apache Kafka & Python)
- **High-Throughput Streaming:** Ingests live Binance WebSocket data (`producer.py`) or local simulated trades (`load_tester.py`) into Kafka topics (`trade_stream`).
- **Resilient Message Broker:** 3-partition Kafka topic handling high parallelism and fault-tolerant ingestion.

### 2. Processing Layer (Apache Flink)
- **Real-time VWAP Calculation:** Aggregates streams into 1-minute Volume Weighted Average Price (VWAP) windows.
- **Data Quality (DQ) Engine:** Identifies anomalies (negative prices, null quantities) and routes them into an isolated Dead Letter Queue (`trade_stream_dlq`) and a Postgres audit log.
- **Whale Detection:** Detects high-volume trades (>0.5 BTC) in real time for AML monitoring.

### 3. Lakehouse Persistence (PostgreSQL & Parquet)
- **Hot Layer (Postgres):** Holds enriched operational data (`enriched_trades`), aggregated metrics (`market_metrics`), and DQ logs for real-time query.
- **Cold Layer (Datalake):** Hive-partitioned Parquet files (`lake_writer.py`) for long-term immutable auditing (5-10 year BOL/AMLO retention).

### 4. Orchestration & Monitoring
- **Workflow:** **Apache Airflow** managing EOD reconciliation reports and DAG-based data recovery.
- **Observability:** Full **Prometheus + Grafana** stack with Alertmanager for real-time SLA tracking and pipeline health monitoring.

---

## 🚦 Quick Start (Unified Single-Command)

### Prerequisites
- Docker & Docker Compose (Desktop or Engine)
- Python 3.10+ (for local testing)

### 1. Spin up the Full Stack
```bash
docker compose up -d
```
*Starts Kafka, PostgreSQL, Flink Cluster, Airflow, Ingestion Producer [Binance WebSocket], Lake Writer [Parquet], and the Monitoring Stack (Prometheus/Grafana).*

### 2. Submit the Stream Processor
```bash
docker exec -d jobmanager flink run -py /opt/streaming/flink_processor.py
```
*Activates the real-time Whale Detection and VWAP Aggregation logic on the Flink cluster.*

### 3. Run the Automated E2E Test
```bash
python test_e2e.py
```
*Verifies the entire 5-phase pipeline: Infrastructure -> Streaming -> Load test -> DB Integrity -> AI Agent (MCP) Audit.*

---

## 📊 Monitoring & Access

| Service | URL | Credentials |
| :--- | :--- | :--- |
| **Kafka UI** | [http://localhost:8080](http://localhost:8080) | (None) |
| **Flink Dashboard** | [http://localhost:8081](http://localhost:8081) | (None) |
| **Airflow Webserver** | [http://localhost:8082](http://localhost:8082) | `admin` / `admin` |
| **Grafana Dashboards**| [http://localhost:3000](http://localhost:3000) | `admin` / `cryptostream_admin` |
| **Prometheus** | [http://localhost:9090](http://localhost:9090) | (None) |
| **Alertmanager** | [http://localhost:9093](http://localhost:9093) | (None) |

---

## ☁️ Cloud Deployment (Kubernetes)

The `/k8s/` directory contains production-grade manifests ready for deployment on **AWS EKS, GCP GKE, or Azure AKS**. 

Included manifests:
- **StatefulSets** for Kafka and Zookeeper (with PersistentVolumeClaims)
- **HPA (Horizontal Pod Autoscaler)** for Flink TaskManagers
- **NetworkPolicies** to enforce zero-trust lateral isolation between data layers
- **Ingress Resources** with NGINX security headers and rate-limiting

*Note: In production, secrets are managed via Kubernetes Secrets or External Secrets Operator (Vault/AWS SM).*

