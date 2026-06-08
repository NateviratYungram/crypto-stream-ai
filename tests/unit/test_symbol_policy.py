import sqlite3

from intelligence.ml import performance_feedback, symbol_policy


def test_policy_helpers_parse_overrides_and_cache(monkeypatch):
    assert symbol_policy._normalize_symbol("ethusdt") == "ETH"
    assert symbol_policy._normalize_side("sell") == "SELL"
    assert symbol_policy._parse_block_overrides(" ethusdt:sell , bad , BTCUSD:BUY ") == {
        ("ETH", "SELL"),
        ("BTCUSD", "BUY"),
    }
    assert symbol_policy._parse_block_overrides(":SELL, ETHUSD:") == set()
    assert symbol_policy._parse_reduce_overrides("ETHUSD:BUY:0.4, XRPUSDT:SELL:1.5, bad, SOLUSD:BUY:nope") == {
        ("ETHUSD", "BUY"): 0.4,
        ("XRP", "SELL"): 1.0,
    }
    assert symbol_policy._parse_reduce_overrides(":SELL:0.5, ETHUSD::0.5") == {}

    symbol_policy._policy_cache["loaded_at"] = 100.0
    symbol_policy._policy_cache["payload"] = {"cached": True}
    monkeypatch.setattr(symbol_policy.time, "time", lambda: 120.0)

    assert symbol_policy.get_symbol_policy_snapshot() == {"cached": True}


def test_symbol_policy_blocks_weak_side_and_reduces_borderline_side(tmp_path, monkeypatch):
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
                ("ETHUSD", "SELL", "signal_feed_analysis", -1.0, "LOSS"),
                ("ETHUSD", "SELL", "signal_feed_analysis", -0.8, "LOSS"),
                ("ETHUSD", "SELL", "signal_feed_analysis", -0.9, "LOSS"),
                ("BTCUSD", "BUY", "signal_feed_analysis", 0.3, "WIN"),
                ("BTCUSD", "BUY", "signal_feed_analysis", 0.2, "WIN"),
                ("BTCUSD", "BUY", "signal_feed_analysis", -0.8, "LOSS"),
            ],
        )

    monkeypatch.setattr(performance_feedback, "PAPER_DB", str(db_path))
    monkeypatch.setattr(symbol_policy, "_POLICY_DB", str(db_path))
    performance_feedback._feedback_cache["loaded_at"] = 0.0
    performance_feedback._feedback_cache["payload"] = None
    symbol_policy._policy_cache["loaded_at"] = 0.0
    symbol_policy._policy_cache["payload"] = None

    snapshot = symbol_policy.get_symbol_policy_snapshot(force_refresh=True)
    rows = {row["key"]: row for row in snapshot["rows"]}

    assert rows["ETHUSD:SELL"]["action"] == "block"
    assert rows["BTCUSD:BUY"]["action"] == "reduce"


def test_symbol_policy_snapshot_honors_manual_env_and_db_overrides(tmp_path, monkeypatch):
    db_path = tmp_path / "paper.db"
    monkeypatch.setattr(symbol_policy, "_POLICY_DB", str(db_path))
    monkeypatch.setattr(
        symbol_policy,
        "get_feedback_snapshot",
        lambda force_refresh=False: {
            "symbol_side": {
                "ETHUSD:SELL": {"trades": 5, "win_rate": 20.0, "pnl": -4.0, "avg_pnl": -0.8},
                "BTCUSD:BUY": {"trades": 4, "win_rate": 40.0, "pnl": -0.4, "avg_pnl": -0.1},
                "XRPUSDT:BUY": {"trades": 4, "win_rate": 70.0, "pnl": 3.0, "avg_pnl": 0.75},
            }
        },
    )
    monkeypatch.setattr(symbol_policy.os, "getenv", lambda key, default=None: {
        "ML_SYMBOL_SIDE_BLOCKLIST": "BTCUSD:BUY",
        "ML_SYMBOL_SIDE_REDUCE": "ETHUSD:SELL:0.3",
    }.get(key, default))
    symbol_policy._policy_cache["loaded_at"] = 0.0
    symbol_policy._policy_cache["payload"] = None

    symbol_policy.upsert_symbol_policy_override("xrpusdt", "buy", "reduce", size_multiplier=0.25, note="manual trim")
    snapshot = symbol_policy.get_symbol_policy_snapshot(force_refresh=True)
    rows = {row["key"]: row for row in snapshot["rows"]}

    assert rows["BTCUSD:BUY"]["action"] == "block"
    assert rows["BTCUSD:BUY"]["reasons"] == ["manual_block_override"]
    assert rows["ETHUSD:SELL"]["action"] == "reduce"
    assert rows["ETHUSD:SELL"]["size_multiplier"] == 0.3
    assert rows["XRP:BUY"]["action"] == "reduce"
    assert rows["XRP:BUY"]["size_multiplier"] == 0.25
    assert rows["XRP:BUY"]["note"] == "manual trim"
    assert snapshot["summary"]["manual_block_overrides"] == 1
    assert snapshot["summary"]["manual_reduce_overrides"] == 2


def test_db_overrides_handles_invalid_reduce_multiplier(tmp_path, monkeypatch):
    db_path = tmp_path / "paper.db"
    monkeypatch.setattr(symbol_policy, "_POLICY_DB", str(db_path))
    symbol_policy._policy_cache["loaded_at"] = 0.0
    symbol_policy._policy_cache["payload"] = None

    with symbol_policy._connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ml_symbol_policy_overrides (
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                action TEXT NOT NULL,
                size_multiplier REAL,
                note TEXT,
                updated_at TEXT,
                PRIMARY KEY(symbol, side)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO ml_symbol_policy_overrides (symbol, side, action, size_multiplier, note, updated_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            """,
            ("ETHUSD", "SELL", "reduce", "bad", "fallback"),
        )
        conn.commit()

    _blocks, reduce_pairs, notes = symbol_policy._db_overrides()

    assert reduce_pairs[("ETHUSD", "SELL")] == 0.5
    assert notes[("ETHUSD", "SELL")] == "fallback"


def test_db_overrides_ignores_allow_rows_without_notes(tmp_path, monkeypatch):
    db_path = tmp_path / "paper.db"
    monkeypatch.setattr(symbol_policy, "_POLICY_DB", str(db_path))

    with symbol_policy._connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ml_symbol_policy_overrides (
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                action TEXT NOT NULL,
                size_multiplier REAL,
                note TEXT,
                updated_at TEXT,
                PRIMARY KEY(symbol, side)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO ml_symbol_policy_overrides (symbol, side, action, size_multiplier, note, updated_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            """,
            ("BTCUSD", "BUY", "allow", 1.0, ""),
        )
        conn.commit()

    block_pairs, reduce_pairs, notes = symbol_policy._db_overrides()

    assert block_pairs == set()
    assert reduce_pairs == {}
    assert notes == {}
