# 🌊 CryptoStream AI 

![Architecture](https://img.shields.io/badge/Architecture-Data%20Lakehouse-blue)
![Tech Stack](https://img.shields.io/badge/Tech-Kafka%20%7C%20Flink%20%7C%20PostgreSQL-orange)
![AI Ready](https://img.shields.io/badge/AI-MCP%20Server-green)
![Status](https://img.shields.io/badge/Status-Production%20Ready-success)

A highly scalable, distributed **Data Lakehouse Architecture** designed from the ground up for generative AI integrations under strict Virtual Banking regulatory standards (BOT/AMLO).

This platform ingests, processes, and persists high-throughput cryptocurrency trading data (1,000+ TPS) in real-time. It provides a hardened security layer via the **Model Context Protocol (MCP)**, allowing AI Agents (Current generation LLMs) to query the aggregated financial data autonomously while maintaining a full zero-trust audit trail.

---

## 🏗️ System Architecture

### 1. Ingestion Layer (Apache Kafka)
- **High-Throughput Streaming:** Ingests live WebSocket data or local simulated trades into Kafka topics (`trade_stream`).
- **HA Ready:** Supported by a 3-node Zookeeper ensemble for robust partition leadership.

### 2. Processing Layer (Apache Flink)
- **Real-time VWAP Calculation:** Aggregates streams into 1-minute Volume Weighted Average Price (VWAP) windows.
- **Data Quality Engine:** Identifies anomalies (e.g. negative prices, null quantities) and routes them into an isolated Dead Letter Queue (`trade_stream_dlq`).
- **Whale Detection:** Detects high-volume trades (>0.5 BTC) in real time.

### 3. Persistance Layer (PostgreSQL)
- **The Lakehouse:** Holds enriched operational data (`enriched_trades`), aggregated metrics (`market_metrics`), and DQ logs.
- **Security First:** Implements isolated Read-Only roles for agent access and decoupled data access patterns.

### 4. Orchestration (Apache Airflow)
- **Daily Reporting:** Nightly batch processing mirroring standard End-of-Day (EOD) bank reporting.
- **DLQ Sweeping:** Automatically retries or parses stranded messages from the Data Quality queue.

### 5. AI Integration (MCP Server - FastAPI)
- **Agent Sandbox:** Exposes introspective `/api/v1/schemas` and execution `/api/v1/query` endpoints natively to GenAI frameworks.
- **Production Hardened:** Fortified with strict Rate Limiting (SlowAPI), API Key Authentication, SQL-Injection protections (Regex blocking destructive keywords), and a permanent `mcp_audit_log`.

---

## 🚦 Quick Start (Local Development)

### Prerequisites
- Docker & Docker Compose
- Python 3.10+

### 1. Spin up the Infrastructure
```bash
docker compose up -d
```
*Starts Zookeeper, Kafka, PostgreSQL, Flink, and Airflow inside the local `crypto-network`.*

### 2. Run the End-to-End Pipeline
```bash
python test_e2e.py
```
*This command orchestrates:*
1. 1,000 TPS Simulated Data Load.
2. Flink real-time transformation.
3. Automated Security Penetration Testing of the MCP Server.

### 3. Access Monitoring Systems
- **Kafka UI:** [http://localhost:8080](http://localhost:8080)
- **Flink Dashboard:** [http://localhost:8081](http://localhost:8081)
- **Airflow Webserver:** [http://localhost:8082](http://localhost:8082) (admin / admin)
- **Grafana (WIP):** [http://localhost:3000](http://localhost:3000)

---

## ☁️ Cloud Deployment (Kubernetes)

The `/k8s/` directory contains production-grade manifests ready for deployment on **AWS EKS, GCP GKE, or Azure AKS**. 

Included manifests:
- **StatefulSets** for Kafka and Zookeeper (with PersistentVolumeClaims)
- **NetworkPolicies** to enforce zero-trust lateral isolation
- **Ingress Resources** with NGINX rate-limiting and security headers

*Note: You must inject your secrets using HashiCorp Vault or AWS Secrets Manager before deploying to production.*
