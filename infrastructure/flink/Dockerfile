FROM flink:1.18-java11

# ============================================================
# CryptoStream AI — Custom Flink Image
# ============================================================
# This image is used for THREE service types in docker-compose.yml:
#   1. jobmanager  — Flink Job Manager (Web UI + coordination)
#   2. taskmanager — Flink Task Manager (executes jobs)
#   3. ingestion-producer — Runs producer.py (Binance WebSocket → Kafka)
#   4. lake-writer — Runs lake_writer.py (Kafka → Parquet)
#
# Having a single shared image keeps the build cache efficient and
# ensures all services use identical Python/library versions.
# ============================================================

# Install Python 3 and pip
RUN apt-get update -y && \
    apt-get install -y --no-install-recommends \
        python3 python3-pip python3-dev curl && \
    ln -sf /usr/bin/python3 /usr/bin/python && \
    rm -rf /var/lib/apt/lists/*

# Install all Python dependencies
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt

# ── Download Flink SQL Connector JARs (Kafka + JDBC/Postgres) ──────────────
# Versions confirmed for Flink 1.18. Using Maven Central for reliability.
RUN wget -q -P /opt/flink/lib/ \
    https://repo1.maven.org/maven2/org/apache/flink/flink-sql-connector-kafka/3.1.0-1.18/flink-sql-connector-kafka-3.1.0-1.18.jar && \
    wget -q -P /opt/flink/lib/ \
    https://repo1.maven.org/maven2/org/apache/flink/flink-connector-jdbc/3.1.2-1.18/flink-connector-jdbc-3.1.2-1.18.jar && \
    wget -q -P /opt/flink/lib/ \
    https://jdbc.postgresql.org/download/postgresql-42.7.2.jar

WORKDIR /opt/flink
