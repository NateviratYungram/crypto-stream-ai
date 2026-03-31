# 🤖 MCP Server (GenAI Agent Integration) — Phase 6

## Overview

This directory contains the **Model Context Protocol (MCP)** server for CryptoStream AI. It acts as a secure bridge between Large Language Models (LLMs like ChatGPT or Claude) and our Data Lakehouse.

**Banking Relevance:** "Chat with Data". Enables Business Users, Compliance Officers, and Branch Managers to ask natural language questions (e.g., *"How many whale transactions happened today?"*) without needing to write SQL or wait for a Data Engineering ticket. 

---

## 🏗️ Architecture

```
User (Natural Language)
      │
      ▼
LLM / Agent (e.g., LangChain, AutoGen)
      │
      ├──▶ 1. Schema Introspection Tool (schema_tool.py)
      │       Gets table schemas to avoid SQL hallucinations.
      │
      ├──▶ 2. SQL Generation (LLM internal)
      │
      └──▶ 3. SQL Query Execution Tool (query_tool.py)
              Sends query to MCP Server.
              │
              ▼
    MCP Server (FastAPI - main.py)
              │ (Validates read-only execution)
              ▼
    PostgreSQL (Hot Storage Layer)
```

---

## 🛡️ Security & Compliance (Banking Standards)

1. **Read-Only Enforcement:** The FastAPI MCP server explicitly blocks `DROP`, `DELETE`, `UPDATE`, `INSERT`, `ALTER`, `TRUNCATE`. In production, this must also connect to PostgreSQL using a dedicated `read-only` role.
2. **Result Set Limits:** Queries are automatically injected with `LIMIT config.max_rows` (default 50-100) to prevent the Agent from crashing the Lakehouse or overflowing the LLM context window.
3. **No Direct Schema Access:** The LLM does not get DDL rights; it must use the `/schemas` endpoint.

---

## 📁 Directory Structure

- `main.py`: The FastAPI server providing `/api/v1/schemas` and `/api/v1/query`.
- `tools/schema_tool.py`: Python tool template (compatible with LangChain/AutoGen) for introspection.
- `tools/query_tool.py`: Python tool template for SQL generation and execution.

---

## 🚀 Quick Start

**1. Start the MCP Server locally:**
```bash
cd mcp_server
pip install fastapi uvicorn psycopg2-binary requests pydantic
uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

**2. Test with cURL:**
```bash
# Get Schemas
curl http://localhost:8080/api/v1/schemas

# Run Query
curl -X POST http://localhost:8080/api/v1/query \
     -H "Content-Type: application/json" \
     -d '{"sql": "SELECT * FROM market_metrics ORDER BY window_start DESC", "max_rows": 5}'
```
