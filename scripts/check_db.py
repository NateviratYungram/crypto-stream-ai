import psycopg2
import time

PG_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "database": "crypto_stream_db",
    "user": "user",
    "password": "password",
}

def check_db():
    try:
        conn = psycopg2.connect(**PG_CONFIG)
        cur = conn.cursor()
        
        queries = [
            ("enriched_trades", "SELECT count(*) FROM enriched_trades"),
            ("market_metrics", "SELECT count(*) FROM market_metrics"),
            ("data_quality_log", "SELECT count(*) FROM data_quality_log"),
            ("mcp_audit_log", "SELECT count(*) FROM mcp_audit_log")
        ]
        
        print("\n--- Project Data Integrity Check ---")
        for name, query in queries:
            try:
                cur.execute(query)
                count = cur.fetchone()[0]
                status = "✅" if count > 0 else "⏳ (Empty)"
                print(f"{status} {name:20}: {count} rows")
            except Exception as e:
                print(f"❌ {name:20}: Error - {e}")
                conn.rollback()

        cur.close()
        conn.close()
    except Exception as e:
        print(f"FAILED to connect to PostgreSQL: {e}")

if __name__ == "__main__":
    check_db()
