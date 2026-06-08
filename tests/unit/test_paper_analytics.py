import sqlite3

from intelligence.ml import paper_analytics


def test_normalize_symbol_and_bucket_metrics_cover_edge_cases():
    assert paper_analytics._normalize_symbol(" btcusdt ") == "BTC"
    assert paper_analytics._normalize_symbol(None) == ""

    rows = [
        {"pnl_usd": 2.0, "outcome": None, "symbol": "BTCUSDT", "side": "buy", "entry_source": ""},
        {"pnl_usd": -1.0, "outcome": None, "symbol": "BTCUSDT", "side": "buy", "entry_source": ""},
        {"pnl_usd": 0.0, "outcome": "LOSS", "symbol": "ETHUSD", "side": "", "entry_source": None},
    ]
    buckets = paper_analytics._bucket_metrics(rows, lambda row: row["symbol"])

    assert buckets[0]["key"] == "BTCUSDT"
    assert buckets[0]["win_rate"] == 0.5
    assert buckets[0]["profit_factor"] == 2.0
    assert buckets[1]["profit_factor"] == 0.0


def test_build_side_scorecard_returns_weak_slices(tmp_path, monkeypatch):
    db_path = tmp_path / "paper.db"
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            CREATE TABLE paper_trades (
                symbol TEXT,
                side TEXT,
                entry_source TEXT,
                pnl_usd REAL,
                outcome TEXT,
                status TEXT,
                opened_at TEXT,
                closed_at TEXT
            )
            """
        )
        con.executemany(
            """
            INSERT INTO paper_trades
            (symbol, side, entry_source, pnl_usd, outcome, status, opened_at, closed_at)
            VALUES (?, ?, ?, ?, ?, 'CLOSED', '2026-01-01', '2026-01-01')
            """,
            [
                ("ETHUSD", "SELL", "auto_paper", -1.0, "LOSS"),
                ("ETHUSD", "SELL", "auto_paper", -0.8, "LOSS"),
                ("ETHUSD", "SELL", "auto_paper", -0.7, "LOSS"),
                ("ETHUSD", "BUY", "auto_paper", 1.2, "WIN"),
                ("ETHUSD", "BUY", "auto_paper", 0.8, "WIN"),
            ],
        )

    monkeypatch.setattr(paper_analytics, "PAPER_DB", str(db_path))
    payload = paper_analytics.build_side_scorecard(limit=10)

    assert payload["available"] is True
    assert any(row["key"] == "ETHUSD:SELL" for row in payload["weak_slices"])


def test_build_side_scorecard_handles_db_error_and_limiting(tmp_path, monkeypatch):
    monkeypatch.setattr(paper_analytics, "PAPER_DB", str(tmp_path / "missing.db"))
    payload = paper_analytics.build_side_scorecard(limit=5)

    assert payload["available"] is False
    assert payload["side"] == []
    assert payload["symbol_side"] == []
    assert payload["source_side"] == []
    assert payload["weak_slices"] == []

    db_path = tmp_path / "paper.db"
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            CREATE TABLE paper_trades (
                symbol TEXT,
                side TEXT,
                entry_source TEXT,
                pnl_usd REAL,
                outcome TEXT,
                status TEXT,
                opened_at TEXT,
                closed_at TEXT
            )
            """
        )
        con.executemany(
            """
            INSERT INTO paper_trades
            (symbol, side, entry_source, pnl_usd, outcome, status, opened_at, closed_at)
            VALUES (?, ?, ?, ?, ?, 'CLOSED', '2026-01-01', '2026-01-01')
            """,
            [
                ("BTCUSDT", "BUY", "", 2.0, None),
                ("BTCUSDT", "BUY", "", -1.0, None),
                ("ETHUSD", "", None, 0.0, "LOSS"),
            ],
        )

    monkeypatch.setattr(paper_analytics, "PAPER_DB", str(db_path))
    payload = paper_analytics.build_side_scorecard(limit=1)

    assert payload["available"] is True
    assert len(payload["side"]) == 1
    assert len(payload["symbol_side"]) == 1
    assert len(payload["source_side"]) == 1
