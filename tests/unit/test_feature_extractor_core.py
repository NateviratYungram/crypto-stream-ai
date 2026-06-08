import numpy as np
import pandas as pd

from intelligence.ml.feature_extractor import (
    FEATURE_COLS,
    compute_hurst_exponent,
    compute_volatility_skew,
    extract_features,
    extract_sequence_features,
)


def _feature_frame(rows=36, trend=1.0):
    index = pd.date_range("2025-01-01 13:00:00", periods=rows, freq="h")
    base = np.linspace(100.0, 100.0 + trend * (rows - 1), rows)
    df = pd.DataFrame(
        {
            "Open": base - 0.5,
            "High": base + 2.0,
            "Low": base - 2.0,
            "Close": base,
            "Volume": np.linspace(1000.0, 2000.0, rows),
            "rsi_14": np.linspace(45.0, 65.0, rows),
            "adx_14": np.linspace(18.0, 35.0, rows),
            "atr_14": np.linspace(1.0, 2.0, rows),
            "macd_hist": np.linspace(-0.5, 0.8, rows),
            "ema_20": base - trend * 0.4,
            "ema_50": base - trend * 0.8,
            "ema_200": base - trend * 1.2,
            "bb_upper": base + 4.0,
            "bb_lower": base - 4.0,
            "bb_mid": base,
            "cmf_20": np.linspace(-0.2, 0.2, rows),
            "rvi_14": np.linspace(40.0, 60.0, rows),
            "regime": ["TRENDING"] * rows,
        },
        index=index,
    )
    return df


def test_hurst_and_volatility_skew_use_safe_defaults_for_short_or_flat_data():
    short = pd.Series([100.0, 101.0, 102.0])
    flat = pd.Series([100.0] * 40)

    assert compute_hurst_exponent(short, window=20) == 0.5
    assert compute_hurst_exponent(flat, window=20) == 0.5
    assert compute_volatility_skew(short, window=20) == 0.0
    assert compute_volatility_skew(flat, window=20) == 0.0


def test_hurst_and_volatility_skew_clip_numeric_results():
    series = pd.Series(np.geomspace(100.0, 160.0, 80))

    hurst = compute_hurst_exponent(series, window=30)
    skew = compute_volatility_skew(series, window=30)

    assert 0.0 <= hurst <= 1.0
    assert -5.0 <= skew <= 5.0


def test_extract_features_returns_full_bullish_feature_set_with_context():
    df = _feature_frame()
    smc_context = {
        "structure": {"structure": "BULLISH", "last_bos": "BULLISH_BOS", "choch": True},
        "nearest_ob": {"type": "bullish_ob", "top": 136.0, "bottom": 130.0},
        "nearest_fvg": {"type": "bullish_fvg", "top": 137.0, "bottom": 131.0},
        "sweeps": {"sweep_detected": True, "type": "bullish_sweep"},
    }

    features = extract_features(
        df,
        35,
        side="long",
        asset_class="stock",
        sentiment_score=0.42,
        daily_context={"d_trend": 1.0, "d_rsi": 61.0, "d_ema_align": 1.0},
        smc_context=smc_context,
    )

    assert set(FEATURE_COLS) == set(features)
    assert features["bullish_align"] == 1.0
    assert features["bearish_align"] == 0.0
    assert features["side_enc"] == 1.0
    assert features["asset_class_enc"] == 2.0
    assert features["session"] == 0.0
    assert features["smc_structure"] == 1.0
    assert features["smc_bos"] == 1.0
    assert features["smc_choch"] == 1.0
    assert features["smc_sweep"] == 1.0
    assert features["smc_structure_htf"] == 1.0
    assert features["sentiment_score"] == 0.42


def test_extract_features_handles_bearish_and_edge_defaults():
    df = _feature_frame(trend=-1.0)
    df.loc[df.index[-1], "Close"] = 0.01
    df.loc[df.index[-1], "rsi_14"] = np.nan
    df.loc[df.index[-1], "bb_upper"] = 0.0
    df.loc[df.index[-1], "bb_lower"] = 0.0

    features = extract_features(
        df,
        35,
        side="short",
        asset_class="macro",
        smc_context={
            "structure": {"structure": "BEARISH", "last_bos": "BEARISH_BOS"},
            "nearest_ob": {"type": "bearish_ob", "top": 105.0, "bottom": 95.0},
            "nearest_fvg": {"type": "bearish_fvg", "top": 104.0, "bottom": 94.0},
            "sweeps": {"sweep_detected": True, "type": "bearish_sweep"},
        },
    )

    assert features["rsi"] == 50.0
    assert features["side_enc"] == 0.0
    assert features["asset_class_enc"] == 1.0
    assert features["smc_structure"] == -1.0
    assert features["smc_bos"] == -1.0
    assert features["smc_ob_type"] == -1.0
    assert features["smc_fvg_type"] == -1.0
    assert features["smc_sweep_dir"] == -1.0
    assert features["bb_pct"] == 0.5


def test_extract_sequence_features_pads_when_history_is_short():
    df = _feature_frame(rows=8)

    sequence = extract_sequence_features(df, 3, window=10, side="buy")

    assert sequence.shape == (10, len(FEATURE_COLS))
    assert np.allclose(sequence[0], sequence[-1])


def test_extract_sequence_features_returns_rolling_window():
    df = _feature_frame(rows=24)

    sequence = extract_sequence_features(df, 20, window=6, side="sell")

    assert sequence.shape == (6, len(FEATURE_COLS))
    assert sequence.dtype == np.float32
    assert sequence[0, FEATURE_COLS.index("side_enc")] == 0.0
    assert sequence[-1, FEATURE_COLS.index("side_enc")] == 0.0
