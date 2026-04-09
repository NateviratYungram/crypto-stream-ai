from fastapi import FastAPI, HTTPException, Request, Depends, Security
from fastapi.security.api_key import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor
import os
import logging
import hashlib
import time
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# ---------------------------------------------------------------------------
# Logging Setup
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("mcp_server")

app = FastAPI(
    title="CryptoStream AI - MCP Server",
    description="Model Context Protocol (MCP) Server allowing GenAI Agents to interact with the CryptoStream Data Lakehouse. Secured with API Key Auth and Rate Limiting.",
    version="1.1.0"
)

# ---------------------------------------------------------------------------
# Security & Rate Limiting Setup
# ---------------------------------------------------------------------------
API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=True)
MCP_API_KEY = os.getenv("MCP_API_KEY", "CHANGE_ME_LOCAL_DEV_KEY")
RATE_LIMIT = os.getenv("MCP_RATE_LIMIT", "60/minute")

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict this to specific domains
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

async def get_api_key(api_key_header: str = Security(api_key_header)):
    if api_key_header == MCP_API_KEY:
        return api_key_header
    raise HTTPException(status_code=403, detail="Could not validate credentials")

# Banking Relevance: DB credentials should be injected via Vault/Secrets Manager in production.
def get_db_connection():
    try:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),   # Default to localhost for local testing
            port=os.getenv("DB_PORT", "5432"),
            dbname=os.getenv("DB_NAME", "crypto_stream_db"),
            user=os.getenv("DB_USER", "cryptostream_user"), # Updated Phase 7 Role
            password=os.getenv("DB_PASS", "CHANGE_ME_IN_PROD")
        )
        return conn
    except Exception as e:
        logger.error(f"Failed to connect to PostgreSQL: {e}")
        raise HTTPException(status_code=500, detail="Database connection failed")

def log_audit_query(api_key: str, query: str, row_count: int, duration_ms: int, client_ip: str):
    """
    Banking Relevance: Regulatory requirement to audit all AI-generated queries 
    against the Data Lakehouse to track data access and prevent exfiltration.
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            hashed_key = hashlib.sha256(api_key.encode()).hexdigest()
            cur.execute(
                """
                INSERT INTO mcp_audit_log 
                (api_key_hash, sql_query, row_count, duration_ms, client_ip)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (hashed_key, query, row_count, duration_ms, client_ip)
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to insert audit log: {e}")
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# API Models
# ---------------------------------------------------------------------------
class QueryRequest(BaseModel):
    sql: str
    max_rows: int = 100

class QueryResponse(BaseModel):
    sql: str
    row_count: int
    data: list[dict]

class SchemaInfo(BaseModel):
    table_name: str
    columns: list[dict]

# ---------------------------------------------------------------------------
# MCP Endpoints
# ---------------------------------------------------------------------------
@app.get("/health")
def health_check():
    """Health check endpoint for Kubernetes/Docker."""
    return {"status": "healthy", "service": "mcp-server"}

@app.get("/api/v1/schemas", response_model=list[SchemaInfo])
@limiter.limit(RATE_LIMIT)
def get_schemas(request: Request, api_key: str = Depends(get_api_key)):
    """
    Introspection tool: Allows the GenAI Agent to discover available tables and columns.
    Banking Relevance: Agents must understand the exact schema before generating SQL
    to avoid inefficient queries or hallucinations.
    """
    logger.info("Agent requested database schema introspection.")
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Query standard PostgreSQL information_schema
            cur.execute("""
                SELECT table_name, column_name, data_type 
                FROM information_schema.columns 
                WHERE table_schema = 'public'
                ORDER BY table_name, ordinal_position;
            """)
            rows = cur.fetchall()
            
            # Group by table
            schemas = {}
            for row in rows:
                t = row["table_name"]
                if t not in schemas:
                    schemas[t] = {"table_name": t, "columns": []}
                schemas[t]["columns"].append({
                    "name": row["column_name"],
                    "type": row["data_type"]
                })
            
            return list(schemas.values())
    finally:
        conn.close()

@app.post("/api/v1/query", response_model=QueryResponse)
@limiter.limit(RATE_LIMIT)
def execute_query(query_req: QueryRequest, request: Request, api_key: str = Depends(get_api_key)):
    """
    Execution tool: Allows the GenAI Agent to run read-only SQL queries.
    Banking Security Note: In production, this MUST use a read-only database role
    to prevent SQL injection from modifying or dropping tables.
    """
    logger.info(f"Agent executing SQL: {query_req.sql} (max_rows: {query_req.max_rows})")
    
    # Basic protection against obvious destructive queries
    forbidden_keywords = ["DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE", "GRANT", "REVOKE"]
    sql_upper = query_req.sql.upper()
    if any(keyword in sql_upper for keyword in forbidden_keywords):
        logger.warning(f"Rejected potentially destructive query: {query_req.sql}")
        raise HTTPException(status_code=403, detail="Only read-only SELECT queries are allowed.")
    
    start_time = time.time()
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Enforce max rows to prevent OOM
            # Strip trailing semicolons to avoid syntax errors when wrapping in subquery
            clean_sql = query_req.sql.strip().rstrip(";")
            safe_sql = f"SELECT * FROM ({clean_sql}) AS subquery LIMIT {query_req.max_rows}"
            try:
                cur.execute(safe_sql)
                rows = cur.fetchall()
                data_dicts = [dict(row) for row in rows]
                row_count = len(data_dicts)
                
                duration_ms = int((time.time() - start_time) * 1000)
                client_ip = request.client.host if request.client else "unknown"
                
                # Asynchronously log the audit trail (in a real app, use background tasks)
                log_audit_query(api_key, safe_sql, row_count, duration_ms, client_ip)
                
                return QueryResponse(
                    sql=query_req.sql,
                    row_count=row_count,
                    data=data_dicts
                )
            except Exception as query_err:
                logger.error(f"Agent SQL Execution failed: {query_err}")
                raise HTTPException(status_code=400, detail=str(query_err))
    finally:
        conn.close()

"""
# Running locally:
# pip install fastapi uvicorn psycopg2-binary slowapi
# uvicorn main:app --host 0.0.0.0 --port 8080 --reload
"""
