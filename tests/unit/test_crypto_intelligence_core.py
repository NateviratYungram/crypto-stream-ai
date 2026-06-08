import sys
from datetime import datetime
from types import SimpleNamespace

import pandas as pd

from intelligence import crypto_intelligence as ci


def _intel_stub():
    return ci.CryptoIntelligence.__new__(ci.CryptoIntelligence)


def _market_frame(rows=30):
    return pd.DataFrame(
        {
            "Close": [100.0 + i for i in range(rows)],
            "Volume": [1000.0 + i * 10 for i in range(rows)],
        }
    )


def test_analyze_and_trade_passes_analysis_into_execution(monkeypatch):
    intel = _intel_stub()
    analyzed = {"master_decision": "LONG", "symbol": "BTC"}
    monkeypatch.setattr(
        ci.CryptoIntelligence,
        "analyze",
        lambda self, symbol, timeframe="15m", limit=60, asset_class="CRYPTO": analyzed,
    )
    monkeypatch.setitem(
        sys.modules,
        "intelligence.execution_bridge",
        SimpleNamespace(
            execute_signal=lambda **kwargs: {
                "status": "DRY_RUN",
                "received_state": kwargs["state"],
                "confirmation_required": kwargs["confirmation_required"],
            }
        ),
    )

    result = ci.CryptoIntelligence.analyze_and_trade(
        intel,
        "BTC",
        timeframe="1h",
        limit=20,
        asset_class="CRYPTO",
        dry_run=True,
        risk_pct=2.0,
        account_balance=1000.0,
        confirmation_required=False,
    )

    assert result["analysis"] is analyzed
    assert result["execution"]["status"] == "DRY_RUN"
    assert result["execution"]["received_state"] is analyzed
    assert result["execution"]["confirmation_required"] is False


def test_get_quick_signals_ml_and_fallback_paths(monkeypatch):
    intel = _intel_stub()
    frame = _market_frame()

    monkeypatch.setattr(
        ci,
        "get_kline_data",
        lambda sym, timeframe, limit=30: None if sym == "MISS" else frame,
    )
    monkeypatch.setattr(ci, "compute_indicators", lambda df: df)
    monkeypatch.setattr(
        ci,
        "get_indicator_summary",
        lambda df, sym: {
            "rsi": {"value": 42 if sym != "EURUSD" else 55},
            "macd": {"signal": "Bullish Cross" if sym != "EURUSD" else "Bearish Cross"},
            "price": 123.45,
            "adx": {"value": 27},
        },
    )

    def fake_gate(symbol, entry_source="signal_feed_analysis", side=None):
        if symbol == "BTC":
            return {
                "live_ready": True,
                "allow_buy_sell": True,
                "mode": "tradeable",
                "minimum_buy_sell_probability": 0.66,
                "minimum_watch_probability": 0.53,
                "blockers": [],
            }
        return {
            "live_ready": False,
            "allow_buy_sell": False,
            "mode": "observe_only",
            "minimum_buy_sell_probability": 0.66,
            "minimum_watch_probability": 0.53,
            "blockers": ["paper_gate"],
        }

    monkeypatch.setattr(ci, "get_trading_quality_gate", fake_gate)
    monkeypatch.setattr(
        ci,
        "score_signal_feedback",
        lambda sym, entry_source="signal_feed_analysis", side=None: {
            "probability_adjustment": 0.05 if sym == "BTC" else 0.0,
            "notes": ["good paper edge"] if sym == "BTC" else [],
            "readiness": {"ok": sym == "BTC"},
        },
    )

    def predict(df, idx, side, symbol, asset_class):
        if symbol == "EURUSD":
            raise RuntimeError("model down")
        if side == "BUY":
            return {"available": True, "win_probability": 0.70, "rationale": ["breakout"], "neural_alignment": True, "mtf_blocked": False, "mtf_reason": ""}
        return {"available": True, "win_probability": 0.40, "rationale": ["countertrend"], "neural_alignment": False, "mtf_blocked": False, "mtf_reason": ""}

    monkeypatch.setitem(
        sys.modules,
        "intelligence.ml.signal_model",
        SimpleNamespace(predict_with_neural_consensus=predict),
    )

    signals = ci.CryptoIntelligence.get_quick_signals(intel, ["MISS", "BTC", "EURUSD"], timeframe="15m")

    assert [s["symbol"] for s in signals] == ["BTCUSDT", "EURUSD"]
    btc = signals[0]
    eur = signals[1]

    assert btc["direction"] == "BUY"
    assert btc["signal_grade"] == "A+"
    assert btc["actionable"] is True
    assert btc["tradeable"] is True
    assert btc["ml_win_prob"] == 0.75
    assert "good paper edge" in " ".join(btc["feedback_notes"])

    assert eur["quality_gate"]["mode"] == "heuristic_fallback"
    assert eur["direction"] in ("WATCH", "HOLD", "SELL", "BUY")
    assert eur["live_ready"] is False
    assert eur["symbol"] == "EURUSD"


def test_get_quick_signals_handles_unavailable_models_and_sorting(monkeypatch):
    intel = _intel_stub()
    frame = _market_frame()

    monkeypatch.setattr(ci, "get_kline_data", lambda sym, timeframe, limit=30: frame)
    monkeypatch.setattr(ci, "compute_indicators", lambda df: df)
    monkeypatch.setattr(
        ci,
        "get_indicator_summary",
        lambda df, sym: {
            "rsi": {"value": 60 if sym == "AAA" else 35},
            "macd": {"signal": "Bearish Cross" if sym == "AAA" else "Bullish Cross"},
            "price": 10.0,
            "adx": {"value": 15},
        },
    )
    monkeypatch.setattr(
        ci,
        "get_trading_quality_gate",
        lambda symbol, entry_source="signal_feed_analysis", side=None: {
            "live_ready": False,
            "allow_buy_sell": False,
            "mode": "observe_only",
            "minimum_buy_sell_probability": 0.66,
            "minimum_watch_probability": 0.53,
            "blockers": ["blocked"],
        },
    )
    monkeypatch.setattr(
        ci,
        "score_signal_feedback",
        lambda sym, entry_source="signal_feed_analysis", side=None: {
            "probability_adjustment": 0.0,
            "notes": [],
            "readiness": {},
        },
    )
    monkeypatch.setitem(
        sys.modules,
        "intelligence.ml.signal_model",
        SimpleNamespace(
            predict_with_neural_consensus=lambda *args, **kwargs: {"available": False, "win_probability": 0.5}
        ),
    )

    signals = ci.CryptoIntelligence.get_quick_signals(intel, ["AAA", "BBB"], timeframe="1h")

    assert len(signals) == 2
    assert signals[0]["confidence"] >= signals[1]["confidence"]
    assert all(signal["quality_gate"]["mode"] == "heuristic_fallback" for signal in signals)


def test_analyze_runs_full_pipeline_with_crypto_paths(monkeypatch):
    intel = _intel_stub()
    intel.intermarket_agent = lambda state: {"intermarket": {"macro_bias": "RISK_ON", "dxy": {"trend": "DOWN"}, "vix": {"level": 18}, "fear_greed": {"value": 72}}}
    intel.confluence_agent = lambda state: {"confluence_score": 81, "confluence_data": {"15m": {"direction": "BUY"}}}
    intel.indicator_agent = lambda state: {"indicator_bias": "BULLISH", "indicator_confidence": 78}
    intel.pattern_agent = lambda state: {"detected_pattern": "flag", "pattern_bias": "BULLISH"}
    intel.trend_agent = lambda state: {"trend_direction": "UP", "trend_bias": "BULLISH"}
    intel.sentiment_agent = lambda state: {"sentiment_label": "BULLISH", "sentiment_score": 22}
    intel.decision_agent = lambda state: {"trade_decision": "LONG", "decision_confidence": 84}
    intel.master_agent = lambda state: {"master_decision": "LONG", "master_confidence": 0.88}

    frame = pd.DataFrame(
        {
            "Close": [100.0, 101.0, 102.0],
            "ema_20": [99.0, 100.0, 101.0],
            "ema_50": [98.0, 99.0, 100.0],
            "adx_14": [20.0, 22.0, 24.0],
            "rsi_14": [55.0, 58.0, 60.0],
        },
        index=pd.date_range("2026-01-01", periods=3, freq="h"),
    )

    def fake_kline(sym, timeframe, limit=200, asset_class="CRYPTO"):
        return frame.copy()

    monkeypatch.setattr(ci, "get_kline_data", fake_kline)
    monkeypatch.setattr(ci, "compute_indicators", lambda df: df.copy())
    monkeypatch.setattr(ci, "get_indicator_summary", lambda df, sym: {"rsi": {"value": 60}, "adx": {"value": 24}, "price": 102.0, "hurst": {"regime": "trend"}})
    monkeypatch.setattr(
        ci,
        "get_smart_money_analysis",
        lambda df: {
            "regime": "TREND",
            "structure": {"structure": "bullish"},
            "session": "LONDON",
            "nearest_ob": {"type": "bullish_ob"},
            "liquidity": {"buy_side": [1]},
        },
    )
    monkeypatch.setattr(ci, "generate_kline_chart", lambda df, sym: "chart-b64")
    monkeypatch.setattr(ci, "generate_trend_chart", lambda df, sym: "trend-b64")
    monkeypatch.setattr(ci, "get_trading_quality_gate", lambda symbol, **kwargs: {"mode": "tradeable", "live_ready": True, "allow_buy_sell": True, "blockers": []})
    monkeypatch.setattr(ci, "check_directional_correlation", lambda symbol, side, asset_class="CRYPTO": {"confirmed": True, "score": 0.9, "conflicts": [], "checked": 3})

    monkeypatch.setitem(
        sys.modules,
        "intelligence.tools.onchain_tools",
        SimpleNamespace(onchain_engine=SimpleNamespace(get_fomo_heatmap=lambda sym: {"retail_sentiment": "GREED", "long_percent": 68, "short_percent": 32})),
    )
    monkeypatch.setitem(
        sys.modules,
        "intelligence.ml.signal_model",
        SimpleNamespace(
            predict_with_neural_consensus=lambda df, idx, side="BUY", symbol="BTC", asset_class="CRYPTO": {
                "available": True,
                "win_probability": 0.73 if side == "BUY" else 0.41,
                "neural_alignment": side == "BUY",
                "mtf_blocked": False,
                "mtf_reason": "",
            }
        ),
    )

    result = ci.CryptoIntelligence.analyze(intel, "BTCUSDT", timeframe="15m", limit=50, include_charts=True, asset_class="CRYPTO")

    assert result["symbol"] == "BTC"
    assert result["quality_gate_mode"] == "tradeable"
    assert result["retail_fomo"]["retail_sentiment"] == "GREED"
    assert result["indicator_summary"]["smart_money"]["regime"] == "TREND"
    assert result["indicator_summary"]["higher_timeframe"]["bias"] == "BULLISH"
    assert result["ml_signal"]["direction"] == "BUY"
    assert result["kline_chart_b64"] == "chart-b64"
    assert result["trend_chart_b64"] == "trend-b64"
    assert result["trade_decision"] == "LONG"
    assert result["master_decision"] == "LONG"
    assert result["directional_correlation"]["confirmed"] is True
    assert result["analysis_time_seconds"] >= 0


def test_analyze_handles_stock_no_data_path(monkeypatch):
    intel = _intel_stub()
    intel.intermarket_agent = lambda state: {"intermarket": {"macro_bias": "NEUTRAL", "dxy": {"trend": "FLAT"}, "vix": {"level": 20}, "fear_greed": {"value": 50}}}
    intel.confluence_agent = lambda state: {"confluence_score": 0, "confluence_data": {"1h": {"direction": "FLAT"}}}
    intel.indicator_agent = lambda state: {"indicator_bias": "NEUTRAL", "indicator_confidence": 50}
    intel.pattern_agent = lambda state: {"detected_pattern": "none", "pattern_bias": "NEUTRAL"}
    intel.trend_agent = lambda state: {"trend_direction": "SIDEWAYS", "trend_bias": "NEUTRAL"}
    intel.sentiment_agent = lambda state: {"sentiment_label": "NEUTRAL", "sentiment_score": 0}
    intel.decision_agent = lambda state: {"trade_decision": "HOLD", "decision_confidence": 40}
    intel.master_agent = lambda state: {"master_decision": "HOLD", "master_confidence": 0.4}

    monkeypatch.setattr(ci, "get_kline_data", lambda *args, **kwargs: pd.DataFrame())
    monkeypatch.setattr(ci, "generate_kline_chart", lambda df, sym: "should-not-run")
    monkeypatch.setattr(ci, "generate_trend_chart", lambda df, sym: "should-not-run")
    monkeypatch.setattr(ci, "check_directional_correlation", lambda *args, **kwargs: {"confirmed": False})

    result = ci.CryptoIntelligence.analyze(intel, "AAPL", timeframe="1h", limit=20, include_charts=True, asset_class="STOCK")

    assert result["symbol"] == "AAPL"
    assert result["quality_gate_mode"] == "tradeable"
    assert result["kline_data"] is None
    assert result["indicator_summary"] == {}
    assert result["kline_chart_b64"] == ""
    assert result["trend_chart_b64"] == ""
    assert result["trade_decision"] == "HOLD"
    assert result["master_decision"] == "HOLD"
    assert result["directional_correlation"]["confirmed"] is True
