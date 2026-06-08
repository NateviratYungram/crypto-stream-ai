import importlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from intelligence import event_logger, visual_analysis
from intelligence.ml import regime_analysis


def test_regime_analysis_and_visual_helpers(tmp_path):
    short = regime_analysis.estimate_hurst_exponent(np.arange(10))
    trending = regime_analysis.estimate_hurst_exponent(np.linspace(1.0, 500.0, 200))
    fallback = regime_analysis.estimate_hurst_exponent(np.array(["bad"] * 200, dtype=object))

    assert short == 0.5
    assert 0.0 <= trending <= 1.0
    assert fallback == 0.5

    missing = visual_analysis.analyze_chart_visually(str(tmp_path / "missing.png"))
    assert "Image file not found" in missing["error"]

    image_path = tmp_path / "chart.png"
    image_path.write_bytes(b"fake")
    result = visual_analysis.analyze_chart_visually(str(image_path), user_query="bias?")
    assert result["status"] == "SUCCESS"
    assert result["action"] == "UPLOAD_TO_LLM_CONTEXT"

    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        snap = visual_analysis.capture_dashboard_snapshot()
        assert snap == "snapshots/dashboard_live.png"
        assert (tmp_path / "snapshots").exists()
    finally:
        os.chdir(cwd)


def test_event_logger_and_helpers(tmp_path, monkeypatch):
    log_path = tmp_path / "audit" / "events.jsonl"
    logger_obj = event_logger.AuditLogger(str(log_path))
    logger_obj.log_event("unit.test", {"ok": True})
    entries = log_path.read_text(encoding="utf-8").strip().splitlines()
    payload = json.loads(entries[0])
    assert payload["type"] == "unit.test"
    assert payload["payload"]["ok"] is True

    calls = []
    monkeypatch.setattr(event_logger, "audit_log", SimpleNamespace(log_event=lambda event_type, payload: calls.append((event_type, payload))))
    event_logger.log_trade_attempt("BTCUSD", "BUY", 1.5, "setup")
    event_logger.log_guard_failure("cooldown", "wait")
    event_logger.log_security_threat("feed", "prompt-injection")
    assert calls[0][0] == "trade.attempt"
    assert calls[1][0] == "safety.guard_failure"
    assert calls[2][0] == "security.threat_detected"


def test_event_logger_handles_write_failures(tmp_path, monkeypatch):
    log_path = tmp_path / "audit" / "events.jsonl"
    logger_obj = event_logger.AuditLogger(str(log_path))
    errors = []

    def failing_open(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(event_logger, "open", failing_open, raising=False)
    monkeypatch.setattr(event_logger.logger, "error", lambda message: errors.append(message))

    logger_obj.log_event("unit.test", {"ok": False})

    assert errors == ["Audit: Failed to write event log: disk full"]


def _load_mt5_ingestion_service(monkeypatch):
    fake_mt5 = SimpleNamespace(
        TIMEFRAME_M15=15,
        TIMEFRAME_H1=60,
        TIMEFRAME_H4=240,
        TIMEFRAME_D1=1440,
        initialize=lambda: True,
        last_error=lambda: "ERR",
        account_info=lambda: SimpleNamespace(company="Broker", login=123),
        copy_rates_from=lambda symbol, tf, now_ts, max_count: [],
        symbol_info=lambda name: SimpleNamespace(name=name),
        symbol_select=lambda name, selected: True,
        shutdown=lambda: True,
    )
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake_mt5)
    if "services.mt5_ingestion_service" in sys.modules:
        del sys.modules["services.mt5_ingestion_service"]
    return importlib.import_module("services.mt5_ingestion_service")


def test_mt5_ingestion_service_core_paths(monkeypatch):
    service = _load_mt5_ingestion_service(monkeypatch)

    monkeypatch.setattr(service.psycopg2, "connect", lambda **kwargs: kwargs)
    assert service.get_conn() == service.DB_CONFIG

    service.mt5 = SimpleNamespace(initialize=lambda: False, last_error=lambda: "oops")
    assert service.init_mt5() is False

    service.mt5 = SimpleNamespace(
        initialize=lambda: True,
        account_info=lambda: SimpleNamespace(company="Broker", login=777),
    )
    assert service.init_mt5() is True

    assert service.upsert_ohlcv(object(), []) == 0

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeConn:
        def __init__(self):
            self.cur = FakeCursor()
            self.committed = False

        def cursor(self):
            return self.cur

        def commit(self):
            self.committed = True

        def close(self):
            self.closed = True

    conn = FakeConn()
    captured = {}
    monkeypatch.setattr(service.psycopg2.extras, "execute_values", lambda cur, sql, tuples, page_size=1000: captured.update({"tuples": tuples, "page_size": page_size}))
    rows = [{"symbol": "BTCUSD", "timeframe": "1h", "ts": "2026-01-01", "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0}]
    assert service.upsert_ohlcv(conn, rows) == 1
    assert conn.committed is True
    assert captured["page_size"] == 1000

    assert service.backfill_symbol(conn, "BTCUSD", "bad-tf") is None

    warnings = []
    upserted = []
    service.mt5 = SimpleNamespace(
        last_error=lambda: "missing",
        copy_rates_from=lambda symbol, tf, now_ts, max_count: [],
    )
    monkeypatch.setattr(service.logger, "warning", lambda message: warnings.append(message))
    monkeypatch.setattr(service, "upsert_ohlcv", lambda conn, rows: upserted.append(rows) or len(rows))
    assert service.backfill_symbol(conn, "BTCUSD", "1h") is None
    assert warnings

    service.mt5 = SimpleNamespace(
        copy_rates_from=lambda symbol, tf, now_ts, max_count: [
            {"time": 1717200000, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "tick_volume": 10},
            {"time": 1717203600, "open": 1.5, "high": 2.5, "low": 1.0, "close": 2.0, "tick_volume": 12},
        ],
        last_error=lambda: "ok",
        symbol_info=lambda name: SimpleNamespace(name=name),
        symbol_select=lambda name, selected: True,
        shutdown=lambda: True,
    )
    service.backfill_symbol(conn, "BTCUSD", "1h", years=1, db_symbol="BTC_ALIAS")
    assert len(upserted[-1]) == 2
    assert upserted[-1][0]["symbol"] == "BTC_ALIAS"

    monkeypatch.setitem(sys.modules, "intelligence.ml.signal_model", SimpleNamespace(TRADE_TRAIN_SYMBOLS=[("BTCUSD", "CRYPTO", "1h")]))
    opened = []
    monkeypatch.setattr(service, "get_conn", lambda: SimpleNamespace(close=lambda: opened.append("closed")))
    monkeypatch.setattr(service, "backfill_symbol", lambda conn, symbol, tf, years=10, db_symbol=None: opened.append((symbol, tf, db_symbol)))
    service.mt5 = SimpleNamespace(
        initialize=lambda: True,
        account_info=lambda: SimpleNamespace(company="Broker", login=999),
        symbol_info=lambda name: SimpleNamespace(name=name) if "BTCUSD" in name else None,
        symbol_select=lambda name, selected: True,
        shutdown=lambda: opened.append("shutdown"),
    )
    service.main()
    assert ("BTCUSD", "15m", "BTCUSD") in opened
    assert "shutdown" in opened


def test_verify_ingestion_paths(monkeypatch):
    import streaming.verify_ingestion as verify

    logs = []
    monkeypatch.setattr(verify.logger, "info", lambda message: logs.append(("info", message)))
    monkeypatch.setattr(verify.logger, "error", lambda message: logs.append(("error", message)))

    monkeypatch.setattr(verify, "KafkaConsumer", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("kafka down")))
    assert verify.verify_data() is None
    assert any("Failed to connect" in msg for level, msg in logs if level == "error")

    class FakeMessage:
        def __init__(self, symbol, price):
            self.value = {"symbol": symbol, "price": price}

    class FakeConsumer:
        def __iter__(self):
            return iter(
                [
                    FakeMessage("BTCUSD", 1),
                    FakeMessage("ETHUSD", 2),
                    FakeMessage("XAUUSD", 3),
                ]
            )

    monkeypatch.setattr(verify, "KafkaConsumer", lambda *args, **kwargs: FakeConsumer())
    with pytest.raises(SystemExit) as success_exit:
        verify.verify_data()
    assert success_exit.value.code == 0

    class EmptyConsumer:
        def __iter__(self):
            return iter([])

    monkeypatch.setattr(verify, "KafkaConsumer", lambda *args, **kwargs: EmptyConsumer())
    with pytest.raises(SystemExit) as fail_exit:
        verify.verify_data()
    assert fail_exit.value.code == 1
