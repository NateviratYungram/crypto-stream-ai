import sqlite3
from types import ModuleType

from intelligence.ml import outcome_tracker


def seed_db(tmp_path):
    db_path = tmp_path / "paper.db"
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            CREATE TABLE paper_trades (
                id TEXT PRIMARY KEY,
                symbol TEXT,
                side TEXT,
                volume REAL,
                entry_price REAL,
                current_price REAL,
                pnl_usd REAL,
                status TEXT,
                opened_at TEXT,
                closed_at TEXT
            )
            """
        )
        con.commit()
    return db_path


def test_resolve_asset_class_and_outcome_rules():
    assert outcome_tracker._resolve_asset_class("BTCUSD") == "CRYPTO"
    assert outcome_tracker._resolve_asset_class("GOLD") == "MACRO"
    assert outcome_tracker._evaluate_trade_outcome("BUY", 95.0, 96.0, 110.0) == ("LOSS", "SL hit @ 95.0")
    assert outcome_tracker._evaluate_trade_outcome("BUY", 111.0, 96.0, 110.0) == ("WIN", "TP hit @ 111.0")
    assert outcome_tracker._evaluate_trade_outcome("SELL", 111.0, 110.0, 95.0) == ("LOSS", "SL hit @ 111.0")
    assert outcome_tracker._evaluate_trade_outcome("SELL", 94.0, 110.0, 95.0) == ("WIN", "TP hit @ 94.0")
    assert outcome_tracker._evaluate_trade_outcome("SELL", 100.0, 110.0, 95.0) == (None, "")
    assert outcome_tracker._evaluate_trade_outcome("SELL", 100.0, None, None) == (None, "")
    assert outcome_tracker._evaluate_trade_outcome("HOLD", 100.0, 110.0, 95.0) == (None, "")
    assert outcome_tracker._evaluate_trade_outcome("BUY", 100.0, None, None) == (None, "")


def test_refresh_policy_caches_calls_both_refreshers(monkeypatch):
    called = []

    threshold_module = ModuleType("intelligence.ml.symbol_threshold")
    threshold_module.refresh_threshold_cache = lambda: called.append("threshold")
    policy_module = ModuleType("intelligence.ml.symbol_policy")
    policy_module.refresh_symbol_policy_cache = lambda: called.append("policy")

    monkeypatch.setitem(
        __import__("sys").modules,
        "intelligence.ml.symbol_threshold",
        threshold_module,
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "intelligence.ml.symbol_policy",
        policy_module,
    )

    outcome_tracker._refresh_policy_caches()

    assert called == ["threshold", "policy"]


def test_migrate_schema_adds_columns(tmp_path, monkeypatch):
    db_path = seed_db(tmp_path)
    monkeypatch.setattr(outcome_tracker, "PAPER_DB", str(db_path))

    outcome_tracker.migrate_schema()

    with sqlite3.connect(db_path) as con:
        cols = {row[1] for row in con.execute("PRAGMA table_info(paper_trades)").fetchall()}
    assert {"sl", "tp", "exit_price", "outcome", "features_json", "ml_score", "close_reason", "label_source", "signal_grade", "macro_bias"}.issubset(cols)


def test_get_open_trades_and_attach_features(tmp_path, monkeypatch):
    db_path = seed_db(tmp_path)
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            INSERT INTO paper_trades (id, symbol, side, volume, entry_price, current_price, pnl_usd, status, opened_at, closed_at)
            VALUES ('t1', 'BTCUSD', 'BUY', 1, 100, 100, 0, 'OPEN', '2026-01-01', NULL)
            """
        )
    monkeypatch.setattr(outcome_tracker, "PAPER_DB", str(db_path))

    outcome_tracker.attach_sl_tp_features("t1", 95.0, 105.0, {"rsi": 50}, ml_score=0.7, signal_grade="A", macro_bias="BULL")
    trades = outcome_tracker.get_open_trades()

    assert len(trades) == 1
    assert trades[0]["sl"] == 95.0
    assert trades[0]["tp"] == 105.0
    assert trades[0]["features_json"] == '{"rsi": 50}'


def test_close_trade_updates_status_and_pnl(tmp_path, monkeypatch):
    db_path = seed_db(tmp_path)
    monkeypatch.setattr(outcome_tracker, "PAPER_DB", str(db_path))
    with sqlite3.connect(db_path) as con:
        con.execute("ALTER TABLE paper_trades ADD COLUMN sl REAL")
        con.execute("ALTER TABLE paper_trades ADD COLUMN tp REAL")
        con.execute("ALTER TABLE paper_trades ADD COLUMN exit_price REAL")
        con.execute("ALTER TABLE paper_trades ADD COLUMN outcome TEXT")
        con.execute("ALTER TABLE paper_trades ADD COLUMN close_reason TEXT")
        con.execute("ALTER TABLE paper_trades ADD COLUMN label_source TEXT")
        con.execute(
            """
            INSERT INTO paper_trades (id, symbol, side, volume, entry_price, current_price, pnl_usd, status, opened_at, closed_at, sl, tp)
            VALUES ('t1', 'BTCUSD', 'BUY', 2, 100, 100, 0, 'OPEN', '2026-01-01', NULL, 95, 105)
            """
        )

    outcome_tracker._close_trade("t1", 106.0, "WIN", "TP hit")

    with sqlite3.connect(db_path) as con:
        row = con.execute("SELECT status, outcome, exit_price, close_reason, label_source, pnl_usd FROM paper_trades WHERE id='t1'").fetchone()
    assert row == ("CLOSED", "WIN", 106.0, "TP hit", "auto_tracker", 12.0)


def test_scan_and_update_closes_trades_and_refreshes_caches(monkeypatch):
    monkeypatch.setattr(
        outcome_tracker,
        "get_open_trades",
        lambda: [
            {"id": "w1", "symbol": "BTCUSD", "side": "BUY", "sl": 95.0, "tp": 105.0},
            {"id": "l1", "symbol": "ETHUSD", "side": "SELL", "sl": 110.0, "tp": 90.0},
            {"id": "n1", "symbol": "GOLD", "side": "BUY", "sl": None, "tp": None},
            {"id": "e1", "symbol": "SOLUSD", "side": "BUY", "sl": 95.0, "tp": 105.0},
        ],
    )
    monkeypatch.setattr(outcome_tracker, "migrate_schema", lambda: None)
    prices = {"BTCUSD": 106.0, "ETHUSD": 111.0, "SOLUSD": None}
    closed = []
    refreshed = {"count": 0}

    summary = outcome_tracker.scan_and_update(
        fetch_price=lambda symbol: prices[symbol],
        close_trade=lambda *args: closed.append(args),
        refresh_caches=False,
    )

    assert summary["scanned"] == 4
    assert summary["closed_win"] == 1
    assert summary["closed_loss"] == 1
    assert summary["errors"] == 1
    assert len(closed) == 2
    assert any(item["trade_id"] == "w1" for item in summary["closed_trades"])
    assert refreshed["count"] == 0


def test_scan_and_update_skips_trade_when_outcome_not_hit(monkeypatch):
    monkeypatch.setattr(outcome_tracker, "migrate_schema", lambda: None)
    monkeypatch.setattr(
        outcome_tracker,
        "get_open_trades",
        lambda: [{"id": "hold", "symbol": "BTCUSD", "side": "SELL", "sl": 110.0, "tp": 95.0}],
    )
    closed = []

    summary = outcome_tracker.scan_and_update(
        fetch_price=lambda symbol: 100.0,
        close_trade=lambda *args: closed.append(args),
        refresh_caches=False,
    )

    assert summary["scanned"] == 1
    assert summary["closed_win"] == 0
    assert summary["closed_loss"] == 0
    assert summary["closed_trades"] == []
    assert closed == []


def test_scan_and_update_refresh_failure_is_swallowed(monkeypatch):
    monkeypatch.setattr(outcome_tracker, "migrate_schema", lambda: None)
    monkeypatch.setattr(outcome_tracker, "get_open_trades", lambda: [{"id": "w1", "symbol": "BTCUSD", "side": "BUY", "sl": 95.0, "tp": 105.0}])
    monkeypatch.setattr(outcome_tracker, "_refresh_policy_caches", lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    summary = outcome_tracker.scan_and_update(fetch_price=lambda symbol: 106.0, close_trade=lambda *args: None, refresh_caches=True)

    assert summary["closed_win"] == 1


def test_fetch_price_uses_technical_engine_and_handles_errors(monkeypatch):
    class FakeSeries:
        @property
        def iloc(self):
            return [100.0, 101.5]

    class FakeFrame:
        empty = False

        def __getitem__(self, key):
            assert key == "Close"
            return FakeSeries()

    monkeypatch.setitem(__import__("sys").modules, "intelligence.technical_engine", type("FakeModule", (), {"get_kline_data": lambda *args, **kwargs: FakeFrame()})())
    assert outcome_tracker._fetch_price("BTCUSD") == 101.5

    class EmptyFrame:
        empty = True

        def __getitem__(self, key):
            raise AssertionError("empty frame should not index Close")

    monkeypatch.setitem(__import__("sys").modules, "intelligence.technical_engine", type("EmptyModule", (), {"get_kline_data": lambda *args, **kwargs: EmptyFrame()})())
    assert outcome_tracker._fetch_price("BTCUSD") is None

    monkeypatch.setitem(__import__("sys").modules, "intelligence.technical_engine", type("BadModule", (), {"get_kline_data": lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("x"))})())
    assert outcome_tracker._fetch_price("BTCUSD") is None


def test_get_ml_stats_counts_closed_labels(tmp_path, monkeypatch):
    db_path = seed_db(tmp_path)
    monkeypatch.setattr(outcome_tracker, "PAPER_DB", str(db_path))
    outcome_tracker.migrate_schema()
    with sqlite3.connect(db_path) as con:
        con.executemany(
            """
            INSERT INTO paper_trades (id, symbol, side, volume, entry_price, current_price, pnl_usd, status, opened_at, closed_at, outcome)
            VALUES (?, 'BTCUSD', 'BUY', 1, 100, 100, 0, 'CLOSED', '2026-01-01', '2026-01-01', ?)
            """,
            [("a", "WIN"), ("b", "LOSS"), ("c", "WIN")],
        )

    stats = outcome_tracker.get_ml_stats()

    assert stats == {"total_labeled": 3, "wins": 2, "losses": 1, "win_rate": 0.6667}
