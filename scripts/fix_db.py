import psycopg2
import os

conn = psycopg2.connect(
    host="localhost",
    port="5432",
    dbname="crypto_stream_db",
    user="user",
    password="password"
)
conn.autocommit = True
cur = conn.cursor()

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
print("mcp_audit_log table created successfully!")
conn.close()
