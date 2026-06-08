import json
import sqlite3
from types import SimpleNamespace

import numpy as np
import pandas as pd

from intelligence.agents import reflector_agent
from intelligence.agents.confluence_agent import (
    _analyze_single_tf,
    _calculate_confluence,
    _get_htfs,
    create_confluence_agent,
)
from intelligence.agents.decision_agent import create_decision_agent


class FakeModels:
    def __init__(self, payload=None, raises=None):
        self.payload = payload or {}
        self.raises = raises
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.raises:
            raise self.raises
        return SimpleNamespace(text=json.dumps(self.payload) if isinstance(self.payload, dict) else self.payload)


def _decision_payload(decision="LONG"):
    return {
        "decision": decision,
        "confidence": 76,
        "entry_zone": {"low": 100, "high": 102, "note": "OB retest"},
        "stop_loss": {"price": 95, "invalidation": "below swing"},
        "take_profit": {"tp1": 110, "tp2": 120, "note": "liquidity target"},
        "risk_reward_ratio": 2.4,
        "forecast_horizon": "4h",
        "justification": "Regime, structure and levels align.",
        "warnings": ["event risk"],
    }


def test_decision_agent_crypto_stock_and_error_paths():
    crypto_models = FakeModels(_decision_payload("LONG"))
    stock_models = FakeModels(_decision_payload("SHORT"))

    crypto = create_decision_agent(SimpleNamespace(models=crypto_models))(
        {
            "symbol": "BTC",
            "asset_class": "CRYPTO",
            "indicator_bias": "BULLISH",
            "pattern_bias": "BULLISH",
            "trend_bias": "NEUTRAL",
            "indicator_summary": {
                "price": 101,
                "atr": {"value": 2},
                "hurst": {"h100": 0.6, "h30": 0.58, "regime": "TRENDING"},
                "smart_money": {
                    "regime": "TREND",
                    "session": "NY",
                    "structure": {"structure": "BULLISH", "last_bos": "BULLISH_BOS", "swing_low": 96},
                    "nearest_ob": {"type": "BULLISH_OB", "top": 102, "bottom": 99, "strength": "HIGH"},
                    "nearest_fvg": {"type": "BULLISH_FVG", "top": 103, "bottom": 100, "gap_size": 3},
                    "liquidity": {"buy_side": [110, 120], "sell_side": [95], "nearest_sweep_target": 110},
                },
                "higher_timeframe": {"bias": "BULLISH", "regime": "TREND"},
            },
        }
    )
    stock = create_decision_agent(SimpleNamespace(models=stock_models))(
        {
            "symbol": "AAPL",
            "asset_class": "STOCK",
            "indicator_bias": "BEARISH",
            "pattern_bias": "BEARISH",
            "trend_bias": "NEUTRAL",
            "indicator_summary": {
                "price": 180,
                "atr": {"value": 4},
                "hurst": {"h100": 0.56, "regime": "TRENDING"},
                "vwap": {"value": 181, "position": "below"},
                "ema": {"signal": "BEARISH", "ema_20": 179, "ema_50": 185, "ema_200": 190},
                "trend_analysis": {"market_phase": "TREND", "primary_trend": "DOWN", "levels": {"support": 170, "resistance": 190}},
                "higher_timeframe": {"bias": "BEARISH", "timeframe": "1d"},
            },
        }
    )
    error = create_decision_agent(SimpleNamespace(models=FakeModels(raises=RuntimeError("llm"))))({})

    assert crypto["trade_decision"] == "LONG"
    assert crypto["decision_confidence"] == 76
    assert "Warnings" in crypto["decision_report"]
    assert "Smart Money" in crypto_models.calls[0]["contents"]
    assert stock["trade_decision"] == "SHORT"
    assert "equity technical" in stock_models.calls[0]["contents"]
    assert error["trade_decision"] == "HOLD"
    assert error["decision_confidence"] == 0


def _ohlc(rows=70, direction=1):
    base = np.linspace(100, 100 + direction * (rows - 1), rows)
    return pd.DataFrame(
        {
            "Open": base - 0.5,
            "High": base + 1.0,
            "Low": base - 1.0,
            "Close": base,
            "Volume": np.linspace(100, 200, rows),
        }
    )


def test_confluence_helpers_and_agent_with_mocked_fetch(monkeypatch):
    assert _get_htfs("15m") == ("1h", "4h")
    assert _get_htfs("4h") == ("1d",)
    assert _get_htfs("unknown") == ("1h", "4h")
    assert _analyze_single_tf(pd.DataFrame()).get("direction") == "NEUTRAL"

    bullish = _analyze_single_tf(_ohlc(direction=1))
    bearish = _analyze_single_tf(_ohlc(direction=-1))
    consensus, score = _calculate_confluence({"15m": bullish, "1h": bullish})
    mixed, mixed_score = _calculate_confluence({"15m": bullish, "1h": bearish})

    assert bullish["direction"] in {"BULLISH", "NEUTRAL"}
    assert bearish["direction"] in {"BEARISH", "NEUTRAL"}
    assert consensus in {"BULLISH", "MIXED"}
    assert score >= 0
    assert mixed in {"MIXED", "BULLISH", "BEARISH"}
    assert mixed_score >= 0

    import intelligence.technical_engine as technical_engine

    monkeypatch.setattr(technical_engine, "get_kline_data", lambda *_args, **_kwargs: _ohlc())
    monkeypatch.setattr(technical_engine, "compute_indicators", lambda df: df)
    result = create_confluence_agent()({"symbol": "BTC", "timeframe": "15m", "kline_data": _ohlc()})

    assert "confluence_data" in result
    assert "15m" in result["confluence_data"]
    assert "1H" in result["confluence_report"]


def _seed_reflector_db(path):
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE paper_trades (
                symbol TEXT, side TEXT, entry_price REAL, current_price REAL, outcome TEXT,
                pnl_usd REAL, ml_score REAL, closed_at TEXT, features_json TEXT, status TEXT,
                signal_grade TEXT, macro_bias TEXT
            );
            """
        )
        conn.executemany(
            """
            INSERT INTO paper_trades
            (symbol, side, entry_price, current_price, outcome, pnl_usd, ml_score, closed_at, features_json, status, signal_grade, macro_bias)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            [
                ("BTC", "LONG", 100, 110, "WIN", 10, 0.8, "2025-01-03T00:00:00", "{}", "CLOSED", "A", "RISK_ON"),
                ("BTC", "SHORT", 120, 125, "LOSS", -5, 0.4, "2025-01-02T00:00:00", "{}", "CLOSED", "B", "RISK_OFF"),
                ("ETH", "LONG", 50, 45, "LOSS", -3, 0.3, "2025-01-01T00:00:00", "{}", "CLOSED", "C", "NEUTRAL"),
            ],
        )


def test_reflector_agent_db_lessons_bias_and_context(tmp_path, monkeypatch):
    db = tmp_path / "paper.db"
    _seed_reflector_db(db)
    monkeypatch.setattr(reflector_agent, "PAPER_DB", str(db))

    outcomes = reflector_agent.get_recent_outcomes(2)
    symbol_memory = reflector_agent.format_symbol_memory("BTC")
    low_bias = reflector_agent.get_bias_adjustments([{"outcome": "LOSS"}, {"outcome": "LOSS"}, {"outcome": "WIN"}])
    high_bias = reflector_agent.get_bias_adjustments([{"outcome": "WIN"}, {"outcome": "WIN"}, {"outcome": "WIN"}])
    client = SimpleNamespace(models=FakeModels("* LESSON 1: Wait\n* LESSON 2: Size\n* LESSON 3: Filter"))
    lessons = reflector_agent.generate_reflexive_lessons(client, "model")
    context = reflector_agent.get_reflexive_context(client, "model")

    assert len(outcomes) == 2
    assert "BTC last 2 trades" in symbol_memory
    assert low_bias["risk_scale"] == 0.5
    assert high_bias["risk_scale"] == 1.2
    assert "LESSON 1" in lessons
    assert context["recent_performance"]["wins"] == 1
    assert context["recent_performance"]["losses"] == 2


def test_reflector_agent_missing_db_and_error_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(reflector_agent, "PAPER_DB", str(tmp_path / "missing.db"))

    assert reflector_agent.get_recent_outcomes() == []
    assert reflector_agent.format_symbol_memory("BTC").startswith("No closed BTC")
    assert reflector_agent.get_bias_adjustments()["risk_scale"] == 1.0
    assert "No recent trade history" in reflector_agent.generate_reflexive_lessons(SimpleNamespace(models=FakeModels()), "model")

    db = tmp_path / "bad.db"
    db.write_text("not sqlite", encoding="utf-8")
    monkeypatch.setattr(reflector_agent, "PAPER_DB", str(db))
    assert reflector_agent.get_recent_outcomes() == []
    assert reflector_agent.get_symbol_outcomes("BTC") == []
