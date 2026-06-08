import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from intelligence import technical_engine as te


def _ohlcv(rows: int = 240, start: float = 100.0, step: float = 0.4) -> pd.DataFrame:
    close = np.array([start + i * step + (i % 5) * 0.15 for i in range(rows)], dtype=float)
    open_ = close - 0.2
    high = close + 0.8
    low = close - 0.9
    volume = np.array([1000 + (i % 10) * 50 for i in range(rows)], dtype=float)
    return pd.DataFrame(
        {
            "Datetime": pd.date_range("2026-01-01", periods=rows, freq="h"),
            "Open": open_,
            "High": high,
            "Low": low,
            "Close": close,
            "Volume": volume,
        }
    )


def test_compute_hurst_exponent_handles_short_flat_and_trending_series():
    assert te.compute_hurst_exponent(pd.Series([1, 2, 3]), window=10) == 0.5
    assert te.compute_hurst_exponent(pd.Series([7.0] * 40), window=30) == 0.5

    hurst = te.compute_hurst_exponent(pd.Series(np.linspace(1, 100, 120)), window=100)
    assert 0.0 <= hurst <= 1.0


def test_dataframe_freshness_checks_timestamp_quality():
    fresh = pd.DataFrame({"Datetime": [pd.Timestamp.now(tz="UTC")]})
    stale = pd.DataFrame({"Datetime": [pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=5)]})

    assert te._is_dataframe_fresh(fresh, "1h") is True
    assert te._is_dataframe_fresh(stale, "1h") is False
    assert te._is_dataframe_fresh(pd.DataFrame({"Close": [1]}), "1h") is False
    assert te._is_dataframe_fresh(None, "1h") is False


def test_get_kline_data_prefers_mt5_when_available(monkeypatch):
    mt5_df = _ohlcv(12)
    monkeypatch.setattr(te, "_MT5_AVAILABLE", True)
    monkeypatch.setattr(te, "mt5_get_rates", lambda symbol, timeframe, count: mt5_df)
    monkeypatch.setattr(te, "_query_market_ohlcv", lambda *args, **kwargs: None)

    result = te.get_kline_data("BTCUSDT", timeframe="15m", limit=12)

    assert result is mt5_df
    assert result.attrs["market_status"] == "OPEN"
    assert "last_update" in result.attrs


def test_get_kline_data_uses_db_cache_before_external_fetch(monkeypatch):
    cached = _ohlcv(20)
    monkeypatch.setattr(te, "_MT5_AVAILABLE", False)
    monkeypatch.setattr(te, "_query_market_ohlcv", lambda *args, **kwargs: cached)

    assert te.get_kline_data("ETH", timeframe="1h", limit=20) is cached


def test_get_kline_data_returns_disabled_ticker_shell(monkeypatch):
    monkeypatch.setattr(te, "_MT5_AVAILABLE", False)
    monkeypatch.setattr(te, "_query_market_ohlcv", lambda *args, **kwargs: None)
    monkeypatch.setattr(te, "YFINANCE_DISABLED_TICKERS", {"NOPE"})
    monkeypatch.setattr(te, "TICKER_ALIASES", {"NOPE": "NOPE"})
    monkeypatch.setattr(te, "SP500_TICKERS", set())
    monkeypatch.setattr(te, "NASDAQ_100_TICKERS", set())
    monkeypatch.setattr(te, "MACRO_MAPPING", {})

    result = te.get_kline_data("NOPE", asset_class="STOCK")

    assert result.iloc[0]["is_speculative"] == True
    assert result.iloc[0]["target_symbol"] == "NOPE"
    assert result.attrs["market_status"] == "NO_DATA"


def test_get_kline_data_normalizes_yfinance_multiindex_and_saves_archive(monkeypatch):
    dates = pd.date_range("2026-01-01", periods=8, freq="D")
    raw = pd.DataFrame(
        {
            ("Open", "AAPL"): range(10, 18),
            ("High", "AAPL"): range(11, 19),
            ("Low", "AAPL"): range(9, 17),
            ("Close", "AAPL"): range(10, 18),
            ("Volume", "AAPL"): range(100, 108),
        },
        index=dates,
    )
    raw.index.name = "Date"
    saved = []

    monkeypatch.setattr(te, "_MT5_AVAILABLE", False)
    monkeypatch.setattr(te, "_query_market_ohlcv", lambda *args, **kwargs: None)
    monkeypatch.setattr(te.archiver, "get_data", lambda *args, **kwargs: None)
    monkeypatch.setattr(te.archiver, "save_data", lambda ticker, timeframe, df: saved.append((ticker, timeframe, len(df))))
    monkeypatch.setattr(te.yf, "download", lambda *args, **kwargs: raw)
    monkeypatch.setattr(te, "SP500_TICKERS", {"AAPL"})
    monkeypatch.setattr(te, "NASDAQ_100_TICKERS", set())

    result = te.get_kline_data("AAPL", timeframe="1d", limit=5, asset_class="STOCK")

    assert list(result.columns) == ["Datetime", "Open", "High", "Low", "Close", "Volume"]
    assert len(result) == 5
    assert result["Close"].iloc[-1] == 17
    assert saved == [("AAPL", "1d", 5)]


def test_get_kline_data_uses_binance_crypto_fallback(monkeypatch):
    class Response:
        status_code = 200

        def json(self):
            base = int(pd.Timestamp("2026-01-01", tz="UTC").timestamp() * 1000)
            return [
                [base + i * 60_000, "1", "3", "0.5", "2", "10", base, "0", 1, "0", "0", "0"]
                for i in range(6)
            ]

    monkeypatch.setattr(te, "_MT5_AVAILABLE", False)
    monkeypatch.setattr(te, "_query_market_ohlcv", lambda *args, **kwargs: None)
    monkeypatch.setattr(te, "_get_pg_engine", lambda: None)
    monkeypatch.setitem(sys.modules, "requests", type("Req", (), {"get": staticmethod(lambda *args, **kwargs: Response())}))

    result = te.get_kline_data("BTC", timeframe="1m", limit=6, asset_class="CRYPTO")

    assert len(result) == 6
    assert result["Close"].tolist() == [2] * 6


def test_compute_indicators_and_summary_cover_bullish_paths():
    df = te.compute_indicators(_ohlcv())

    expected_columns = {
        "rsi_14",
        "macd",
        "macd_signal",
        "stoch_k",
        "willr_14",
        "adx_14",
        "atr_14",
        "bb_upper",
        "ema_20",
        "ema_50",
        "ema_200",
        "volume_sma_20",
        "cmf_20",
        "rvi_14",
        "hurst_100",
        "hurst_30",
        "vwap",
    }
    assert expected_columns.issubset(df.columns)

    summary = te.get_indicator_summary(df, symbol="BTC")
    assert summary["symbol"] == "BTC"
    assert summary["price"] > 0
    assert summary["ema"]["long_term"] in {"BULLISH", "BEARISH"}
    assert "patterns" in summary
    assert "trend_analysis" in summary


def test_indicator_summary_handles_empty_and_speculative_data():
    assert te.get_indicator_summary(pd.DataFrame()) == {}

    shell = pd.DataFrame([{"is_speculative": True, "target_symbol": "XYZ"}])
    summary = te.get_indicator_summary(shell, symbol="XYZ")

    assert summary["status"] == "SPECULATIVE_MODE"
    assert summary["symbol"] == "XYZ"


def test_detect_patterns_covers_reversal_and_continuation_shapes():
    morning_star = pd.DataFrame(
        [
            {"Open": 10, "High": 11, "Low": 9, "Close": 10},
            {"Open": 10, "High": 11, "Low": 9, "Close": 10},
            {"Open": 12, "High": 13, "Low": 8, "Close": 9},
            {"Open": 8.8, "High": 9.2, "Low": 8.5, "Close": 8.9},
            {"Open": 9, "High": 13, "Low": 8.8, "Close": 12},
        ]
    )
    detected = te.detect_patterns(morning_star)["detected"]
    assert "Morning Star (Bullish Reversal)" in detected

    doji_inside = pd.DataFrame(
        [
            {"Open": 10, "High": 11, "Low": 9, "Close": 10.5},
            {"Open": 10.5, "High": 11.5, "Low": 9.5, "Close": 10},
            {"Open": 10, "High": 12, "Low": 8, "Close": 11},
            {"Open": 11, "High": 13, "Low": 7, "Close": 12},
            {"Open": 10, "High": 12.5, "Low": 7.5, "Close": 10.1},
        ]
    )
    detected = te.detect_patterns(doji_inside)["detected"]
    assert "Doji (Indecision)" in detected
    assert "Inside Bar (Consolidation)" in detected


def test_trend_session_and_regime_detection():
    df = _ohlcv(40)
    assert te.analyze_trend_channels(df)["primary_trend"] == "UP"
    assert te.analyze_trend_channels(_ohlcv(5))["status"] == "Insufficient data for trend analysis"

    assert te.detect_session(datetime(2026, 1, 1, 23, tzinfo=timezone.utc)) == "ASIA"
    assert te.detect_session(datetime(2026, 1, 1, 8, tzinfo=timezone.utc)) == "LONDON"
    assert te.detect_session(datetime(2026, 1, 1, 15, tzinfo=timezone.utc)) == "NEW_YORK"
    assert te.detect_session(datetime(2026, 1, 1, 21, tzinfo=timezone.utc)) == "OFF"

    trend_df = df.assign(adx_14=30, atr_14=1.0, bb_upper=120.0, bb_lower=90.0)
    chaos_df = df.assign(adx_14=10, atr_14=[1.0] * 39 + [10.0], bb_upper=120.0, bb_lower=90.0)
    range_df = df.assign(adx_14=10, atr_14=1.0, bb_upper=120.0, bb_lower=90.0)

    assert te.detect_market_regime(trend_df) == "TREND"
    assert te.detect_market_regime(chaos_df) == "CHAOS"
    assert te.detect_market_regime(range_df) == "RANGE"
    assert te.detect_market_regime(pd.DataFrame()) == "UNKNOWN"


def test_smart_money_components_detect_structures_and_zones():
    df = pd.DataFrame(
        [
            {"Open": 10, "High": 11, "Low": 9, "Close": 10},
            {"Open": 10, "High": 12, "Low": 8, "Close": 11},
            {"Open": 11, "High": 15, "Low": 10, "Close": 14},
            {"Open": 14, "High": 13, "Low": 7, "Close": 8},
            {"Open": 8, "High": 12, "Low": 9, "Close": 11},
            {"Open": 11, "High": 14, "Low": 10, "Close": 13},
            {"Open": 13, "High": 16, "Low": 12, "Close": 15},
            {"Open": 15, "High": 13, "Low": 6, "Close": 7},
            {"Open": 7, "High": 11, "Low": 8, "Close": 10},
            {"Open": 10, "High": 15, "Low": 9, "Close": 14},
            {"Open": 14, "High": 18, "Low": 13, "Close": 17},
            {"Open": 17, "High": 15, "Low": 5, "Close": 6},
            {"Open": 6, "High": 12, "Low": 7, "Close": 11},
            {"Open": 11, "High": 16, "Low": 10, "Close": 15},
            {"Open": 15, "High": 19, "Low": 14, "Close": 18},
            {"Open": 18, "High": 17, "Low": 4, "Close": 5},
            {"Open": 5, "High": 13, "Low": 6, "Close": 12},
            {"Open": 12, "High": 17, "Low": 11, "Close": 16},
            {"Open": 16, "High": 20, "Low": 15, "Close": 19},
            {"Open": 19, "High": 23, "Low": 18, "Close": 22},
            {"Open": 22, "High": 26, "Low": 21, "Close": 27},
        ]
    )

    structure = te.detect_market_structure(df, lookback=21)
    assert structure["structure"] in {"BULLISH", "BEARISH", "NEUTRAL"}
    assert te.detect_order_blocks(df)
    assert te.detect_fvg(df)

    pools = te.detect_liquidity_pools(
        pd.DataFrame(
            [
                {"High": 10, "Low": 5, "Close": 8},
                {"High": 10.01, "Low": 5.01, "Close": 8},
                {"High": 12, "Low": 4, "Close": 8},
                {"High": 12.01, "Low": 4.01, "Close": 8},
                {"High": 14, "Low": 6, "Close": 8},
                {"High": 14.01, "Low": 6.01, "Close": 8},
                {"High": 16, "Low": 7, "Close": 8},
                {"High": 16.01, "Low": 7.01, "Close": 8},
                {"High": 18, "Low": 3, "Close": 8},
                {"High": 18.01, "Low": 3.01, "Close": 8},
            ]
        ),
        lookback=10,
        tolerance_pct=0.002,
    )
    assert pools["buy_side"]
    assert pools["sell_side"]

    bullish_sweep = pd.DataFrame(
        [{"High": 12, "Low": 10, "Close": 11}] * 38
        + [{"High": 13, "Low": 9, "Close": 11}, {"High": 12, "Low": 8, "Close": 11}]
    )
    assert te.detect_liquidity_sweeps(bullish_sweep, lookback=40)["type"] == "BULLISH_SWEEP"

    bundle = te.get_smart_money_analysis(df.assign(adx_14=30, atr_14=1, bb_upper=30, bb_lower=1))
    assert {"session", "regime", "structure", "order_blocks", "fvg", "liquidity", "sweeps"}.issubset(bundle)
