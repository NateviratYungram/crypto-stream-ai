from datetime import datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from intelligence.ml import signal_scanner


class FakeCursor:
    def __init__(self, fetchone_results=None):
        self.fetchone_results = list(fetchone_results or [])
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        if self.fetchone_results:
            return self.fetchone_results.pop(0)
        return None


class FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False
        self.closed = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


def _market_df():
    rows = 60
    return pd.DataFrame(
        {
            "Open": [100.0] * rows,
            "High": [101.0] * rows,
            "Low": [99.0] * rows,
            "Close": [100.0] * rows,
            "Volume": [1000.0] * rows,
            "RSI": [55.0] * rows,
            "ATR": [2.0] * rows,
            "MACD_Hist": [0.3] * rows,
            "Volume_Ratio": [1.2] * rows,
        }
    )


def test_send_telegram_returns_false_without_credentials(monkeypatch):
    monkeypatch.setattr(signal_scanner, "_TG_TOKEN", None)
    monkeypatch.setattr(signal_scanner, "_TG_CHAT_ID", None)

    assert signal_scanner._send_telegram("hello") is False


def test_send_telegram_posts_message(monkeypatch):
    monkeypatch.setattr(signal_scanner, "_TG_TOKEN", "token")
    monkeypatch.setattr(signal_scanner, "_TG_CHAT_ID", "chat")
    captured = {}

    class FakeRequests:
        @staticmethod
        def post(url, json=None, timeout=None):
            captured["url"] = url
            captured["json"] = json
            captured["timeout"] = timeout
            return SimpleNamespace(status_code=200)

    import sys

    monkeypatch.setitem(sys.modules, "requests", FakeRequests)

    assert signal_scanner._send_telegram("hello") is True
    assert captured["url"].endswith("/sendMessage")
    assert captured["json"]["chat_id"] == "chat"
    assert captured["timeout"] == 8


def test_send_telegram_returns_false_on_http_failure_and_exception(monkeypatch):
    monkeypatch.setattr(signal_scanner, "_TG_TOKEN", "token")
    monkeypatch.setattr(signal_scanner, "_TG_CHAT_ID", "chat")

    class BadStatusRequests:
        @staticmethod
        def post(url, json=None, timeout=None):
            return SimpleNamespace(status_code=500)

    import sys

    monkeypatch.setitem(sys.modules, "requests", BadStatusRequests)
    assert signal_scanner._send_telegram("hello") is False

    class FailingRequests:
        @staticmethod
        def post(url, json=None, timeout=None):
            raise RuntimeError("network")

    monkeypatch.setitem(sys.modules, "requests", FailingRequests)
    assert signal_scanner._send_telegram("hello") is False


def test_us_market_open_checks_weekday_and_hours(monkeypatch):
    class OpenDateTime:
        @staticmethod
        def now(tz=None):
            return datetime(2026, 5, 25, 10, 0)

    monkeypatch.setattr(signal_scanner, "datetime", OpenDateTime)

    assert signal_scanner._us_market_open() is True

    class WeekendDateTime:
        @staticmethod
        def now(tz=None):
            return datetime(2026, 5, 24, 10, 0)

    monkeypatch.setattr(signal_scanner, "datetime", WeekendDateTime)

    assert signal_scanner._us_market_open() is False


def test_us_market_open_uses_fallback_timezone_when_zoneinfo_fails(monkeypatch):
    real_datetime = signal_scanner.datetime

    class FallbackDateTime:
        @staticmethod
        def now(tz=None):
            if tz is None:
                raise RuntimeError("tz unavailable")
            return real_datetime(2026, 5, 25, 14, 0, tzinfo=tz)

    monkeypatch.setattr(signal_scanner, "datetime", FallbackDateTime)

    assert signal_scanner._us_market_open() is True


def test_get_sentiment_returns_latest_score(monkeypatch):
    class FakePgCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params):
            self.params = params

        def fetchone(self):
            return (1.75,)

    class FakePgConn:
        def cursor(self):
            return FakePgCursor()

        def close(self):
            self.closed = True

    monkeypatch.setattr(signal_scanner.psycopg2, "connect", lambda **kwargs: FakePgConn())

    assert signal_scanner._get_sentiment("btcusd") == 1.75


def test_get_sentiment_handles_empty_and_connection_errors(monkeypatch):
    class EmptyPgCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params):
            return None

        def fetchone(self):
            return None

    class EmptyPgConn:
        def cursor(self):
            return EmptyPgCursor()

        def close(self):
            return None

    monkeypatch.setattr(signal_scanner.psycopg2, "connect", lambda **kwargs: EmptyPgConn())
    assert signal_scanner._get_sentiment("btcusd") == 0.0

    monkeypatch.setattr(signal_scanner.psycopg2, "connect", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("db down")))
    assert signal_scanner._get_sentiment("btcusd") == 0.0


def test_scan_creates_alert_for_best_side(monkeypatch):
    cursor = FakeCursor(fetchone_results=[None])
    conn = FakeConn(cursor)
    monkeypatch.setattr(signal_scanner.sqlite3, "connect", lambda path: conn)
    monkeypatch.setattr(signal_scanner, "TRADE_TRAIN_SYMBOLS", [("BTCUSD", "CRYPTO", "1h")])
    monkeypatch.setattr(signal_scanner, "get_market_status_data", lambda: {"forex": {"status": "OPEN"}, "stocks": {"status": "OPEN"}})
    monkeypatch.setattr(signal_scanner, "get_kline_data", lambda *args, **kwargs: _market_df())
    monkeypatch.setattr(signal_scanner, "compute_indicators", lambda df: df)
    monkeypatch.setattr(signal_scanner, "_get_sentiment", lambda sym: 0.0)
    monkeypatch.setattr(signal_scanner.InstitutionalGuard, "check_all_guards", lambda sym, side: True)
    monkeypatch.setattr(signal_scanner, "predict_with_neural_consensus", lambda df, idx, side, symbol, asset_class, sentiment_score: {"available": True, "win_pct": 88.0 if side == "BUY" else 72.0, "roc_auc": 0.64, "n_samples": 321})
    monkeypatch.setattr(signal_scanner, "get_trading_quality_gate", lambda *args, **kwargs: {"minimum_buy_sell_probability": 0.55})
    monkeypatch.setattr(signal_scanner, "get_threshold_for_side", lambda *args, **kwargs: 0.6)
    monkeypatch.setattr(signal_scanner, "paper_entry_performance_gate", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(signal_scanner, "get_symbol_policy", lambda *args, **kwargs: {"action": "allow"})
    monkeypatch.setattr(signal_scanner, "_send_telegram", lambda text: True)

    result = signal_scanner.scan_for_high_probability_signals()

    assert result == {"scanned": 1, "found": 1, "skipped_duplicates": 0, "errors": 0}
    assert conn.committed is True
    assert conn.closed is True
    insert_sql = [sql for sql, _ in cursor.executed if "INSERT INTO active_alerts" in sql]
    assert len(insert_sql) == 1


def test_scan_skips_duplicate_and_reduce_policy(monkeypatch):
    cursor = FakeCursor(fetchone_results=[("existing",)])
    conn = FakeConn(cursor)
    monkeypatch.setattr(signal_scanner.sqlite3, "connect", lambda path: conn)
    monkeypatch.setattr(signal_scanner, "TRADE_TRAIN_SYMBOLS", [("ETHUSD", "MACRO", "15m")])
    monkeypatch.setattr(signal_scanner, "get_market_status_data", lambda: {"forex": {"status": "OPEN"}, "stocks": {"status": "OPEN"}})
    monkeypatch.setattr(signal_scanner, "get_kline_data", lambda *args, **kwargs: _market_df())
    monkeypatch.setattr(signal_scanner, "compute_indicators", lambda df: df)
    monkeypatch.setattr(signal_scanner, "_get_sentiment", lambda sym: 0.0)
    monkeypatch.setattr(signal_scanner.InstitutionalGuard, "check_all_guards", lambda sym, side: True)
    monkeypatch.setattr(signal_scanner, "predict_with_neural_consensus", lambda df, idx, side, symbol, asset_class, sentiment_score: {"available": True, "win_pct": 92.0 if side == "BUY" else 40.0, "roc_auc": 0.7, "n_samples": 500})
    monkeypatch.setattr(signal_scanner, "get_trading_quality_gate", lambda *args, **kwargs: {"minimum_buy_sell_probability": 0.5})
    monkeypatch.setattr(signal_scanner, "get_threshold_for_side", lambda *args, **kwargs: 0.5)
    monkeypatch.setattr(signal_scanner, "paper_entry_performance_gate", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(signal_scanner, "get_symbol_policy", lambda *args, **kwargs: {"action": "reduce"})
    monkeypatch.setattr(signal_scanner, "_send_telegram", lambda text: True)

    result = signal_scanner.scan_for_high_probability_signals()

    assert result["found"] == 0
    assert result["skipped_duplicates"] == 1


def test_scan_blocks_on_performance_gate_and_handles_prediction_errors(monkeypatch):
    cursor = FakeCursor()
    conn = FakeConn(cursor)
    monkeypatch.setattr(signal_scanner.sqlite3, "connect", lambda path: conn)
    monkeypatch.setattr(signal_scanner, "TRADE_TRAIN_SYMBOLS", [("SOLUSD", "CRYPTO", "4h"), ("SOLUSD", "CRYPTO", "4h")])
    monkeypatch.setattr(signal_scanner, "get_market_status_data", lambda: {"forex": {"status": "OPEN"}, "stocks": {"status": "OPEN"}})
    monkeypatch.setattr(signal_scanner, "get_kline_data", lambda *args, **kwargs: _market_df())
    monkeypatch.setattr(signal_scanner, "compute_indicators", lambda df: df)
    monkeypatch.setattr(signal_scanner, "_get_sentiment", lambda sym: 0.0)
    monkeypatch.setattr(signal_scanner.InstitutionalGuard, "check_all_guards", lambda sym, side: side == "BUY")

    def fake_predict(df, idx, side, symbol, asset_class, sentiment_score):
        if side == "BUY":
            return {"available": True, "win_pct": 90.0, "roc_auc": 0.7, "n_samples": 400}
        raise RuntimeError("prediction failed")

    monkeypatch.setattr(signal_scanner, "predict_with_neural_consensus", fake_predict)
    monkeypatch.setattr(signal_scanner, "get_trading_quality_gate", lambda *args, **kwargs: {"minimum_buy_sell_probability": 0.5})
    monkeypatch.setattr(signal_scanner, "get_threshold_for_side", lambda *args, **kwargs: 0.5)
    monkeypatch.setattr(signal_scanner, "paper_entry_performance_gate", lambda *args, **kwargs: {"ok": False, "blockers": ["paper_drag"]})
    monkeypatch.setattr(signal_scanner, "get_symbol_policy", lambda *args, **kwargs: {"action": "allow"})

    result = signal_scanner.scan_for_high_probability_signals()

    assert result == {"scanned": 1, "found": 0, "skipped_duplicates": 0, "errors": 0}


def test_scan_skips_short_data_drift_critical_policy_block_and_top_level_errors(monkeypatch):
    short_df = _market_df().head(10)
    full_df = _market_df()
    cursor = FakeCursor(fetchone_results=[None])
    conn = FakeConn(cursor)

    monkeypatch.setattr(signal_scanner.sqlite3, "connect", lambda path: conn)
    monkeypatch.setattr(
        signal_scanner,
        "TRADE_TRAIN_SYMBOLS",
        [
            ("SHORT", "CRYPTO", "1h"),
            ("DRIFT", "CRYPTO", "1h"),
            ("BLOCK", "CRYPTO", "1h"),
            ("CRASH", "CRYPTO", "1h"),
        ],
    )
    monkeypatch.setattr(signal_scanner, "get_market_status_data", lambda: {"forex": {"status": "OPEN"}, "stocks": {"status": "OPEN"}})

    def fake_get_kline_data(sym, **kwargs):
        if sym == "SHORT":
            return short_df
        if sym == "CRASH":
            raise RuntimeError("feed down")
        return full_df

    monkeypatch.setattr(signal_scanner, "get_kline_data", fake_get_kline_data)
    monkeypatch.setattr(signal_scanner, "compute_indicators", lambda df: df)
    monkeypatch.setattr(signal_scanner, "_get_sentiment", lambda sym: 0.0)
    monkeypatch.setattr(signal_scanner.InstitutionalGuard, "check_all_guards", lambda sym, side: True)
    monkeypatch.setattr(signal_scanner, "predict_with_neural_consensus", lambda *args, **kwargs: {"available": True, "win_pct": 90.0, "roc_auc": 0.8, "n_samples": 200})
    monkeypatch.setattr(signal_scanner, "get_trading_quality_gate", lambda *args, **kwargs: {"minimum_buy_sell_probability": 0.5})
    monkeypatch.setattr(signal_scanner, "get_threshold_for_side", lambda *args, **kwargs: 0.5)
    monkeypatch.setattr(signal_scanner, "paper_entry_performance_gate", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(signal_scanner, "get_symbol_policy", lambda sym, side, force_refresh=True: {"action": "block"} if sym == "BLOCK" else {"action": "allow"})

    import sys

    drift_module = SimpleNamespace(get_drift_report=lambda feats: {"status": "CRITICAL_DRIFT", "integrity_score": 12} if feats.get("rsi") == 55.0 else {"status": "OK"})
    monkeypatch.setitem(sys.modules, "intelligence.ml.drift_monitor", drift_module)

    result = signal_scanner.scan_for_high_probability_signals()

    assert result == {"scanned": 4, "found": 0, "skipped_duplicates": 0, "errors": 1}


def test_scan_handles_drift_exception_sentiment_blocks_threshold_and_stock_telegram_context(monkeypatch):
    cursor = FakeCursor(fetchone_results=[None])
    conn = FakeConn(cursor)
    monkeypatch.setattr(signal_scanner.sqlite3, "connect", lambda path: conn)
    monkeypatch.setattr(
        signal_scanner,
        "TRADE_TRAIN_SYMBOLS",
        [
            ("NEG", "CRYPTO", "1h"),
            ("POS", "CRYPTO", "1h"),
            ("STOCK1", "STOCK", "15m"),
        ],
    )
    monkeypatch.setattr(signal_scanner, "get_market_status_data", lambda: {"forex": {"status": "CLOSED"}, "stocks": {"status": "HALTED"}})
    monkeypatch.setattr(signal_scanner, "get_kline_data", lambda *args, **kwargs: _market_df())
    monkeypatch.setattr(signal_scanner, "compute_indicators", lambda df: df)

    sentiments = {"NEG": -25.0, "POS": 25.0, "STOCK1": 0.0}
    monkeypatch.setattr(signal_scanner, "_get_sentiment", lambda sym: sentiments[sym])
    monkeypatch.setattr(signal_scanner.InstitutionalGuard, "check_all_guards", lambda sym, side: True)

    def fake_predict(df, idx, side, symbol, asset_class, sentiment_score):
        if symbol == "STOCK1":
            return {"available": True, "win_pct": 82.0 if side == "BUY" else 70.0, "roc_auc": 0.66, "n_samples": 123}
        return {"available": False, "win_pct": 0.0}

    monkeypatch.setattr(signal_scanner, "predict_with_neural_consensus", fake_predict)
    monkeypatch.setattr(signal_scanner, "get_trading_quality_gate", lambda *args, **kwargs: {"minimum_buy_sell_probability": 0.85})
    monkeypatch.setattr(signal_scanner, "get_threshold_for_side", lambda *args, **kwargs: 0.9)
    monkeypatch.setattr(signal_scanner, "paper_entry_performance_gate", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(signal_scanner, "get_symbol_policy", lambda *args, **kwargs: {"action": "allow"})

    import sys

    drift_module = SimpleNamespace(get_drift_report=lambda feats: (_ for _ in ()).throw(RuntimeError("drift unavailable")))
    monkeypatch.setitem(sys.modules, "intelligence.ml.drift_monitor", drift_module)

    sent_messages = []
    monkeypatch.setattr(signal_scanner, "_send_telegram", lambda text: sent_messages.append(text) or True)

    result = signal_scanner.scan_for_high_probability_signals(threshold=80.0)

    assert result == {"scanned": 3, "found": 0, "skipped_duplicates": 0, "errors": 0}
    assert sent_messages == []

    monkeypatch.setattr(signal_scanner, "get_trading_quality_gate", lambda *args, **kwargs: {"minimum_buy_sell_probability": 0.6})
    monkeypatch.setattr(signal_scanner, "get_threshold_for_side", lambda *args, **kwargs: 0.6)

    result = signal_scanner.scan_for_high_probability_signals(threshold=80.0)

    assert result == {"scanned": 3, "found": 1, "skipped_duplicates": 0, "errors": 0}
    assert sent_messages
    assert "Exchange Status: *HALTED*" in sent_messages[0]


def test_scan_skips_when_no_side_is_available(monkeypatch):
    cursor = FakeCursor()
    conn = FakeConn(cursor)
    monkeypatch.setattr(signal_scanner.sqlite3, "connect", lambda path: conn)
    monkeypatch.setattr(signal_scanner, "TRADE_TRAIN_SYMBOLS", [("NONE", "CRYPTO", "1h")])
    monkeypatch.setattr(signal_scanner, "get_market_status_data", lambda: {"forex": {"status": "OPEN"}, "stocks": {"status": "OPEN"}})
    monkeypatch.setattr(signal_scanner, "get_kline_data", lambda *args, **kwargs: _market_df())
    monkeypatch.setattr(signal_scanner, "compute_indicators", lambda df: df)
    monkeypatch.setattr(signal_scanner, "_get_sentiment", lambda sym: 0.0)
    monkeypatch.setattr(signal_scanner.InstitutionalGuard, "check_all_guards", lambda sym, side: True)
    monkeypatch.setattr(signal_scanner, "predict_with_neural_consensus", lambda *args, **kwargs: {"available": False})

    result = signal_scanner.scan_for_high_probability_signals()

    assert result == {"scanned": 1, "found": 0, "skipped_duplicates": 0, "errors": 0}


def test_scan_reduce_policy_can_raise_threshold_until_setup_is_skipped(monkeypatch):
    cursor = FakeCursor()
    conn = FakeConn(cursor)
    monkeypatch.setattr(signal_scanner.sqlite3, "connect", lambda path: conn)
    monkeypatch.setattr(signal_scanner, "TRADE_TRAIN_SYMBOLS", [("REDUCE", "MACRO", "1h")])
    monkeypatch.setattr(signal_scanner, "get_market_status_data", lambda: {"forex": {"status": "OPEN"}, "stocks": {"status": "OPEN"}})
    monkeypatch.setattr(signal_scanner, "get_kline_data", lambda *args, **kwargs: _market_df())
    monkeypatch.setattr(signal_scanner, "compute_indicators", lambda df: df)
    monkeypatch.setattr(signal_scanner, "_get_sentiment", lambda sym: 0.0)
    monkeypatch.setattr(signal_scanner.InstitutionalGuard, "check_all_guards", lambda sym, side: True)
    monkeypatch.setattr(
        signal_scanner,
        "predict_with_neural_consensus",
        lambda df, idx, side, symbol, asset_class, sentiment_score: {
            "available": True,
            "win_pct": 82.0 if side == "BUY" else 70.0,
            "roc_auc": 0.62,
            "n_samples": 250,
        },
    )
    monkeypatch.setattr(signal_scanner, "get_trading_quality_gate", lambda *args, **kwargs: {"minimum_buy_sell_probability": 0.80})
    monkeypatch.setattr(signal_scanner, "get_threshold_for_side", lambda *args, **kwargs: 0.80)
    monkeypatch.setattr(signal_scanner, "paper_entry_performance_gate", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(signal_scanner, "get_symbol_policy", lambda *args, **kwargs: {"action": "reduce", "reasons": ["cooldown"]})
    monkeypatch.setattr(signal_scanner, "_send_telegram", lambda text: True)

    result = signal_scanner.scan_for_high_probability_signals(threshold=80.0)

    assert result == {"scanned": 1, "found": 0, "skipped_duplicates": 0, "errors": 0}


def test_scan_handles_prediction_exception_and_macro_telegram_context(monkeypatch):
    cursor = FakeCursor(fetchone_results=[None])
    conn = FakeConn(cursor)
    monkeypatch.setattr(signal_scanner.sqlite3, "connect", lambda path: conn)
    monkeypatch.setattr(
        signal_scanner,
        "TRADE_TRAIN_SYMBOLS",
        [("ERR", "CRYPTO", "1h"), ("EURUSD", "MACRO", "4h")],
    )
    monkeypatch.setattr(signal_scanner, "get_market_status_data", lambda: {"forex": {"status": "ASIA_OPEN"}, "stocks": {"status": "OPEN"}})
    monkeypatch.setattr(signal_scanner, "get_kline_data", lambda *args, **kwargs: _market_df())
    monkeypatch.setattr(signal_scanner, "compute_indicators", lambda df: df)
    monkeypatch.setattr(signal_scanner, "_get_sentiment", lambda sym: 0.0)
    monkeypatch.setattr(signal_scanner.InstitutionalGuard, "check_all_guards", lambda sym, side: True)

    def fake_predict(df, idx, side, symbol, asset_class, sentiment_score):
        if symbol == "ERR" and side == "BUY":
            raise RuntimeError("model exploded")
        if symbol == "ERR":
            return {"available": False}
        return {"available": True, "win_pct": 84.0 if side == "BUY" else 74.0, "roc_auc": 0.67, "n_samples": 321}

    monkeypatch.setattr(signal_scanner, "predict_with_neural_consensus", fake_predict)
    monkeypatch.setattr(signal_scanner, "get_trading_quality_gate", lambda *args, **kwargs: {"minimum_buy_sell_probability": 0.6})
    monkeypatch.setattr(signal_scanner, "get_threshold_for_side", lambda *args, **kwargs: 0.6)
    monkeypatch.setattr(signal_scanner, "paper_entry_performance_gate", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(signal_scanner, "get_symbol_policy", lambda *args, **kwargs: {"action": "allow"})

    sent_messages = []
    monkeypatch.setattr(signal_scanner, "_send_telegram", lambda text: sent_messages.append(text) or True)

    result = signal_scanner.scan_for_high_probability_signals(threshold=80.0)

    assert result == {"scanned": 2, "found": 1, "skipped_duplicates": 0, "errors": 0}
    assert any("Market Status: *ASIA_OPEN*" in message for message in sent_messages)


def test_scan_blocks_symbol_policy_before_dedup(monkeypatch):
    cursor = FakeCursor(fetchone_results=[("should-not-be-used",)])
    conn = FakeConn(cursor)
    monkeypatch.setattr(signal_scanner.sqlite3, "connect", lambda path: conn)
    monkeypatch.setattr(signal_scanner, "TRADE_TRAIN_SYMBOLS", [("BLOCKME", "CRYPTO", "1h")])
    monkeypatch.setattr(signal_scanner, "get_market_status_data", lambda: {"forex": {"status": "OPEN"}, "stocks": {"status": "OPEN"}})
    monkeypatch.setattr(signal_scanner, "get_kline_data", lambda *args, **kwargs: _market_df())
    monkeypatch.setattr(signal_scanner, "compute_indicators", lambda df: df)
    monkeypatch.setattr(signal_scanner, "_get_sentiment", lambda sym: 0.0)
    monkeypatch.setattr(signal_scanner.InstitutionalGuard, "check_all_guards", lambda sym, side: True)
    monkeypatch.setattr(
        signal_scanner,
        "predict_with_neural_consensus",
        lambda df, idx, side, symbol, asset_class, sentiment_score: {"available": True, "win_pct": 88.0 if side == "BUY" else 70.0, "roc_auc": 0.7, "n_samples": 100},
    )
    monkeypatch.setattr(signal_scanner, "get_trading_quality_gate", lambda *args, **kwargs: {"minimum_buy_sell_probability": 0.6})
    monkeypatch.setattr(signal_scanner, "get_threshold_for_side", lambda *args, **kwargs: 0.6)
    monkeypatch.setattr(signal_scanner, "paper_entry_performance_gate", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(signal_scanner, "get_symbol_policy", lambda *args, **kwargs: {"action": "block", "reasons": ["manual_pause"]})

    result = signal_scanner.scan_for_high_probability_signals(threshold=80.0)

    assert result == {"scanned": 1, "found": 0, "skipped_duplicates": 0, "errors": 0}
    assert not any("SELECT id FROM active_alerts" in sql for sql, _ in cursor.executed)
