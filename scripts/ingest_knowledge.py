"""CLI for ingesting and retrieving RAG knowledge documents.

Examples:
    python scripts/ingest_knowledge.py ingest-file README.md --source-type md
    python scripts/ingest_knowledge.py retrieve "How does the data flow work?"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from intelligence.rag import (
    get_knowledge_feedback_stats,
    get_knowledge_observability,
    get_knowledge_stats,
    ingest_knowledge_document,
    ingest_knowledge_file,
    record_knowledge_feedback,
    retrieve_knowledge_context,
)


PROJECT_KNOWLEDGE_FILES = [
    ("README.md", "project_readme", "Project README"),
    ("USER_GUIDE.md", "project_guide", "User guide"),
    ("project_context.md", "project_context", "Project context"),
    ("docs/MT5_BRIDGE.md", "runbook", "MT5 bridge runbook"),
    ("docs/rag/project_overview.md", "rag_corpus", "Project overview for RAG"),
    ("docs/rag/data_architecture.md", "rag_corpus", "Data architecture for RAG"),
    ("docs/rag/rag_and_ai_agent.md", "rag_corpus", "RAG and AI agent guide"),
    ("docs/rag/feedback_loop.md", "rag_corpus", "RAG feedback loop guide"),
    ("docs/rag/production_rag_controls.md", "rag_corpus", "Production RAG controls guide"),
    ("docs/rag/operations_readiness.md", "rag_corpus", "Operations readiness guide"),
    ("docs/rag/mt5_live_trading.md", "rag_corpus", "MT5 live trading guide"),
]

PROJECT_CODE_FILES = [
    ("chat_server.py", "code_api", "FastAPI chat server"),
    ("intelligence/rag/retrieval.py", "code_rag", "RAG retrieval implementation"),
    ("intelligence/mt5_connector.py", "code_mt5", "MT5 connector"),
    ("intelligence/mt5_bridge_server.py", "code_mt5", "MT5 bridge server"),
    ("intelligence/tools/market_tools.py", "code_tools", "Market tools"),
    ("airflow/dags/anomaly_detection_dag.py", "code_pipeline", "Anomaly detection DAG"),
    ("streaming/lake_writer.py", "code_pipeline", "Lake writer"),
    ("streaming/producer.py", "code_pipeline", "Streaming producer"),
    ("mcp_server/main.py", "code_mcp", "MCP server"),
    ("mcp_server/tools/query_tool.py", "code_mcp", "SQL query MCP tool"),
]


def _print_json(payload: Dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def _existing_files(entries: Iterable[tuple[str, str, str]]) -> List[tuple[Path, str, str]]:
    files: List[tuple[Path, str, str]] = []
    for relative_path, source_type, title in entries:
        path = ROOT / relative_path
        if path.exists() and path.is_file():
            files.append((path, source_type, title))
    return files


def ingest_project_knowledge(include_code: bool, chunk_chars: int, overlap: int, max_chunks: int) -> Dict[str, Any]:
    """Ingest a curated, secret-safe project corpus for better RAG answers."""
    entries = list(PROJECT_KNOWLEDGE_FILES)
    if include_code:
        entries.extend(PROJECT_CODE_FILES)

    results = []
    for path, source_type, title in _existing_files(entries):
        result = ingest_knowledge_file(
            path=str(path),
            title=title,
            source_type=source_type,
            metadata={
                "corpus": "cryptostream_project",
                "relative_path": str(path.relative_to(ROOT)).replace("\\", "/"),
                "curated": True,
                "tenant_id": "public",
            },
            chunk_chars=chunk_chars,
            overlap=overlap,
            max_chunks=max_chunks,
        )
        results.append(result)

    errors = [result for result in results if result.get("status") == "ERROR"]
    stats = get_knowledge_stats()
    return {
        "status": "ERROR" if errors else "SUCCESS",
        "ingested_files": len(results),
        "errors": errors,
        "results": results,
        "stats": stats,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="CryptoStream AI RAG knowledge utility")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_file = subparsers.add_parser("ingest-file", help="Ingest a local document")
    ingest_file.add_argument("path", help="Path to .txt, .md, .csv, .json, .yaml, .log, or .pdf")
    ingest_file.add_argument("--title", help="Document title")
    ingest_file.add_argument("--source-type", help="Source type label, e.g. md, pdf, research, news")
    ingest_file.add_argument("--chunk-chars", type=int, default=1_200)
    ingest_file.add_argument("--overlap", type=int, default=160)
    ingest_file.add_argument("--max-chunks", type=int, default=60)

    ingest_text = subparsers.add_parser("ingest-text", help="Ingest raw text from a file-like source URI")
    ingest_text.add_argument("source_uri", help="Stable source URI or external identifier")
    ingest_text.add_argument("--content-file", required=True, help="Text file whose contents should be ingested")
    ingest_text.add_argument("--title", help="Document title")
    ingest_text.add_argument("--source-type", default="text")
    ingest_text.add_argument("--tenant-id", default="public")
    ingest_text.add_argument("--chunk-chars", type=int, default=1_200)
    ingest_text.add_argument("--overlap", type=int, default=160)
    ingest_text.add_argument("--max-chunks", type=int, default=60)

    ingest_project = subparsers.add_parser("ingest-project", help="Ingest the curated CryptoStream AI project corpus")
    ingest_project.add_argument("--include-code", action="store_true", help="Also ingest selected implementation files")
    ingest_project.add_argument("--chunk-chars", type=int, default=1_200)
    ingest_project.add_argument("--overlap", type=int, default=160)
    ingest_project.add_argument("--max-chunks-per-file", type=int, default=120)

    retrieve = subparsers.add_parser("retrieve", help="Retrieve RAG context for a query")
    retrieve.add_argument("query", help="Natural-language query")
    retrieve.add_argument("--limit", type=int, default=5)
    retrieve.add_argument("--source-type", help="Optional source type filter")
    retrieve.add_argument("--min-similarity", type=float, default=0.0)
    retrieve.add_argument("--tenant-id", default="public")
    retrieve.add_argument("--user-id")
    retrieve.add_argument("--experiment-arm", choices=["baseline", "hybrid_rerank"])
    retrieve.add_argument("--no-rerank", action="store_true")

    feedback = subparsers.add_parser("feedback", help="Record feedback for a RAG retrieval")
    feedback.add_argument("--retrieval-id", help="Retrieval ID returned by retrieve")
    feedback.add_argument("--rating", required=True, choices=["up", "down", "neutral", "needs_more_context", "wrong_source"])
    feedback.add_argument("--useful", choices=["true", "false"], help="Optional boolean usefulness label")
    feedback.add_argument("--query", help="Original query if retrieval-id is unavailable")
    feedback.add_argument("--selected-citation", help="Citation the user is reacting to")
    feedback.add_argument("--comment", help="Short feedback comment")
    feedback.add_argument("--expected-answer", help="What the answer should have included")

    feedback_stats = subparsers.add_parser("feedback-stats", help="Show RAG feedback summary")
    feedback_stats.add_argument("--limit", type=int, default=20)

    observability = subparsers.add_parser("observability", help="Show RAG latency, cost, A/B, and annotation queue")
    observability.add_argument("--tenant-id", default="public")
    observability.add_argument("--limit", type=int, default=50)

    subparsers.add_parser("stats", help="Show RAG corpus statistics")

    args = parser.parse_args()

    if args.command == "ingest-file":
        result = ingest_knowledge_file(
            path=args.path,
            title=args.title,
            source_type=args.source_type,
            chunk_chars=args.chunk_chars,
            overlap=args.overlap,
            max_chunks=args.max_chunks,
        )
    elif args.command == "ingest-text":
        content = Path(args.content_file).read_text(encoding="utf-8", errors="ignore")
        result = ingest_knowledge_document(
            source_uri=args.source_uri,
            content=content,
            title=args.title,
            source_type=args.source_type,
            metadata={"tenant_id": args.tenant_id},
            chunk_chars=args.chunk_chars,
            overlap=args.overlap,
            max_chunks=args.max_chunks,
        )
    elif args.command == "ingest-project":
        result = ingest_project_knowledge(
            include_code=args.include_code,
            chunk_chars=args.chunk_chars,
            overlap=args.overlap,
            max_chunks=args.max_chunks_per_file,
        )
    elif args.command == "stats":
        result = get_knowledge_stats()
    elif args.command == "feedback":
        useful = None
        if args.useful is not None:
            useful = args.useful == "true"
        result = record_knowledge_feedback(
            retrieval_id=args.retrieval_id,
            rating=args.rating,
            useful=useful,
            query=args.query,
            selected_citation=args.selected_citation,
            comment=args.comment,
            expected_answer=args.expected_answer,
            metadata={"source": "cli"},
        )
    elif args.command == "feedback-stats":
        result = get_knowledge_feedback_stats(limit=args.limit)
    elif args.command == "observability":
        result = get_knowledge_observability(limit=args.limit, tenant_id=args.tenant_id)
    else:
        result = retrieve_knowledge_context(
            query=args.query,
            limit=args.limit,
            source_type=args.source_type,
            min_similarity=args.min_similarity,
            tenant_id=args.tenant_id,
            user_id=args.user_id,
            experiment_arm=args.experiment_arm,
            rerank=not args.no_rerank,
        )

    _print_json(result)
    return 0 if result.get("status") != "ERROR" else 1


if __name__ == "__main__":
    raise SystemExit(main())
