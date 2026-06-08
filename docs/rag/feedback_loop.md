# RAG Feedback Loop Guide

The RAG feedback loop lets CryptoStream AI improve retrieval quality from real user behavior. Every retrieval response includes a `retrieval_id` and citations. A user, operator, or frontend can send feedback against that retrieval id with a rating such as `up`, `down`, `neutral`, `needs_more_context`, or `wrong_source`.

Feedback is stored separately from the knowledge documents. This keeps the main retrieval corpus stable while still giving the developer a way to identify weak areas. The feedback table records the retrieval id, query, rating, usefulness label, selected citation, comment, expected answer, metadata, and timestamp.

The feedback loop is useful for production-style RAG because evaluation tests cannot cover every real question. Evaluation catches known cases. Feedback catches user frustration, missing context, wrong citations, and questions that appear after the project changes.

Recommended workflow:

- Retrieve context through `/api/rag/retrieve`.
- Save the returned `retrieval_id` and citations in the UI.
- Let the user mark the answer helpful or not helpful.
- Send feedback to `/api/rag/feedback`.
- Review `/api/rag/feedback/stats` to find repeated negative queries.
- Add or update curated docs for weak topics.
- Re-run `scripts/ingest_knowledge.py ingest-project --include-code`.
- Re-run `scripts/evaluate_rag.py` in normal mode and `--disable-embeddings` fallback mode.

Good feedback comments should be specific. Examples:

- `needs_more_context`: The answer did not explain the MT5 live trading safety checklist.
- `wrong_source`: The result quoted source code when a user-facing runbook would be clearer.
- `down`: The answer missed the difference between RAG knowledge and live market tools.
- `up`: The answer used the project overview and RAG guide correctly.

In Thai: feedback loop คือระบบให้ผู้ใช้บอกว่า RAG ตอบดีหรือไม่ดี แล้วเอาข้อมูลนั้นกลับไปปรับเอกสารและ ranking ต่อ. มันทำให้ RAG ดีขึ้นจากการใช้งานจริง ไม่ใช่ดีแค่จากชุดทดสอบที่เราคิดเอง.
