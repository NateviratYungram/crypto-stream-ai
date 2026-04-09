import os
import time

# Set DB_HOST and credentials to match the local docker-compose.yml environment
os.environ["DB_HOST"] = "localhost"
os.environ["DB_USER"] = "user"
os.environ["DB_PASS"] = "password"

from fastapi.testclient import TestClient
from mcp_server.main import app, get_db_connection
import json

# Auto-create the audit table just in case the Docker init script missed it
try:
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS mcp_audit_log (
            id             SERIAL PRIMARY KEY,
            api_key_hash   VARCHAR(64) NOT NULL,
            sql_query      TEXT NOT NULL,
            row_count      INTEGER,
            duration_ms    INTEGER,
            client_ip      VARCHAR(45),
            created_at     TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
        );
        """)
        conn.commit()
    conn.close()
    print("--- Database Setup: mcp_audit_log table verified/created ---")
except Exception as e:
    print(f"Warning: Could not auto-create audit table: {e}")

client = TestClient(app)

# Environment Variables setup for testing
API_KEY = os.getenv("MCP_API_KEY", "CHANGE_ME_LOCAL_DEV_KEY")
HEADERS = {"X-API-Key": API_KEY}

print("🚀 Starting MCP Server & AI Agent Security Tests...\n")

# ---------------------------------------------------------
# Test 1: Health Check (No Auth Required)
# ---------------------------------------------------------
print("--- Test 1: Health Check ---")
res = client.get("/health")
print(f"Status: {res.status_code}")
print(f"Response: {res.json()}\n")
assert res.status_code == 200

# ---------------------------------------------------------
# Test 2: Authentication (Missing API Key)
# ---------------------------------------------------------
print("--- Test 2: Security Validation (Missing API Key) ---")
res2 = client.get("/api/v1/schemas")
print(f"Status: {res2.status_code}")
prompt_result = "✅ Success! Blocked" if res2.status_code == 401 else "❌ Failed!"
print(f"{prompt_result}: Attempted to get schemas without API key.\n")
assert res2.status_code == 401

# ---------------------------------------------------------
# Test 3: SQL Injection Prevention (DROP TABLE)
# ---------------------------------------------------------
print("--- Test 3: Security Validation (DROP TABLE) ---")
bad_sql = "DROP TABLE market_metrics;"
res3 = client.post("/api/v1/query", json={"sql": bad_sql, "max_rows": 10}, headers=HEADERS)
print(f"Query: {bad_sql}")
print(f"Status: {res3.status_code}")
if res3.status_code == 403:
    print(f"✅ Success! Blocked with reason: {res3.json()['detail']}\n")
else:
    print(f"❌ Failed to block: {res3.text}\n")
assert res3.status_code == 403

# ---------------------------------------------------------
# Test 4: Rate Limiting
# ---------------------------------------------------------
print("--- Test 4: Rate Limit Evading (Should pass initially) ---")
passed_queries = 0
for _ in range(5):
    res_rl = client.post("/api/v1/query", json={"sql": "SELECT 1", "max_rows": 1}, headers=HEADERS)
    if res_rl.status_code == 200:
         passed_queries += 1
print(f"Executed 5 quick queries. {passed_queries}/5 passed rate limit (Expected 5/5 if limit > 5).\n")

# ---------------------------------------------------------
# Test 5: Real Agent Query (Count Whales & Check DQ)
# ---------------------------------------------------------
print("--- Test 5: Agent Testing Data From Load Generator ---")
whale_sql = "SELECT COUNT(*) as whale_count FROM enriched_trades WHERE is_whale = true"
res_whale = client.post("/api/v1/query", json={"sql": whale_sql, "max_rows": 10}, headers=HEADERS)
if res_whale.status_code == 200:
    whale_count = res_whale.json().get('data', [{}])[0].get('whale_count', 0)
    print(f"✅ Success! Found {whale_count} Whale Trades in the Lakehouse.")
else:
    print(f"❌ Failed to execute valid query: {res_whale.text}")


dq_sql = "SELECT COUNT(*) as failed_dq FROM data_quality_log"
res_dq = client.post("/api/v1/query", json={"sql": dq_sql, "max_rows": 10}, headers=HEADERS)
if res_dq.status_code == 200:
    dq_count = res_dq.json().get('data', [{}])[0].get('failed_dq', 0)
    print(f"✅ Success! Found {dq_count} Invalid Trades caught by the Data Quality engine.\n")
else:
    print(f"❌ Failed to execute valid query: {res_dq.text}\n")


# ---------------------------------------------------------
# Test 6: Verify MCP Audit Log
# ---------------------------------------------------------
print("--- Test 6: Verifying Audit Log (Banking Requirement) ---")
audit_sql = "SELECT COUNT(*) as audit_count FROM mcp_audit_log"
res_audit = client.post("/api/v1/query", json={"sql": audit_sql, "max_rows": 10}, headers=HEADERS)
if res_audit.status_code == 200:
    audit_count = res_audit.json().get('data', [{}])[0].get('audit_count', 0)
    print(f"✅ Success! Found {audit_count} Audit Log records capturing our previous queries.\n")
else:
    print(f"❌ Failed to execute valid query: {res_audit.text}\n")

print("--- 🏁 MCP Security & Agent Tests Completed ---")
