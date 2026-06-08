# Data Architecture and Pipeline Notes

CryptoStream AI uses a layered architecture so each part has a clear responsibility. Sources provide raw market and broker information. Ingestion jobs move data into the platform. Processing jobs clean, enrich, and score the data. Storage layers keep both operational state and historical records. API and frontend layers turn the data into user workflows.

The main ingestion pattern is event plus batch. Streaming data can flow through Kafka topics for near-real-time updates. Scheduled Python and Airflow jobs collect or refresh slower-moving information, such as macro data, outcome scans, or anomaly baselines. The architecture is intentionally close to a modern data stack: Kafka for streaming, Airflow for orchestration, PostgreSQL for operational persistence, Parquet/data lake storage for analytical history, dbt-style transformations for modeled analytics, and pgvector for vector search.

PostgreSQL is the core local database. It stores application state, knowledge documents, knowledge chunks, vector embeddings, anomaly records, signal history, and operational metadata. pgvector enables semantic retrieval for RAG. If embeddings are unavailable, the RAG layer falls back to PostgreSQL full-text keyword search so local demos still work.

The data lake layer is used for historical market records and analytical workloads. A lake writer can persist normalized market events in durable files. This lets the project talk credibly about OLTP plus OLAP patterns: PostgreSQL supports low-latency app queries, while lake files support larger historical scans and future warehouse export.

Airflow DAGs represent production-style orchestration. The anomaly detection DAG is a good example: it runs on a schedule, reads recent market data, computes adaptive checks, writes results, and makes the output available to dashboards and readiness APIs. This is directly relevant to junior data engineering work because it shows scheduled pipeline ownership instead of only notebook analysis.

Data quality controls are represented by anomaly detection, readiness checks, schema initialization scripts, and CI tests. Examples of data quality questions the system should answer:

- Are required tables available?
- Is PostgreSQL reachable?
- Are expected RAG chunks present?
- Are market rows recent enough?
- Are anomaly jobs producing output?
- Are Telegram and MT5 integrations configured and reachable?

For interview explanation, the data flow can be described as: market data enters through APIs or streaming, pipelines validate and store it, analytics jobs produce features and anomalies, RAG stores project knowledge, and the AI agent uses all of that context to answer the user more accurately.
