from intelligence.rag.retrieval import (
    _content_hash,
    _vector_literal,
    chunk_text,
    normalize_text,
)


def test_normalize_text_preserves_paragraph_breaks():
    text = "Alpha   beta\r\n\r\n\r\nGamma\t delta"

    assert normalize_text(text) == "Alpha beta\n\nGamma delta"


def test_chunk_text_splits_long_content_with_overlap():
    text = "\n\n".join(
        [
            "A" * 120,
            "B" * 120,
            "C" * 120,
        ]
    )

    chunks = chunk_text(text, chunk_chars=180, overlap=20)

    assert len(chunks) >= 2
    assert all(len(chunk) <= 220 for chunk in chunks)
    assert chunks[0].startswith("A")
    assert "C" in chunks[-1]


def test_content_hash_is_stable():
    assert _content_hash("same document") == _content_hash("same document")
    assert _content_hash("same document") != _content_hash("different document")


def test_vector_literal_formats_pgvector_value():
    assert _vector_literal([0.1, -2, 3.1415926535]) == "[0.10000000,-2.00000000,3.14159265]"
    assert _vector_literal(None) is None
