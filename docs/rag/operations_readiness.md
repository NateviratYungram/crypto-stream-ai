# Operations and Readiness Guide

CryptoStream AI includes readiness checks because a production-style system should be able to report what is working and what is not. The main readiness API aggregates component status across database, RAG, Telegram, MT5, Kafka, and core API behavior. The goal is to make system health visible before the user trusts the AI agent for answers or trading support.

Key components to check:

- PostgreSQL: reachable, schema initialized, expected tables available.
- RAG: knowledge documents exist, chunks exist, embeddings exist when configured, retrieval returns relevant context.
- Telegram: bot token and chat id configured, test notification can send.
- MT5 bridge: Windows host bridge reachable, authenticated by API key, MT5 terminal connected, live trading flag visible.
- Kafka and data services: containers running and topics or producers available.
- Chat server: API responds to health/readiness endpoints and can serve user requests.

The readiness score should be treated as an operational indicator, not a guarantee of profit or trading correctness. A 100 percent readiness score means configured systems are reachable and basic checks passed. It does not mean every market decision is safe. Trading still requires risk controls, position sizing, stop loss rules, and human review.

Common operational issues:

- API endpoints can become slow if background market jobs are blocked by network errors.
- External providers such as Yahoo Finance, Binance, or DNS can fail independently of the local code.
- RAG quality depends on having enough curated documents and embeddings.
- MT5 live trading requires the host bridge, terminal login, broker connection, and explicit live-trading enablement.
- Telegram requires both a valid bot token and the correct chat id.

Best practice is to use a layered test:

- Database count test: confirm documents, chunks, and embedded chunks.
- Retrieval test: ask representative questions and verify expected terms appear.
- API test: call `/api/rag/retrieve` and chat endpoints.
- Readiness test: call `/api/system/readiness`.
- Notification test: send a Telegram test message.
- MT5 safety test: verify account and quote endpoints before any trade.

In Thai: สถานะพร้อมใช้งาน 100% คือระบบหลักเชื่อมต่อและตรวจผ่าน แต่ไม่ใช่การรับประกันกำไร. ก่อนเทรดจริงต้องตรวจ account, quote, risk, stop loss, volume และคำสั่งให้ชัดเจนเสมอ.
