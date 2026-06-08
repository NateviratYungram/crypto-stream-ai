"""RAG-style knowledge ingestion and retrieval backed by PostgreSQL/pgvector.

This module handles document chunking, embedding generation, persistence, and
retrieval without adding a framework dependency. If embeddings are unavailable,
retrieval falls back to PostgreSQL full-text search so local demos still work.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional in lightweight smoke tests
    def load_dotenv(*_args, **_kwargs):
        return False

try:
    import psycopg2
    import psycopg2.extras
except Exception:  # pragma: no cover - handled at runtime in lightweight tests
    psycopg2 = None

try:
    from google import genai as _genai
    from google.genai import types as _genai_types
except Exception:  # pragma: no cover - embedding gracefully degrades
    _genai = None
    _genai_types = None

load_dotenv()

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = os.getenv("RAG_EMBEDDING_MODEL", "gemini-embedding-001")
EMBEDDING_DIM = 768
DEFAULT_CHUNK_CHARS = 1_200
DEFAULT_CHUNK_OVERLAP = 160
MAX_DEFAULT_CHUNKS = 60
SOURCE_RANK_BOOST_SQL = """
    CASE
        WHEN kd.source_type = 'rag_corpus' THEN 0.120
        WHEN kd.source_type = 'runbook' THEN 0.090
        WHEN kd.source_type IN ('project_readme', 'project_guide', 'project_context') THEN 0.070
        WHEN kd.source_type LIKE 'code_%%' THEN -0.080
        ELSE 0.000
    END
"""
TEXT_FILE_SUFFIXES = {
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".json",
    ".yaml",
    ".yml",
    ".log",
}
CODE_FILE_SUFFIXES = {
    ".py",
    ".sql",
    ".ps1",
    ".sh",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".toml",
    ".ini",
    ".cfg",
}
RAG_EXPERIMENT_ID = os.getenv("RAG_EXPERIMENT_ID", "rag_hybrid_rerank_v1")
RAG_ESTIMATED_EMBED_COST_PER_1K = float(os.getenv("RAG_ESTIMATED_EMBED_COST_PER_1K", "0.0001"))


def _get_db_conn():
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is required for knowledge retrieval")

    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "crypto_stream_db"),
        user=os.getenv("DB_USER", "user"),
        password=os.getenv("DB_PASS", "password"),
        connect_timeout=3,
    )


def _jsonb(value: Optional[Dict[str, Any]]) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True)


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _vector_literal(values: Optional[Sequence[float]]) -> Optional[str]:
    if not values:
        return None
    return "[" + ",".join(f"{float(v):.8f}" for v in values) + "]"


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _estimate_embedding_cost(tokens: int) -> float:
    return round((max(tokens, 0) / 1000.0) * RAG_ESTIMATED_EMBED_COST_PER_1K, 8)


def normalize_text(text: str) -> str:
    """Normalize whitespace while preserving paragraph boundaries."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_long_paragraph(paragraph: str, chunk_chars: int, overlap: int) -> List[str]:
    chunks: List[str] = []
    start = 0
    while start < len(paragraph):
        end = min(start + chunk_chars, len(paragraph))
        window = paragraph[start:end]
        if end < len(paragraph):
            split_at = max(window.rfind(". "), window.rfind(" "), window.rfind("\n"))
            if split_at > chunk_chars * 0.55:
                end = start + split_at + 1
                window = paragraph[start:end]
        chunks.append(window.strip())
        if end >= len(paragraph):
            break
        start = max(end - overlap, start + 1)
    return [chunk for chunk in chunks if chunk]


def chunk_text(
    text: str,
    chunk_chars: int = DEFAULT_CHUNK_CHARS,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> List[str]:
    """Chunk text for embedding using paragraph-aware windows."""
    if chunk_chars <= 0:
        raise ValueError("chunk_chars must be greater than 0")
    if overlap < 0 or overlap >= chunk_chars:
        raise ValueError("overlap must be >= 0 and smaller than chunk_chars")

    normalized = normalize_text(text)
    if not normalized:
        return []

    paragraphs = [p.strip() for p in normalized.split("\n\n") if p.strip()]
    chunks: List[str] = []
    current = ""

    for paragraph in paragraphs:
        if len(paragraph) > chunk_chars:
            if current:
                chunks.append(current.strip())
                current = ""
            chunks.extend(_split_long_paragraph(paragraph, chunk_chars, overlap))
            continue

        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= chunk_chars:
            current = candidate
            continue

        if current:
            chunks.append(current.strip())
        prefix = current[-overlap:].strip() if overlap and current else ""
        current = f"{prefix}\n\n{paragraph}".strip() if prefix else paragraph

    if current:
        chunks.append(current.strip())

    return chunks


def _get_embedding(text: str, task_type: str = "SEMANTIC_SIMILARITY") -> Optional[List[float]]:
    """Generate an embedding, returning None if local config cannot support it."""
    if os.getenv("RAG_DISABLE_EMBEDDINGS", "").lower() in {"1", "true", "yes"}:
        return None

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or _genai is None:
        return None

    try:
        client = _genai.Client(api_key=api_key)
        config = None
        if _genai_types is not None:
            config = _genai_types.EmbedContentConfig(
                output_dimensionality=EMBEDDING_DIM,
                task_type=task_type,
            )
        result = client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=text,
            config=config,
        )
        return result.embeddings[0].values
    except Exception as exc:
        logger.warning("Knowledge embedding failed; keyword fallback remains available: %s", exc)
        return None


def _get_query_embedding_literal_cached(conn, query: str) -> tuple[Optional[str], bool]:
    """Return a cached query embedding literal when possible to avoid repeat API cost."""
    if os.getenv("RAG_DISABLE_EMBEDDINGS", "").lower() in {"1", "true", "yes"}:
        return None, False
    if not os.getenv("GEMINI_API_KEY") or _genai is None:
        return None, False

    query_hash = _content_hash(normalize_text(query).lower())
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT embedding::text
            FROM knowledge_query_embeddings
            WHERE query_hash = %s AND model = %s;
            """,
            (query_hash, EMBEDDING_MODEL),
        )
        row = cur.fetchone()
        if row and row[0]:
            cur.execute(
                """
                UPDATE knowledge_query_embeddings
                SET hit_count = hit_count + 1, updated_at = NOW()
                WHERE query_hash = %s AND model = %s;
                """,
                (query_hash, EMBEDDING_MODEL),
            )
            return str(row[0]), True

    embedding_literal = _vector_literal(_get_embedding(query, "RETRIEVAL_QUERY"))
    if not embedding_literal:
        return None, False

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO knowledge_query_embeddings
                (query_hash, model, embedding, token_estimate, hit_count, updated_at)
            VALUES (%s, %s, %s::vector, %s, 0, NOW())
            ON CONFLICT (query_hash, model) DO UPDATE SET
                embedding = EXCLUDED.embedding,
                token_estimate = EXCLUDED.token_estimate,
                updated_at = NOW()
            RETURNING embedding::text;
            """,
            (query_hash, EMBEDDING_MODEL, embedding_literal, _estimate_tokens(query)),
        )
        stored = cur.fetchone()
    return str(stored[0]) if stored and stored[0] else embedding_literal, False


def ensure_knowledge_schema(conn) -> None:
    """Create the RAG tables and indexes if they are missing."""
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_documents (
                id             BIGSERIAL PRIMARY KEY,
                source_uri     TEXT UNIQUE NOT NULL,
                title          TEXT NOT NULL,
                source_type    VARCHAR(40) NOT NULL DEFAULT 'text',
                content_sha256 CHAR(64) NOT NULL,
                metadata       JSONB NOT NULL DEFAULT '{}'::jsonb,
                chunk_count    INTEGER NOT NULL DEFAULT 0,
                ingested_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS knowledge_chunks (
                id             BIGSERIAL PRIMARY KEY,
                document_id    BIGINT NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
                chunk_index    INTEGER NOT NULL,
                content        TEXT NOT NULL,
                content_tsv    TSVECTOR GENERATED ALWAYS AS
                               (to_tsvector('simple', coalesce(content, ''))) STORED,
                embedding      vector({EMBEDDING_DIM}),
                token_estimate INTEGER NOT NULL,
                metadata       JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(document_id, chunk_index)
            );
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_knowledge_documents_source_type
                ON knowledge_documents (source_type, updated_at DESC);
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_text
                ON knowledge_chunks USING GIN (content_tsv);
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_embedding
                ON knowledge_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
            """
        )
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS knowledge_query_embeddings (
                query_hash     CHAR(64) NOT NULL,
                model          TEXT NOT NULL,
                embedding      vector({EMBEDDING_DIM}) NOT NULL,
                token_estimate INTEGER NOT NULL,
                hit_count      INTEGER NOT NULL DEFAULT 0,
                created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (query_hash, model)
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_retrieval_events (
                id             UUID PRIMARY KEY,
                query          TEXT NOT NULL,
                source_type    TEXT,
                result_count   INTEGER NOT NULL DEFAULT 0,
                citations      JSONB NOT NULL DEFAULT '[]'::jsonb,
                metadata       JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_feedback (
                id                BIGSERIAL PRIMARY KEY,
                retrieval_id      UUID REFERENCES knowledge_retrieval_events(id) ON DELETE SET NULL,
                query             TEXT,
                rating            VARCHAR(20) NOT NULL,
                useful            BOOLEAN,
                selected_citation TEXT,
                comment           TEXT,
                expected_answer   TEXT,
                metadata          JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CHECK (rating IN ('up', 'down', 'neutral', 'needs_more_context', 'wrong_source'))
            );
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_knowledge_feedback_retrieval
                ON knowledge_feedback (retrieval_id, created_at DESC);
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_knowledge_feedback_rating
                ON knowledge_feedback (rating, created_at DESC);
            """
        )
    conn.commit()


def ingest_knowledge_document(
    source_uri: str,
    content: str,
    title: Optional[str] = None,
    source_type: str = "text",
    metadata: Optional[Dict[str, Any]] = None,
    chunk_chars: int = DEFAULT_CHUNK_CHARS,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
    max_chunks: int = MAX_DEFAULT_CHUNKS,
    skip_unchanged: bool = True,
) -> Dict[str, Any]:
    """Ingest text into the knowledge base and embed chunks when configured."""
    clean_content = normalize_text(content)
    if not clean_content:
        return {"status": "ERROR", "error": "content is empty"}

    chunks = chunk_text(clean_content, chunk_chars=chunk_chars, overlap=overlap)
    if not chunks:
        return {"status": "ERROR", "error": "no chunks produced"}
    if len(chunks) > max_chunks:
        return {
            "status": "ERROR",
            "error": f"document produced {len(chunks)} chunks; max_chunks is {max_chunks}",
            "chunk_count": len(chunks),
        }

    doc_title = title or Path(source_uri).name or source_uri
    digest = _content_hash(clean_content)
    conn = _get_db_conn()

    try:
        ensure_knowledge_schema(conn)
        with conn.cursor() as cur:
            if skip_unchanged:
                cur.execute(
                    """
                    SELECT
                        kd.id,
                        kd.chunk_count,
                        COUNT(kc.id) AS chunk_rows,
                        COUNT(kc.id) FILTER (WHERE kc.embedding IS NOT NULL) AS embedded_chunks
                    FROM knowledge_documents kd
                    LEFT JOIN knowledge_chunks kc ON kc.document_id = kd.id
                    WHERE kd.source_uri = %s AND kd.content_sha256 = %s
                    GROUP BY kd.id, kd.chunk_count;
                    """,
                    (source_uri, digest),
                )
                existing = cur.fetchone()
                embeddings_configured = bool(os.getenv("GEMINI_API_KEY") and _genai is not None)
                if (
                    existing
                    and int(existing[1]) == len(chunks)
                    and int(existing[2]) == len(chunks)
                    and (not embeddings_configured or int(existing[3]) == len(chunks))
                ):
                    return {
                        "status": "SKIPPED",
                        "document_id": existing[0],
                        "source_uri": source_uri,
                        "title": doc_title,
                        "source_type": source_type,
                        "chunk_count": len(chunks),
                        "embedded_chunks": int(existing[3]),
                        "embedding_model": EMBEDDING_MODEL if int(existing[3]) else None,
                        "content_sha256": digest,
                    }

            cur.execute(
                """
                INSERT INTO knowledge_documents
                    (source_uri, title, source_type, content_sha256, metadata, chunk_count, updated_at)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s, NOW())
                ON CONFLICT (source_uri) DO UPDATE SET
                    title = EXCLUDED.title,
                    source_type = EXCLUDED.source_type,
                    content_sha256 = EXCLUDED.content_sha256,
                    metadata = EXCLUDED.metadata,
                    chunk_count = EXCLUDED.chunk_count,
                    updated_at = NOW()
                RETURNING id;
                """,
                (source_uri, doc_title, source_type, digest, _jsonb(metadata), len(chunks)),
            )
            document_id = cur.fetchone()[0]
            cur.execute("DELETE FROM knowledge_chunks WHERE document_id = %s;", (document_id,))

            embedded_chunks = 0
            for index, chunk in enumerate(chunks):
                embedding_literal = _vector_literal(_get_embedding(chunk, "RETRIEVAL_DOCUMENT"))
                if embedding_literal:
                    embedded_chunks += 1
                cur.execute(
                    """
                    INSERT INTO knowledge_chunks
                        (document_id, chunk_index, content, embedding, token_estimate, metadata)
                    VALUES (%s, %s, %s, %s::vector, %s, %s::jsonb);
                    """,
                    (
                        document_id,
                        index,
                        chunk,
                        embedding_literal,
                        _estimate_tokens(chunk),
                        _jsonb({"source_uri": source_uri, "title": doc_title, **(metadata or {})}),
                    ),
                )

        conn.commit()
        return {
            "status": "SUCCESS",
            "document_id": document_id,
            "source_uri": source_uri,
            "title": doc_title,
            "source_type": source_type,
            "chunk_count": len(chunks),
            "embedded_chunks": embedded_chunks,
            "embedding_model": EMBEDDING_MODEL if embedded_chunks else None,
            "content_sha256": digest,
        }
    except Exception as exc:
        conn.rollback()
        logger.error("Knowledge ingestion failed for %s: %s", source_uri, exc)
        return {"status": "ERROR", "error": str(exc), "source_uri": source_uri}
    finally:
        conn.close()


def _extract_file_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except Exception as exc:
            raise RuntimeError("Install pypdf to ingest PDF files") from exc
        reader = PdfReader(str(path))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)

    if suffix in TEXT_FILE_SUFFIXES | CODE_FILE_SUFFIXES:
        return path.read_text(encoding="utf-8", errors="ignore")

    raise ValueError(f"Unsupported knowledge file type: {suffix}")


def ingest_knowledge_file(
    path: str,
    title: Optional[str] = None,
    source_type: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    chunk_chars: int = DEFAULT_CHUNK_CHARS,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
    max_chunks: int = MAX_DEFAULT_CHUNKS,
) -> Dict[str, Any]:
    """Read a local document and ingest it into the vector knowledge base."""
    file_path = Path(path).expanduser().resolve()
    content = _extract_file_text(file_path)
    file_type = source_type or file_path.suffix.lower().lstrip(".") or "file"
    merged_metadata = {"file_name": file_path.name, **(metadata or {})}
    return ingest_knowledge_document(
        source_uri=str(file_path),
        content=content,
        title=title or file_path.stem,
        source_type=file_type,
        metadata=merged_metadata,
        chunk_chars=chunk_chars,
        overlap=overlap,
        max_chunks=max_chunks,
    )


def _apply_retrieval_filters(
    filters: List[str],
    params: List[Any],
    source_type: Optional[str],
    tenant_id: str,
) -> None:
    if source_type:
        filters.append("kd.source_type = %s")
        params.append(source_type)
    filters.append("(COALESCE(kd.metadata->>'tenant_id', 'public') IN ('public', %s))")
    params.append(tenant_id)


QUERY_EXPANSION_TERMS = {
    "rag": ("retrieval augmented generation", "knowledge", "context", "citation"),
    "retrieval": ("rag", "search", "context"),
    "rerank": ("reranker", "ranking", "hybrid_rerank"),
    "reranker": ("rerank", "ranking", "hybrid_rerank"),
    "a/b": ("ab", "experiment", "baseline", "hybrid_rerank"),
    "ab": ("a/b", "experiment", "baseline", "hybrid_rerank"),
    "annotation": ("feedback", "human review", "label"),
    "feedback": ("annotation", "human review", "rating"),
    "cost": ("estimated_cost_usd", "tokens", "budget"),
    "latency": ("p95", "avg_latency_ms", "response time"),
    "tenant": ("tenant_id", "permissions", "isolation"),
    "permission": ("tenant", "tenant_id", "isolation"),
    "permissions": ("tenant", "tenant_id", "isolation"),
    "vector": ("pgvector", "embedding", "semantic"),
    "embedding": ("vector", "pgvector", "semantic"),
    "mt5": ("metatrader5", "bridge", "broker"),
    "metatrader5": ("mt5", "bridge", "broker"),
    "telegram": ("notification", "alert", "chat id"),
    "anomaly": ("data quality", "dq", "validation"),
    "pipeline": ("etl", "elt", "kafka", "airflow"),
    "ค่าใช้จ่าย": ("cost", "estimated_cost_usd", "tokens"),
    "ต้นทุน": ("cost", "estimated_cost_usd", "tokens"),
    "สิทธิ์": ("permissions", "tenant", "tenant_id"),
    "หน่วง": ("latency", "p95", "response time"),
    "เร็ว": ("latency", "p95", "response time"),
}


def _expand_query_for_retrieval(query: str) -> str:
    """Add local project/domain synonyms for free keyword recall."""
    terms = _keyword_terms(query)
    additions: List[str] = []
    lowered = query.lower()
    for term in terms:
        for expansion in QUERY_EXPANSION_TERMS.get(term, ()):
            if expansion.lower() not in lowered and expansion not in additions:
                additions.append(expansion)
        if len(additions) >= 16:
            break
    if not additions:
        return query
    return f"{query} {' '.join(additions)}"


def _keyword_search(
    cur,
    query: str,
    limit: int,
    source_type: Optional[str],
    tenant_id: str,
) -> List[Dict[str, Any]]:
    filters = ["kc.content_tsv @@ plainto_tsquery('simple', %s)"]
    params: List[Any] = [query, query]
    _apply_retrieval_filters(filters, params, source_type, tenant_id)

    params.append(limit)
    cur.execute(
        f"""
        SELECT
            kd.source_uri,
            kd.title,
            kd.source_type,
            kc.chunk_index,
            kc.content,
            kc.metadata,
            kc.token_estimate,
            ts_rank_cd(kc.content_tsv, plainto_tsquery('simple', %s)) + {SOURCE_RANK_BOOST_SQL} AS score,
            NULL::float AS similarity,
            'keyword' AS search_type
        FROM knowledge_chunks kc
        JOIN knowledge_documents kd ON kd.id = kc.document_id
        WHERE {" AND ".join(filters)}
        ORDER BY score DESC, kd.updated_at DESC
        LIMIT %s;
        """,
        params,
    )
    text_rows = [dict(row) for row in cur.fetchall()]

    terms = _keyword_terms(query)
    if not terms:
        return text_rows

    like_filters = []
    like_params: List[Any] = []
    score_parts = []
    for term in terms:
        pattern = f"%{term}%"
        like_filters.append("(lower(kc.content) LIKE %s OR lower(kd.title) LIKE %s)")
        like_params.extend([pattern, pattern])
        score_parts.append(
            "(CASE WHEN lower(kc.content) LIKE %s THEN 1 ELSE 0 END + "
            "CASE WHEN lower(kd.title) LIKE %s THEN 2 ELSE 0 END)"
        )

    filters = [f"({' OR '.join(like_filters)})"]
    params = [*like_params]
    score_params = []
    for term in terms:
        pattern = f"%{term}%"
        score_params.extend([pattern, pattern])
    _apply_retrieval_filters(filters, params, source_type, tenant_id)

    cur.execute(
        f"""
        SELECT
            kd.source_uri,
            kd.title,
            kd.source_type,
            kc.chunk_index,
            kc.content,
            kc.metadata,
            kc.token_estimate,
            (0.25 + ({' + '.join(score_parts)})::float * 0.060 + {SOURCE_RANK_BOOST_SQL}) AS score,
            NULL::float AS similarity,
            'keyword_substring' AS search_type
        FROM knowledge_chunks kc
        JOIN knowledge_documents kd ON kd.id = kc.document_id
        WHERE {" AND ".join(filters)}
        ORDER BY score DESC, kd.updated_at DESC
        LIMIT %s;
        """,
        [*score_params, *params, limit],
    )
    substring_rows = [dict(row) for row in cur.fetchall()]
    return _merge_keyword_rows(text_rows, substring_rows, limit)


def _row_key(row: Dict[str, Any]) -> tuple[str, int]:
    return (str(row.get("source_uri") or ""), int(row.get("chunk_index") or 0))


def _merge_keyword_rows(
    text_rows: List[Dict[str, Any]],
    substring_rows: List[Dict[str, Any]],
    limit: int,
) -> List[Dict[str, Any]]:
    merged: Dict[tuple[str, int], Dict[str, Any]] = {}
    for row in text_rows:
        merged[_row_key(row)] = dict(row)

    for row in substring_rows:
        key = _row_key(row)
        if key in merged:
            merged[key]["score"] = max(float(merged[key].get("score") or 0), float(row.get("score") or 0)) + 0.05
            merged[key]["search_type"] = "keyword_hybrid"
            continue
        merged[key] = dict(row)

    rows = sorted(merged.values(), key=lambda row: float(row.get("score") or 0), reverse=True)
    return rows[:limit]


def _merge_hybrid_rows(
    vector_rows: List[Dict[str, Any]],
    keyword_rows: List[Dict[str, Any]],
    limit: int,
) -> List[Dict[str, Any]]:
    merged: Dict[tuple[str, int], Dict[str, Any]] = {}
    rrf_k = 60.0

    for rank, row in enumerate(vector_rows, 1):
        key = _row_key(row)
        copy = dict(row)
        copy["vector_score"] = float(row.get("score") or 0)
        copy["keyword_score"] = 0.0
        copy["rrf_score"] = 1.0 / (rrf_k + rank)
        copy["vector_rank"] = rank
        copy["keyword_rank"] = None
        merged[key] = copy

    for rank, row in enumerate(keyword_rows, 1):
        key = _row_key(row)
        keyword_score = float(row.get("score") or 0)
        rrf_score = 1.0 / (rrf_k + rank)
        if key in merged:
            merged[key]["keyword_score"] = max(float(merged[key].get("keyword_score") or 0), keyword_score)
            merged[key]["rrf_score"] = float(merged[key].get("rrf_score") or 0) + rrf_score
            merged[key]["keyword_rank"] = rank
            merged[key]["score"] = (
                float(merged[key].get("score") or 0)
                + min(0.18, keyword_score * 0.18)
                + float(merged[key].get("rrf_score") or 0) * 0.45
            )
            merged[key]["search_type"] = "hybrid"
            continue

        copy = dict(row)
        copy["vector_score"] = 0.0
        copy["keyword_score"] = keyword_score
        copy["rrf_score"] = rrf_score
        copy["vector_rank"] = None
        copy["keyword_rank"] = rank
        copy["score"] = float(copy.get("score") or 0) + rrf_score * 0.45
        merged[key] = copy

    rows = sorted(
        merged.values(),
        key=lambda row: (
            float(row.get("rrf_score") or 0),
            float(row.get("score") or 0),
            float(row.get("keyword_score") or 0),
            float(row.get("similarity") or 0),
        ),
        reverse=True,
    )
    return _diversify_rows(rows, limit)


def _assign_experiment_arm(query: str, tenant_id: str, experiment_id: str, requested_arm: Optional[str]) -> str:
    valid = {"baseline", "hybrid_rerank"}
    if requested_arm in valid:
        return requested_arm
    digest = hashlib.sha256(f"{experiment_id}:{tenant_id}:{query}".encode("utf-8")).hexdigest()
    return "hybrid_rerank" if int(digest[:8], 16) % 2 else "baseline"


def _rerank_rows(query: str, rows: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    """Local reranker model: lexical intent overlap + source trust + retrieval scores."""
    expanded_query = _expand_query_for_retrieval(query)
    terms = set(_keyword_terms(expanded_query))
    if not terms:
        return _diversify_rows(rows, limit)

    source_trust = {
        "rag_corpus": 0.16,
        "runbook": 0.13,
        "project_readme": 0.10,
        "project_guide": 0.08,
        "project_context": 0.08,
    }
    reranked = []
    for row in rows:
        title = str(row.get("title") or "").lower()
        content = str(row.get("content") or "").lower()
        text = f"{title} {content}"
        overlap = sum(1 for term in terms if term in text) / max(len(terms), 1)
        title_overlap = sum(1 for term in terms if term in title) / max(len(terms), 1)
        source_type = str(row.get("source_type") or "")
        lexical_score = overlap * 0.28
        title_score = title_overlap * 0.10
        trust_score = source_trust.get(source_type, -0.04 if source_type.startswith("code_") else 0.0)
        vector_score = float(row.get("similarity") or 0) * 0.12
        rrf_score = float(row.get("rrf_score") or 0) * 0.35
        base_score = float(row.get("score") or 0)
        row_copy = dict(row)
        row_copy["pre_rerank_score"] = base_score
        row_copy["rerank_score"] = base_score + lexical_score + title_score + trust_score + vector_score + rrf_score
        row_copy["reranker_model"] = "local_cross_signal_v2"
        reranked.append(row_copy)

    reranked.sort(key=lambda row: float(row.get("rerank_score") or 0), reverse=True)
    return _diversify_rows(reranked, limit)


def _keyword_terms(query: str) -> List[str]:
    stop_words = {
        "the",
        "and",
        "for",
        "with",
        "what",
        "does",
        "this",
        "that",
        "how",
        "should",
        "into",
        "from",
        "are",
        "why",
        "is",
        "it",
        "to",
        "of",
        "a",
        "an",
    }
    raw_terms = re.findall(r"[a-zA-Z0-9_]{2,}|[\u0E00-\u0E7F]{2,}", query.lower())
    terms: List[str] = []
    for term in raw_terms:
        if term in stop_words or term in terms:
            continue
        terms.append(term)
        if len(terms) >= 12:
            break
    return terms


def _diversify_rows(rows: List[Dict[str, Any]], limit: int, max_per_document: int = 2) -> List[Dict[str, Any]]:
    if len(rows) <= limit:
        return rows

    selected: List[Dict[str, Any]] = []
    deferred: List[Dict[str, Any]] = []
    counts: Dict[str, int] = {}

    for row in rows:
        source_uri = str(row.get("source_uri") or "")
        count = counts.get(source_uri, 0)
        if count < max_per_document:
            selected.append(row)
            counts[source_uri] = count + 1
        else:
            deferred.append(row)
        if len(selected) >= limit:
            break

    if len(selected) < limit:
        selected.extend(deferred[: limit - len(selected)])
    return selected[:limit]


def _record_retrieval_event(
    conn,
    retrieval_id: str,
    query: str,
    source_type: Optional[str],
    snippets: List[Dict[str, Any]],
    metadata: Dict[str, Any],
) -> None:
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO knowledge_retrieval_events
                    (id, query, source_type, result_count, citations, metadata)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb)
                ON CONFLICT (id) DO NOTHING;
                """,
                (
                    retrieval_id,
                    query,
                    source_type,
                    len(snippets),
                    json.dumps([item["citation"] for item in snippets], ensure_ascii=False),
                    _jsonb(
                        {
                            "search_types": sorted({item["search_type"] for item in snippets}),
                            "source_types": sorted({item["source_type"] for item in snippets}),
                            **metadata,
                        }
                    ),
                ),
            )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.warning("Knowledge retrieval event logging failed: %s", exc)


def retrieve_knowledge_context(
    query: str,
    limit: int = 5,
    source_type: Optional[str] = None,
    min_similarity: float = 0.0,
    tenant_id: str = "public",
    user_id: Optional[str] = None,
    experiment_id: str = RAG_EXPERIMENT_ID,
    experiment_arm: Optional[str] = None,
    rerank: bool = True,
) -> Dict[str, Any]:
    """Retrieve RAG context snippets for a user query."""
    clean_query = normalize_text(query)
    if not clean_query:
        return {"status": "ERROR", "error": "query is empty"}

    limit = max(1, min(int(limit), 12))
    tenant_id = normalize_text(tenant_id or "public") or "public"
    experiment_id = normalize_text(experiment_id or RAG_EXPERIMENT_ID) or RAG_EXPERIMENT_ID
    assigned_arm = _assign_experiment_arm(clean_query, tenant_id, experiment_id, experiment_arm)
    rerank_enabled = bool(rerank and assigned_arm == "hybrid_rerank")
    retrieval_id = str(uuid.uuid4())
    started = time.perf_counter()
    query_tokens = _estimate_tokens(clean_query)
    expanded_query = _expand_query_for_retrieval(clean_query)
    query_expanded = expanded_query != clean_query
    conn = _get_db_conn()

    try:
        ensure_knowledge_schema(conn)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            rows: List[Dict[str, Any]] = []
            vector_rows: List[Dict[str, Any]] = []
            candidate_limit = max(limit * 5, 24)
            embedding_literal, query_embedding_cache_hit = _get_query_embedding_literal_cached(conn, clean_query)

            if embedding_literal:
                filters = ["kc.embedding IS NOT NULL"]
                params: List[Any] = [embedding_literal, embedding_literal]
                _apply_retrieval_filters(filters, params, source_type, tenant_id)
                params.extend([embedding_literal, candidate_limit])

                vector_sql = f"""
                    SELECT
                        kd.source_uri,
                        kd.title,
                        kd.source_type,
                        kc.chunk_index,
                        kc.content,
                        kc.metadata,
                        kc.token_estimate,
                        1 - (kc.embedding <=> %s::vector) + {SOURCE_RANK_BOOST_SQL} AS score,
                        1 - (kc.embedding <=> %s::vector) AS similarity,
                        'vector' AS search_type
                    FROM knowledge_chunks kc
                    JOIN knowledge_documents kd ON kd.id = kc.document_id
                    WHERE {" AND ".join(filters)}
                    ORDER BY score DESC, kc.embedding <=> %s::vector
                    LIMIT %s;
                    """
                cur.execute(vector_sql, params)
                vector_rows = [dict(row) for row in cur.fetchall()]

                if not vector_rows:
                    # ivfflat can return no candidates on very small local corpora.
                    # Force exact scan as a correctness fallback for smoke/dev datasets.
                    cur.execute("SET LOCAL enable_indexscan = off;")
                    cur.execute("SET LOCAL enable_bitmapscan = off;")
                    cur.execute(vector_sql, params)
                    vector_rows = [dict(row) for row in cur.fetchall()]

                vector_rows = [row for row in vector_rows if float(row.get("similarity") or 0) >= min_similarity]

            keyword_rows = _keyword_search(cur, expanded_query, candidate_limit, source_type, tenant_id)
            if vector_rows:
                rows = _merge_hybrid_rows(vector_rows, keyword_rows, limit)
            else:
                rows = _diversify_rows(keyword_rows, limit)
            if rerank_enabled:
                rows = _rerank_rows(clean_query, rows, limit)

        snippets = []
        for row in rows:
            score = row.get("similarity") if row.get("similarity") is not None else row.get("score")
            metadata = row.get("metadata") or {}
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except Exception:
                    metadata = {}
            source_path = metadata.get("relative_path") or row["source_uri"]
            citation = f"{row['title']}#{row['chunk_index']} ({source_path})"
            snippets.append(
                {
                    "title": row["title"],
                    "source_uri": row["source_uri"],
                    "source_path": source_path,
                    "source_type": row["source_type"],
                    "chunk_index": row["chunk_index"],
                    "score": float(score or 0),
                    "rank_score": float(row.get("score") or 0),
                    "pre_rerank_score": float(row.get("pre_rerank_score") or row.get("score") or 0),
                    "rerank_score": float(row.get("rerank_score") or row.get("score") or 0),
                    "reranker_model": row.get("reranker_model"),
                    "rrf_score": float(row.get("rrf_score") or 0),
                    "vector_rank": row.get("vector_rank"),
                    "keyword_rank": row.get("keyword_rank"),
                    "similarity": float(row.get("similarity") or 0) if row.get("similarity") is not None else None,
                    "search_type": row["search_type"],
                    "citation": citation,
                    "metadata": metadata,
                    "content": row["content"],
                }
            )

        context = "\n\n".join(
            f"[{idx}] {item['citation']} - {item['source_type']}, "
            f"{item['search_type']} score={item['rerank_score']:.3f}\n{item['content']}"
            for idx, item in enumerate(snippets, 1)
        )
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        returned_tokens = sum(_estimate_tokens(item["content"]) for item in snippets)
        total_tokens = query_tokens + returned_tokens
        estimated_cost_usd = _estimate_embedding_cost(query_tokens if embedding_literal and not query_embedding_cache_hit else 0)
        telemetry = {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "experiment_id": experiment_id,
            "experiment_arm": assigned_arm,
            "rerank_enabled": rerank_enabled,
            "reranker_model": "local_cross_signal_v2" if rerank_enabled else None,
            "latency_ms": latency_ms,
            "query_tokens": query_tokens,
            "returned_tokens": returned_tokens,
            "total_tokens": total_tokens,
            "estimated_cost_usd": estimated_cost_usd,
            "embedding_used": bool(embedding_literal),
            "query_embedding_cache_hit": query_embedding_cache_hit,
            "query_expanded": query_expanded,
            "rrf_enabled": bool(vector_rows and keyword_rows),
            "candidate_limit": candidate_limit,
        }
        _record_retrieval_event(conn, retrieval_id, clean_query, source_type, snippets, telemetry)
        return {
            "status": "SUCCESS",
            "retrieval_id": retrieval_id,
            "query": clean_query,
            "tenant_id": tenant_id,
            "experiment": {
                "id": experiment_id,
                "arm": assigned_arm,
                "rerank_enabled": rerank_enabled,
            },
            "telemetry": telemetry,
            "result_count": len(snippets),
            "chunks": snippets,
            "citations": [item["citation"] for item in snippets],
            "context": context,
        }
    except Exception as exc:
        logger.error("Knowledge retrieval failed: %s", exc)
        return {"status": "ERROR", "error": str(exc), "query": clean_query}
    finally:
        conn.close()


def get_knowledge_stats() -> Dict[str, Any]:
    """Return small operational stats for the local RAG knowledge base."""
    conn = _get_db_conn()
    try:
        ensure_knowledge_schema(conn)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*) AS documents,
                    COALESCE(SUM(chunk_count), 0) AS declared_chunks
                FROM knowledge_documents;
                """
            )
            document_stats = dict(cur.fetchone())
            cur.execute(
                """
                SELECT
                    COUNT(*) AS chunks,
                    COUNT(*) FILTER (WHERE embedding IS NOT NULL) AS embedded_chunks,
                    COALESCE(SUM(token_estimate), 0) AS token_estimate
                FROM knowledge_chunks;
                """
            )
            chunk_stats = dict(cur.fetchone())
            cur.execute(
                """
                SELECT
                    source_type,
                    COUNT(DISTINCT kd.id) AS documents,
                    COUNT(kc.id) AS chunks,
                    COUNT(kc.id) FILTER (WHERE kc.embedding IS NOT NULL) AS embedded_chunks
                FROM knowledge_documents kd
                LEFT JOIN knowledge_chunks kc ON kc.document_id = kd.id
                GROUP BY source_type
                ORDER BY chunks DESC, source_type ASC;
                """
            )
            by_source_type = [dict(row) for row in cur.fetchall()]

        return {
            "status": "SUCCESS",
            **document_stats,
            **chunk_stats,
            "by_source_type": by_source_type,
        }
    except Exception as exc:
        logger.error("Knowledge stats failed: %s", exc)
        return {"status": "ERROR", "error": str(exc)}
    finally:
        conn.close()


def record_knowledge_feedback(
    retrieval_id: Optional[str],
    rating: str,
    useful: Optional[bool] = None,
    query: Optional[str] = None,
    selected_citation: Optional[str] = None,
    comment: Optional[str] = None,
    expected_answer: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Record user/operator feedback for a RAG retrieval result."""
    rating = normalize_text(rating).lower()
    valid_ratings = {"up", "down", "neutral", "needs_more_context", "wrong_source"}
    if rating not in valid_ratings:
        return {"status": "ERROR", "error": f"rating must be one of {sorted(valid_ratings)}"}

    conn = _get_db_conn()
    try:
        ensure_knowledge_schema(conn)
        event_query = None
        if retrieval_id:
            with conn.cursor() as cur:
                cur.execute("SELECT query FROM knowledge_retrieval_events WHERE id = %s;", (retrieval_id,))
                row = cur.fetchone()
                if row:
                    event_query = row[0]

        feedback_query = query or event_query
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO knowledge_feedback
                    (retrieval_id, query, rating, useful, selected_citation, comment, expected_answer, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                RETURNING id, created_at;
                """,
                (
                    retrieval_id,
                    feedback_query,
                    rating,
                    useful,
                    selected_citation,
                    comment,
                    expected_answer,
                    _jsonb(metadata),
                ),
            )
            feedback_id, created_at = cur.fetchone()
        conn.commit()
        return {
            "status": "SUCCESS",
            "feedback_id": feedback_id,
            "retrieval_id": retrieval_id,
            "rating": rating,
            "useful": useful,
            "query": feedback_query,
            "created_at": created_at,
        }
    except Exception as exc:
        conn.rollback()
        logger.error("Knowledge feedback recording failed: %s", exc)
        return {"status": "ERROR", "error": str(exc)}
    finally:
        conn.close()


def get_knowledge_feedback_stats(limit: int = 20) -> Dict[str, Any]:
    """Summarize retrieval feedback so weak RAG areas can be improved."""
    limit = max(1, min(int(limit), 100))
    conn = _get_db_conn()
    try:
        ensure_knowledge_schema(conn)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*) AS feedback_count,
                    COUNT(*) FILTER (WHERE useful IS TRUE OR rating = 'up') AS positive_count,
                    COUNT(*) FILTER (
                        WHERE useful IS FALSE OR rating IN ('down', 'needs_more_context', 'wrong_source')
                    ) AS negative_count
                FROM knowledge_feedback;
                """
            )
            summary = dict(cur.fetchone())
            cur.execute(
                """
                SELECT rating, COUNT(*) AS count
                FROM knowledge_feedback
                GROUP BY rating
                ORDER BY count DESC, rating ASC;
                """
            )
            by_rating = [dict(row) for row in cur.fetchall()]
            cur.execute(
                """
                SELECT
                    kf.id,
                    kf.retrieval_id,
                    kf.query,
                    kf.rating,
                    kf.useful,
                    kf.selected_citation,
                    kf.comment,
                    kf.expected_answer,
                    kf.created_at,
                    kre.citations
                FROM knowledge_feedback kf
                LEFT JOIN knowledge_retrieval_events kre ON kre.id = kf.retrieval_id
                ORDER BY kf.created_at DESC
                LIMIT %s;
                """,
                (limit,),
            )
            recent = [dict(row) for row in cur.fetchall()]
            cur.execute(
                """
                SELECT
                    COALESCE(query, '(unknown)') AS query,
                    COUNT(*) AS feedback_count,
                    COUNT(*) FILTER (
                        WHERE useful IS FALSE OR rating IN ('down', 'needs_more_context', 'wrong_source')
                    ) AS negative_count
                FROM knowledge_feedback
                GROUP BY COALESCE(query, '(unknown)')
                HAVING COUNT(*) FILTER (
                    WHERE useful IS FALSE OR rating IN ('down', 'needs_more_context', 'wrong_source')
                ) > 0
                ORDER BY negative_count DESC, feedback_count DESC
                LIMIT %s;
                """,
                (limit,),
            )
            improvement_candidates = [dict(row) for row in cur.fetchall()]

        total = int(summary.get("feedback_count") or 0)
        positive = int(summary.get("positive_count") or 0)
        satisfaction = round((positive / total) * 100, 1) if total else None
        return {
            "status": "SUCCESS",
            **summary,
            "satisfaction_percent": satisfaction,
            "by_rating": by_rating,
            "recent": recent,
            "improvement_candidates": improvement_candidates,
        }
    except Exception as exc:
        logger.error("Knowledge feedback stats failed: %s", exc)
        return {"status": "ERROR", "error": str(exc)}
    finally:
        conn.close()


def get_knowledge_observability(limit: int = 50, tenant_id: str = "public") -> Dict[str, Any]:
    """Summarize RAG latency, estimated cost, A/B arms, and annotation queue."""
    limit = max(1, min(int(limit), 200))
    tenant_id = normalize_text(tenant_id or "public") or "public"
    conn = _get_db_conn()
    try:
        ensure_knowledge_schema(conn)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*) AS retrieval_count,
                    ROUND(AVG((metadata->>'latency_ms')::numeric), 2) AS avg_latency_ms,
                    ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY (metadata->>'latency_ms')::numeric)::numeric, 2)
                        AS p95_latency_ms,
                    ROUND(SUM(COALESCE((metadata->>'estimated_cost_usd')::numeric, 0)), 8) AS estimated_cost_usd,
                    SUM(COALESCE((metadata->>'total_tokens')::int, 0)) AS total_tokens,
                    COUNT(*) FILTER (WHERE metadata->>'query_embedding_cache_hit' = 'true') AS query_cache_hits,
                    COUNT(*) FILTER (WHERE metadata->>'query_expanded' = 'true') AS expanded_query_count
                FROM knowledge_retrieval_events
                WHERE COALESCE(metadata->>'tenant_id', 'public') IN ('public', %s);
                """,
                (tenant_id,),
            )
            summary = dict(cur.fetchone())
            cur.execute(
                """
                SELECT
                    COALESCE(metadata->>'experiment_arm', 'unknown') AS arm,
                    COUNT(*) AS retrieval_count,
                    ROUND(AVG((metadata->>'latency_ms')::numeric), 2) AS avg_latency_ms,
                    ROUND(SUM(COALESCE((metadata->>'estimated_cost_usd')::numeric, 0)), 8) AS estimated_cost_usd
                FROM knowledge_retrieval_events
                WHERE COALESCE(metadata->>'tenant_id', 'public') IN ('public', %s)
                GROUP BY COALESCE(metadata->>'experiment_arm', 'unknown')
                ORDER BY retrieval_count DESC, arm ASC;
                """,
                (tenant_id,),
            )
            by_experiment = [dict(row) for row in cur.fetchall()]
            cur.execute(
                """
                SELECT
                    kre.id AS retrieval_id,
                    kre.query,
                    kre.result_count,
                    kre.citations,
                    kre.metadata,
                    kre.created_at,
                    COUNT(kf.id) AS feedback_count,
                    COUNT(kf.id) FILTER (
                        WHERE kf.useful IS FALSE OR kf.rating IN ('down', 'needs_more_context', 'wrong_source')
                    ) AS negative_feedback_count
                FROM knowledge_retrieval_events kre
                LEFT JOIN knowledge_feedback kf ON kf.retrieval_id = kre.id
                WHERE COALESCE(kre.metadata->>'tenant_id', 'public') IN ('public', %s)
                GROUP BY kre.id
                ORDER BY negative_feedback_count DESC, feedback_count ASC, kre.created_at DESC
                LIMIT %s;
                """,
                (tenant_id, limit),
            )
            annotation_queue = [dict(row) for row in cur.fetchall()]
            cur.execute(
                """
                SELECT
                    COALESCE(kre.metadata->>'experiment_arm', 'unknown') AS arm,
                    COUNT(kf.id) AS feedback_count,
                    COUNT(kf.id) FILTER (WHERE kf.useful IS TRUE OR kf.rating = 'up') AS positive_count,
                    COUNT(kf.id) FILTER (
                        WHERE kf.useful IS FALSE OR kf.rating IN ('down', 'needs_more_context', 'wrong_source')
                    ) AS negative_count
                FROM knowledge_feedback kf
                LEFT JOIN knowledge_retrieval_events kre ON kre.id = kf.retrieval_id
                WHERE COALESCE(kre.metadata->>'tenant_id', 'public') IN ('public', %s)
                GROUP BY COALESCE(kre.metadata->>'experiment_arm', 'unknown')
                ORDER BY feedback_count DESC, arm ASC;
                """,
                (tenant_id,),
            )
            feedback_by_arm = [dict(row) for row in cur.fetchall()]

        return {
            "status": "SUCCESS",
            "tenant_id": tenant_id,
            "summary": summary,
            "by_experiment": by_experiment,
            "feedback_by_arm": feedback_by_arm,
            "annotation_queue": annotation_queue,
        }
    except Exception as exc:
        logger.error("Knowledge observability failed: %s", exc)
        return {"status": "ERROR", "error": str(exc)}
    finally:
        conn.close()
