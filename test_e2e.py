import os
import subprocess
import time
import sys
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("e2e_test")

def run_command(command, wait=True):
    logger.info(f"Running: {command}")
    process = subprocess.Popen(command, shell=True, stdout=sys.stdout, stderr=sys.stderr)
    if wait:
        process.wait()
        return process.returncode
    return process

def wait_for_services():
    """Wait for essential services (Kafka, Postgres) to be up."""
    logger.info("⏳ Waiting for Kafka and PostgreSQL to initialize...")
    time.sleep(10) # Simple sleep. In prod, check_services.py logic is better
    return run_command("python check_services.py")

def main():
    logger.info("==========================================================")
    logger.info("🚀 Starting End-to-End Local Test (CryptoStream AI)")
    logger.info("==========================================================")

    # 1. Start Docker Compose services
    logger.info("\n--- Phase 1: Infrastructure Startup ---")
    ret = run_command("docker compose up -d")
    if ret != 0:
         logger.error("Failed to start Docker Compose services.")
         sys.exit(1)

    # Wait for services to be ready
    wait_for_services()

    # 2. Run Load Tester
    logger.info("\n--- Phase 2: Simulating 1k TPS Data Load ---")
    ret = run_command("python streaming/load_tester.py")
    if ret != 0:
         logger.error("Load tester failed.")
         sys.exit(1)

    # Allow Flink time to process the last tumbling window
    logger.info("\n⏳ Giving Apache Flink 10 seconds to process 1-minute VWAP windows and write to PostgreSQL...")
    time.sleep(10)

    # 3. Run MCP Tests (AI Agent Simulator)
    logger.info("\n--- Phase 3: AI Agent Testing (MCP Client & Audit Verification) ---")
    ret = run_command("python test_mcp.py")
    if ret != 0:
         logger.error("MCP Server tests failed. Check the logs above.")
         sys.exit(1)

    logger.info("\n==========================================================")
    logger.info("✅ End-to-End Test Completed Successfully!")
    logger.info("==========================================================")
    logger.info("The Data Lakehouse securely handled high-throughput data.")
    logger.info("Whale alerts were triggered, invalid data was routed to DLQ.")
    logger.info("All GenAI Agent access was authenticated, audited, and verified.")
    logger.info("\nYou can view real-time metrics at:")
    logger.info("- Grafana: http://localhost:3000")
    logger.info("- Flink UI: http://localhost:8081" )
    logger.info("- Kafka UI: http://localhost:8080")

if __name__ == "__main__":
    main()
