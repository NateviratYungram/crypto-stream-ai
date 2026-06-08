"""Small repeatable quality check for the CryptoStream AI RAG corpus."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from intelligence.rag import get_knowledge_stats, retrieve_knowledge_context


@dataclass(frozen=True)
class EvalCase:
    name: str
    query: str
    expected_terms: tuple[str, ...]
    expected_sources: tuple[str, ...] = ()
    min_results: int = 1
    require_query_expansion: bool = False


EVAL_CASES = [
    EvalCase(
        name="project_overview",
        query="What does CryptoStream AI do and why is it useful for a junior data engineer portfolio?",
        expected_terms=("market", "pipeline", "rag", "data", "agent"),
        expected_sources=("rag_corpus", "project_readme"),
    ),
    EvalCase(
        name="rag_agent_value",
        query="How does RAG make the AI finance agent smarter?",
        expected_terms=("rag", "finance agent", "project", "knowledge"),
        expected_sources=("rag_corpus",),
    ),
    EvalCase(
        name="data_architecture",
        query="Explain the data architecture: Kafka, Airflow, PostgreSQL, pgvector, data lake",
        expected_terms=("kafka", "airflow", "postgresql", "pgvector", "lake"),
        expected_sources=("rag_corpus",),
    ),
    EvalCase(
        name="operations_readiness",
        query="How should I check if the system is ready for users?",
        expected_terms=("readiness", "postgresql", "telegram", "mt5", "rag"),
        expected_sources=("rag_corpus",),
    ),
    EvalCase(
        name="mt5_safety",
        query="What safety checks are required before MT5 live trading?",
        expected_terms=("mt5", "bridge", "quote", "account", "live trading"),
        expected_sources=("rag_corpus", "runbook"),
    ),
    EvalCase(
        name="thai_rag_value",
        query="RAG ช่วยให้ AI finance agent ตอบผู้ใช้ดีขึ้นยังไง",
        expected_terms=("rag", "finance agent", "knowledge", "project"),
        expected_sources=("rag_corpus",),
    ),
    EvalCase(
        name="telegram_readiness",
        query="How do Telegram alerts fit into readiness and operations?",
        expected_terms=("telegram", "readiness", "notifications", "configured"),
        expected_sources=("rag_corpus",),
    ),
    EvalCase(
        name="anomaly_pipeline",
        query="How does anomaly detection support data quality in this project?",
        expected_terms=("anomaly", "data", "quality", "airflow"),
        expected_sources=("rag_corpus", "code_pipeline"),
    ),
    EvalCase(
        name="pgvector_fallback",
        query="What happens if embeddings are unavailable in the RAG system?",
        expected_terms=("embedding", "keyword", "fallback", "postgresql"),
        expected_sources=("rag_corpus", "code_rag"),
    ),
    EvalCase(
        name="broker_bridge",
        query="Why does Docker need an MT5 bridge on the Windows host?",
        expected_terms=("docker", "windows", "bridge", "metatrader5"),
        expected_sources=("rag_corpus", "runbook"),
    ),
    EvalCase(
        name="portfolio_interview",
        query="Which job requirements does this project demonstrate for a junior data engineer?",
        expected_terms=("python", "sql", "pipeline", "vector", "data"),
        expected_sources=("rag_corpus", "project_readme"),
    ),
    EvalCase(
        name="live_vs_rag",
        query="When should the agent use RAG and when should it use live market tools?",
        expected_terms=("rag", "live", "tools", "market"),
        expected_sources=("rag_corpus",),
    ),
    EvalCase(
        name="production_rag_controls",
        query=(
            "How do reranking, A/B testing, human annotation, latency cost monitoring, "
            "and tenant permissions work in this RAG system?"
        ),
        expected_terms=("reranker", "a/b", "annotation", "tenant", "latency"),
        expected_sources=("rag_corpus",),
    ),
    EvalCase(
        name="free_quality_controls",
        query="RAG ลดค่าใช้จ่าย latency และแยกสิทธิ์ tenant ได้ยังไง",
        expected_terms=("rag", "cost", "latency", "tenant", "feedback"),
        expected_sources=("rag_corpus",),
        require_query_expansion=True,
    ),
]


def _evaluate_case(case: EvalCase, limit: int) -> Dict[str, Any]:
    result = retrieve_knowledge_context(case.query, limit=limit)
    context = (result.get("context") or "").lower()
    telemetry = result.get("telemetry") or {}
    experiment = result.get("experiment") or {}
    found_terms = [term for term in case.expected_terms if term.lower() in context]
    source_types = [chunk.get("source_type") for chunk in result.get("chunks", [])]
    found_sources = [source for source in case.expected_sources if source in source_types]
    citations = result.get("citations") or []
    passed = (
        result.get("status") == "SUCCESS"
        and result.get("result_count", 0) >= case.min_results
        and len(found_terms) >= max(1, len(case.expected_terms) - 1)
        and (not case.expected_sources or bool(found_sources))
        and len(citations) == result.get("result_count", 0)
        and bool(result.get("retrieval_id"))
        and isinstance(telemetry.get("latency_ms"), (int, float))
        and experiment.get("arm") in {"baseline", "hybrid_rerank"}
        and (not case.require_query_expansion or telemetry.get("query_expanded") is True)
    )
    return {
        "name": case.name,
        "status": result.get("status"),
        "passed": passed,
        "query": case.query,
        "result_count": result.get("result_count", 0),
        "found_terms": found_terms,
        "found_sources": found_sources,
        "expected_terms": list(case.expected_terms),
        "expected_sources": list(case.expected_sources),
        "citations": citations,
        "retrieval_id": result.get("retrieval_id"),
        "telemetry": telemetry,
        "experiment": experiment,
        "top_results": [
            {
                "title": chunk.get("title"),
                "source_type": chunk.get("source_type"),
                "search_type": chunk.get("search_type"),
                "score": chunk.get("score"),
                "rank_score": chunk.get("rank_score"),
                "pre_rerank_score": chunk.get("pre_rerank_score"),
                "rerank_score": chunk.get("rerank_score"),
                "reranker_model": chunk.get("reranker_model"),
                "citation": chunk.get("citation"),
            }
            for chunk in result.get("chunks", [])[:3]
        ],
        "error": result.get("error"),
}


def _embedding_cache_smoke() -> Dict[str, Any]:
    query = "How does RAG cost latency and tenant isolation work?"
    first = retrieve_knowledge_context(query, limit=3, experiment_arm="hybrid_rerank")
    second = retrieve_knowledge_context(query, limit=3, experiment_arm="hybrid_rerank")
    first_telemetry = first.get("telemetry") or {}
    second_telemetry = second.get("telemetry") or {}
    skipped = not first_telemetry.get("embedding_used")
    passed = bool(
        skipped
        or (
            first.get("status") == "SUCCESS"
            and second.get("status") == "SUCCESS"
            and second_telemetry.get("query_embedding_cache_hit") is True
            and float(second_telemetry.get("estimated_cost_usd") or 0) == 0.0
        )
    )
    return {
        "name": "query_embedding_cache",
        "passed": passed,
        "skipped": skipped,
        "first_cache_hit": first_telemetry.get("query_embedding_cache_hit"),
        "second_cache_hit": second_telemetry.get("query_embedding_cache_hit"),
        "second_estimated_cost_usd": second_telemetry.get("estimated_cost_usd"),
        "first_status": first.get("status"),
        "second_status": second.get("status"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate RAG retrieval against representative project questions")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument(
        "--disable-embeddings",
        action="store_true",
        help="Force keyword fallback retrieval for resilience testing",
    )
    args = parser.parse_args()

    if args.disable_embeddings:
        os.environ["RAG_DISABLE_EMBEDDINGS"] = "1"

    stats = get_knowledge_stats()
    cases: List[Dict[str, Any]] = [_evaluate_case(case, args.limit) for case in EVAL_CASES]
    cache_smoke = _embedding_cache_smoke()
    passed = all(case["passed"] for case in cases) and cache_smoke["passed"]
    payload = {
        "status": "SUCCESS" if passed else "ERROR",
        "passed": passed,
        "case_count": len(cases),
        "passed_count": sum(1 for case in cases if case["passed"]),
        "cache_smoke": cache_smoke,
        "stats": stats,
        "cases": cases,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
