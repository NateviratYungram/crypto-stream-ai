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
    smc_context: Dict = None,
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
    d_trend     = float(dc.get("d_trend", 0.0))
    d_rsi       = float(dc.get("d_rsi", 50.0))
    d_ema_align = float(dc.get("d_ema_align", 0.5))

    # ── Rate of Change (momentum at 3 and 10 bars) ───────────────────────────
    roc_3 = roc_10 = 0.0
    if idx >= 10 and "Close" in df.columns:
        p3  = float(df["Close"].iloc[idx - 3]  or price)
        p10 = float(df["Close"].iloc[idx - 10] or price)
        roc_3  = (price - p3)  / p3  * 100 if p3  > 0 else 0.0
        roc_10 = (price - p10) / p10 * 100 if p10 > 0 else 0.0
    roc_3  = float(np.clip(roc_3,  -20.0, 20.0))
    roc_10 = float(np.clip(roc_10, -20.0, 20.0))

    # ── RSI slope — momentum of momentum ─────────────────────────────────────
    rsi_slope_5 = 0.0
    if idx >= 5 and "rsi_14" in df.columns:
        prev_rsi = df["rsi_14"].iloc[idx - 5]
        if not np.isnan(float(prev_rsi)):
            rsi_slope_5 = float(np.clip(rsi - float(prev_rsi), -30.0, 30.0))

    # ── ATR direction — is volatility expanding or contracting? ──────────────
    atr_direction = 0.0
    if idx >= 5 and "atr_14" in df.columns and atr > 0:
        prev_atr = float(df["atr_14"].iloc[idx - 5] or atr)
        if prev_atr > 0:
            atr_direction = 1.0 if atr > prev_atr * 1.05 else (-1.0 if atr < prev_atr * 0.95 else 0.0)

    # ── Price position in 20-bar High/Low channel ─────────────────────────────
    channel_pct_20 = 0.5
    lookback = min(20, idx)
    if lookback >= 5 and "High" in df.columns and "Low" in df.columns:
        ch_high = float(df["High"].iloc[idx - lookback : idx + 1].max())
        ch_low  = float(df["Low"].iloc[idx - lookback  : idx + 1].min())
        ch_range = ch_high - ch_low
        if ch_range > 0:
            channel_pct_20 = float(np.clip((price - ch_low) / ch_range, 0.0, 1.0))

    # ── Trend bar ratio — fraction of last 5 bars that closed up ─────────────
    trend_bar_ratio = 0.5
    if idx >= 5 and "Close" in df.columns:
        closes_5 = df["Close"].iloc[idx - 5 : idx + 1].values
        ups = sum(1 for i in range(1, len(closes_5)) if closes_5[i] > closes_5[i - 1])
        trend_bar_ratio = float(ups) / max(len(closes_5) - 1, 1)

    # ── MACD histogram sign ───────────────────────────────────────────────────
    macd_hist_sign = 1.0 if macd_hist > 0 else (-1.0 if macd_hist < 0 else 0.0)

    # ── ADX slope — is trend accelerating or fading? ─────────────────────────
    adx_slope_5 = 0.0
    if idx >= 5 and "adx_14" in df.columns:
        prev_adx = df["adx_14"].iloc[idx - 5]
        if not np.isnan(float(prev_adx)):
            adx_slope_5 = float(np.clip(adx - float(prev_adx), -30.0, 30.0))

    # ── RSI Divergence — price vs RSI direction mismatch ─────────────────────
    # +1 = bullish divergence (price lower low, RSI higher low)
    # -1 = bearish divergence (price higher high, RSI lower high)
    #  0 = no divergence
    rsi_divergence = 0.0
    if idx >= 10 and "rsi_14" in df.columns and "Close" in df.columns:
        p_now  = price
        p_back = float(df["Close"].iloc[idx - 10] or price)
        r_now  = rsi
        r_back = float(df["rsi_14"].iloc[idx - 10] or rsi)
        if not np.isnan(r_back):
            price_falling = p_now < p_back * 0.995
            price_rising  = p_now > p_back * 1.005
            rsi_rising    = r_now > r_back + 1.0
            rsi_falling   = r_now < r_back - 1.0
            if price_falling and rsi_rising:
                rsi_divergence = 1.0   # bullish divergence
            elif price_rising and rsi_falling:
                rsi_divergence = -1.0  # bearish divergence

    # ── Bollinger Band squeeze — BB width vs 20-bar BB-width average ──────────
    # Low bb_squeeze_ratio → tight bands → breakout imminent
    bb_squeeze_ratio = 1.0
    if idx >= 20 and "bb_upper" in df.columns and "bb_lower" in df.columns:
        current_width = bb_upper - bb_lower
        widths = []
        for j in range(idx - 20, idx):
            bu = float(df["bb_upper"].iloc[j] or 0)
            bl = float(df["bb_lower"].iloc[j] or 0)
            if bu > bl:
                widths.append(bu - bl)
        if widths and np.mean(widths) > 0 and current_width > 0:
            bb_squeeze_ratio = float(np.clip(current_width / np.mean(widths), 0.1, 3.0))

    # ── Price structure — higher highs/lower lows (trend structure) ───────────
    # +1 = HH + HL (uptrend structure)
    # -1 = LH + LL (downtrend structure)
    #  0 = no clear structure
    price_structure = 0.0
    if idx >= 10 and "High" in df.columns and "Low" in df.columns:
        idx - 5
        h_recent  = float(df["High"].iloc[idx - 4 : idx + 1].max())
        h_earlier = float(df["High"].iloc[idx - 10 : idx - 4].max())
        l_recent  = float(df["Low"].iloc[idx - 4 : idx + 1].min())
        l_earlier = float(df["Low"].iloc[idx - 10 : idx - 4].min())
        if h_recent > h_earlier and l_recent > l_earlier:
            price_structure = 1.0   # higher highs + higher lows
        elif h_recent < h_earlier and l_recent < l_earlier:
            price_structure = -1.0  # lower highs + lower lows

    # ── BB position extremes — overbought/oversold on BB ─────────────────────
    bb_extreme = 0.0
    if bb_pct >= 0.95:
        bb_extreme = 1.0   # touching upper band
    elif bb_pct <= 0.05:
        bb_extreme = -1.0  # touching lower band

    # ── SMC / ICT features ────────────────────────────────────────────────────
    _smc = smc_context or {}
    _struct = _smc.get("structure") or {}
    _struct_str = str(_struct.get("structure", "NEUTRAL")).upper()
    smc_structure  = 1.0 if _struct_str == "BULLISH" else (-1.0 if _struct_str == "BEARISH" else 0.0)
    _bos = str(_struct.get("last_bos") or "").upper()
    smc_bos        = 1.0 if _bos == "BULLISH_BOS" else (-1.0 if _bos == "BEARISH_BOS" else 0.0)
    smc_choch      = 1.0 if bool(_struct.get("choch", False)) else 0.0

    _ob = _smc.get("nearest_ob") or {}
    _ob_type = str(_ob.get("type", "")).upper()
    smc_ob_type    = 1.0 if "BULLISH" in _ob_type else (-1.0 if "BEARISH" in _ob_type else 0.0)
    _ob_mid = (float(_ob.get("top", price) or price) + float(_ob.get("bottom", price) or price)) / 2.0 if _ob else price
    smc_ob_dist    = float(np.clip((price - _ob_mid) / max(_ob_mid, 1e-9) * 100, -20.0, 20.0)) if _ob else 0.0

    _fvg = _smc.get("nearest_fvg") or {}
    _fvg_type = str(_fvg.get("type", "")).upper()
    smc_fvg_type   = 1.0 if "BULLISH" in _fvg_type else (-1.0 if "BEARISH" in _fvg_type else 0.0)
    _fvg_mid = (float(_fvg.get("top", price) or price) + float(_fvg.get("bottom", price) or price)) / 2.0 if _fvg else price
    smc_fvg_dist   = float(np.clip((price - _fvg_mid) / max(_fvg_mid, 1e-9) * 100, -20.0, 20.0)) if _fvg else 0.0

    _sw = _smc.get("sweeps") or {}
    smc_sweep      = 1.0 if bool(_sw.get("sweep_detected", False)) else 0.0
    _sw_type = str(_sw.get("type") or "").upper()
    smc_sweep_dir  = 1.0 if "BULLISH" in _sw_type else (-1.0 if "BEARISH" in _sw_type else 0.0)

    # ── SMC interaction features ──────────────────────────────────────────────
    # OB type × proximity: rewards being inside a matching OB (0-1 scale)
    smc_ob_zone_quality = smc_ob_type * max(0.0, 1.0 - abs(smc_ob_dist) / 20.0)
    # Structure × daily trend agreement: strongest when both align
    smc_structure_htf   = smc_structure * d_trend

    # ── Lag features (give tree models sequential context) ────────────────────
    rsi_lag3 = 0.0
    if idx >= 3 and "rsi_14" in df.columns:
        v = df["rsi_14"].iloc[idx - 3]
        if not np.isnan(float(v)):
            rsi_lag3 = float(np.clip(float(v) - 50.0, -50.0, 50.0))

    adx_lag5 = adx  # default to current if not enough history
    if idx >= 5 and "adx_14" in df.columns:
        v = df["adx_14"].iloc[idx - 5]
        if not np.isnan(float(v)):
            adx_lag5 = float(v)

    macd_hist_lag5 = 0.0
    if idx >= 5 and "macd_hist" in df.columns and atr > 0:
        v = df["macd_hist"].iloc[idx - 5]
        if not np.isnan(float(v)):
            macd_hist_lag5 = float(np.clip(float(v) / atr, -5.0, 5.0))

    channel_pct_lag5 = channel_pct_20  # default to current
    if idx >= 5 and "High" in df.columns and "Low" in df.columns:
        lookback5 = min(20, idx - 5)
        if lookback5 >= 5:
            ch5_high = float(df["High"].iloc[idx - 5 - lookback5 : idx - 5 + 1].max())
            ch5_low  = float(df["Low"].iloc[idx - 5 - lookback5  : idx - 5 + 1].min())
            ch5_range = ch5_high - ch5_low
            p5 = float(df["Close"].iloc[idx - 5] or price)
            if ch5_range > 0:
                channel_pct_lag5 = float(np.clip((p5 - ch5_low) / ch5_range, 0.0, 1.0))

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
        # ── New high-signal features ─────────────────────────────────────────
        "roc_3":           roc_3,
        "roc_10":          roc_10,
        "rsi_slope_5":     rsi_slope_5,
        "atr_direction":   atr_direction,
        "channel_pct_20":  channel_pct_20,
        "trend_bar_ratio": trend_bar_ratio,
        "macd_hist_sign":  macd_hist_sign,
        "adx_slope_5":     adx_slope_5,
        "rsi_divergence":  rsi_divergence,
        "bb_squeeze_ratio": bb_squeeze_ratio,
        "price_structure": price_structure,
        "bb_extreme":      bb_extreme,
        # SMC / ICT
        "smc_structure":        smc_structure,
        "smc_bos":              smc_bos,
        "smc_choch":            smc_choch,
        "smc_ob_type":          smc_ob_type,
        "smc_ob_dist":          smc_ob_dist,
        "smc_fvg_type":         smc_fvg_type,
        "smc_fvg_dist":         smc_fvg_dist,
        "smc_sweep":            smc_sweep,
        "smc_sweep_dir":        smc_sweep_dir,
        # SMC interaction
        "smc_ob_zone_quality":  smc_ob_zone_quality,
        "smc_structure_htf":    smc_structure_htf,
        # Lag features
        "rsi_lag3":             rsi_lag3,
        "adx_lag5":             adx_lag5,
        "macd_hist_lag5":       macd_hist_lag5,
        "channel_pct_lag5":     channel_pct_lag5,
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
    "roc_3", "roc_10", "rsi_slope_5", "atr_direction",
    "channel_pct_20", "trend_bar_ratio", "macd_hist_sign", "adx_slope_5",
    "rsi_divergence", "bb_squeeze_ratio", "price_structure", "bb_extreme",
    # SMC / ICT
    "smc_structure", "smc_bos", "smc_choch",
    "smc_ob_type", "smc_ob_dist",
    "smc_fvg_type", "smc_fvg_dist",
    "smc_sweep", "smc_sweep_dir",
    # SMC interaction
    "smc_ob_zone_quality", "smc_structure_htf",
    # Lag features
    "rsi_lag3", "adx_lag5", "macd_hist_lag5", "channel_pct_lag5",
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
