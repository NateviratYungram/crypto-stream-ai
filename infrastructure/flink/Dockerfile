FROM flink:1.18-java11

# Install Python 3 and PIP
RUN apt-get update -y && \
    apt-get install -y python3 python3-pip python3-dev && \
    ln -s /usr/bin/python3 /usr/bin/python

# Install PyFlink and dependencies
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install -r /tmp/requirements.txt

# Download Connector JARs (Kafka & Postgres) — versions confirmed for Flink 1.18
# Using repo1.maven.org (Maven Central primary mirror, more reliable than repo.maven.apache.org)
RUN wget -q -P /opt/flink/lib/ https://repo1.maven.org/maven2/org/apache/flink/flink-sql-connector-kafka/3.1.0-1.18/flink-sql-connector-kafka-3.1.0-1.18.jar && \
    wget -q -P /opt/flink/lib/ https://repo1.maven.org/maven2/org/apache/flink/flink-connector-jdbc/3.1.2-1.18/flink-connector-jdbc-3.1.2-1.18.jar && \
    wget -q -P /opt/flink/lib/ https://jdbc.postgresql.org/download/postgresql-42.7.2.jar

WORKDIR /opt/flink
