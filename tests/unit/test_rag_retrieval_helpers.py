import json

import pytest

from intelligence.rag import retrieval


def _row(source, idx, score=0.1, title="RAG Runbook", content="rag retrieval latency cost", source_type="runbook"):
    return {
        "source_uri": source,
        "title": title,
        "source_type": source_type,
        "chunk_index": idx,
        "content": content,
        "metadata": {"relative_path": f"docs/{source}.md"},
        "token_estimate": 10,
        "score": score,
        "similarity": score,
        "search_type": "keyword",
    }


def test_retrieval_helper_estimates_json_and_vector_values():
    assert retrieval._jsonb({"b": 2, "a": 1}) == '{"a": 1, "b": 2}'
    assert retrieval._jsonb(None) == "{}"
    assert retrieval._estimate_tokens("") == 1
    assert retrieval._estimate_tokens("abcd" * 5) == 5
    assert retrieval._estimate_embedding_cost(2500) > 0


def test_split_long_paragraph_and_chunk_validation():
    paragraph = "Sentence one. " * 80
    chunks = retrieval._split_long_paragraph(paragraph, chunk_chars=120, overlap=20)

    assert len(chunks) > 2
    assert all(chunk for chunk in chunks)

    with pytest.raises(ValueError):
        retrieval.chunk_text("x", chunk_chars=0)
    with pytest.raises(ValueError):
        retrieval.chunk_text("x", chunk_chars=10, overlap=10)
    assert retrieval.chunk_text("   ") == []


def test_query_terms_expansion_and_experiment_assignment():
    terms = retrieval._keyword_terms("How does RAG latency and MT5 permissions work?")
    expanded = retrieval._expand_query_for_retrieval("RAG latency MT5")
    arm = retrieval._assign_experiment_arm("query", "tenant", "exp", None)

    assert "rag" in terms
    assert "latency" in terms
    assert "retrieval augmented generation" in expanded
    assert "metatrader5" in expanded
    assert retrieval._assign_experiment_arm("q", "t", "e", "baseline") == "baseline"
    assert arm in {"baseline", "hybrid_rerank"}


def test_merge_keyword_rows_deduplicates_and_boosts_overlap():
    text_rows = [_row("a", 0, score=0.3), _row("b", 0, score=0.2)]
    substring_rows = [_row("a", 0, score=0.4), _row("c", 0, score=0.1)]

    merged = retrieval._merge_keyword_rows(text_rows, substring_rows, limit=3)

    assert [row["source_uri"] for row in merged] == ["a", "b", "c"]
    assert merged[0]["search_type"] == "keyword_hybrid"
    assert merged[0]["score"] == pytest.approx(0.45)


def test_merge_hybrid_rows_combines_vector_and_keyword_rankings():
    vector_rows = [_row("a", 0, score=0.8), _row("b", 0, score=0.7)]
    keyword_rows = [_row("b", 0, score=0.6), _row("c", 0, score=0.5)]

    merged = retrieval._merge_hybrid_rows(vector_rows, keyword_rows, limit=3)
    by_source = {row["source_uri"]: row for row in merged}

    assert set(by_source) == {"a", "b", "c"}
    assert by_source["b"]["search_type"] == "hybrid"
    assert by_source["b"]["vector_rank"] == 2
    assert by_source["b"]["keyword_rank"] == 1
    assert by_source["c"]["vector_rank"] is None


def test_rerank_and_diversify_rows_prioritize_terms_and_limit_documents():
    rows = [
        _row("doc1", 0, score=0.1, title="Code file", content="python helper", source_type="code_py"),
        _row("doc1", 1, score=0.2, title="RAG latency guide", content="rag latency p95 cost", source_type="project_guide"),
        _row("doc1", 2, score=0.3, title="RAG cost", content="cost tokens", source_type="rag_corpus"),
        _row("doc2", 0, score=0.05, title="RAG runbook", content="retrieval feedback", source_type="runbook"),
    ]

    reranked = retrieval._rerank_rows("rag latency cost", rows, limit=3)
    diversified = retrieval._diversify_rows(rows, limit=3, max_per_document=1)

    assert reranked[0]["reranker_model"] == "local_cross_signal_v2"
    assert reranked[0]["rerank_score"] >= reranked[-1]["rerank_score"]
    assert [row["source_uri"] for row in diversified] == ["doc1", "doc2", "doc1"]


def test_apply_filters_adds_source_and_tenant_constraints():
    filters = []
    params = []

    retrieval._apply_retrieval_filters(filters, params, source_type="runbook", tenant_id="team-a")

    assert filters[0] == "kd.source_type = %s"
    assert "tenant_id" in filters[1]
    assert params == ["runbook", "team-a"]


def test_extract_file_text_for_text_and_unsupported_suffix(tmp_path):
    text_file = tmp_path / "note.md"
    text_file.write_text("hello knowledge", encoding="utf-8")
    unsupported = tmp_path / "image.bin"
    unsupported.write_bytes(b"x")

    assert retrieval._extract_file_text(text_file) == "hello knowledge"
    with pytest.raises(ValueError, match="Unsupported knowledge file type"):
        retrieval._extract_file_text(unsupported)


class FakeCursor:
    def __init__(self, rows=None, fail=False):
        self.rows = rows or []
        self.fail = fail
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if self.fail:
            raise RuntimeError("db down")

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        rows, self.rows = self.rows, []
        return rows


class FakeConn:
    def __init__(self, cursor):
        self.cursor_obj = cursor
        self.commits = 0
        self.rollbacks = 0

    def cursor(self, *args, **kwargs):
        return self.cursor_obj

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_record_retrieval_event_success_and_failure():
    snippet = {"citation": "Doc#0", "search_type": "keyword", "source_type": "runbook"}
    ok_conn = FakeConn(FakeCursor())
    fail_conn = FakeConn(FakeCursor(fail=True))

    retrieval._record_retrieval_event(
        ok_conn,
        "00000000-0000-0000-0000-000000000001",
        "rag",
        "runbook",
        [snippet],
        {"tenant_id": "public"},
    )
    retrieval._record_retrieval_event(fail_conn, "id", "rag", None, [snippet], {})

    assert ok_conn.commits == 1
    sql, params = ok_conn.cursor_obj.executed[0]
    assert "knowledge_retrieval_events" in sql
    assert json.loads(params[4]) == ["Doc#0"]
    assert fail_conn.rollbacks == 1
