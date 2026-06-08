import importlib
import json
import sqlite3


def _seed_closed_trade(conn, symbol: str, side: str, outcome: str, pnl_usd: float) -> None:
    conn.execute(
        """
        INSERT INTO paper_trades (symbol, side, entry_source, status, outcome, pnl_usd, opened_at, closed_at)
        VALUES (?, ?, 'signal_feed_analysis', 'CLOSED', ?, ?, '2026-05-01 00:00:00', '2026-05-01 01:00:00')
        """,
        (symbol, side, outcome, pnl_usd),
    )


def test_threshold_helpers_and_load_fallback(tmp_path, monkeypatch):
    module = importlib.import_module("intelligence.ml.symbol_threshold")

    assert module._is_stock_like("#nvda") is True
    assert module._normalize_symbol("ethusdt") == "ETH"
    assert module._normalize_side("sell") == "SELL"
    assert module._win_rate_to_floor(0.3, 3) == 0.62
    assert module._win_rate_to_floor(0.46, 10) == 0.55
    assert module._win_rate_to_floor(0.39, 10) == 0.62
    assert module._win_rate_to_floor(0.2, 10) == 0.70
    assert module._side_floor(0.6, 2, 1.0) == module.DEFAULT_THRESHOLD

    broken_file = tmp_path / "broken.json"
    broken_file.write_text("{bad json", encoding="utf-8")
    monkeypatch.setattr(module, "THRESHOLD_FILE", str(broken_file))
    assert module.load_thresholds() == {}

    missing_file = tmp_path / "missing.json"
    monkeypatch.setattr(module, "THRESHOLD_FILE", str(missing_file))
    assert module.load_thresholds() == {}


def test_update_thresholds_writes_symbol_and_side_floors(tmp_path, monkeypatch):
    db_path = tmp_path / "paper.db"
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            CREATE TABLE paper_trades (
                symbol TEXT,
                side TEXT,
                entry_source TEXT,
                status TEXT,
                outcome TEXT,
                pnl_usd REAL,
                opened_at TEXT,
                closed_at TEXT
            )
            """
        )
        for _ in range(6):
            _seed_closed_trade(con, "BTCUSD", "BUY", "LOSS", -0.8)
        for _ in range(4):
            _seed_closed_trade(con, "BTCUSD", "SELL", "WIN", 0.9)
        for _ in range(3):
            _seed_closed_trade(con, "AAPL", "BUY", "LOSS", -1.2)
        _seed_closed_trade(con, "ETHUSD", "", "WIN", 1.0)
        con.commit()

    module = importlib.import_module("intelligence.ml.symbol_threshold")
    monkeypatch.setenv("PAPER_TRADE_DB", str(db_path))
    monkeypatch.setattr(module, "THRESHOLD_FILE", str(tmp_path / "thresholds.json"))

    thresholds = module.update_thresholds()

    assert thresholds["BTCUSD"] >= 0.62
    assert thresholds["BTCUSD:BUY"] >= 0.68
    assert thresholds["BTCUSD:SELL"] == 0.5

    saved = json.loads((tmp_path / "thresholds.json").read_text(encoding="utf-8"))
    assert saved["BTCUSD:BUY"] >= 0.68


def test_get_threshold_for_side_prefers_side_specific_value(monkeypatch):
    module = importlib.import_module("intelligence.ml.symbol_threshold")
    monkeypatch.setattr(module, "_CACHE", {"ETHUSD": 0.55, "ETHUSD:SELL": 0.68})

    assert module.get_threshold("ETHUSD") == 0.55
    assert module.get_threshold_for_side("ETHUSD", "SELL") == 0.68
    assert module.get_threshold_for_side("ETHUSDT", "SELL") == 0.68
    assert module.get_threshold_for_side("SOLUSD", None) == 0.5


def test_update_thresholds_handles_missing_db_and_query_failure(tmp_path, monkeypatch):
    module = importlib.import_module("intelligence.ml.symbol_threshold")

    missing_db = tmp_path / "missing.db"
    monkeypatch.setenv("PAPER_TRADE_DB", str(missing_db))
    assert module.update_thresholds() == {}

    live_db = tmp_path / "live.db"
    live_db.write_text("", encoding="utf-8")
    monkeypatch.setenv("PAPER_TRADE_DB", str(live_db))
    monkeypatch.setattr(module.sqlite3, "connect", lambda path: (_ for _ in ()).throw(sqlite3.OperationalError("db down")))
    assert module.update_thresholds() == {}


def test_refresh_threshold_cache_and_fallback_lookups(monkeypatch):
    module = importlib.import_module("intelligence.ml.symbol_threshold")
    monkeypatch.setattr(module, "update_thresholds", lambda: {"BTC": 0.61, "ETHUSD:BUY": 0.67})

    refreshed = module.refresh_threshold_cache()

    assert refreshed == {"BTC": 0.61, "ETHUSD:BUY": 0.67}
    assert module.get_threshold("BTCUSD") == 0.61
    assert module.get_threshold_for_side("ETHUSDT", "BUY") == 0.67
    assert module.get_threshold("UNKNOWN") == module.DEFAULT_THRESHOLD
