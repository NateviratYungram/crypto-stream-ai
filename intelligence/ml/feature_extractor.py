# -*- coding: utf-8 -*-
"""
ML Feature Extractor
Converts a DataFrame row (with indicators) into a flat feature dict
suitable for training / inference with the signal model.
"""
from typing import Dict

import numpy as np
import pandas as pd

REGIME_MAP = {"TRENDING": 2, "TRANSITIONING": 1, "RANGING": 0}
SIDE_MAP   = {"BUY": 1, "LONG": 1, "SELL": 0, "SHORT": 0}


def compute_hurst_exponent(series: pd.Series, window: int = 20) -> float:
    """
    Simplified Hurst Exponent calculation based on R/S analysis.
    H > 0.5: Trending (Persistent)
    H < 0.5: Mean Reverting (Anti-persistent)
    H = 0.5: Random Walk
    """
    if len(series) < window:
        return 0.5

    # Use log returns
    vals = np.log(series / series.shift(1)).dropna().values[-window:]
    if len(vals) < 5:
        return 0.5

    # Simplified R/S: Range of cumulative deviations / Standard Deviation
    mean_val = np.mean(vals)
    cum_dev  = np.cumsum(vals - mean_val)
    r = np.max(cum_dev) - np.min(cum_dev)
    s = np.std(vals)

    if s == 0:
        return 0.5
    res = r / s

    # Hurst ~ log(R/S) / log(n)
    h = np.log(res) / np.log(window)
    return float(np.clip(h, 0.0, 1.0))

def compute_volatility_skew(series: pd.Series, window: int = 20) -> float:
    """
    Measures the skewness of log returns.
    Positive: Tail of higher returns (Bullish bias)
    Negative: Tail of lower returns (Bearish/Crash bias)
    """
    if len(series) < window:
        return 0.0
    returns = np.log(series / series.shift(1)).dropna().values[-window:]
    if len(returns) < 5:
        return 0.0

    # Skewness calculation
    mean = np.mean(returns)
    std  = np.std(returns)
    if std == 0:
        return 0.0

    skew = np.mean((returns - mean)**3) / (std**3)
    return float(np.clip(skew, -5.0, 5.0))

def extract_features(
    df: pd.DataFrame,
    idx: int,
    side: str = "BUY",
    symbol: str = "UNKNOWN",
    asset_class: str = "CRYPTO",
    sentiment_score: float = 0.0,
    daily_context: Dict[str, float] = None,
) -> Dict[str, float]:
    """
    Extract ML features from df at row `idx`.

    Required indicator columns (from technical_engine.compute_indicators):
      rsi_14, adx_14, atr_14, macd, macd_signal, macd_hist,
      ema_20, ema_50, ema_200, bb_upper, bb_lower, bb_mid, regime

    Returns a flat dict of float features, safe to pass directly to
    sklearn predict / a DataFrame row.
    """
    row   = df.iloc[idx]
    price = float(row["Close"])
    if price <= 0:
        price = 1.0

    def _f(key: str, default: float = 0.0) -> float:
        v = row.get(key, default)
        return float(v) if (v is not None and not (isinstance(v, float) and np.isnan(v))) else default

    # ── Core oscillators ────────────────────────────────────────────────────
    rsi  = _f("rsi_14", 50.0)
    adx  = _f("adx_14", 20.0)
    atr  = _f("atr_14", 0.0)
    atr_pct = (atr / price * 100) if price > 0 else 0.0

    # ── EMA distances (% from price) ────────────────────────────────────────
    ema20  = _f("ema_20",  price)
    ema50  = _f("ema_50",  price)
    ema200 = _f("ema_200", price)

    price_vs_ema20  = (price - ema20)  / ema20  * 100 if ema20  > 0 else 0.0
    price_vs_ema50  = (price - ema50)  / ema50  * 100 if ema50  > 0 else 0.0
    price_vs_ema200 = (price - ema200) / ema200 * 100 if ema200 > 0 else 0.0
    ema20_vs_ema50  = (ema20 - ema50)  / ema50  * 100 if ema50  > 0 else 0.0

    # Full alignment: 1 = bullish stack, -1 = bearish stack, 0 = mixed
    bullish_align = 1.0 if (price > ema20 > ema50 > ema200) else 0.0
    bearish_align = 1.0 if (price < ema20 < ema50 < ema200) else 0.0

    # ── EMA20 slope (5-bar change) ───────────────────────────────────────────
    ema20_slope = 0.0
    if idx >= 5:
        prev_ema20 = float(df["ema_20"].iloc[idx - 5] or ema20)
        ema20_slope = (ema20 - prev_ema20) / prev_ema20 * 100 if prev_ema20 > 0 else 0.0

    # ── MACD histogram (ATR-normalised) ─────────────────────────────────────
    macd_hist = _f("macd_hist", 0.0)
    macd_hist_norm = (macd_hist / atr) if atr > 0 else 0.0

    # ── Bollinger Band position [0=lower, 1=upper] ──────────────────────────
    bb_upper = _f("bb_upper", price * 1.02)
    bb_lower = _f("bb_lower", price * 0.98)
    bb_width = bb_upper - bb_lower
    bb_pct   = ((price - bb_lower) / bb_width) if bb_width > 0 else 0.5

    # ── Volume ratio (vs 20-bar mean) ────────────────────────────────────────
    vol = _f("Volume", 1.0)
    if idx >= 20 and "Volume" in df.columns:
        vol_mean = float(df["Volume"].iloc[idx - 20:idx].mean() or 1.0)
        vol_ratio = vol / vol_mean if vol_mean > 0 else 1.0
    else:
        vol_ratio = 1.0
    vol_ratio = min(vol_ratio, 10.0)  # cap outliers

    # ── Regime encoding ──────────────────────────────────────────────────────
    regime_str = str(row.get("regime", "RANGING")).upper()
    regime_enc = float(REGIME_MAP.get(regime_str, 0))

    # ── Time features ────────────────────────────────────────────────────────
    ts = df.index[idx]
    if hasattr(ts, "hour"):
        hour  = float(ts.hour)
        dow   = float(ts.dayofweek)
        h     = ts.hour
        if 7 <= h < 16:
            session = 1.0   # London
        elif 13 <= h < 22:
            session = 2.0  # NY
        elif 0 <= h < 8:
            session = 0.0  # Asia
        else:
            session = 3.0  # Off-hours
    else:
        hour = dow = 0.0
        session = 3.0

    # ── Asset class encoding ─────────────────────────────────────────────────
    ac_map = {"CRYPTO": 0.0, "MACRO": 1.0, "STOCK": 2.0}
    asset_class_enc = ac_map.get(asset_class.upper(), 0.0)

    # ── Direction ────────────────────────────────────────────────────────────
    side_enc = float(SIDE_MAP.get(side.upper(), 1))

    # ── Fractal Multi-Scale Efficiency ──────────────────────────────────────
    close_series = df["Close"].iloc[max(0, idx-100):idx+1]
    hurst = compute_hurst_exponent(close_series, window=30)
    v_skew = compute_volatility_skew(close_series, window=30)

    # ── Daily trend context (multi-timeframe) ────────────────────────────────
    dc = daily_context or {}
    d_trend     = float(dc.get("d_trend", 0.0))    # % price vs daily EMA50 (clipped ±20)
    d_rsi       = float(dc.get("d_rsi", 50.0))     # daily RSI-14
    d_ema_align = float(dc.get("d_ema_align", 0.5)) # 1.0 = above daily EMA200, 0.0 = below

    return {
        "rsi":            rsi,
        "adx":            adx,
        "atr_pct":        atr_pct,
        "price_vs_ema20": price_vs_ema20,
        "price_vs_ema50": price_vs_ema50,
        "price_vs_ema200":price_vs_ema200,
        "ema20_vs_ema50": ema20_vs_ema50,
        "ema20_slope":    ema20_slope,
        "bullish_align":  bullish_align,
        "bearish_align":  bearish_align,
        "macd_hist_norm": macd_hist_norm,
        "bb_pct":         bb_pct,
        "vol_ratio":      vol_ratio,
        "regime_enc":     regime_enc,
        "hour":           hour,
        "dow":            dow,
        "session":        session,
        "asset_class_enc":asset_class_enc,
        "side_enc":       side_enc,
        "sentiment_score":sentiment_score,
        "cmf":           _f("cmf_20", 0.0),
        "rvi":           _f("rvi_14", 50.0),
        "hurst_exponent":  hurst,
        "vol_skew":        v_skew,
        "d_trend":         d_trend,
        "d_rsi":           d_rsi,
        "d_ema_align":     d_ema_align,
    }


FEATURE_COLS = [
    "rsi", "adx", "atr_pct",
    "price_vs_ema20", "price_vs_ema50", "price_vs_ema200",
    "ema20_vs_ema50", "ema20_slope",
    "bullish_align", "bearish_align",
    "macd_hist_norm", "bb_pct", "vol_ratio",
    "regime_enc", "hour", "dow", "session",
    "asset_class_enc", "side_enc", "sentiment_score",
    "cmf", "rvi", "hurst_exponent", "vol_skew",
    "d_trend", "d_rsi", "d_ema_align",
]


def extract_sequence_features(
    df: pd.DataFrame,
    idx: int,
    window: int = 10,
    side: str = "BUY",
    symbol: str = "UNKNOWN",
    asset_class: str = "CRYPTO",
    sentiment_score: float = 0.0,
) -> np.ndarray:
    """
    Extract a 2D sequence of features [window, len(FEATURE_COLS)] for Deep Learning.
    Returns a numpy array of shape (window, num_features).
    """
    if idx < window - 1:
        # Pad with the first available features if not enough history
        base_feat = extract_features(df, idx, side, symbol, asset_class, sentiment_score)
        flat = np.array([base_feat[col] for col in FEATURE_COLS])
        return np.tile(flat, (window, 1))

    sequence = []
    for i in range(idx - window + 1, idx + 1):
        feat = extract_features(df, i, side, symbol, asset_class, sentiment_score)
        sequence.append([feat[col] for col in FEATURE_COLS])

    return np.array(sequence, dtype=np.float32)
