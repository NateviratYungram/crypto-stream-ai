import pandas as pd

from intelligence.tools import market_tool_primitives as primitives


def test_safe_num_handles_invalid_and_nan():
    assert primitives._safe_num("1.23456") == 1.2346
    assert primitives._safe_num(float("nan"), default=9.0) == 9.0
    assert primitives._safe_num("bad", default=5.0) == 5.0


def test_build_chart_analysis_returns_empty_for_short_frames():
    assert primitives._build_chart_analysis(None) == {}
    assert primitives._build_chart_analysis(pd.DataFrame([{"Close": 1.0}])) == {}


def test_build_chart_analysis_generates_buy_zone_signal():
    frame = pd.DataFrame(
        [
            {
                "rsi_14": 55,
                "macd_hist": -0.2,
                "ema_20": 100,
                "ema_50": 101,
                "ema_200": 102,
                "Close": 100,
                "High": 110,
                "Low": 95,
                "atr_14": 2,
            },
            {
                "rsi_14": 30,
                "macd_hist": 0.4,
                "ema_20": 100,
                "ema_50": 99,
                "ema_200": 98,
                "Close": 96,
                "High": 108,
                "Low": 94,
                "atr_14": 2.5,
            },
        ]
    )

    result = primitives._build_chart_analysis(frame)

    assert result["rsi"]["signal"].startswith("OVERSOLD")
    assert result["macd"]["signal"].startswith("BULLISH_CROSS")
    assert result["ema_trend"] == "SIDEWAYS"
    assert result["action_summary"].startswith("BUY_ZONE")


def test_bias_from_label_maps_common_terms():
    assert primitives._bias_from_label("strong bull trend") == "BULLISH"
    assert primitives._bias_from_label("overbought sell zone") == "BEARISH"
    assert primitives._bias_from_label("flat") == "NEUTRAL"


def test_derive_trade_signal_returns_buy_with_confluence():
    analysis = {
        "chart_analysis": {"ema_trend": "BULLISH", "action_summary": "BUY_ZONE"},
        "higher_timeframe": {"bias": "BULLISH", "adx": 25},
        "smart_money": {"structure": {"structure": "BULLISH", "last_bos": "BULLISH"}},
        "historical_pulse": {"statistical_bias": "BULLISH"},
        "whale_pulse": {"bias": "BULLISH"},
        "retail_fomo": {"institutional_bias": "BULLISH"},
        "ema": {"signal": "BULLISH"},
    }
    ml_stats = {"side": "BUY", "neural_win_probability": 0.62, "edge_score": 0.7}

    result = primitives._derive_trade_signal(analysis, ml_stats)

    assert result["action"] == "BUY"
    assert result["bias"] == "BULLISH"
    assert result["confidence"] >= 60
    assert result["blockers"] == []


def test_derive_trade_signal_returns_hold_when_signals_conflict():
    analysis = {
        "chart_analysis": {"ema_trend": "SIDEWAYS", "action_summary": "WATCH"},
        "higher_timeframe": {"bias": "NEUTRAL", "adx": 10},
        "smart_money": {"structure": {"structure": "BEARISH", "last_bos": "BULLISH"}},
        "historical_pulse": {"statistical_bias": "NEUTRAL"},
        "whale_pulse": {"bias": "BEARISH"},
        "retail_fomo": {"institutional_bias": "BULLISH"},
        "ema": {"signal": "NEUTRAL"},
    }

    result = primitives._derive_trade_signal(analysis, {})

    assert result["action"] == "HOLD"
    assert result["blockers"]
    assert result["ml_probability"] is None


def test_derive_trade_signal_returns_sell_when_bearish_confluence():
    analysis = {
        "chart_analysis": {"ema_trend": "BEARISH", "action_summary": "SELL_ZONE"},
        "higher_timeframe": {"bias": "BEARISH", "adx": 30},
        "smart_money": {"structure": {"structure": "BEARISH", "last_bos": "BEARISH"}},
        "historical_pulse": {"statistical_bias": "BEARISH"},
        "whale_pulse": {"bias": "BEARISH"},
        "retail_fomo": {"institutional_bias": "BEARISH"},
        "ema": {"signal": "BEARISH"},
    }
    ml_stats = {"side": "SELL", "neural_win_probability": 0.68, "edge_score": 0.75}

    result = primitives._derive_trade_signal(analysis, ml_stats)

    assert result["action"] == "SELL"
    assert result["bias"] == "BEARISH"


def test_build_chart_analysis_returns_empty_on_missing_columns():
    frame = pd.DataFrame([{"High": 1}, {"High": 2}])

    assert primitives._build_chart_analysis(frame) == {}


def test_build_chart_analysis_covers_bearish_and_sell_zone_paths():
    frame = pd.DataFrame(
        [
            {
                "rsi_14": 60,
                "macd_hist": 0.3,
                "ema_20": 105,
                "ema_50": 104,
                "ema_200": 103,
                "Close": 106,
                "High": 106,
                "Low": 95,
                "atr_14": 2,
            },
            {
                "rsi_14": 75,
                "macd_hist": -0.4,
                "ema_20": 102,
                "ema_50": 103,
                "ema_200": 104,
                "Close": 105,
                "High": 108,
                "Low": 96,
                "atr_14": 2.5,
            },
        ]
    )

    result = primitives._build_chart_analysis(frame)

    assert result["rsi"]["signal"].startswith("OVERBOUGHT")
    assert result["macd"]["signal"].startswith("BEARISH_CROSS")
    assert result["ema_trend"].startswith("SIDEWAYS")
    assert result["action_summary"].startswith("SELL_ZONE")


def test_build_chart_analysis_covers_bullish_momentum_and_bearish_trend():
    frame = pd.DataFrame(
        [
            {
                "rsi_14": 50,
                "macd_hist": 0.2,
                "ema_20": 100,
                "ema_50": 101,
                "ema_200": 102,
                "Close": 99,
                "High": 103,
                "Low": 94,
                "atr_14": 1.5,
            },
            {
                "rsi_14": 45,
                "macd_hist": 0.4,
                "ema_20": 98,
                "ema_50": 99,
                "ema_200": 100,
                "Close": 97,
                "High": 102,
                "Low": 93,
                "atr_14": 1.6,
            },
        ]
    )

    result = primitives._build_chart_analysis(frame)

    assert result["macd"]["signal"] == "BULLISH_MOMENTUM"
    assert result["ema_trend"].startswith("BEARISH")


def test_build_chart_analysis_returns_empty_when_comparison_raises(monkeypatch):
    frame = pd.DataFrame(
        [
            {"rsi_14": 50, "macd_hist": 0.1, "ema_20": 1, "ema_50": 1, "ema_200": 1, "Close": 1, "High": 1, "Low": 1, "atr_14": 1},
            {"rsi_14": object(), "macd_hist": 0.2, "ema_20": 1, "ema_50": 1, "ema_200": 1, "Close": 1, "High": 1, "Low": 1, "atr_14": 1},
        ]
    )

    monkeypatch.setattr(primitives, "_safe_num", lambda value, default=None, digits=4: value)

    assert primitives._build_chart_analysis(frame) == {}


def test_calculate_trade_pnl_for_buy_and_sell_paths():
    buy = primitives.calculate_trade_pnl("gold", "buy", 1.0, 2000.0, 2005.0, account_balance=10000)
    sell = primitives.calculate_trade_pnl("eurusd", "sell", 0.5, 1.10, 1.08)

    assert buy["pnl_usd"] == 500.0
    assert buy["pct_of_balance"] == 5.0
    assert buy["balance_after"] == 10500.0
    assert sell["pnl_usd"] == 1000.0
    assert sell["direction"] == "profit"


def test_calculate_trade_pnl_rejects_invalid_action():
    result = primitives.calculate_trade_pnl("BTCUSD", "hold", 1.0, 100, 101)

    assert result == {"error": "Invalid action: hold. Must be BUY or SELL."}


def test_derive_trade_signal_covers_undecided_ml_and_mid_confluence_paths():
    analysis = {
        "chart_analysis": {"ema_trend": "BULLISH", "action_summary": "BUY_ZONE"},
        "higher_timeframe": {"bias": "BULLISH", "adx": 20},
        "smart_money": {"structure": {"structure": "BULLISH", "last_bos": "NEUTRAL"}},
        "historical_pulse": {"statistical_bias": "NEUTRAL"},
        "whale_pulse": {"bias": "NEUTRAL"},
        "retail_fomo": {"institutional_bias": "NEUTRAL"},
        "ema": {"signal": "NEUTRAL"},
    }

    undecided = primitives._derive_trade_signal(
        analysis,
        {"side": "BUY", "neural_win_probability": 0.50, "edge_score": 0.52},
    )
    assert "ML probability is undecided at 0.50" in undecided["blockers"]
    assert undecided["action"] == "BUY"

    mid_confluence = primitives._derive_trade_signal(
        analysis,
        {"side": "BUY", "neural_win_probability": 0.61, "edge_score": 0.55},
    )
    assert mid_confluence["action"] == "BUY"

    second_branch = primitives._derive_trade_signal(
        {
            "chart_analysis": {"ema_trend": "BULLISH", "action_summary": "WATCH"},
            "higher_timeframe": {"bias": "BULLISH", "adx": 20},
            "smart_money": {"structure": {"structure": "NEUTRAL", "last_bos": "NEUTRAL"}},
            "historical_pulse": {"statistical_bias": "NEUTRAL"},
            "whale_pulse": {"bias": "NEUTRAL"},
            "retail_fomo": {"institutional_bias": "NEUTRAL"},
            "ema": {"signal": "NEUTRAL"},
        },
        {"side": "BUY", "neural_win_probability": 0.60, "edge_score": 0.51},
    )
    assert second_branch["action"] == "BUY"

    third_branch = primitives._derive_trade_signal(
        {
            "chart_analysis": {"ema_trend": "NEUTRAL", "action_summary": "WATCH"},
            "higher_timeframe": {"bias": "BULLISH", "adx": 20},
            "smart_money": {"structure": {"structure": "BULLISH", "last_bos": "BEARISH"}},
            "historical_pulse": {"statistical_bias": "NEUTRAL"},
            "whale_pulse": {"bias": "BEARISH"},
            "retail_fomo": {"institutional_bias": "BEARISH"},
            "ema": {"signal": "NEUTRAL"},
        },
        {"side": "NEUTRAL", "neural_win_probability": 0.60, "edge_score": 0.50},
    )
    assert third_branch["action"] == "BUY"


def test_calculate_trade_pnl_covers_loss_and_exception_paths(monkeypatch):
    loss = primitives.calculate_trade_pnl("eurusd", "buy", 0.5, 1.10, 1.08)
    assert loss["direction"] == "loss"

    errors = []
    monkeypatch.setattr(primitives.logger, "error", lambda message, exc: errors.append((message, str(exc))))

    broken = primitives.calculate_trade_pnl(None, "buy", 1.0, 100, 101)

    assert broken == {"error": "'NoneType' object has no attribute 'strip'"}
    assert errors == [("Error in calculate_trade_pnl: %s", "'NoneType' object has no attribute 'strip'")]
