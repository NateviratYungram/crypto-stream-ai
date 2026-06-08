from types import SimpleNamespace

import pandas as pd

from intelligence import risk_manager as rm


def test_calculate_kelly_size_handles_rr_floor_macro_and_caps(monkeypatch):
    manager = rm.RiskManager()

    assert manager.calculate_kelly_size(0.6, 0, 1000.0) == 0.01

    fake_macro = SimpleNamespace(get_macro_risk_data=lambda: {"risk_multiplier": 0.5, "regime": "risk_off", "vix": 30})
    import sys

    monkeypatch.setitem(sys.modules, "intelligence.tools.macro_tools", fake_macro)
    sniper = manager.calculate_kelly_size(0.9, 2.0, 1000.0, is_v8_sniper=True)
    normal = manager.calculate_kelly_size(0.7, 2.0, 1000.0, is_v8_sniper=False)

    assert 0 <= sniper <= 0.05
    assert 0 <= normal <= 0.02

    fake_broken_macro = SimpleNamespace(
        get_macro_risk_data=lambda: (_ for _ in ()).throw(RuntimeError("macro down"))
    )
    import sys

    monkeypatch.setitem(sys.modules, "intelligence.tools.macro_tools", fake_broken_macro)
    assert manager.calculate_kelly_size(0.7, 2.0, 1000.0, is_v8_sniper=False) <= 0.02

    fake_macro_neutral = SimpleNamespace(get_macro_risk_data=lambda: {"risk_multiplier": 1.0, "regime": "normal", "vix": 18})
    monkeypatch.setitem(sys.modules, "intelligence.tools.macro_tools", fake_macro_neutral)
    assert manager.calculate_kelly_size(0.7, 2.0, 1000.0, is_v8_sniper=False) <= 0.02


def test_check_correlation_risk_safe_high_and_unknown(monkeypatch):
    manager = rm.RiskManager(max_correlation=0.85)

    monkeypatch.setattr(rm, "get_active_trades", lambda: [])
    assert manager.check_correlation_risk("BTCUSD")["status"] == "SAFE"

    monkeypatch.setattr(rm, "get_active_trades", lambda: [{"symbol": "ETHUSD"}])
    close_prices = pd.DataFrame({"BTCUSD": [100, 110, 120], "ETHUSD": [200, 220, 240]})
    monkeypatch.setattr(rm.yf, "download", lambda symbols, period, interval, progress=False: {"Close": close_prices})
    high = manager.check_correlation_risk("BTCUSD")
    assert high["status"] == "HIGH_CORRELATION"
    assert high["conflicts"][0]["symbol"] == "ETHUSD"

    low_corr_prices = pd.DataFrame({"BTCUSD": [100, 101, 102], "ETHUSD": [200, 199, 201]})
    monkeypatch.setattr(rm.yf, "download", lambda symbols, period, interval, progress=False: {"Close": low_corr_prices})
    safe = manager.check_correlation_risk("BTCUSD")
    assert safe["status"] == "SAFE"
    assert safe["conflicts"] == []

    monkeypatch.setattr(rm.yf, "download", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("download failed")))
    unknown = manager.check_correlation_risk("BTCUSD")
    assert unknown["status"] == "UNKNOWN"


def test_check_equity_protection_and_news_shield(monkeypatch):
    manager = rm.RiskManager(max_daily_loss_pct=3.0)

    monkeypatch.setattr(rm, "get_mt5_account_info", lambda: {"error": "offline"})
    assert manager.check_equity_protection()["status"] == "ERROR"

    monkeypatch.setattr(rm, "get_mt5_account_info", lambda: {"balance": 1000.0, "equity": 950.0})
    blocked = manager.check_equity_protection()
    assert blocked["status"] == "BLOCKED"
    assert blocked["reason"] == "DAILY_LOSS_LIMIT"

    monkeypatch.setattr(rm, "get_mt5_account_info", lambda: {"balance": 1000.0, "equity": 990.0})
    assert manager.check_equity_protection()["status"] == "SAFE"

    fake_calendar = SimpleNamespace(calendar_engine=SimpleNamespace(get_upcoming_high_impact=lambda currencies: [{"title": "CPI", "time": "12:30", "country": "USD"}]))
    import sys

    monkeypatch.setitem(sys.modules, "intelligence.tools.calendar_tools", fake_calendar)
    news = manager.check_news_shield("EURUSD")
    assert news["status"] == "BLOCKED"
    assert "CPI" in news["reason"]

    fake_calendar_ok = SimpleNamespace(calendar_engine=SimpleNamespace(get_upcoming_high_impact=lambda currencies: []))
    monkeypatch.setitem(sys.modules, "intelligence.tools.calendar_tools", fake_calendar_ok)
    safe = manager.check_news_shield("BTCUSD")
    assert safe["status"] == "SAFE"

    captured = {}
    fake_calendar_jpy = SimpleNamespace(
        calendar_engine=SimpleNamespace(
            get_upcoming_high_impact=lambda currencies: captured.setdefault("currencies", currencies) or []
        )
    )
    monkeypatch.setitem(sys.modules, "intelligence.tools.calendar_tools", fake_calendar_jpy)
    manager.check_news_shield("JPY")
    assert captured["currencies"] == ["JPY"]

    captured_default = {}
    fake_calendar_default = SimpleNamespace(
        calendar_engine=SimpleNamespace(
            get_upcoming_high_impact=lambda currencies: captured_default.setdefault("currencies", currencies) or []
        )
    )
    monkeypatch.setitem(sys.modules, "intelligence.tools.calendar_tools", fake_calendar_default)
    manager.check_news_shield("AUDCAD")
    assert captured_default["currencies"] == ["USD"]

    monkeypatch.setitem(sys.modules, "intelligence.tools.calendar_tools", SimpleNamespace(calendar_engine=SimpleNamespace(get_upcoming_high_impact=lambda currencies: (_ for _ in ()).throw(RuntimeError("calendar down")))))
    assert manager.check_news_shield("GBPUSD")["status"] == "SAFE"
