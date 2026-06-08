# CryptoStream AI User Guide

This guide is the current quick-start reference for running and demoing CryptoStream AI locally.

## 1. Recommended Run Mode

The easiest way to run the full platform is Docker Compose from the project root:

```bash
docker compose up -d
docker compose ps
```

This starts the main local stack, including:

- Frontend
- Chat/API server
- MCP server
- PostgreSQL
- Kafka and Zookeeper
- Airflow
- Grafana
- Marquez

## 2. Main URLs

Use these URLs after the stack is up:

| URL | Service | Purpose |
|---|---|---|
| `http://localhost` | Frontend | Main web UI |
| `http://localhost:8888` | Chat/API server | Backend entrypoint |
| `http://localhost:8888/docs` | API docs | FastAPI Swagger docs |
| `http://localhost:8000/health` | MCP server | MCP health check |
| `http://localhost:8082/login/` | Airflow | DAG and scheduler UI |
| `http://localhost:3000` | Grafana | Metrics dashboards |
| `http://localhost:8080` | Kafka UI | Kafka topics and broker view |
| `http://localhost:3001` | Marquez Web | Data lineage UI |
| `http://localhost:5001` | Marquez API | Lineage API |

## 3. Health Checks

If the web app loads but some features look incomplete, check these first:

```bash
docker compose ps
```

```bash
curl http://localhost:8888/api/health
```

Expected result:

- `status: ok`
- `db: ok`
- `mcp: ok`

Check Airflow:

```bash
curl http://localhost:8082/health
```

Check MCP:

```bash
curl http://localhost:8000/health
```

## 4. Demo-Safe Flow

For a presentation or live walkthrough, this is the safest order:

1. Open the main frontend at `http://localhost`
2. Open backend docs at `http://localhost:8888/docs`
3. Open Airflow at `http://localhost:8082/login/`
4. Open Grafana at `http://localhost:3000`
5. Open Kafka UI at `http://localhost:8080`
6. Open Marquez at `http://localhost:3001`

Recommended demo tabs:

- Frontend
- API docs
- Airflow
- Grafana
- Kafka UI
- Marquez

## 5. Known Non-Blocking Caveat

You may still see warnings related to the MT5 bridge in logs.

That does not block the main web platform, dashboards, ingestion, Airflow, or observability stack. If the MT5 bridge is not configured on the host machine, avoid presenting broker-execution-specific flows.

## 6. Manual Development Mode

If you want to run services outside Docker for development, the common split is:

1. Infrastructure:

```bash
docker compose up -d postgres redis kafka zookeeper
```

2. MCP server:

```bash
python -m uvicorn mcp_server.main:app --host 127.0.0.1 --port 8000
```

3. Chat server:

```bash
python chat_server.py
```

4. Frontend:

```bash
cd frontend
npm install
npm run dev
```

In frontend dev mode, the UI is typically available at:

- `http://localhost:5173`

## 7. Common Recovery Commands

If a dependency was left stopped from an older session:

```bash
docker start postgres zookeeper kafka kafka-ui
```

If you need to recheck status:

```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

If you need logs:

```bash
docker compose logs --tail=100
```

## 8. Before Pushing or Presenting

Run these quick checks:

```bash
docker compose ps
```

```bash
curl http://localhost:8888/api/health
```

```bash
curl http://localhost:8082/health
```

Then manually confirm:

- Frontend opens
- API docs open
- Airflow opens
- Grafana opens
- Kafka UI opens
- Marquez opens

If all of the above are reachable, the local platform is ready for normal use and demo mode.
