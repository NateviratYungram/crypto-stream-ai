from datetime import datetime
from types import SimpleNamespace

import pandas as pd

from intelligence.guards import correlation_guardian as cg
from intelligence.guards.institutional_guard import InstitutionalGuard
import intelligence.guards.institutional_guard as ig


def test_check_correlation_safety_paths(monkeypatch):
    monkeypatch.setattr(cg, "_MT5_AVAILABLE", False)
    assert cg.check_correlation_safety("BTCUSD") == {"passed": True}

    monkeypatch.setattr(cg, "_MT5_AVAILABLE", True)

    fake_mt5 = SimpleNamespace(positions_get=lambda: [])
    monkeypatch.setitem(__import__("sys").modules, "MetaTrader5", fake_mt5)
    assert cg.check_correlation_safety("BTCUSD") == {"passed": True}

    positions = [
        SimpleNamespace(symbol="BTCUSD.a"),
        SimpleNamespace(symbol="ETHUSD"),
    ]
    fake_mt5 = SimpleNamespace(positions_get=lambda: positions)
    monkeypatch.setitem(__import__("sys").modules, "MetaTrader5", fake_mt5)

    blocked = cg.check_correlation_safety("SOLUSD")
    assert blocked["passed"] is False
    assert blocked["group"] == "CRYPTO"
    assert blocked["current_count"] == 2
    assert "BTCUSD.a" in blocked["reason"]

    allowed = cg.check_correlation_safety("XAUUSD")
    assert allowed["passed"] is True
    assert allowed["current_group_count"] == 0

    unknown = cg.check_correlation_safety("WEIRDPAIR")
    assert unknown == {"passed": True}


def test_check_directional_correlation_paths(monkeypatch):
    stock = cg.check_directional_correlation("AAPL", "LONG", asset_class="STOCK")
    assert stock == {"confirmed": True, "score": 1.0, "conflicts": [], "checked": 0}

    no_peers = cg.check_directional_correlation("UNKNOWN", "LONG", asset_class="CRYPTO")
    assert no_peers == {"confirmed": True, "score": 1.0, "conflicts": [], "checked": 0}

    monkeypatch.setitem(__import__("sys").modules, "intelligence.technical_engine", SimpleNamespace())
    fallback = cg.check_directional_correlation("BTCUSD", "LONG", asset_class="CRYPTO")
    assert fallback == {"confirmed": True, "score": 1.0, "conflicts": [], "checked": 0}

    frame_bull = pd.DataFrame({"Close": [100.0] * 60, "ema_50": [99.0] * 60})
    frame_bear = pd.DataFrame({"Close": [100.0] * 60, "ema_50": [101.0] * 60})

    def fake_kline(symbol, timeframe, limit=60, asset_class="CRYPTO"):
        if symbol == "SOLUSD":
            return frame_bear.copy()
        if symbol == "ETHUSD":
            return frame_bull.copy()
        return pd.DataFrame()

    monkeypatch.setitem(
        __import__("sys").modules,
        "intelligence.technical_engine",
        SimpleNamespace(
            get_kline_data=fake_kline,
            compute_indicators=lambda df: df,
        ),
    )

    long_check = cg.check_directional_correlation("BTCUSD", "LONG", asset_class="CRYPTO")
    assert long_check["confirmed"] is True
    assert long_check["score"] == 0.5
    assert long_check["conflicts"] == ["SOLUSD"]
    assert long_check["checked"] == 2

    short_check = cg.check_directional_correlation("BTCUSD", "SHORT", asset_class="CRYPTO")
    assert short_check["confirmed"] is True
    assert short_check["score"] == 0.5
    assert "ETHUSD" in short_check["conflicts"]


def test_institutional_guard_checks(monkeypatch):
    class FridayClose(datetime):
        @classmethod
        def utcnow(cls):
            return cls(2026, 6, 5, 22, 5, 0)

    monkeypatch.setattr(ig, "datetime", FridayClose)
    assert InstitutionalGuard.check_time_guard() is False

    class Saturday(datetime):
        @classmethod
        def utcnow(cls):
            return cls(2026, 6, 6, 12, 0, 0)

    monkeypatch.setattr(ig, "datetime", Saturday)
    assert InstitutionalGuard.check_time_guard() is False

    class SundayOpen(datetime):
        @classmethod
        def utcnow(cls):
            return cls(2026, 6, 7, 21, 0, 0)

    monkeypatch.setattr(ig, "datetime", SundayOpen)
    assert InstitutionalGuard.check_time_guard() is False

    class Rollover(datetime):
        @classmethod
        def utcnow(cls):
            return cls(2026, 6, 8, 22, 0, 0)

    monkeypatch.setattr(ig, "datetime", Rollover)
    assert InstitutionalGuard.check_time_guard() is False

    class SafeHour(datetime):
        @classmethod
        def utcnow(cls):
            return cls(2026, 6, 8, 10, 0, 0)

    monkeypatch.setattr(ig, "datetime", SafeHour)
    assert InstitutionalGuard.check_time_guard() is True

    monkeypatch.setattr(ig, "mt5", None)
    assert InstitutionalGuard.check_spread_guard("EURUSD") is True
    assert InstitutionalGuard.check_exposure_guard("EURUSD") is True

    fake_mt5 = SimpleNamespace(symbol_info=lambda symbol: None, positions_get=lambda symbol=None: None)
    monkeypatch.setattr(ig, "mt5", fake_mt5)
    assert InstitutionalGuard.check_spread_guard("EURUSD") is False
    assert InstitutionalGuard.check_exposure_guard("EURUSD") is True

    fake_mt5 = SimpleNamespace(
        symbol_info=lambda symbol: SimpleNamespace(spread=100 if symbol == "EURUSD" else 5),
        positions_get=lambda symbol=None: [1, 2, 3] if symbol == "EURUSD" else [1],
    )
    monkeypatch.setattr(ig, "mt5", fake_mt5)
    assert InstitutionalGuard.check_spread_guard("EURUSD") is False
    assert InstitutionalGuard.check_spread_guard("GBPUSD") is True
    assert InstitutionalGuard.check_exposure_guard("EURUSD") is False
    assert InstitutionalGuard.check_exposure_guard("GBPUSD") is True


def test_institutional_guard_check_all_guards(monkeypatch):
    monkeypatch.setattr(InstitutionalGuard, "check_time_guard", staticmethod(lambda: True))
    monkeypatch.setattr(InstitutionalGuard, "check_spread_guard", staticmethod(lambda symbol: True))
    monkeypatch.setattr(InstitutionalGuard, "check_exposure_guard", staticmethod(lambda symbol: True))
    assert InstitutionalGuard.check_all_guards("BTCUSD", "BUY") is True

    monkeypatch.setattr(InstitutionalGuard, "check_time_guard", staticmethod(lambda: False))
    assert InstitutionalGuard.check_all_guards("BTCUSD", "BUY") is False
