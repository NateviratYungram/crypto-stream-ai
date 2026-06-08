import sqlite3

from intelligence.ml import performance_feedback


def test_helper_functions_and_empty_payload(monkeypatch):
    row = {"outcome": None, "pnl_usd": -2.5}

    assert performance_feedback._normalize_symbol("ethusdt") == "ETH"
    assert performance_feedback._split_symbol_side("ethusdt:sell") == ("ETH", "SELL")
    assert performance_feedback._safe_outcome(row) == "LOSS"

    monkeypatch.setattr(
        performance_feedback.sqlite3,
        "connect",
        lambda path: (_ for _ in ()).throw(sqlite3.OperationalError("db down")),
    )

    payload = performance_feedback._build_payload()

    assert payload == {
        "strategy": {},
        "symbol": {},
        "symbol_side": {},
        "recommendations": [],
    }


def test_get_feedback_snapshot_uses_cache(monkeypatch):
    performance_feedback._feedback_cache["loaded_at"] = 100.0
    performance_feedback._feedback_cache["payload"] = {"cached": True}
    monkeypatch.setattr(performance_feedback.time, "time", lambda: 120.0)

    assert performance_feedback.get_feedback_snapshot() == {"cached": True}


def test_score_signal_feedback_uses_explicit_side(tmp_path, monkeypatch):
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
                ("ETHUSD", "SELL", "signal_feed_analysis", -2.0, "LOSS"),
                ("ETHUSD", "SELL", "signal_feed_analysis", -3.0, "LOSS"),
                ("ETHUSD", "BUY", "signal_feed_analysis", 4.0, "WIN"),
                ("ETHUSD", "BUY", "signal_feed_analysis", 5.0, "WIN"),
            ],
        )

    monkeypatch.setattr(performance_feedback, "PAPER_DB", str(db_path))
    performance_feedback._feedback_cache["loaded_at"] = 0.0
    performance_feedback._feedback_cache["payload"] = None

    result = performance_feedback.score_signal_feedback("ETHUSD", side="SELL")

    assert result["side"] == "SELL"
    assert result["symbol_side_stats"]["trades"] == 3
    assert result["readiness"]["symbol_side_evaluable"] is True
    assert result["readiness"]["symbol_side_ready"] is False
    assert any("symbol-side drag" in note for note in result["notes"])


def test_score_signal_feedback_rewards_positive_tailwinds(monkeypatch):
    monkeypatch.setattr(
        performance_feedback,
        "get_feedback_snapshot",
        lambda force_refresh=False: {
            "strategy": {
                "signal_feed_analysis": {"trades": 8, "wins": 5, "pnl": 12.0, "win_rate": 62.5, "avg_pnl": 1.5},
            },
            "symbol": {
                "ETH": {"trades": 4, "wins": 3, "pnl": 8.0, "win_rate": 75.0, "avg_pnl": 2.0},
            },
            "symbol_side": {
                "ETH:BUY": {"trades": 3, "wins": 2, "pnl": 3.0, "win_rate": 66.7, "avg_pnl": 1.0},
            },
        },
    )

    result = performance_feedback.score_signal_feedback("ETHUSDT:BUY")

    assert result["symbol"] == "ETH"
    assert result["side"] == "BUY"
    assert result["probability_adjustment"] > 0
    assert any("source tailwind" in note for note in result["notes"])
    assert any("symbol strength" in note for note in result["notes"])
    assert any("symbol-side strength" in note for note in result["notes"])


def test_paper_entry_performance_gate_blocks_weak_symbol_side(tmp_path, monkeypatch):
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
                ("XRPUSDT", "BUY", "signal_feed_analysis", -1.5, "LOSS"),
                ("XRPUSDT", "BUY", "signal_feed_analysis", -1.2, "LOSS"),
                ("XRPUSDT", "BUY", "signal_feed_analysis", -0.9, "LOSS"),
                ("XRPUSDT", "BUY", "signal_feed_analysis", -1.1, "LOSS"),
                ("XRPUSDT", "BUY", "signal_feed_analysis", -0.8, "LOSS"),
            ],
        )

    monkeypatch.setattr(performance_feedback, "PAPER_DB", str(db_path))
    performance_feedback._feedback_cache["loaded_at"] = 0.0
    performance_feedback._feedback_cache["payload"] = None

    result = performance_feedback.paper_entry_performance_gate("XRPUSDT", "BUY", "signal_feed_analysis")

    assert result["ok"] is False
    assert result["blockers"]


def test_paper_training_label_gate_keeps_high_win_rate_small_negative_slice(tmp_path, monkeypatch):
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
                ("ETHUSD", "BUY", "signal_feed_analysis", 1.2, "WIN"),
                ("ETHUSD", "BUY", "signal_feed_analysis", 1.1, "WIN"),
                ("ETHUSD", "BUY", "signal_feed_analysis", 0.9, "WIN"),
                ("ETHUSD", "BUY", "signal_feed_analysis", 1.0, "WIN"),
                ("ETHUSD", "BUY", "signal_feed_analysis", -4.3, "LOSS"),
            ],
        )

    monkeypatch.setattr(performance_feedback, "PAPER_DB", str(db_path))
    performance_feedback._feedback_cache["loaded_at"] = 0.0
    performance_feedback._feedback_cache["payload"] = None

    training_gate = performance_feedback.paper_training_label_gate("ETHUSD", "BUY", "signal_feed_analysis")
    execution_gate = performance_feedback.paper_entry_performance_gate("ETHUSD", "BUY", "signal_feed_analysis")

    assert training_gate["ok"] is True
    assert training_gate["mode"] == "training"
    assert execution_gate["ok"] is False
    assert execution_gate["blockers"]


def test_paper_performance_gates_emit_warnings_and_training_blockers(monkeypatch):
    snapshot = {
        "strategy": {
            "signal_feed_analysis": {"trades": 12, "wins": 5, "pnl": 5.0, "win_rate": 41.7, "avg_pnl": 0.4},
            "manual_ui": {"trades": 12, "wins": 2, "pnl": -4.0, "win_rate": 16.7, "avg_pnl": -0.4},
        },
        "symbol": {
            "ETH": {"trades": 5, "wins": 2, "pnl": 3.0, "win_rate": 40.0, "avg_pnl": 0.6},
            "XRP": {"trades": 5, "wins": 1, "pnl": -2.0, "win_rate": 20.0, "avg_pnl": -0.4},
        },
        "symbol_side": {
            "ETH:BUY": {"trades": 3, "wins": 1, "pnl": 1.0, "win_rate": 33.3, "avg_pnl": 0.3},
            "XRP:SELL": {"trades": 3, "wins": 0, "pnl": -1.0, "win_rate": 0.0, "avg_pnl": -0.4},
        },
    }
    monkeypatch.setattr(performance_feedback, "get_feedback_snapshot", lambda force_refresh=False: snapshot)

    execution_gate = performance_feedback.paper_entry_performance_gate("ETHUSD", "BUY", "signal_feed_analysis")
    training_gate = performance_feedback.paper_training_label_gate("XRPUSD", "SELL", "manual_ui")

    assert execution_gate["ok"] is True
    assert execution_gate["warnings"]
    assert training_gate["ok"] is False
    assert training_gate["blockers"]
    assert training_gate["warnings"] == []


def test_score_signal_feedback_neutral_threshold_paths(monkeypatch):
    monkeypatch.setattr(
        performance_feedback,
        "get_feedback_snapshot",
        lambda force_refresh=False: {
            "strategy": {
                "signal_feed_analysis": {"trades": 5, "wins": 2, "pnl": 0.0, "win_rate": 50.0, "avg_pnl": 0.0},
            },
            "symbol": {
                "ETHUSD": {"trades": 3, "wins": 1, "pnl": 0.0, "win_rate": 50.0, "avg_pnl": 0.0},
            },
            "symbol_side": {
                "ETHUSD:SELL": {"trades": 3, "wins": 1, "pnl": 0.0, "win_rate": 50.0, "avg_pnl": 0.0},
            },
        },
    )

    result = performance_feedback.score_signal_feedback("ETHUSD", side="SELL")

    assert result["probability_adjustment"] == 0.0
    assert result["notes"] == []
    assert result["readiness"]["source_ready"] is False
    assert result["readiness"]["symbol_ready"] is False
    assert result["readiness"]["symbol_side_ready"] is True


def test_score_signal_feedback_below_threshold_skips_adjustments(monkeypatch):
    monkeypatch.setattr(
        performance_feedback,
        "get_feedback_snapshot",
        lambda force_refresh=False: {
            "strategy": {
                "signal_feed_analysis": {"trades": 4, "wins": 2, "pnl": 3.0, "win_rate": 50.0, "avg_pnl": 0.75},
            },
            "symbol": {
                "BTCUSD": {"trades": 2, "wins": 1, "pnl": 2.0, "win_rate": 50.0, "avg_pnl": 1.0},
            },
            "symbol_side": {
                "BTCUSD:BUY": {"trades": 2, "wins": 1, "pnl": 2.0, "win_rate": 50.0, "avg_pnl": 1.0},
            },
        },
    )

    result = performance_feedback.score_signal_feedback("BTCUSD", side="BUY")

    assert result["probability_adjustment"] == 0.0
    assert result["notes"] == []
    assert result["readiness"] == {
        "source_ready": False,
        "symbol_ready": False,
        "symbol_side_ready": False,
        "symbol_side_evaluable": False,
    }


def test_paper_performance_gates_allow_neutral_stats_without_warnings(monkeypatch):
    snapshot = {
        "strategy": {
            "signal_feed_analysis": {"trades": 12, "wins": 6, "pnl": 1.0, "win_rate": 50.0, "avg_pnl": 0.1},
            "manual_ui": {"trades": 12, "wins": 5, "pnl": 0.5, "win_rate": 45.0, "avg_pnl": 0.05},
        },
        "symbol": {
            "ETHUSD": {"trades": 5, "wins": 2, "pnl": 1.0, "win_rate": 50.0, "avg_pnl": 0.1},
            "XRPUSD": {"trades": 5, "wins": 2, "pnl": 0.5, "win_rate": 45.0, "avg_pnl": 0.05},
        },
        "symbol_side": {
            "ETHUSD:BUY": {"trades": 3, "wins": 2, "pnl": 1.0, "win_rate": 50.0, "avg_pnl": 0.1},
            "XRPUSD:SELL": {"trades": 3, "wins": 2, "pnl": 0.5, "win_rate": 45.0, "avg_pnl": 0.05},
        },
    }
    monkeypatch.setattr(performance_feedback, "get_feedback_snapshot", lambda force_refresh=False: snapshot)

    execution_gate = performance_feedback.paper_entry_performance_gate("ETHUSD", "BUY", "signal_feed_analysis")
    training_gate = performance_feedback.paper_training_label_gate("XRPUSD", "SELL", "manual_ui")

    assert execution_gate["ok"] is True
    assert execution_gate["warnings"] == []
    assert execution_gate["blockers"] == []
    assert training_gate["ok"] is True
    assert training_gate["warnings"] == []
    assert training_gate["blockers"] == []
