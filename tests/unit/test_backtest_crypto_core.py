from types import SimpleNamespace

import pandas as pd

from intelligence import backtest_crypto as btc


def _signal_df():
    return pd.DataFrame(
        {
            "Close": [100.0, 101.0, 102.0, 103.0, 104.0],
            "High": [101.0, 102.0, 103.0, 104.0, 105.0],
            "Low": [99.0, 100.0, 101.0, 102.0, 103.0],
            "macd": [-1.0, 1.0, 0.5, 0.1, -0.5],
            "macd_signal": [0.0, 0.0, 0.2, 0.0, 0.0],
            "rsi_14": [50.0, 50.0, 30.0, 50.0, 80.0],
            "ema_20": [99.0, 100.0, 101.0, 103.0, 105.0],
            "ema_50": [98.0, 99.0, 100.0, 102.0, 106.0],
            "adx_14": [10.0, 30.0, 15.0, 22.0, 30.0],
            "hurst_100": [0.50, 0.60, 0.40, 0.50, 0.60],
            "atr_14": [1.0, 1.0, 1.0, 1.0, 1.0],
        }
    )


def test_bps_slippage_and_regime_helpers():
    assert btc._bps_to_rate(5) == 0.0005
    assert btc._bps_to_rate(-1) == 0.0
    assert btc._bps_to_rate("bad") == 0.0

    assert btc._apply_slippage(100.0, 1, True, 0.01) == 101.0
    assert btc._apply_slippage(100.0, 1, False, 0.01) == 99.0
    assert btc._apply_slippage(100.0, -1, True, 0.01) == 99.0
    assert btc._apply_slippage(100.0, -1, False, 0.01) == 101.0

    params = {"adx_trending_threshold": 25, "adx_ranging_threshold": 20}
    assert btc._classify_regime(30, params) == "TRENDING"
    assert btc._classify_regime(10, params) == "RANGING"
    assert btc._classify_regime(22, params) == "TRANSITIONING"


def test_generate_backtest_signals_handles_missing_and_ml_paths(monkeypatch):
    assert btc.generate_backtest_signals(pd.DataFrame({"Close": [1, 2, 3]})).empty

    monkeypatch.setattr(btc, "extract_features", lambda df, idx, side, asset_class="crypto": {"idx": idx, "side": side, "asset_class": asset_class})
    monkeypatch.setattr(btc, "predict_win_probability", lambda feats: {"win_pct": 77})

    df = btc.generate_backtest_signals(_signal_df(), params={"use_ml_filter": True}, asset_class="crypto")

    assert list(df["signal"]) == [0, 1, 0, 0, -1]
    assert list(df["regime"]) == ["RANGING", "TRENDING", "RANGING", "TRANSITIONING", "TRENDING"]
    assert df.loc[1, "ml_edge"] == 77
    assert df.loc[4, "ml_edge"] == 77


def test_generate_backtest_signals_respects_hard_blocks_and_regime_filters():
    df = pd.DataFrame(
        {
            "Close": [100.0, 101.0, 99.0, 100.0],
            "High": [101.0, 102.0, 100.0, 101.0],
            "Low": [99.0, 100.0, 98.0, 99.0],
            "macd": [-1.0, 1.0, 0.0, -1.0],
            "macd_signal": [0.0, 0.0, 0.0, 0.0],
            "rsi_14": [50.0, 90.0, 20.0, 50.0],
            "ema_20": [99.0, 100.0, 100.0, 99.0],
            "ema_50": [98.0, 99.0, 101.0, 100.0],
            "adx_14": [30.0, 30.0, 15.0, 30.0],
            "hurst_100": [0.60, 0.60, 0.60, 0.40],
            "atr_14": [1.0, 1.0, 1.0, 1.0],
        }
    )

    result = btc.generate_backtest_signals(df)

    assert result["signal"].sum() == 0


def test_simulate_trades_covers_no_trades_success_and_ambiguous_bar():
    assert btc.simulate_trades(pd.DataFrame()).get("error")

    no_trades = btc.simulate_trades(pd.DataFrame({"signal": [0], "atr_14": [1.0], "Close": [100.0], "High": [101.0], "Low": [99.0]}))
    assert no_trades["status"] == "no_trades"

    long_df = pd.DataFrame(
        [
            {"Close": 100.0, "High": 100.0, "Low": 100.0, "atr_14": 10.0, "adx_14": 35.0, "signal": 1, "regime": "TRENDING"},
            {"Close": 102.0, "High": 150.0, "Low": 101.0, "atr_14": 10.0, "adx_14": 35.0, "signal": 0, "regime": "TRENDING"},
        ]
    )
    success = btc.simulate_trades(
        long_df,
        initial_balance=100.0,
        risk_pct=2.0,
        leverage=1.0,
        use_trailing_stop=False,
        timeframe="1h",
        sl_atr_mult=1.0,
        tp1_atr_mult=1.0,
        tp2_atr_mult_base=2.0,
        fee_bps=0.0,
        slippage_bps=0.0,
    )
    assert success["status"] == "success"
    assert success["wins"] == 1
    assert success["exits_tp"] == 1
    assert success["regime_breakdown"] == {"TRENDING": 1}

    ambiguous_df = pd.DataFrame(
        [
            {"Close": 100.0, "High": 100.0, "Low": 100.0, "atr_14": 10.0, "adx_14": 35.0, "signal": 1, "regime": "TRENDING"},
            {"Close": 100.0, "High": 140.0, "Low": 80.0, "atr_14": 10.0, "adx_14": 35.0, "signal": 0, "regime": "TRENDING"},
        ]
    )
    ambiguous = btc.simulate_trades(
        ambiguous_df,
        initial_balance=100.0,
        risk_pct=2.0,
        leverage=1.0,
        use_trailing_stop=False,
        timeframe="1h",
        sl_atr_mult=1.0,
        tp1_atr_mult=1.0,
        tp2_atr_mult_base=2.0,
        fee_bps=0.0,
        slippage_bps=0.0,
    )
    assert ambiguous["status"] == "success"
    assert ambiguous["losses"] == 1
    assert ambiguous["exits_sl"] == 1


def test_run_crypto_backtest_success_and_error_paths(monkeypatch):
    monkeypatch.setattr(btc, "get_kline_data", lambda *args, **kwargs: None)
    assert "No data found" in btc.run_crypto_backtest("BTCUSD")["error"]

    short_df = pd.DataFrame({"Close": [1] * 10})
    monkeypatch.setattr(btc, "get_kline_data", lambda *args, **kwargs: short_df)
    assert "Insufficient data" in btc.run_crypto_backtest("BTCUSD")["error"]

    base_df = pd.DataFrame({"Close": [1] * 40})
    monkeypatch.setattr(btc, "get_kline_data", lambda *args, **kwargs: base_df)
    monkeypatch.setattr(btc, "compute_indicators", lambda df: df.assign(atr_14=1.0))
    monkeypatch.setattr(btc, "generate_backtest_signals", lambda df, params=None, asset_class="crypto": pd.DataFrame({"signal": [1], "atr_14": [1.0]}))
    monkeypatch.setattr(btc, "simulate_trades", lambda df, **kwargs: {"status": "success", "final_balance": 120.0, "total_trades": 3})

    ok = btc.run_crypto_backtest("BTCUSD", timeframe="1h", risk_pct=3.0, leverage=2.0)
    assert ok["symbol"] == "BTCUSD"
    assert ok["timeframe"] == "1h"
    assert ok["candles_analyzed"] == 40
    assert ok["risk_pct"] == 3.0
    assert ok["leverage"] == 2.0


def test_score_optimize_validation_walkforward_and_portfolio(monkeypatch):
    assert btc._score({"status": "error"}) == -9999.0
    assert btc._score({"status": "success", "net_return_pct": 10, "max_drawdown_pct": 2, "profit_factor": 2, "win_rate_pct": 50}) == 81.0

    monkeypatch.setattr(
        btc,
        "get_kline_data",
        lambda *args, **kwargs: pd.DataFrame(
            {"Close": list(range(int(kwargs["limit"] if "limit" in kwargs else (args[2] if len(args) > 2 else 200))))}
        ),
    )
    monkeypatch.setattr(btc, "compute_indicators", lambda df: df)
    monkeypatch.setattr(btc, "generate_backtest_signals", lambda df, params=None, asset_class="crypto": df.assign(signal=1, atr_14=1.0))

    def _sim(df, risk_pct=2.0, leverage=1.0, timeframe="15m", sl_atr_mult=1.5, tp1_atr_mult=2.0, tp2_atr_mult_base=3.0, **kwargs):
        total = 12 if len(df) >= 100 else 6
        return {
            "status": "success",
            "total_trades": total,
            "net_return_pct": round((30 - sl_atr_mult * 10) + (10 if len(df) >= 100 else 5), 2),
            "max_drawdown_pct": round(sl_atr_mult * 5, 2),
            "profit_factor": round(1.0 + max(0.0, 2.0 - sl_atr_mult), 2),
            "win_rate_pct": 55.0,
            "final_balance": 100.0 + len(df) / 10.0,
        }

    monkeypatch.setattr(btc, "simulate_trades", _sim)

    optimized = btc.optimize_backtest("BTCUSD", timeframe="1h", limit=200)
    assert optimized["status"] == "success"
    assert optimized["symbol"] == "BTCUSD"
    assert optimized["train_bars"] == 140
    assert optimized["test_bars"] == 60
    assert optimized["best_params"]["sl_atr_mult"] in [1.2, 1.5, 1.8]

    validation = btc.run_v8_validation("BTCUSD", timeframe="1h", limit=1000)
    assert validation["status"] == "success"

    walk = btc.walk_forward_backtest("BTCUSD", timeframe="1h", limit=1000)
    assert walk["status"] == "success"
    assert walk["windows_run"] > 0
    assert len(walk["equity_curve"]) == walk["windows_run"] + 1

    monkeypatch.setattr(
        btc,
        "run_crypto_backtest",
        lambda sym, timeframe, limit, risk_pct, leverage, params=None, initial_balance=100.0: {
            "status": "success" if sym != "MISS" else "error",
            "symbol": sym,
            "final_balance": initial_balance + 10.0,
            "net_return_pct": 20.0,
            "cagr_pct": 15.0,
            "years_tested": 1.0,
            "total_trades": 5,
            "win_rate_pct": 60.0,
            "profit_factor": 1.8,
            "sharpe_ratio": 1.2,
            "max_drawdown_pct": 5.0,
        },
    )

    portfolio = btc.run_portfolio_backtest(["BTCUSD", "ETHUSD", "MISS"], initial_balance=120.0)
    assert portfolio["status"] == "success"
    assert portfolio["mode"] == "PORTFOLIO"
    assert portfolio["final_balance"] == 140.0
    assert portfolio["total_trades"] == 10
    assert len(portfolio["per_asset"]) == 2

    no_assets = btc.run_portfolio_backtest(["MISS"], initial_balance=100.0)
    assert no_assets["error"] == "No data for any symbol"
