from fastapi import FastAPI, HTTPException, Request, Depends, Security
from fastapi.security.api_key import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import psycopg2
from psycopg2 import pool as pg_pool
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from typing import Optional
import os
import logging
import hashlib
import time
import re
import sqlparse
from sqlparse.tokens import DML
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

# ---------------------------------------------------------------------------
# Connection Pool Implementation (CRIT-01 Fix)
# ---------------------------------------------------------------------------
_db_pool: Optional[pg_pool.ThreadedConnectionPool] = None

def get_db_pool() -> pg_pool.ThreadedConnectionPool:
    global _db_pool
    if _db_pool is None:
        # Use read-only role if specified
        db_user = os.getenv("DB_USER_READONLY", os.getenv("DB_USER", "cryptostream_user"))
        _db_pool = pg_pool.ThreadedConnectionPool(
            minconn=1, maxconn=5,
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", "5432"),
            dbname=os.getenv("DB_NAME", "crypto_stream_db"),
            user=db_user,
            password=os.getenv("DB_PASS", "CHANGE_ME_IN_PROD")
        )
        logger.info("✅ DB connection pool initialized (min=1, max=5)")
    return _db_pool

@contextmanager
def get_db_conn(read_only=True):
    """Safely get a pooled connection and return it back when done."""
    conn = get_db_pool().getconn()
    try:
        # Configuration for safety
        if read_only:
            conn.set_session(readonly=True, autocommit=False)
        else:
            conn.set_session(readonly=False, autocommit=True)
        yield conn
    except Exception as e:
        logger.error(f"Database context error: {e}")
        raise
    finally:
        get_db_pool().putconn(conn)


def validate_select_only(sql: str) -> bool:
    """
    Validates that SQL query is a pure SELECT statement.
    Uses sqlparse for proper tokenization and validation.
    Returns True if safe, False otherwise.
    """
    if not sql or not isinstance(sql, str):
        return False
    
    # Basic pattern check: must start with SELECT (allowing leading whitespace and comments)
    cleaned = sql.strip().upper()
    
    # Check for obvious injection patterns
    dangerous_patterns = [
        r";\s*DROP\s+",
        r";\s*DELETE\s+",
        r";\s*UPDATE\s+",
        r";\s*INSERT\s+",
        r";\s*ALTER\s+",
        r";\s*TRUNCATE\s+",
        r";\s*CREATE\s+",
        r";\s*GRANT\s+",
        r";\s*REVOKE\s+",
        r"EXEC\s*\(",
        r"EXECUTE\s*\(",
        r"xp_cmdshell",
        r"sp_executesql",
        r"--",
        r"/\*.*\*/",  # Block comments that could hide malicious code
    ]
    
    for pattern in dangerous_patterns:
        if re.search(pattern, sql, re.IGNORECASE):
            logger.warning(f"SQL injection pattern detected: {pattern}")
            return False
    
    # Parse with sqlparse
    try:
        parsed = sqlparse.parse(sql)
        if not parsed:
            return False
        
        for statement in parsed:
            # Must be a SELECT statement
            first_token = None
            for token in statement.tokens:
                if not token.is_whitespace:
                    first_token = token
                    break
            
            if first_token is None:
                return False
            
            # Check if first meaningful token is SELECT
            if first_token.ttype is DML:
                if first_token.value.upper() != "SELECT":
                    logger.warning(f"Non-SELECT DML detected: {first_token.value}")
                    return False
            elif hasattr(first_token, 'value'):
                if first_token.value.upper() != "SELECT":
                    logger.warning(f"Query must start with SELECT, found: {first_token.value}")
                    return False
            else:
                logger.warning(f"Unexpected first token type: {type(first_token)}")
                return False
            
            # Walk all tokens to ensure no forbidden keywords appear as identifiers
            forbidden_in_identifiers = {'drop', 'delete', 'update', 'insert', 'alter', 
                                        'truncate', 'grant', 'revoke', 'create'}
            for token in statement.flatten():
                if token.value and token.value.lower() in forbidden_in_identifiers:
                    # Check context - if it's not a DML keyword but used as identifier, still block
                    if token.ttype not in (sqlparse.tokens.Name, sqlparse.tokens.Literal.String.Single):
                        logger.warning(f"Forbidden keyword detected: {token.value}")
                        return False
        
        return True
        
    except Exception as e:
        logger.error(f"SQL parsing error: {e}")
        return False

def log_audit_query(api_key: str, query: str, row_count: int, duration_ms: int, client_ip: str):
    """
    Banking Relevance: Regulatory requirement to audit all AI-generated queries 
    against the Data Lakehouse to track data access and prevent exfiltration.
    """
    with get_db_conn(read_only=False) as conn:
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
                # Autocommit is True for non-read-only in our pool helper
        except Exception as e:
            logger.error(f"Failed to insert audit log: {e}")

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
    with get_db_conn(read_only=True) as conn:
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

@app.post("/api/v1/query", response_model=QueryResponse)
@limiter.limit(RATE_LIMIT)
def execute_query(query_req: QueryRequest, request: Request, api_key: str = Depends(get_api_key)):
    """
    Execution tool: Allows the GenAI Agent to run read-only SQL queries.
    Banking Security: Enforces read-only database role and validates SQL structure.
    """
    logger.info(f"Agent executing SQL: {query_req.sql} (max_rows: {query_req.max_rows})")
    
    # Multi-layer security validation:
    # 1. SQL structure validation (must be pure SELECT)
    if not validate_select_only(query_req.sql):
        logger.warning(f"Rejected invalid or non-SELECT query: {query_req.sql}")
        raise HTTPException(status_code=403, detail="Only read-only SELECT queries are allowed. Query structure validation failed.")
    
    # 2. Additional check: Ensure no stacked queries (semicolon injection)
    if query_req.sql.count(';') > 1 or (';' in query_req.sql and not query_req.sql.strip().endswith(';')):
        logger.warning(f"Rejected query with suspicious semicolon usage: {query_req.sql}")
        raise HTTPException(status_code=403, detail="Query contains disallowed characters or structure.")
    
    start_time = time.time()
    # CRITICAL: Force read-only connection at database level via pool
    with get_db_conn(read_only=True) as conn:
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
                
                # Audit the query
                log_audit_query(api_key, safe_sql, row_count, duration_ms, client_ip)
                
                return QueryResponse(
                    sql=query_req.sql,
                    row_count=row_count,
                    data=data_dicts
                )
            except psycopg2.Error as query_err:
                # PostgreSQL read-only violations will be caught here
                logger.error(f"Agent SQL Execution failed (possible read-only violation): {query_err}")
                raise HTTPException(status_code=400, detail=f"Query execution failed: {str(query_err)}")
            except Exception as query_err:
                logger.error(f"Agent SQL Execution failed: {query_err}")
                raise HTTPException(status_code=400, detail=str(query_err))

"""
# Running locally:
# pip install fastapi uvicorn psycopg2-binary slowapi
# uvicorn main:app --host 0.0.0.0 --port 8080 --reload
"""
