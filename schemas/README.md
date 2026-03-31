# 📋 Schema Registry — Data Contract & Governance

## Why Schema Registry?

In financial systems, **data contracts** between services are not optional. When Kafka carries unvalidated JSON, a single upstream change (adding a field, changing a type) can silently corrupt downstream pipelines — causing bad trades, missing reports, or regulatory violations.

**Schema Registry solves this** by acting as a centralized "contract database" for all Kafka topics. Every message must conform to the registered schema before it can be produced or consumed.

---

## 🏦 Banking Relevance

| Risk Without Schema Registry | Banking Impact |
|---|---|
| Producer changes `price` from string to float | Flink CAST fails → downstream data corruption |
| Field `trade_id` renamed to `id` | Audit trail broken — AMLO compliance failure |
| New optional field added silently | DQ checks miss new invalid states |
| No schema versioning | Impossible to replay historical data with old consumers |

**Schema Registry gives you Schema Evolution** — controlled, backward/forward-compatible changes with full audit trail. This is equivalent to how banks manage **API contracts** between core banking systems.

---

## 📁 Schemas in This Project

### [`trade_event.avsc`](./trade_event.avsc) — Primary Trade Stream Schema

The canonical schema for every event on the `trade_stream` Kafka topic.

```
Producer (Binance WebSocket)
        │  validates against trade_event.avsc
        ▼
Kafka topic: trade_stream
        │  validates against trade_event.avsc
        ├──▶ Flink Processor (flink_processor.py)
        └──▶ Lake Writer (lake_writer.py)
```

**All producers and consumers share this single schema definition.**

---

## 🔄 Schema Evolution Rules

This project follows **Confluent Schema Registry BACKWARD_TRANSITIVE** compatibility:

| Change Type | Allowed? | Example |
|---|---|---|
| Add optional field with default | ✅ Yes | Add `exchange_fee` with `"default": 0` |
| Remove optional field | ✅ Yes | Remove deprecated field |
| Change field type (e.g., string → int) | ❌ No | Breaking change — requires new topic |
| Remove required field | ❌ No | Missing data in consumers |
| Rename a field | ❌ No | Breaks all consumers immediately |

---

## 🚀 Production Setup (Confluent Schema Registry)

In a production Virtual Banking environment, you would deploy:

```yaml
# docker-compose addition
schema-registry:
  image: confluentinc/cp-schema-registry:7.5.0
  environment:
    SCHEMA_REGISTRY_HOST_NAME: schema-registry
    SCHEMA_REGISTRY_KAFKASTORE_BOOTSTRAP_SERVERS: 'kafka:29092'
  ports:
    - "8081:8081"
```

**Register the schema:**
```bash
curl -X POST http://localhost:8081/subjects/trade_stream-value/versions \
  -H "Content-Type: application/vnd.schemaregistry.v1+json" \
  -d "{\"schema\": $(cat schemas/trade_event.avsc | jq -Rs .)}"
```

**Producer with Avro serialization:**
```python
from confluent_kafka.avro import AvroProducer

producer = AvroProducer({
    'bootstrap.servers': 'kafka:29092',
    'schema.registry.url': 'http://schema-registry:8081'
}, default_value_schema=trade_schema)
```

---

## 📊 Schema Versioning History

| Version | Date | Change | Compatibility |
|---|---|---|---|
| v1 | 2026-03-20 | Initial schema — 7 core fields from Binance feed | N/A |

---

## 🏗️ Integration with Flink

The Flink SQL DDL in `streaming/flink_processor.py` mirrors this schema exactly. When Schema Registry is active, Flink would use the **Avro connector with Schema Registry** instead of raw JSON:

```sql
-- Future: Schema Registry-backed Flink source
CREATE TABLE trade_stream (...)
WITH (
    'connector'                            = 'kafka',
    'format'                               = 'avro-confluent',
    'avro-confluent.url'                   = 'http://schema-registry:8081',
    'avro-confluent.subject'               = 'trade_stream-value'
)
```
