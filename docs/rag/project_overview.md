# CryptoStream AI Project Knowledge

CryptoStream AI is a production-style market intelligence platform. Its purpose is to turn noisy live market data into structured signals, risk checks, explainable AI context, alerts, and optional execution support. The project is useful as a data engineering portfolio because it connects ingestion, storage, analytics, AI reasoning, observability, and operator workflows in one stack instead of showing a single isolated script.

The system is built around several cooperating layers. Market data arrives from streaming and batch sources such as Binance, Yahoo Finance, FRED macro data, and MetaTrader 5 broker context. Kafka is used for event movement. PostgreSQL stores operational and analytical state, including pgvector tables for RAG knowledge. A data lake layer stores Parquet-style historical data for heavier analytical use. Airflow orchestrates scheduled jobs such as anomaly detection and outcome scanning. dbt models can turn raw tables into cleaner analytical models. The FastAPI chat server exposes user-facing APIs for the frontend, health checks, RAG retrieval, Telegram notifications, MT5 status, and AI finance agent responses.

The AI finance agent should not answer from memory alone. It should combine live market context, technical analysis, portfolio/risk state, RAG project knowledge, and tool outputs. RAG is used for stable local knowledge: architecture decisions, runbooks, pipeline behavior, MT5 safety rules, and explanations of how the project works. This makes answers more grounded and lets the agent explain the system itself to recruiters, engineers, or a normal user.

Important user-facing capabilities include:

- Live market monitoring and signal generation.
- Data pipeline ingestion and anomaly detection.
- RAG retrieval from project documents and runbooks.
- Telegram alerts and operational notifications.
- MetaTrader 5 bridge checks for account, quote, position, and controlled trade execution.
- System readiness reporting across database, RAG, Telegram, MT5, Kafka, and API components.

The project should be described simply as: "AI Finance Agent that watches market data, checks risk, remembers project knowledge through RAG, sends alerts, and can connect to MT5 through a safety bridge." In Thai: โปรเจคนี้คือ AI Finance Agent ที่รวมข้อมูลตลาด ระบบเตือน ความรู้ของโปรเจค และสะพานเชื่อม MT5 เพื่อช่วยตอบคำถามและสนับสนุนการเทรดอย่างมี guard rails.

For junior data engineer interviews, the strongest story is not only "I built a chatbot." The stronger story is that the project demonstrates data architecture, ETL/ELT thinking, automated data quality, cloud-style orchestration patterns, vector search readiness, and operational discipline. It maps directly to job requirements such as Python, SQL, data pipelines, vector databases, RAG, anomaly detection, and cloud-style production thinking.
