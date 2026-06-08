# RAG and AI Agent Guide

RAG means Retrieval-Augmented Generation. In this project it means the AI finance agent can retrieve relevant local knowledge before answering. Instead of relying only on the model's general memory, the agent can look up project-specific facts such as architecture, MT5 safety behavior, Telegram setup, pipeline responsibilities, and operational readiness.

The RAG implementation uses PostgreSQL with pgvector. Documents are normalized, split into overlapping chunks, embedded with the configured embedding model when available, and saved in `knowledge_documents` and `knowledge_chunks`. Each chunk stores text, metadata, token estimates, optional vector embeddings, and full-text search indexes. Retrieval first tries vector similarity search. If embeddings are missing or the vector search returns no useful rows, the system falls back to keyword search.

Good RAG in this project should do three jobs:

- Ground answers about the project so the AI does not invent architecture details.
- Help normal users understand the system in plain language.
- Help engineering reviewers see evidence of data engineering, RAG, orchestration, and operational readiness.

RAG makes the AI finance agent smarter, but it does not replace live market tools. RAG is best for stable knowledge. Live tools are best for changing facts such as account balance, open positions, quote prices, health checks, alerts, and recent signals. A strong answer should combine both when needed: RAG for "how this system works" and live tools for "what is happening now."

Important retrieval topics include:

- "What does this project do?"
- "How does RAG improve the AI finance agent?"
- "How does the data pipeline work?"
- "What does the MT5 bridge do?"
- "Is live trading safe?"
- "How does anomaly detection support data quality?"
- "Why is this relevant for a junior data engineer role?"

The expected benefit is better answer quality. Without RAG, the assistant may answer generically. With RAG, it can cite the project's actual design: Kafka, Airflow, PostgreSQL, pgvector, FastAPI, Telegram, MT5 bridge, anomaly detection, and readiness checks.

In Thai: RAG ทำให้ AI Finance Agent ฉลาดขึ้น เพราะมันมีคลังความรู้ของโปรเจคให้ค้นก่อนตอบ ไม่ใช่ตอบจากความจำกว้าง ๆ อย่างเดียว. แต่ RAG ไม่ใช่ข้อมูล live market; ราคาปัจจุบัน บัญชี MT5 และสถานะระบบต้องมาจาก tool/API สด.
