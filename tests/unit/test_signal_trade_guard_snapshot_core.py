import json
import sys
from types import SimpleNamespace

import pytest

from intelligence import snapshots
from intelligence.guard_layer import apply_guard, create_guard_agent
from intelligence.signal_broadcaster import SignalBroadcaster, get_signal_broadcaster
from intelligence.trade_logger import TradeLogger, get_trade_logger


def test_guard_layer_allows_clean_trade_and_blocks_risky_paths():
    guard = create_guard_agent()

    allowed = guard(
        {
            "master_decision": "LONG",
            "master_confidence": 0.75,
            "confluence_score": 60,
            "rsi": 55,
            "regime": "TRENDING",
        }
    )
    blocked = guard(
        {
            "master_decision": "LONG",
            "master_confidence": 20,
            "confluence_score": 5,
            "rsi": 90,
            "regime": "CHAOS",
            "session_losses": 5,
        }
    )
    merged = apply_guard({"master_decision": "SHORT", "master_confidence": "bad"}, {"min_confidence": 0.5})

    assert allowed["guard_passed"] is True
    assert blocked["guard_passed"] is False
    assert blocked["master_decision"] == "NO_TRADE"
    assert "CHAOS regime" in blocked["guard_override_reason"]
    assert "RSI overbought" in blocked["guard_override_reason"]
    assert merged["master_decision"] == "NO_TRADE"


def test_signal_broadcaster_config_send_and_singleton(monkeypatch, tmp_path):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    disabled = SignalBroadcaster({"enable_notifications": False})
    no_chat = SignalBroadcaster({"enable_notifications": True, "telegram_bot_token": "token"})

    assert disabled.send_signal("hello") == {"status": "Notifications disabled"}
    assert no_chat.send_signal("hello") == {"status": "No notification channels configured"}

    calls = []

    def fake_post(url, data=None, files=None, timeout=None):
        calls.append({"url": url, "data": data, "files": files, "timeout": timeout})
        return SimpleNamespace(status_code=200, text="ok")

    monkeypatch.setitem(sys.modules, "requests", SimpleNamespace(post=fake_post))
    image = tmp_path / "chart.png"
    image.write_bytes(b"png")
    sb = SignalBroadcaster({"telegram_bot_token": "token", "telegram_chat_id": "chat"})

    text_result = sb.send_signal("message")
    photo_result = sb.send_signal("caption", image_path=str(image))

    assert text_result["telegram"]["status"] == "OK"
    assert photo_result["telegram"]["status"] == "OK"
    assert calls[0]["data"]["parse_mode"] == "Markdown"
    assert "sendPhoto" in calls[1]["url"]

    monkeypatch.setattr("intelligence.signal_broadcaster._sb_instance", None)
    first = get_signal_broadcaster({"telegram_bot_token": "a"})
    second = get_signal_broadcaster({"telegram_bot_token": "b"})
    assert first is second
    assert second.config["telegram_bot_token"] == "a"


def test_signal_broadcaster_telegram_failure_and_formatters(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "requests",
        SimpleNamespace(post=lambda *_args, **_kwargs: SimpleNamespace(status_code=500, text="failure body")),
    )
    sb = SignalBroadcaster({"telegram_bot_token": "token", "telegram_chat_id": "chat"})

    failed = sb.send_signal("message")
    msg = sb.format_trade_signal(
        {
            "master_decision": "LONG",
            "master_confidence": 0.82,
            "symbol": "BTC",
            "timeframe": "1h",
            "master_reasoning": "high confluence",
            "signal_grade": "A",
            "size_multiplier": 0.5,
            "entry_zone": {"low": 100, "high": 105},
            "stop_loss": {"price": 95},
            "take_profit": {"tp1": 110, "tp2": 120},
            "risk_reward_ratio": 2.5,
            "ml_signal": {"buy_pct": 70.5, "sell_pct": 29.5, "neural_alignment": True},
            "confluence_score": 88,
            "confluence_breakdown": "trend+momentum",
            "intermarket": {
                "macro_bias": "RISK_ON",
                "vix": {"level": "LOW"},
                "dxy": {"trend": "DOWN"},
                "fear_greed": {"value": 65},
                "funding": {"rate_pct": 0.0123},
            },
            "filter_notes": ["mtf ok", "cooldown ok"],
        }
    )
    alert = sb.format_execution_alert(
        {"symbol": "BTC", "master_decision": "LONG"},
        {
            "status": "BLOCKED",
            "trade_details": {"volume": 1, "entry_price": 100, "sl": 95, "tp": 110, "risk_usd": 10, "risk_pct": 1},
            "reason": "guard",
            "cb_status": {"daily_pnl": -1, "weekly_pnl": -2},
            "guard_result": {"guard_override_reason": "risk blocked"},
        },
    )

    assert failed["telegram"]["status"] == "FAILED"
    assert "Confidence" in msg
    assert "ML Prob" in msg
    assert "TradingView" in msg
    assert "Guard" in alert


def test_trade_logger_persistence_statistics_reports_and_singleton(tmp_path, monkeypatch):
    log_file = tmp_path / "trades.json"
    logger = TradeLogger({"trade_log_file": str(log_file), "portfolio_balance": 1000})

    logger.log_trade(
        {
            "symbol": "BTC",
            "action": "BUY",
            "status": "EXECUTED",
            "ticket": "t1",
            "timestamp": "2025-01-01T10:00:00",
            "profit": 25,
        }
    )
    logger.log_trade(
        {
            "symbol": "ETH",
            "action": "SELL",
            "status": "DRY_RUN",
            "timestamp": "2025-01-01T11:00:00",
            "pnl": -10,
        }
    )
    logger.log_trade({"symbol": "X", "status": "SKIPPED", "timestamp": "bad"})

    assert logger.update_trade_close("t1", 30.4, True) is True
    assert logger.update_trade_close("missing", -1, False) is False

    stats = logger.get_statistics()
    recent = logger.get_recent_trades(2)
    heatmap = logger.get_session_heatmap()
    report = logger.get_weekly_report()

    assert stats["total_trades"] == 2
    assert stats["wins"] == 1
    assert stats["losses"] == 1
    assert stats["total_pnl"] == 20.4
    assert len(recent) == 2
    assert heatmap[10]["wins"] == 1
    assert heatmap[11]["losses"] == 1
    assert "Weekly Report" in report

    monkeypatch.setattr("intelligence.trade_logger._tl_instance", None)
    first = get_trade_logger({"trade_log_file": str(log_file)})
    second = get_trade_logger({"trade_log_file": str(tmp_path / "other.json")})
    assert first is second


def test_trade_logger_empty_and_corrupt_files(tmp_path):
    log_file = tmp_path / "empty.json"
    logger = TradeLogger({"trade_log_file": str(log_file)})
    assert logger.get_statistics()["total_trades"] == 0

    log_file.write_text("{bad json", encoding="utf-8")
    assert logger._load() == []
    assert logger.get_recent_trades() == []


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
            raise RuntimeError("db error")

    def fetchone(self):
        return self.rows.pop(0) if self.rows else [101]


class FakeConn:
    def __init__(self, cursor):
        self.cursor_obj = cursor
        self.commits = 0
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed = True


def test_snapshots_table_success_and_failure(monkeypatch):
    ok_conn = FakeConn(FakeCursor())
    monkeypatch.setattr(snapshots, "_get_db_conn", lambda: ok_conn)

    assert snapshots.initialize_snapshot_table() is True
    assert ok_conn.commits == 1
    assert ok_conn.closed is True

    monkeypatch.setattr(snapshots, "_get_db_conn", lambda: (_ for _ in ()).throw(RuntimeError("no db")))
    assert snapshots.initialize_snapshot_table() is False


def test_take_account_snapshot_paths(monkeypatch):
    monkeypatch.setitem(sys.modules, "MetaTrader5", None)
    assert snapshots.take_account_snapshot()["error"] == "MetaTrader5 not available"

    mt5_module = SimpleNamespace(
        positions_get=lambda: [
            SimpleNamespace(symbol="BTCUSD", volume=0.2),
            SimpleNamespace(symbol="BTCUSD", volume=0.3),
            SimpleNamespace(symbol="ETHUSD", volume=1.0),
        ]
    )
    monkeypatch.setitem(sys.modules, "MetaTrader5", mt5_module)

    import intelligence.mt5_connector as mt5_connector

    monkeypatch.setattr(mt5_connector, "initialize_mt5", lambda: True)
    monkeypatch.setattr(
        mt5_connector,
        "get_mt5_account_info",
        lambda: {"balance": 1000, "equity": 1010, "margin_level": 200, "profit": 10},
    )
    conn = FakeConn(FakeCursor(rows=[[202]]))
    monkeypatch.setattr(snapshots, "_get_db_conn", lambda: conn)

    result = snapshots.take_account_snapshot()

    assert result == {"status": "SUCCESS", "snapshot_id": 202, "equity": 1010, "positions": 3}
    params = conn.cursor_obj.executed[0][1]
    assert json.loads(params[-1]) == {"BTCUSD": 0.5, "ETHUSD": 1.0}

    monkeypatch.setattr(mt5_connector, "initialize_mt5", lambda: False)
    assert snapshots.take_account_snapshot()["error"] == "Failed to connect to MT5"
