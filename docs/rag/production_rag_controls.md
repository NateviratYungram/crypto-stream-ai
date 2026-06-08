# Production RAG Controls

CryptoStream AI now includes production-style RAG controls around retrieval quality, experiments, observability, annotation, and tenant isolation.

## Local Reranker

The first-stage retrieval uses vector and keyword signals. The local reranker then reorders candidates using query term overlap, source trust, vector similarity, and source type. Curated project docs and runbooks are preferred for user-facing explanations, while source code remains available for engineering questions.

The current reranker is `local_cross_signal_v1`. It is intentionally dependency-light and model-ready: the retrieval event stores the reranker model name, pre-rerank score, rerank score, and experiment arm so a later model-based reranker can be compared without changing the API contract.

## A/B Testing

Retrieval assigns each query to an experiment arm:

- `baseline`: hybrid retrieval without reranking.
- `hybrid_rerank`: hybrid retrieval plus local reranker.

Assignment is deterministic from experiment id, tenant id, and query text. This makes tests repeatable and lets operators compare latency, feedback, and citation quality by arm.

## Monitoring Latency and Cost

Every retrieval event records telemetry in metadata:

- tenant id and user id
- experiment id and arm
- rerank enabled flag
- latency in milliseconds
- query tokens, returned tokens, and total tokens
- estimated embedding cost
- whether embeddings were used
- source types and search types returned

The observability endpoint summarizes retrieval count, average latency, p95 latency, estimated cost, total tokens, experiment arms, feedback by arm, and the annotation queue.

## Human Annotation Dashboard

The annotation dashboard reads `/api/rag/observability` and `/api/rag/feedback/stats`. It shows recent retrievals, citations, feedback status, negative feedback candidates, experiment arms, and latency/cost metrics. Human reviewers can use this to decide which documents need better content, which citations are wrong, and which queries should become new evaluation cases.

## Multi-Tenant Permissions

Knowledge documents support a `tenant_id` metadata field. Retrieval filters documents so a tenant can see public documents and its own tenant documents. This prevents tenant-specific notes or private runbooks from leaking into another tenant's RAG context.

Default project corpus documents are ingested as `tenant_id=public`. Private tenant documents can be ingested through the RAG ingest API with a tenant id.

In Thai: ตอนนี้ RAG มีระบบแบบ production มากขึ้น: reranker, A/B testing, observability, dashboard สำหรับ human review และ tenant filter เพื่อแยกข้อมูลระหว่างลูกค้าหรือ workspace.
