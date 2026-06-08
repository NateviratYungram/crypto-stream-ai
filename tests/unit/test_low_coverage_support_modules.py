import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd

from intelligence import archiver, brain, heartbeat, persona
from intelligence.guards import CooldownGuard, GuardPipeline, MaxPositionSizeGuard
from intelligence.guards import macro_shield
from intelligence.tools import macro_tools, onchain_tools


def test_brain_and_persona_disk_paths(tmp_path, monkeypatch):
    brain_file = tmp_path / "brain.json"
    monkeypatch.setattr(brain, "BRAIN_STATE_FILE", str(brain_file))

    empty = brain.get_brain_state()
    assert empty["emotion"] == "NEUTRAL"

    updated = brain.update_brain_state("Watch BTC liquidity", "calm")
    assert updated["status"] == "SUCCESS"
    assert updated["state"]["emotion"] == "CALM"
    assert "Watch BTC liquidity" in brain_file.read_text()

    brain_file.write_text("{bad json", encoding="utf-8")
    broken = brain.get_brain_state()
    assert "error" in broken

    persona_file = tmp_path / "persona.md"
    monkeypatch.setattr(persona, "PERSONA_FILE", str(persona_file))

    current = persona.get_current_persona()
    assert "CryptoStream AI" in current
    assert persona_file.exists()

    assert persona.update_persona("New persona instructions")
    assert persona.get_current_persona() == "New persona instructions"

    monkeypatch.setattr(persona, "open", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("no write")), raising=False)
    assert persona.update_persona("fail") is False


def test_macro_shield_and_guard_pipeline_paths(monkeypatch):
    now = datetime.now(timezone.utc)
    macro_shield._NEWS_SHIELD_STATE["danger_zones"] = [
        {"time": now + timedelta(minutes=10), "event": "FOMC"},
        {"time": now + timedelta(minutes=90), "event": "Low Priority"},
    ]

    zones = macro_shield.get_economic_calendar()
    status = macro_shield.is_in_danger_zone()
    report = macro_shield.get_macro_safety_report()

    assert len(zones) == 2
    assert status["blocked"] is True
    assert status["event"] == "FOMC"
    assert "MACRO SHIELD ACTIVE" in report

    macro_shield._NEWS_SHIELD_STATE["danger_zones"] = [
        {"time": now + timedelta(minutes=120), "event": "Later Event"}
    ]
    assert macro_shield.is_in_danger_zone() == {"blocked": False}
    assert "Neutral" in macro_shield.get_macro_safety_report()

    monkeypatch.setattr(macro_shield.logger, "error", lambda message: None)
    macro_shield.refresh_news_calendar()

    guard = GuardPipeline([MaxPositionSizeGuard(), CooldownGuard(cooldown_seconds=300)])
    monkeypatch.setattr("os.path.exists", lambda path: False)
    passed, messages = guard.run({"symbol": "BTCUSD", "volume": 1.0}, {"balance": 1000})
    assert passed is True
    assert any("No trade history" in message for message in messages)


def test_cooldown_guard_and_heartbeat_paths(tmp_path, monkeypatch):
    history_file = tmp_path / "trade_history.json"
    guard = CooldownGuard(cooldown_seconds=300)
    guard.history_file = str(history_file)

    history_file.write_text(json.dumps([{"symbol": "BTCUSD", "time": 999999999999}]), encoding="utf-8")
    blocked = guard.validate({"symbol": "BTCUSD"}, {})
    assert blocked.passed is False
    assert "Cooldown active" in blocked.message

    history_file.write_text(json.dumps([{"symbol": "ETHUSD", "time": 1}]), encoding="utf-8")
    missing = guard.validate({"symbol": "BTCUSD"}, {})
    assert missing.passed is True

    history_file.write_text("{oops", encoding="utf-8")
    unreadable = guard.validate({"symbol": "BTCUSD"}, {})
    assert unreadable.passed is True

    monkeypatch.setattr(heartbeat, "initialize_mt5", lambda: False)
    assert heartbeat.perform_system_heartbeat()["status"] == "ERROR"

    monkeypatch.setattr(heartbeat, "initialize_mt5", lambda: True)
    monkeypatch.setattr(
        heartbeat,
        "get_mt5_account_info",
        lambda: {"balance": 1000.0, "equity": 930.0, "margin_level": 200.0},
    )
    monkeypatch.setattr(
        heartbeat,
        "get_portfolio_analytics",
        lambda: {"risk_warnings": ["Concentration too high"]},
    )
    monkeypatch.setattr(
        heartbeat,
        "get_brain_state",
        lambda: {"frontal_lobe": "Protect capital", "last_updated": "2026-06-02T00:00:00"},
    )
    monkeypatch.setitem(
        sys.modules,
        "intelligence.snapshots",
        SimpleNamespace(take_account_snapshot=lambda: "snapshot-ok"),
    )
    report = heartbeat.perform_system_heartbeat()
    assert report["status"] == "WARNING"
    assert "Concentration too high" in report["alerts"]
    assert any("CRITICAL DRAWDOWN" in alert for alert in report["alerts"])
    assert any("MARGIN WARNING" in alert for alert in report["alerts"])


def test_macro_tools_and_onchain_paths(monkeypatch):
    class FakeSeries:
        def __init__(self, value):
            self.iloc = [value]

    class FakeHistory:
        def __init__(self, close_value, empty=False):
            self.empty = empty
            self._close_value = close_value

        def __getitem__(self, key):
            assert key == "Close"
            return FakeSeries(self._close_value)

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, period="1d"):
            values = {"^VIX": 36.0, "DX-Y.NYB": 101.5, "^TNX": 5.2}
            return FakeHistory(values[self.symbol])

    monkeypatch.setattr(macro_tools.yf, "Ticker", FakeTicker)
    risk = macro_tools.get_macro_risk_data()
    assert risk["danger_level"] == 90
    assert risk["regime"] == "EXTREME_VOLATILITY"
    assert risk["risk_multiplier"] == 0.5

    monkeypatch.setattr(macro_tools.yf, "Ticker", lambda symbol: (_ for _ in ()).throw(RuntimeError("yf down")))
    fallback = macro_tools.get_macro_risk_data()
    assert fallback["regime"] == "UNKNOWN"
    assert fallback["risk_multiplier"] == 1.0

    tool = onchain_tools.OnChainTools()
    assert tool.get_fomo_heatmap("XAUUSD")["status"] == "UNAVAILABLE"

    class FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    monkeypatch.setattr(
        onchain_tools.requests,
        "get",
        lambda url, timeout=5: FakeResponse(200, [{"longAccount": "0.71", "shortAccount": "0.29"}]),
    )
    heatmap = tool.get_fomo_heatmap("BTCUSD")
    assert heatmap["status"] == "SUCCESS"
    assert heatmap["institutional_bias"] == "SHORT"

    monkeypatch.setattr(onchain_tools.requests, "get", lambda url, timeout=5: FakeResponse(500, []))
    failed = tool.get_fomo_heatmap("ETHUSD")
    assert failed["status"] == "FAILED"

    monkeypatch.setattr(onchain_tools.requests, "get", lambda url, timeout=5: (_ for _ in ()).throw(RuntimeError("boom")))
    errored = tool.get_fomo_heatmap(object())
    assert errored["status"] == "ERROR"


def test_archiver_save_get_and_bootstrap_paths(tmp_path, monkeypatch):
    db_path = tmp_path / "archive.sqlite"
    store = archiver.IntelligenceArchiver(str(db_path))

    frame = pd.DataFrame(
        {
            "Open": [1.0, 2.0],
            "High": [1.5, 2.5],
            "Low": [0.5, 1.5],
            "Close": [1.2, 2.2],
            "Volume": [100.0, 200.0],
        },
        index=pd.to_datetime(["2024-01-01", "2024-01-02"]),
    )

    store.save_data("btcusd", "1h", frame)
    fetched = store.get_data("BTCUSD", "1h", limit=5)
    assert list(fetched["Close"]) == [1.2, 2.2]
    assert store.get_data("ETHUSD", "1h") is None

    monkeypatch.setitem(
        sys.modules,
        "intelligence.technical_engine",
        SimpleNamespace(get_kline_data=lambda symbol, timeframe, limit, asset_class: frame),
    )
    assert store.bootstrap_history("XAUUSD", asset_class="MACRO", timeframe="1d", years=5) == 2

    class FakeResponse:
        status_code = 200

        def json(self):
            return [
                [1000, "1", "2", "0.5", "1.5", "10", 0, 0, 0, 0, 0, 0],
                [2000, "1.5", "2.5", "1.0", "2.0", "11", 0, 0, 0, 0, 0, 0],
            ]

    monkeypatch.setattr(archiver.requests, "get", lambda url, params, timeout=10: FakeResponse())
    monkeypatch.setattr(archiver.time, "sleep", lambda seconds: None)
    synced = store.bootstrap_history("BTCUSDT", asset_class="CRYPTO", timeframe="1h", years=1)
    assert synced == 0

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM ohlcv_archive WHERE symbol = ?", ("BTCUSDT",)).fetchone()[0]
    assert count >= 2
