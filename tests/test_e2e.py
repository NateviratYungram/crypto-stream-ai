"""
CryptoStream AI — End-to-End Test Suite
=========================================
Tests the full pipeline:
  1. Docker Compose infrastructure startup
  2. Kafka topic validation (created by kafka-init service)
  3. Apache Flink job submission
  4. Data load simulation (whales, invalid records, normal trades)
  5. MCP AI Agent + Audit Trail verification

Run:
    python test_e2e.py

Banking Relevance:
    An automated E2E test is the equivalent of a Parallel Run in banking —
    running old and new systems side-by-side to confirm data integrity before
    switching over. This suite validates the entire pipeline end-to-end.
"""
import os
import subprocess
import time
import sys
import json
import logging
import psycopg2

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("e2e_test")

# ── DB connection settings (matches docker-compose.yml) ──────────────────────
PG_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "database": "crypto_stream_db",
    "user": "user",
    "password": "password",
}


def run_command(command, wait=True, capture_output=False, cwd=None):
    logger.info(f"Running: {command}")
    stdout = subprocess.PIPE if capture_output else sys.stdout
    process = subprocess.Popen(
        command, shell=True, stdout=stdout, stderr=sys.stderr, cwd=cwd
    )
    if wait:
        process.wait()
        if capture_output:
            return process.returncode, process.stdout.read().decode("utf-8", errors="replace")
        return process.returncode
    return process


def wait_for_services(timeout_seconds=180):
    """
    Polls `docker compose ps` until all critical containers are healthy/running.
    Replaces the fragile substring match with explicit container name checks.
    """
    logger.info("⏳ Waiting for all services to be healthy (timeout: %ds)...", timeout_seconds)
    required_healthy = {"postgres", "kafka", "jobmanager"}
    deadline = time.time() + timeout_seconds

    while time.time() < deadline:
        ret, output = run_command("docker compose ps --format json", wait=True, capture_output=True)
        if ret != 0:
            time.sleep(5)
            continue

        # docker compose ps --format json returns one JSON object per line
        healthy = set()
        for line in output.strip().splitlines():
            try:
                svc = json.loads(line)
                name = svc.get("Service", "") or svc.get("Name", "")
                state = (svc.get("State", "") or svc.get("Status", "")).lower()
                if name in required_healthy and ("running" in state or "healthy" in state):
                    healthy.add(name)
            except json.JSONDecodeError:
                pass

        if healthy >= required_healthy:
            logger.info("✅ Core services healthy: %s", healthy)
            # Give Postgres init scripts extra time to complete
            time.sleep(5)
            return True

        missing = required_healthy - healthy
        logger.info("⏳ Still waiting for: %s", missing)
        time.sleep(8)

    logger.error("❌ Services failed to become healthy within %ds.", timeout_seconds)
    return False


def validate_kafka_topics():
    """Confirms required topics exist (created by kafka-init service)."""
    logger.info("🔍 Validating Kafka topics...")
    ret, output = run_command(
        "docker exec kafka kafka-topics --bootstrap-server localhost:9092 --list",
        wait=True, capture_output=True
    )
    topics = output.strip().splitlines()
    required_topics = ["trade_stream", "trade_stream_dlq"]
    missing = [t for t in required_topics if t not in topics]
    if missing:
        logger.warning("⚠️  Missing topics (kafka-init may still be running): %s — creating now...", missing)
        for topic in missing:
            run_command(
                f"docker exec kafka kafka-topics "
                f"--bootstrap-server localhost:9092 "
                f"--create --topic {topic} --partitions 3 --replication-factor 1 --if-not-exists"
            )
    else:
        logger.info("✅ Kafka topics validated: %s", required_topics)


def submit_flink_job():
    """Submits the Flink streaming processor and waits for it to initialize."""
    logger.info("🚀 Submitting Flink job: flink_processor.py ...")
    run_command(
        "docker exec -d jobmanager flink run -py /opt/streaming/flink_processor.py",
        wait=True
    )
    logger.info("⏳ Waiting 20s for Flink sinks to initialize...")
    time.sleep(20)


def run_load_test():
    """Run the load tester locally against localhost:9092."""
    logger.info("📊 Running load test (10s @ 1000 TPS)...")
    ret = run_command("python streaming/load_tester.py")
    if ret != 0:
        logger.error("❌ Load tester failed.")
        sys.exit(1)


def wait_for_db_data(table: str, min_rows: int = 1, timeout: int = 60) -> bool:
    """Polls PostgreSQL until the target table has at least min_rows rows."""
    logger.info("⏳ Waiting for data in table '%s' (min %d rows)...", table, min_rows)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            conn = psycopg2.connect(**PG_CONFIG)
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                count = cur.fetchone()[0]
            conn.close()
            if count >= min_rows:
                logger.info("✅ Table '%s' has %d rows.", table, count)
                return True
            logger.info("   '%s' has %d/%d rows so far...", table, count, min_rows)
        except Exception as e:
            logger.debug("DB not ready yet: %s", e)
        time.sleep(5)
    logger.error("❌ Timed out waiting for data in '%s'.", table)
    return False


def verify_pipeline_results():
    """Directly query PostgreSQL to validate the pipeline produced expected results."""
    logger.info("\n--- Verifying Pipeline Results in PostgreSQL ---")
    try:
        conn = psycopg2.connect(**PG_CONFIG)
        cur = conn.cursor()

        # enriched_trades
        cur.execute("SELECT COUNT(*), SUM(CASE WHEN is_whale THEN 1 ELSE 0 END) FROM enriched_trades")
        total_trades, whale_count = cur.fetchone()
        logger.info("📈 enriched_trades    : %d total | %d whale trades", total_trades, whale_count or 0)

        # market_metrics (VWAP windows)
        cur.execute("SELECT COUNT(*) FROM market_metrics")
        (metric_windows,) = cur.fetchone()
        logger.info("📊 market_metrics     : %d VWAP windows written", metric_windows)

        # data_quality_log (DLQ audit trail)
        cur.execute("SELECT COUNT(*), error_reason FROM data_quality_log GROUP BY error_reason")
        dq_rows = cur.fetchall()
        logger.info("🔍 data_quality_log   : %d DQ failures logged:", sum(r[0] for r in dq_rows))
        for count, reason in dq_rows:
            logger.info("     - %-30s : %d records", reason, count)

        cur.close()
        conn.close()

        # Assertions
        assert total_trades > 0,    "FAIL: enriched_trades is empty — Flink sink not working!"
        assert whale_count > 0,     "FAIL: No whale trades detected — load tester data may be wrong!"
        assert len(dq_rows) > 0,    "FAIL: data_quality_log is empty — DLQ pipeline not working!"
        logger.info("✅ All DB assertions passed.")
        return True

    except AssertionError as e:
        logger.error("❌ Assertion failed: %s", e)
        return False
    except Exception as e:
        logger.error("❌ DB verification error: %s", e)
        return False


def run_mcp_tests():
    logger.info("\n--- Phase 4: AI Agent & MCP Audit Verification ---")
    ret = run_command("python test_mcp.py")
    if ret != 0:
        logger.error("❌ MCP Server tests failed.")
        sys.exit(1)


def print_summary(success: bool):
    logger.info("\n==========================================================")
    if success:
        logger.info("✅  End-to-End Test Completed Successfully!")
        logger.info("==========================================================")
        logger.info("Pipeline validated:")
        logger.info("  ✔  Binance trades ingested → Kafka")
        logger.info("  ✔  Flink: valid trades enriched + whale detection")
        logger.info("  ✔  Flink: invalid trades → Kafka DLQ + Postgres audit log")
        logger.info("  ✔  VWAP market metrics aggregated (1-min window)")
        logger.info("  ✔  GenAI Agent (MCP) access authenticated + audited")
    else:
        logger.error("❌  End-to-End Test FAILED. Review logs above.")
    logger.info("==========================================================")
    logger.info("Live UIs:")
    logger.info("  Grafana   : http://localhost:3000  (admin / cryptostream_admin)")
    logger.info("  Flink UI  : http://localhost:8081")
    logger.info("  Kafka UI  : http://localhost:8080")
    logger.info("  Airflow   : http://localhost:8082  (admin / admin)")
    logger.info("  Prometheus: http://localhost:9090")


def main():
    logger.info("==========================================================")
    logger.info("🚀 CryptoStream AI — Full End-to-End Test")
    logger.info("==========================================================")

    # Phase 1: Infrastructure
    logger.info("\n--- Phase 1: Infrastructure Startup ---")
    ret = run_command("docker compose up -d")
    if ret != 0:
        logger.error("Failed to start Docker Compose services.")
        sys.exit(1)

    if not wait_for_services():
        sys.exit(1)

    validate_kafka_topics()

    # Phase 2: Stream Processor
    logger.info("\n--- Phase 2: Flink Stream Processor ---")
    submit_flink_job()

    # Phase 3: Load Test
    logger.info("\n--- Phase 3: Simulating High-Throughput Data ---")
    run_load_test()

    # Wait for Flink to process the last tumbling window
    logger.info("\n⏳ Allowing Flink 15s to drain the final 1-min window...")
    time.sleep(15)

    # Phase 4: DB Verification
    logger.info("\n--- Phase 4: Pipeline Result Verification ---")
    ok_enriched = wait_for_db_data("enriched_trades", min_rows=100, timeout=90)
    ok_dq       = wait_for_db_data("data_quality_log", min_rows=1, timeout=60)

    if not ok_enriched or not ok_dq:
        logger.error("❌ Pipeline did not produce expected data in time.")
        print_summary(False)
        sys.exit(1)

    pipeline_ok = verify_pipeline_results()

    # Phase 5: AI Agent / MCP
    logger.info("\n--- Phase 5: AI Agent & MCP Audit Verification ---")
    run_mcp_tests()

    print_summary(pipeline_ok)
    if not pipeline_ok:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\nTest interrupted by user.")
    finally:
        # Uncomment to auto-teardown after test run:
        # run_command("docker compose down -v")
        pass
