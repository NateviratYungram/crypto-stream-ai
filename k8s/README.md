# ☸️ Kubernetes Manifests — CryptoStream AI (Phase 7)

## Overview

This directory contains Kubernetes manifests for deploying the entire CryptoStream AI stack in a **cloud-native, self-healing** environment. This replaces Docker Compose for production Virtual Banking workloads.

**Banking Relevance:** Thai Virtual Banks are required to demonstrate **High Availability (HA)** and **Disaster Recovery (DR)** capabilities to the BOT. Kubernetes provides both through self-healing Pods, rolling deployments, and multi-zone scheduling.

---

## 📁 Directory Structure

```
k8s/
├── namespace.yaml                  # Isolates CryptoStream from other workloads
├── network-policies.yaml           # Zero-Trust Network Segmentation
├── ingress.yaml                    # Nginx Ingress with rate-limiting & security headers
├── kafka/
│   ├── zookeeper-statefulset.yaml  # ZK Ensemble (3 nodes)
│   └── kafka-statefulset.yaml      # Kafka Cluster (3 brokers, HA)
├── flink/
│   ├── flink-jobmanager.yaml       # Stream processing coordinator
│   ├── flink-taskmanager.yaml      # Stream processing workers
│   └── flink-hpa.yaml              # Horizontal Pod Autoscaler for TaskManagers
├── postgres/
│   ├── postgres-configmap.yaml     # Init schema + Performance Tuning
│   └── postgres-deployment.yaml    # Hot storage (Deployment + PVC + Secret)
├── airflow/
│   └── airflow-deployment.yaml     # Batch orchestration (Webserver + Scheduler + RBAC)
├── mcp-server/
│   └── mcp-server-deployment.yaml  # AI Agent API (Rate-limited, Audited)
└── monitoring/
    └── monitoring-deployment.yaml  # Prometheus + Grafana + Exporters + Alertmanager
```

---

## 🚀 Deployment Order

```bash
# 1. Create namespace & network policies first
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/network-policies.yaml

# 2. Deploy storage (Postgres must be ready before others)
kubectl apply -f k8s/postgres/

# 3. Deploy coordination & messaging (ZooKeeper then Kafka)
kubectl apply -f k8s/kafka/zookeeper-statefulset.yaml
kubectl apply -f k8s/kafka/kafka-statefulset.yaml

# 4. Deploy stream processing (Flink)
kubectl apply -f k8s/flink/

# 5. Deploy orchestration & AI components
kubectl apply -f k8s/airflow/
kubectl apply -f k8s/mcp-server/

# 6. Deploy Observability & Routing
kubectl apply -f k8s/monitoring/
kubectl apply -f k8s/ingress.yaml

# Verify all pods are Running
kubectl get pods -n cryptostream
```

---

## 🔍 Key Design Decisions

### KubernetesExecutor for Airflow
Instead of CeleryExecutor (which requires Redis), `KubernetesExecutor` runs each DAG task in its own Pod. This aligns with banking principles of **task isolation** and **audit traceability** — every regulatory report task has its own isolated log.

### PersistentVolumeClaim for PostgreSQL
Data survives Pod restarts via PVC. In production, use a **StorageClass** backed by your cloud provider's managed disks (GKE Persistent Disk, EKS EBS) for durability guarantees required by regulatory audits.

### Secrets Management
All Secrets in this directory use placeholder values (`CHANGE_ME_IN_PROD`). In production Virtual Banking, **NEVER store credentials in YAML files**. Use:
- **HashiCorp Vault** + External Secrets Operator
- **Google Secret Manager** (GKE)
- **AWS Secrets Manager** (EKS)

---

## 📈 Phase 7 Scaling Roadmap

| Component | Current | Phase 7 Target | Method |
|---|---|---|---|
| Kafka | 3 brokers | 3 brokers (HA) | StatefulSet + replication-factor=3 |
| Flink TaskManager | Auto-scale | Auto-scale | HPA on CPU/memory |
| PostgreSQL | Single + Tuning | HA with Patroni | postgres-ha Helm chart |
| Airflow | KubernetesExecutor | KubernetesExecutor | Isolated Pods for EOD jobs |
| Security | Zero-Trust | Zero-Trust | NetworkPolicies + Ingress Hardening |

---

## 🏦 HA and DR Architecture

```
                    Load Balancer
                         │
            ┌────────────┼────────────┐
            │            │            │
       Flink Pod 1  Flink Pod 2  Flink Pod 3   (Multi-zone)
            │            │            │
            └────────────┼────────────┘
                         │
                  Kafka Cluster (3 brokers)
                  Replication Factor = 3
                         │
                  PostgreSQL HA (Patroni)
                  Primary + 2 Replicas
```

**RTO (Recovery Time Objective):** < 2 minutes (K8s auto-restarts failed Pods)
**RPO (Recovery Point Objective):** < 5 minutes (Kafka retention + Flink checkpoints)
