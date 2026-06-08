# -*- coding: utf-8 -*-
"""
ML Signal Model — Self-Learning Trade Quality Predictor

Pipeline:
  1. build_ml_dataset()  — run backtests on multiple symbols, collect labeled rows
  2. train_model()       — train GradientBoostingClassifier, save to disk
  3. predict_win_prob()  — given current market features, return WIN probability

The model learns: "given these technical conditions, what is the probability
that this signal will hit TP before SL?"
Integrated V6: Adaptive Retraining & Neural Attention.
"""
import json
import logging
import os
import pickle
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from dotenv import load_dotenv

from .feature_extractor import FEATURE_COLS, extract_features
from .signal_model_support_helpers import (
    apply_calibration as _helper_apply_calibration,
)
from .signal_model_support_helpers import (
    build_calibration_profile as _helper_build_calibration_profile,
)
from .signal_model_support_helpers import (
    build_dataset_report as _helper_build_dataset_report,
)
from .signal_model_support_helpers import (
    build_sufficiency_status as _helper_build_sufficiency_status,
)
from .signal_model_support_helpers import (
    count_reason as _helper_count_reason,
)
from .signal_model_support_helpers import (
    model_promotion_gate as _helper_model_promotion_gate,
)
from .signal_model_support_helpers import (
    normalize_paper_symbol as _helper_normalize_paper_symbol,
)
from .signal_model_support_helpers import (
    paper_feature_coverage as _helper_paper_feature_coverage,
)
from .signal_model_support_helpers import (
    paper_label_quality_decision as _helper_paper_label_quality_decision,
)
from .signal_model_support_helpers import (
    prune_weak_slices as _helper_prune_weak_slices,
)

try:
    from .neural_optimizer import TORCH_AVAILABLE, get_neural_optimizer
except (ImportError, SyntaxError, Exception):
    TORCH_AVAILABLE = False
    def get_neural_optimizer(*a, **kw): return None

load_dotenv()

logger = logging.getLogger(__name__)

MODEL_PATH    = Path(os.getenv("ML_MODEL_PATH", "data/signal_model.pkl"))
DATASET_PATH  = Path(os.getenv("ML_DATASET_PATH", "data/ml_dataset.parquet"))
PAPER_DB_PATH = os.getenv("PAPER_TRADE_DB", "persistence.db")
PAPER_TRAIN_INCLUDE_SOURCES = {
    source.strip()
    for source in os.getenv("ML_PAPER_TRAIN_INCLUDE_SOURCES", "auto_paper,shadow_label").split(",")
    if source.strip()
}
PAPER_TRAIN_MIN_ABS_PNL = float(os.getenv("ML_PAPER_TRAIN_MIN_ABS_PNL", "0.000001"))
ML_MODEL_MIN_PROMOTION_AUC = float(os.getenv("ML_MODEL_MIN_PROMOTION_AUC", "0.50"))
ML_MODEL_MIN_PROMOTION_ACCURACY = float(os.getenv("ML_MODEL_MIN_PROMOTION_ACCURACY", "0.35"))
ML_MODEL_PROMOTION_ACCURACY_TOLERANCE = float(os.getenv("ML_MODEL_PROMOTION_ACCURACY_TOLERANCE", "0.005"))
ML_MODEL_PROMOTION_MIN_AUC_IMPROVEMENT = float(os.getenv("ML_MODEL_PROMOTION_MIN_AUC_IMPROVEMENT", "0.005"))
ML_MODEL_PROMOTION_MAX_ACCURACY_REGRESSION = float(os.getenv("ML_MODEL_PROMOTION_MAX_ACCURACY_REGRESSION", "0.032"))
_LAST_PAPER_LABEL_QUALITY_REPORT: Dict[str, Any] = {
    "available": False,
    "included": 0,
    "excluded": 0,
    "reasons": {},
}

# Training assets — two tiers:
# DEFAULT_SYMBOLS = full list used by the ML scanner (signal detection)
DEFAULT_SYMBOLS = [
    # ── Crypto 24/7 ──────────────────────────────────────────────────────────
    ("BTC",    "CRYPTO", "1h"),
    ("ETH",    "CRYPTO", "1h"),
    ("SOL",    "CRYPTO", "1h"),
    ("XRP",    "CRYPTO", "1h"),
    ("BNB",    "CRYPTO", "1h"),
    ("DOGE",   "CRYPTO", "1h"),
    ("AVAX",   "CRYPTO", "1h"),
    ("LINK",   "CRYPTO", "1h"),
    # ── Macro ────────────────────────────────────────────────────────────────
    ("GOLD",   "MACRO",  "1h"),
    ("SILVER", "MACRO",  "1h"),
    ("OIL",    "MACRO",  "1h"),
    # ── US Equities (scanner skips when market closed) ────────────────────────
    ("NASDAQ", "MACRO",  "1h"),
    ("SP500",  "MACRO",  "1h"),
    ("NVDA",   "STOCK",  "1h"),
    ("TSLA",   "STOCK",  "1h"),
    ("AAPL",   "STOCK",  "1h"),
]

# ── TRADEABLE ASSET Training Set (Broker-verified MT5 symbols) ───────────────
# Maximized universe: Crypto, Forex (major + minor + cross), Commodities
# across 15m / 1h / 4h / 1d — 1d gives 20+ years of daily data via yfinance
TRADE_TRAIN_SYMBOLS = [
    # ── Crypto — 15m + 1h + 4h + 1d ────────────────────────────────────────
    ("BTCUSD",  "CRYPTO", "15m"),
    ("BTCUSD",  "CRYPTO", "1h"),
    ("BTCUSD",  "CRYPTO", "4h"),
    ("BTCUSD",  "CRYPTO", "1d"),
    ("ETHUSD",  "CRYPTO", "15m"),
    ("ETHUSD",  "CRYPTO", "1h"),
    ("ETHUSD",  "CRYPTO", "4h"),
    ("ETHUSD",  "CRYPTO", "1d"),
    ("SOLUSD",  "CRYPTO", "1h"),
    ("SOLUSD",  "CRYPTO", "4h"),
    ("SOLUSD",  "CRYPTO", "1d"),
    ("XRPUSD",  "CRYPTO", "1h"),
    ("XRPUSD",  "CRYPTO", "4h"),
    ("XRPUSD",  "CRYPTO", "1d"),
    ("BNBUSD",  "CRYPTO", "1h"),
    ("BNBUSD",  "CRYPTO", "4h"),
    ("BNBUSD",  "CRYPTO", "1d"),
    ("ADAUSD",  "CRYPTO", "1h"),
    ("ADAUSD",  "CRYPTO", "4h"),
    ("DOTUSD",  "CRYPTO", "1h"),
    ("DOTUSD",  "CRYPTO", "4h"),
    ("LINKUSD", "CRYPTO", "1h"),
    ("LINKUSD", "CRYPTO", "4h"),
    ("AVAXUSD", "CRYPTO", "1h"),
    ("AVAXUSD", "CRYPTO", "4h"),
    ("LTCUSD",  "CRYPTO", "1h"),
    ("LTCUSD",  "CRYPTO", "4h"),
    ("LTCUSD",  "CRYPTO", "1d"),
    ("ATOMUSD", "CRYPTO", "1h"),
    ("UNIUSD",  "CRYPTO", "1h"),
    ("MATICUSD","CRYPTO", "1h"),
    # ── Commodities — 15m + 1h + 4h + 1d ────────────────────────────────────
    ("GOLD",    "MACRO",  "15m"),
    ("GOLD",    "MACRO",  "1h"),
    ("GOLD",    "MACRO",  "4h"),
    ("GOLD",    "MACRO",  "1d"),
    ("SILVER",  "MACRO",  "1h"),
    ("SILVER",  "MACRO",  "4h"),
    ("SILVER",  "MACRO",  "1d"),
    ("OIL",     "MACRO",  "1h"),
    ("OIL",     "MACRO",  "4h"),
    ("OIL",     "MACRO",  "1d"),
    # ── Major Forex — 15m + 1h + 4h + 1d ────────────────────────────────────
    ("EURUSD",  "MACRO",  "15m"),
    ("EURUSD",  "MACRO",  "1h"),
    ("EURUSD",  "MACRO",  "4h"),
    ("EURUSD",  "MACRO",  "1d"),
    ("GBPUSD",  "MACRO",  "15m"),
    ("GBPUSD",  "MACRO",  "1h"),
    ("GBPUSD",  "MACRO",  "4h"),
    ("GBPUSD",  "MACRO",  "1d"),
    ("USDJPY",  "MACRO",  "1h"),
    ("USDJPY",  "MACRO",  "4h"),
    ("USDJPY",  "MACRO",  "1d"),
    ("USDCHF",  "MACRO",  "1h"),
    ("USDCHF",  "MACRO",  "4h"),
    ("USDCHF",  "MACRO",  "1d"),
    ("AUDUSD",  "MACRO",  "1h"),
    ("AUDUSD",  "MACRO",  "4h"),
    ("AUDUSD",  "MACRO",  "1d"),
    ("NZDUSD",  "MACRO",  "1h"),
    ("NZDUSD",  "MACRO",  "4h"),
    ("USDCAD",  "MACRO",  "1h"),
    ("USDCAD",  "MACRO",  "4h"),
    ("USDCAD",  "MACRO",  "1d"),
    # ── Minor / Cross Forex — 1h + 4h + 1d ──────────────────────────────────
    ("EURGBP",  "MACRO",  "1h"),
    ("EURGBP",  "MACRO",  "4h"),
    ("EURGBP",  "MACRO",  "1d"),
    ("EURJPY",  "MACRO",  "1h"),
    ("EURJPY",  "MACRO",  "4h"),
    ("EURJPY",  "MACRO",  "1d"),
    ("EURCHF",  "MACRO",  "1h"),
    ("EURCHF",  "MACRO",  "4h"),
    ("EURCAD",  "MACRO",  "1h"),
    ("EURAUD",  "MACRO",  "1h"),
    ("GBPJPY",  "MACRO",  "1h"),
    ("GBPJPY",  "MACRO",  "4h"),
    ("GBPJPY",  "MACRO",  "1d"),
    ("GBPCHF",  "MACRO",  "1h"),
    ("GBPCAD",  "MACRO",  "1h"),
    ("AUDJPY",  "MACRO",  "1h"),
    ("AUDJPY",  "MACRO",  "4h"),
    ("CADJPY",  "MACRO",  "1h"),
    ("CADJPY",  "MACRO",  "4h"),
    ("CHFJPY",  "MACRO",  "1h"),
    ("AUDNZD",  "MACRO",  "1h"),
    ("AUDCAD",  "MACRO",  "1h"),
    ("NZDCAD",  "MACRO",  "1h"),
    ("NZDJPY",  "MACRO",  "1h"),
    # ── Global Indices — 1d (20+ years of daily data) ────────────────────────
    ("NASDAQ",  "MACRO",  "1d"),
    ("SP500",   "MACRO",  "1d"),
    ("^DJI",    "MACRO",  "1d"),
    ("^GDAXI",  "MACRO",  "1d"),   # DAX
    ("^FTSE",   "MACRO",  "1d"),   # FTSE 100
    ("^FCHI",   "MACRO",  "1d"),   # CAC 40
    ("^N225",   "MACRO",  "1d"),   # Nikkei 225
    ("^HSI",    "MACRO",  "1d"),   # Hang Seng
    # ── More Commodities — 1h + 4h + 1d ─────────────────────────────────────
    ("NG=F",    "MACRO",  "1d"),   # Natural Gas
    ("HG=F",    "MACRO",  "1d"),   # Copper
    ("ZW=F",    "MACRO",  "1d"),   # Wheat
    ("ZC=F",    "MACRO",  "1d"),   # Corn
]

# Full universe — all timeframes for maximum coverage
TRAIN_SYMBOLS = TRADE_TRAIN_SYMBOLS
DEFAULT_TRAIN_LIMIT = 500000
ML_CORE_SYMBOLS = ["BTCUSD", "ETHUSD", "GOLD", "EURUSD"]
ML_SUFFICIENCY_TARGETS = {
    "paper_labels":      int(os.getenv("ML_READY_MIN_PAPER_LABELS", "100")),
    "training_samples":  int(os.getenv("ML_READY_MIN_MODEL_SAMPLES", "1500")),
    "core_symbols":      len(ML_CORE_SYMBOLS),
}
AUTO_RETRAIN_MIN_RECENT_OUTCOMES = 20
AUTO_RETRAIN_DECAY_WIN_RATE = 0.45
AUTO_RETRAIN_NEW_OUTCOMES_THRESHOLD = 25
AUTO_RETRAIN_MAX_AGE_DAYS = 7.0


def _prepare_training_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Sanitize OHLCV history before indicator or label generation."""
    if df is None or df.empty:
        return pd.DataFrame()

    df = df.copy()
    df = df[~df.index.duplicated(keep="last")].sort_index()

    required_cols = ["Open", "High", "Low", "Close"]
    for col in required_cols:
        if col not in df.columns:
            return pd.DataFrame()
        df[col] = pd.to_numeric(df[col], errors="coerce")

    if "Volume" in df.columns:
        df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce").fillna(0)

    df = df.replace([np.inf, -np.inf], np.nan)
    df = df.dropna(subset=required_cols)
    df = df[
        (df["Open"] > 0)
        & (df["High"] > 0)
        & (df["Low"] > 0)
        & (df["Close"] > 0)
        & (df["High"] >= df["Low"])
    ]

    if "Volume" in df.columns:
        df["Volume"] = df["Volume"].clip(lower=0)

    return df


def _is_valid_feature_row(feats: Dict[str, Any]) -> bool:
    """Drop pathological rows that would degrade model quality."""
    try:
        for col in FEATURE_COLS:
            value = float(feats.get(col, 0.0))
            if not np.isfinite(value):
                return False

        atr_pct = abs(float(feats.get("atr_pct", 0.0)))
        adx = float(feats.get("adx", 0.0))
        rsi = float(feats.get("rsi", 50.0))
        bb_pct = float(feats.get("bb_pct", 0.5))
        vol_ratio = float(feats.get("vol_ratio", 1.0))

        if atr_pct <= 0 or atr_pct > 25:
            return False
        if adx < 0 or adx > 100:
            return False
        if rsi < 0 or rsi > 100:
            return False
        if bb_pct < -0.5 or bb_pct > 1.5:
            return False
        if vol_ratio < 0 or vol_ratio > 25:
            return False
    except Exception:
        return False

    return True


# ─────────────────────────────────────────────────────────────────────────────
# Dataset Builder
# ─────────────────────────────────────────────────────────────────────────────

def _build_htf_bars(symbol: str, asset_class: str, timeframe: str, limit: int = 5000) -> dict:
    """Fetch HTF bars, compute indicators, return {date: row} lookup."""
    from intelligence.technical_engine import compute_indicators, get_kline_data
    try:
        df = get_kline_data(symbol, timeframe=timeframe, limit=limit, asset_class=asset_class, ignore_freshness=True)
        if df is None or len(df) < 30:
            return {}
        df = compute_indicators(df)
        lookup: dict = {}
        for ts, row in df.iterrows():
            try:
                d_key = pd.Timestamp(ts, unit="ms").date() if isinstance(ts, (int, float)) else pd.Timestamp(ts).date()
            except Exception:
                continue
            lookup[d_key] = row
        return lookup
    except Exception:
        return {}


# VIX lookup cache (date → vix_close) — refreshed per dataset build
_VIX_CACHE: dict = {}


def _build_vix_context() -> dict:
    """Fetch VIX daily data and return {date: vix_level}. High VIX = risk-off."""
    global _VIX_CACHE
    if _VIX_CACHE:
        return _VIX_CACHE
    from intelligence.technical_engine import get_kline_data
    try:
        df = get_kline_data("^VIX", timeframe="1d", limit=3000, asset_class="MACRO", ignore_freshness=True)
        if df is None or df.empty:
            return {}
        lookup: dict = {}
        for ts, row in df.iterrows():
            try:
                d_key = pd.Timestamp(ts, unit="ms").date() if isinstance(ts, (int, float)) else pd.Timestamp(ts).date()
            except Exception:
                continue
            v = float(row.get("Close", 0) or 0)
            if v > 0:
                lookup[d_key] = v
        _VIX_CACHE = lookup
        logger.info(f"[ML-Dataset] VIX context loaded: {len(lookup)} days")
        return lookup
    except Exception as exc:
        logger.warning(f"[ML-Dataset] VIX context failed: {exc}")
        return {}


def _build_daily_context(symbol: str, asset_class: str) -> dict:
    """
    Fetch 1d + 4h bars, compute indicators, return {date: context_dict}.
    Context includes daily trend, 4h trend, EMA alignment, and VIX regime.
    """
    daily_rows = _build_htf_bars(symbol, asset_class, "1d", limit=3000)
    h4_rows    = _build_htf_bars(symbol, asset_class, "4h", limit=10000)
    vix_ctx    = _build_vix_context()

    if not daily_rows:
        return {}

    # Build 4h date → latest row mapping (use last 4h bar of each day)
    h4_by_date: dict = {}
    for d, row in h4_rows.items():
        h4_by_date[d] = row  # overwrites with latest bar of that date

    lookup: dict = {}
    for d_key, row in daily_rows.items():
        price  = float(row.get("Close", 0) or 0)
        ema20  = float(row.get("ema_20",  price) or price) or price
        ema50  = float(row.get("ema_50",  price) or price) or price
        ema200 = float(row.get("ema_200", price) or price) or price
        rsi    = float(row.get("rsi_14",  50.0)  or 50.0)
        d_trend = max(-20.0, min(20.0, (price - ema50) / ema50 * 100)) if ema50 > 0 else 0.0

        # 4h trend alignment
        h4_bullish = h4_sell = False
        if d_key in h4_by_date:
            h4r = h4_by_date[d_key]
            h4p   = float(h4r.get("Close", 0) or 0)
            h4e20 = float(h4r.get("ema_20", h4p) or h4p) or h4p
            h4e50 = float(h4r.get("ema_50", h4p) or h4p) or h4p
            h4_bullish = h4p > h4e20 and h4e20 > h4e50
            h4_sell    = h4p < h4e20 and h4e20 < h4e50

        # VIX regime: >25 = elevated fear, >35 = crisis
        vix = float(vix_ctx.get(d_key, 0) or 0)
        vix_risk_off = vix > 25.0  # block aggressive buys in high fear
        vix_crisis   = vix > 35.0  # block all new positions in crisis

        lookup[d_key] = {
            "d_trend":      d_trend,
            "d_rsi":        rsi,
            "d_ema_align":  1.0 if price > ema200 else 0.0,
            "d_bullish":    price > ema20 and ema20 > ema50,
            "d_bearish":    price < ema20 and ema20 < ema50,
            "h4_bullish":   h4_bullish,
            "h4_bearish":   h4_sell,
            "vix":          vix,
            "vix_risk_off": vix_risk_off,
            "vix_crisis":   vix_crisis,
        }
    return lookup


def _generate_training_signals(
    df: pd.DataFrame,
    tf: str,
    daily_ctx_lookup: dict = None,
    asset_class: str = "CRYPTO",
) -> pd.DataFrame:
    """
    Quality-focused signal generator for ML training data.

    Signals only fire when multiple conditions agree — creating fewer but
    higher-quality examples. Three types require EMA alignment + ADX:
      Type A — Trend-following: EMA stack aligned, RSI not extended, ADX confirms
      Type C — Momentum breakout: strong ADX + full EMA alignment + RSI cap
      Type D — MACD+EMA confluence: MACD histogram agrees with EMA trend

    When daily_ctx_lookup is provided, signals are additionally gated by the
    daily trend direction — no longs against a daily downtrend and vice versa.
    """
    import numpy as np
    df = df.copy()
    required = {"rsi_14", "ema_20", "ema_50", "adx_14", "atr_14", "macd_hist"}
    if not required.issubset(df.columns):
        required_base = {"rsi_14", "ema_20", "ema_50", "adx_14", "atr_14"}
        if not required_base.issubset(df.columns):
            return df

    # MTF gate disabled for training — MTF context is already encoded as features
    # (d_trend, d_rsi, d_ema_align). Gating here blocks entire assets/periods
    # (e.g. SOL in a downtrend) from generating any training examples, which is
    # worse than having the model learn the MTF relationship from labels.
    use_mtf  = False
    adx_min  = 20
    cooldown = 6

    close = df["Close"].values
    ema20 = df["ema_20"].values
    ema50 = df["ema_50"].values
    rsi   = df["rsi_14"].values
    adx   = df["adx_14"].values
    macd_hist_col = df["macd_hist"].values if "macd_hist" in df.columns else np.zeros(len(df))
    n     = len(df)

    signals   = np.zeros(n, dtype=int)
    last_buy  = -cooldown - 1
    last_sell = -cooldown - 1

    for i in range(1, n):
        r   = float(rsi[i])            if not np.isnan(rsi[i])           else 50.0
        a   = float(adx[i])            if not np.isnan(adx[i])           else 0.0
        c   = float(close[i])
        e20 = float(ema20[i])          if not np.isnan(ema20[i])         else c
        e50 = float(ema50[i])          if not np.isnan(ema50[i])         else c
        mh  = float(macd_hist_col[i])  if not np.isnan(macd_hist_col[i]) else 0.0

        # ── Multi-timeframe gate: 4h + Daily + VIX macro regime ─────────────
        daily_buy_ok  = True
        daily_sell_ok = True
        if use_mtf:
            try:
                ts = df.index[i]
                d_key = ts.date() if hasattr(ts, "date") else pd.Timestamp(ts, unit="ms").date()
                dc = daily_ctx_lookup.get(d_key)  # None = date not in lookup

                if dc is None:
                    # Date not matched in daily context — bypass gate for this bar.
                    # This handles timestamp mismatches (different yfinance/archive
                    # formats between 1h and 1d data for the same symbol).
                    daily_buy_ok  = True
                    daily_sell_ok = True
                else:
                    d_bullish  = bool(dc.get("d_bullish",  False))
                    d_bearish  = bool(dc.get("d_bearish",  False))
                    vix_crisis = bool(dc.get("vix_crisis", False))
                    # Training gate: daily trend alignment + VIX crisis only.
                    daily_buy_ok  = d_bullish and not vix_crisis
                    daily_sell_ok = d_bearish and not vix_crisis
            except Exception:
                pass

        # Type A — Trend-following: EMA stack + ADX (no RSI filter for training).
        # RSI excluded here so strongly trending assets (e.g. SOL in a downtrend
        # where RSI stays < 45) still generate training examples. The labels
        # (WIN/LOSS) teach the model when RSI context matters.
        buy_a  = c > e20 and e20 > e50 and a > adx_min
        sell_a = c < e20 and e20 < e50 and a > adx_min

        # Type C — Strong momentum: high ADX, RSI not at extreme (wide tolerance)
        buy_c  = a > 28 and c > e20 and e20 > e50 and r < 70
        sell_c = a > 28 and c < e20 and e20 < e50 and r > 30

        # Type D — MACD+EMA confluence (no RSI filter for same reason as A)
        buy_d  = mh > 0 and c > e50 and e20 > e50 and a > 15
        sell_d = mh < 0 and c < e50 and e20 < e50 and a > 15

        want_buy  = (buy_a  or buy_c  or buy_d)  and daily_buy_ok
        want_sell = (sell_a or sell_c or sell_d) and daily_sell_ok

        if want_buy and (i - last_buy) > cooldown:
            signals[i] = 1
            last_buy = i
        elif want_sell and (i - last_sell) > cooldown:
            signals[i] = -1
            last_sell = i

    df["signal"] = signals
    return df


def build_ml_dataset(
    symbols: List[Tuple[str, str, str]] = None,
    limit: int = DEFAULT_TRAIN_LIMIT,
    sl_mult: float = 1.2,
    tp_mult: float = 2.0,   # 2R target → breakeven 37.5%, actual win ~37-40%
    max_bars: int = 72,     # more time to resolve → fewer timeouts
    sequence_length: int = 20,
) -> pd.DataFrame:
    """
    Run backtests across symbols and return a labeled ML dataset.

    Label:
      1 = WIN  (price hit TP within max_bars)
      0 = LOSS (price hit SL or timed out)
    """

    from intelligence.technical_engine import compute_indicators, get_kline_data

    symbols = symbols or TRAIN_SYMBOLS
    rows: List[Dict] = []

    # 1. Pull core historical dataset from multi-source engine
    for sym, asset_class, tf in symbols:
        try:
            # Use deep lookback (limit) as requested (Up to 500,000+ bars for 10-year history)
            df = get_kline_data(sym, timeframe=tf, limit=limit, asset_class=asset_class, ignore_freshness=True)
            df = _prepare_training_frame(df)
            if df is None or len(df) < (sequence_length + 200):
                logger.warning(f"[ML-Dataset] {sym}: insufficient data ({len(df) if df is not None else 0} bars)")
                continue

            # Daily trend context: fetch first so MTF gate applies during signal generation
            daily_ctx_lookup: dict = {}
            if tf in ("15m", "1h", "4h"):
                daily_ctx_lookup = _build_daily_context(sym, asset_class)

            # Compute indicators then generate MTF-gated signals
            df = compute_indicators(df)
            df = _generate_training_signals(df, tf, daily_ctx_lookup=daily_ctx_lookup, asset_class=asset_class)
            df = df.dropna(subset=["rsi_14", "ema_20", "ema_50", "adx_14", "atr_14"])

            signal_idx = df.index[df["signal"] != 0].tolist()
            logger.info(f"[ML-Dataset] {sym}/{tf}: {len(signal_idx)} signals found in {len(df)} bars")

            # Pre-compute SMC for each signal bar (CRYPTO/MACRO only, ~100-bar slice)
            smc_bar_cache: dict = {}
            if asset_class in ("CRYPTO", "MACRO") and signal_idx:
                try:
                    from intelligence.technical_engine import (
                        get_smart_money_analysis as _get_smc,
                    )
                    for _pos in signal_idx:
                        _i = df.index.get_loc(_pos)
                        _start = max(0, _i - 100)
                        smc_bar_cache[_i] = _get_smc(df.iloc[_start:_i + 1])
                except Exception as _se:
                    logger.debug(f"[ML-Dataset] SMC pre-compute failed for {sym}: {_se}")

            close_arr = df["Close"].values
            high_arr  = df["High"].values
            low_arr   = df["Low"].values
            atr_arr   = df["atr_14"].values

            # Pre-calculate features for all rows to speed up sequence synthesis
            feature_list = []
            for i in range(len(df)):
                dc_i = None
                if daily_ctx_lookup:
                    try:
                        ts_raw = df.index[i]
                        if isinstance(ts_raw, (int, float)):
                            d_key_i = pd.Timestamp(ts_raw, unit="ms").date()
                        else:
                            d_key_i = pd.Timestamp(ts_raw).date()
                        dc_i = daily_ctx_lookup.get(d_key_i)
                    except Exception:
                        pass
                feature_list.append(extract_features(
                    df, i, symbol=sym, asset_class=asset_class,
                    daily_context=dc_i, smc_context=smc_bar_cache.get(i),
                ))

            feat_df = pd.DataFrame(feature_list)

            # Determine outcomes (Labels)
            for pos in signal_idx:
                i = df.index.get_loc(pos)
                if i < sequence_length:
                    continue

                entry  = float(close_arr[i])
                atr_v  = float(atr_arr[i]) if not np.isnan(atr_arr[i]) else 0
                sig    = int(df.loc[pos, "signal"])
                side   = "BUY" if sig == 1 else "SELL"

                if atr_v <= 0 or entry <= 0:
                    continue

                sl = entry - atr_v * sl_mult if side == "BUY" else entry + atr_v * sl_mult
                tp = entry + atr_v * tp_mult if side == "BUY" else entry - atr_v * tp_mult

                label = None
                for j in range(i + 1, min(i + 1 + max_bars, len(close_arr))):
                    h = float(high_arr[j])
                    low_price = float(low_arr[j])
                    if side == "BUY":
                        if low_price <= sl:
                            label = 0
                            break
                        if h >= tp:
                            label = 1
                            break
                    else:
                        if h >= sl:
                            label = 0
                            break
                        if low_price <= tp:
                            label = 1
                            break

                if label is None:
                    label = 0  # Default to loss if timed out

                # ── Sequential Data for Neural V8 ──
                # Extract the last `sequence_length` feature vectors
                seq = feat_df.iloc[i-sequence_length+1 : i+1][FEATURE_COLS].fillna(0).values

                # Flat features for Ensemble (just the current bar)
                feats = feature_list[i].copy()
                feats["label"] = label
                feats["symbol"] = sym
                feats["side"] = side
                feats["entry"] = entry
                feats["asset_class"] = asset_class
                feats["timeframe"] = tf
                feats["signal_time"] = str(pos)
                feats["_symbol_order"] = symbols.index((sym, asset_class, tf))
                feats["_bar_pos"] = i
                feats["_sequence"] = seq.tolist() # Store as list for parquet/json compatibility
                if _is_valid_feature_row(feats):
                    rows.append(feats)

        except Exception as e:
            logger.error(f"[ML-Dataset] {sym} error: {e}", exc_info=True)

    if not rows:
        logger.warning("[ML-Dataset] No rows generated!")
        return pd.DataFrame()

    dataset = pd.DataFrame(rows)
    dataset = dataset.drop_duplicates(subset=["symbol", "timeframe", "side", "signal_time"], keep="last")
    dataset = dataset.replace([np.inf, -np.inf], np.nan)
    feature_cols = [c for c in FEATURE_COLS if c in dataset.columns]
    dataset = dataset.dropna(subset=["label"] + feature_cols)
    logger.info(f"[ML-Dataset] Total rows: {len(dataset)} | WIN rate: {dataset['label'].mean():.1%}")

    # Append paper trade outcomes from SQLite
    try:
        paper_rows = _load_paper_trade_outcomes()
        if paper_rows:
            paper_df = pd.DataFrame(paper_rows)
            dataset  = pd.concat([dataset, paper_df], ignore_index=True)
            logger.info(f"[ML-Dataset] +{len(paper_rows)} paper trade outcomes appended")
    except Exception as e:
        logger.warning(f"[ML-Dataset] Paper trade load failed: {e}")

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    dataset.to_parquet(DATASET_PATH, index=False)
    logger.info(f"[ML-Dataset] Saved to {DATASET_PATH}")
    return dataset


def _normalize_paper_symbol(symbol: str) -> str:
    return _helper_normalize_paper_symbol(symbol)


def _count_reason(report: Dict[str, Any], reason: str) -> None:
    _helper_count_reason(report, reason)


def _paper_feature_coverage(features: Dict[str, Any]) -> int:
    return _helper_paper_feature_coverage(features, FEATURE_COLS)


def _paper_label_quality_decision(row: sqlite3.Row, features: Dict[str, Any]) -> Dict[str, Any]:
    from intelligence.ml.performance_feedback import paper_training_label_gate
    from intelligence.ml.symbol_policy import get_symbol_policy

    return _helper_paper_label_quality_decision(
        row,
        features,
        feature_cols=FEATURE_COLS,
        include_sources=PAPER_TRAIN_INCLUDE_SOURCES,
        min_abs_pnl=PAPER_TRAIN_MIN_ABS_PNL,
        label_gate_fn=paper_training_label_gate,
        symbol_policy_fn=get_symbol_policy,
    )


def _scan_paper_trade_outcomes() -> Tuple[List[Dict], Dict[str, Any]]:
    """Load closed paper trades and keep only labels that are safe for retraining."""
    rows: List[Dict[str, Any]] = []
    report: Dict[str, Any] = {
        "available": True,
        "policy": {
            "include_sources": sorted(PAPER_TRAIN_INCLUDE_SOURCES),
            "min_abs_pnl_for_timeout": PAPER_TRAIN_MIN_ABS_PNL,
            "min_feature_coverage": max(8, min(len(FEATURE_COLS), 12)),
        },
        "included": 0,
        "excluded": 0,
        "reasons": {},
        "by_source": {},
        "by_symbol": {},
        "examples": [],
    }
    try:
        con = sqlite3.connect(PAPER_DB_PATH, timeout=15)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout=15000")
        cur = con.cursor()
        cur.execute("""
            SELECT id, symbol, side, entry_price, sl, tp, outcome, features_json,
                   closed_at, pnl_usd, entry_source, close_reason
            FROM paper_trades
            WHERE status='CLOSED' AND outcome IS NOT NULL AND features_json IS NOT NULL
            ORDER BY datetime(COALESCE(closed_at, opened_at)) ASC
        """)
        for r in cur.fetchall():
            outcome = str(r["outcome"] or "").upper().strip()
            if outcome not in ("WIN", "LOSS"):
                continue
            try:
                feats = json.loads(r["features_json"] or "{}")
            except Exception:
                feats = {}
            decision = _paper_label_quality_decision(r, feats)
            source = decision["entry_source"]
            symbol = decision["symbol"]
            report["by_source"].setdefault(source, {"included": 0, "excluded": 0})
            report["by_symbol"].setdefault(symbol, {"included": 0, "excluded": 0})

            if not decision["include"]:
                report["excluded"] += 1
                report["by_source"][source]["excluded"] += 1
                report["by_symbol"][symbol]["excluded"] += 1
                for reason in decision["reasons"]:
                    _count_reason(report, reason)
                if len(report["examples"]) < 20:
                    report["examples"].append({
                        "trade_id": r["id"],
                        "symbol": symbol,
                        "side": decision["side"],
                        "entry_source": source,
                        "pnl_usd": round(float(decision["pnl_usd"]), 6),
                        "reasons": decision["reasons"],
                        "blockers": (decision.get("performance_gate") or {}).get("blockers", [])[:3],
                    })
                continue

            feats["label"] = 1 if outcome == "WIN" else 0
            feats["symbol"] = symbol
            feats["side"] = decision["side"]
            feats["entry"] = r["entry_price"]
            feats["timeframe"] = feats.get("timeframe") or feats.get("focus_timeframe") or "paper"
            feats["entry_source"] = source
            rows.append(feats)
            report["included"] += 1
            report["by_source"][source]["included"] += 1
            report["by_symbol"][symbol]["included"] += 1
        con.close()
    except Exception as exc:
        report["available"] = False
        report["error"] = str(exc)
    return rows, report


def _load_paper_trade_outcomes() -> List[Dict]:
    """Load quality-filtered paper labels for ML retraining."""
    global _LAST_PAPER_LABEL_QUALITY_REPORT
    rows, report = _scan_paper_trade_outcomes()
    _LAST_PAPER_LABEL_QUALITY_REPORT = report
    return rows


def get_paper_label_quality_report(force_refresh: bool = False) -> Dict[str, Any]:
    """Report which paper labels will be included or pruned from retraining."""
    global _LAST_PAPER_LABEL_QUALITY_REPORT
    if force_refresh or not _LAST_PAPER_LABEL_QUALITY_REPORT.get("available"):
        _, report = _scan_paper_trade_outcomes()
        _LAST_PAPER_LABEL_QUALITY_REPORT = report
    return _LAST_PAPER_LABEL_QUALITY_REPORT


def _cached_dataset_with_fresh_paper_labels() -> Optional[pd.DataFrame]:
    """Use the saved historical dataset and refresh only paper labels for auto-retrain."""
    if not DATASET_PATH.exists():
        return None
    try:
        dataset = pd.read_parquet(DATASET_PATH)
        if dataset is None or dataset.empty:
            return None
        mask = pd.Series(True, index=dataset.index)
        if "timeframe" in dataset.columns:
            mask &= dataset["timeframe"].astype(str).str.lower() != "paper"
        if "entry_source" in dataset.columns:
            mask &= dataset["entry_source"].isna()
        dataset = dataset.loc[mask].copy()
        paper_rows = _load_paper_trade_outcomes()
        if paper_rows:
            dataset = pd.concat([dataset, pd.DataFrame(paper_rows)], ignore_index=True)
        logger.info(
            "[AutoRetrain] Reusing cached dataset with %d quality paper labels",
            len(paper_rows),
        )
        return dataset
    except Exception as exc:
        logger.warning(f"[AutoRetrain] Cached dataset reuse failed: {exc}")
        return None


def _build_dataset_report(dataset: pd.DataFrame) -> List[Dict[str, Any]]:
    """Summarize dataset quality per symbol/timeframe slice."""
    return _helper_build_dataset_report(dataset)


def _build_sufficiency_status(
    dataset: pd.DataFrame,
    outcomes_count: int,
    dataset_report: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Track whether data is sufficient enough to trust iterative model improvement."""
    return _helper_build_sufficiency_status(
        dataset,
        outcomes_count,
        core_symbols=ML_CORE_SYMBOLS,
        targets=ML_SUFFICIENCY_TARGETS,
        dataset_report=dataset_report,
    )


def get_live_sufficiency_status(bundle: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Refresh sufficiency using live paper-trade labels plus saved dataset coverage."""
    if bundle is None:
        bundle = _load_model()

    if bundle is None:
        return _build_sufficiency_status(pd.DataFrame(), 0, [])

    dataset_report = bundle.get("dataset_report") or []
    present_symbols = sorted({str(row.get("symbol")) for row in dataset_report if row.get("symbol")})
    core_covered = [symbol for symbol in ML_CORE_SYMBOLS if symbol in present_symbols]
    training_samples = int(bundle.get("n_samples") or 0)

    outcomes_count = int(bundle.get("outcomes_at_retrain") or 0)
    try:
        con = sqlite3.connect(str(PAPER_DB_PATH))
        outcomes_count = int(
            con.execute(
                "SELECT COUNT(*) FROM paper_trades WHERE outcome IS NOT NULL AND status='CLOSED'"
            ).fetchone()[0]
            or 0
        )
        con.close()
    except Exception:
        pass

    paper_progress = min(outcomes_count / ML_SUFFICIENCY_TARGETS["paper_labels"], 1.0) if ML_SUFFICIENCY_TARGETS["paper_labels"] else 1.0
    sample_progress = min(training_samples / ML_SUFFICIENCY_TARGETS["training_samples"], 1.0) if ML_SUFFICIENCY_TARGETS["training_samples"] else 1.0
    core_progress = min(len(core_covered) / ML_SUFFICIENCY_TARGETS["core_symbols"], 1.0) if ML_SUFFICIENCY_TARGETS["core_symbols"] else 1.0
    overall_progress = round(float((paper_progress + sample_progress + core_progress) / 3.0), 4)

    return {
        "targets": ML_SUFFICIENCY_TARGETS,
        "current": {
            "paper_labels": int(outcomes_count),
            "training_samples": training_samples,
            "core_symbols_covered": len(core_covered),
        },
        "progress": {
            "paper_labels": round(float(paper_progress), 4),
            "training_samples": round(float(sample_progress), 4),
            "core_symbols": round(float(core_progress), 4),
            "overall": overall_progress,
        },
        "core_symbols": {
            "target": ML_CORE_SYMBOLS,
            "covered": core_covered,
            "missing": [symbol for symbol in ML_CORE_SYMBOLS if symbol not in core_covered],
        },
        "ready_for_improvement": bool(
            outcomes_count >= ML_SUFFICIENCY_TARGETS["paper_labels"]
            and training_samples >= ML_SUFFICIENCY_TARGETS["training_samples"]
            and len(core_covered) >= ML_SUFFICIENCY_TARGETS["core_symbols"]
        ),
    }


def _prune_weak_slices(
    dataset: pd.DataFrame,
    min_samples: int = 30,
    min_wins: int = 6,
    min_losses: int = 6,
) -> Tuple[pd.DataFrame, List[Dict[str, Any]]]:
    """Drop slices that are too thin or too one-sided to be stable."""
    return _helper_prune_weak_slices(
        dataset,
        min_samples=min_samples,
        min_wins=min_wins,
        min_losses=min_losses,
    )


def _build_calibration_profile(y_true: np.ndarray, y_prob: np.ndarray, bins: int = 6) -> Dict[str, Any]:
    """Create a simple quantile-based calibration map from holdout predictions."""
    return _helper_build_calibration_profile(y_true, y_prob, bins=bins)


def _apply_calibration(prob: float, calibration: Dict[str, Any]) -> float:
    """Map raw probability to empirical holdout win rate."""
    return _helper_apply_calibration(prob, calibration)


def _model_promotion_gate(acc: float, auc: float, walk_forward: Dict[str, Any]) -> Dict[str, Any]:
    """Prevent weak retrains from replacing the production model."""
    return _helper_model_promotion_gate(
        acc,
        auc,
        walk_forward,
        min_promotion_auc=ML_MODEL_MIN_PROMOTION_AUC,
        min_promotion_accuracy=ML_MODEL_MIN_PROMOTION_ACCURACY,
        accuracy_tolerance=ML_MODEL_PROMOTION_ACCURACY_TOLERANCE,
        min_auc_improvement=ML_MODEL_PROMOTION_MIN_AUC_IMPROVEMENT,
        max_accuracy_regression=ML_MODEL_PROMOTION_MAX_ACCURACY_REGRESSION,
        model_exists=MODEL_PATH.exists(),
        load_incumbent=_load_model,
    )


def _walk_forward_evaluate(
    base_model,
    X: np.ndarray,
    y: np.ndarray,
    min_train_size: int = 5000,
    test_window: int = 3000,
    max_folds: int = 6,
) -> Dict[str, Any]:
    """Evaluate with expanding-window folds to reduce one-split bias."""
    # Adapt window sizes to available data — always do at least 3 folds
    n = len(X)
    if n < 1000:
        return {"available": False, "folds": [], "summary": None}
    # Scale down windows if dataset is smaller than defaults
    effective_train = min(min_train_size, max(200, n // 8))
    effective_test  = min(test_window,   max(80,  n // 20))
    if n < (effective_train + effective_test):
        return {"available": False, "folds": [], "summary": None}

    from sklearn.base import clone
    from sklearn.metrics import accuracy_score, roc_auc_score

    folds: List[Dict[str, Any]] = []
    train_end = effective_train

    while train_end + effective_test <= n and len(folds) < max_folds:
        X_train = X[:train_end]
        y_train = y[:train_end]
        X_test = X[train_end:train_end + effective_test]
        y_test = y[train_end:train_end + effective_test]

        class_counts = pd.Series(y_train).value_counts()
        sample_weights = np.array(
            [len(y_train) / max(class_counts.get(label, 1) * len(class_counts), 1) for label in y_train],
            dtype=float,
        )

        fold_model = clone(base_model)
        try:
            fold_model.fit(X_train, y_train, clf__sample_weight=sample_weights)
        except TypeError:
            fold_model.fit(X_train, y_train)
        y_pred = fold_model.predict(X_test)
        y_prob = fold_model.predict_proba(X_test)[:, 1]
        auc = roc_auc_score(y_test, y_prob) if len(set(y_test)) > 1 else 0.5

        folds.append({
            "train_size": int(len(X_train)),
            "test_size": int(len(X_test)),
            "accuracy": round(float(accuracy_score(y_test, y_pred)), 4),
            "roc_auc": round(float(auc), 4),
            "win_rate_test": round(float(np.mean(y_test)), 4),
        })
        train_end += effective_test

    if not folds:
        return {"available": False, "folds": [], "summary": None}

    summary = {
        "fold_count": len(folds),
        "avg_accuracy": round(float(np.mean([fold["accuracy"] for fold in folds])), 4),
        "avg_roc_auc": round(float(np.mean([fold["roc_auc"] for fold in folds])), 4),
        "min_roc_auc": round(float(np.min([fold["roc_auc"] for fold in folds])), 4),
        "max_roc_auc": round(float(np.max([fold["roc_auc"] for fold in folds])), 4),
    }
    return {"available": True, "folds": folds, "summary": summary}


# ─────────────────────────────────────────────────────────────────────────────
# Model Training
# ─────────────────────────────────────────────────────────────────────────────

def train_model(
    symbols: List[Tuple[str, str, str]] = None,
    limit: int = DEFAULT_TRAIN_LIMIT,
    dataset: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """
    Build dataset → train GradientBoostingClassifier → save model.
    Returns summary metrics.
    """
    try:
        from sklearn.metrics import accuracy_score, roc_auc_score
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler
    except ImportError:
        return {"error": "scikit-learn not installed. Run: pip install scikit-learn"}

    if dataset is None:
        dataset = build_ml_dataset(symbols=symbols, limit=limit)

    if dataset.empty or "label" not in dataset.columns:
        return {"error": "Empty dataset — no signals found"}

    dataset, pruned_slices = _prune_weak_slices(dataset)
    if dataset.empty:
        return {"error": "All dataset slices were pruned as too weak for stable training"}

    # Keep chronology so evaluation matches time-series behavior better than random splits.
    if "signal_time" in dataset.columns:
        signal_time = pd.to_datetime(dataset["signal_time"], errors="coerce")
        symbol_order = (
            pd.to_numeric(dataset["_symbol_order"], errors="coerce")
            if "_symbol_order" in dataset.columns
            else pd.Series(0, index=dataset.index, dtype=float)
        )
        bar_pos = (
            pd.to_numeric(dataset["_bar_pos"], errors="coerce")
            if "_bar_pos" in dataset.columns
            else pd.Series(0, index=dataset.index, dtype=float)
        )
        dataset = dataset.assign(
            _signal_time_sort=signal_time,
            _symbol_order_sort=symbol_order.fillna(0),
            _bar_pos_sort=bar_pos.fillna(0),
        ).sort_values(
            by=["_signal_time_sort", "_symbol_order_sort", "_bar_pos_sort"],
            kind="stable",
        )

    # Use only rows that have all feature columns
    available = [c for c in FEATURE_COLS if c in dataset.columns]
    X_ens = dataset[available].fillna(0).values
    y = dataset["label"].values

    # Build neural sequences — filter NaN rows, enforce uniform shape, align y labels
    X_neu = None
    y_neu = None
    if "_sequence" in dataset.columns:
        try:
            seq_mask = dataset["_sequence"].notna()
            seq_indices = dataset.index[seq_mask].tolist()
            seq_raw     = dataset.loc[seq_mask, "_sequence"].tolist()
            ref_shape   = None
            good: list  = []
            good_idx: list = []
            for idx, s in zip(seq_indices, seq_raw):
                try:
                    a = np.array(s, dtype=np.float32)
                    if ref_shape is None and a.ndim == 2:
                        ref_shape = a.shape
                    if a.shape == ref_shape:
                        good.append(a)
                        good_idx.append(idx)
                except Exception:
                    pass
            if good:
                X_neu = np.stack(good)
                y_neu = dataset.loc[good_idx, "label"].values  # aligned labels
                logger.info(f"[ML-Train] Neural sequences prepared: {X_neu.shape}")
        except Exception as e:
            logger.warning(f"[ML-Train] Neural sequence prep failed: {e}")

    if len(X_ens) < 50:
        return {"error": f"Not enough training samples: {len(X_ens)} (need ≥ 50)"}

    split_idx = max(int(len(X_ens) * 0.75), 1)
    split_idx = min(split_idx, len(X_ens) - 1)
    X_train_ens, X_test_ens = X_ens[:split_idx], X_ens[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]
    split_method = "time_ordered_holdout_75_25"
    class_counts = pd.Series(y_train).value_counts()
    sample_weights = np.array(
        [len(y_train) / max(class_counts.get(label, 1) * len(class_counts), 1) for label in y_train],
        dtype=float,
    )


    from sklearn.ensemble import (
        HistGradientBoostingClassifier,
        RandomForestClassifier,
        VotingClassifier,
    )

    # HistGradientBoostingClassifier: native missing-value handling, faster than GBM,
    # class_weight='balanced' handles the ~37% win-rate imbalance without double-weighting.
    # RF with 200 trees + balanced weights + min_samples_leaf guards against overfitting.
    model = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", VotingClassifier(
            estimators=[
                ("hgbm", HistGradientBoostingClassifier(
                    max_iter=300,
                    max_depth=5,
                    learning_rate=0.04,
                    min_samples_leaf=40,
                    l2_regularization=0.2,
                    class_weight="balanced",
                    random_state=42,
                )),
                ("rf", RandomForestClassifier(
                    n_estimators=200,
                    max_depth=10,
                    random_state=42,
                    class_weight="balanced",
                    n_jobs=-1,
                    min_samples_leaf=20,
                ))
            ],
            voting="soft"
        )),
    ])

    logger.info(f"[ML-Train] Training Ensemble V4 (HGBM+RF) on {len(X_train_ens)} samples...")
    try:
        model.fit(X_train_ens, y_train, clf__sample_weight=sample_weights)
    except TypeError:
        # HistGradientBoostingClassifier uses class_weight internally; sample_weight is optional
        model.fit(X_train_ens, y_train)
    walk_forward = _walk_forward_evaluate(model, X_ens, y)

    # Neural V8 Training (Attention-GRU on temporal sequences)
    if X_neu is not None and y_neu is not None and TORCH_AVAILABLE:
        try:
            trainer = get_neural_optimizer(input_size=len(available))
            if trainer:
                logger.info(f"[ML-Train] Training Neural V8 on {len(X_neu)} sequences...")
                val_loss = trainer.train_on_sequences(X_neu, y_neu, epochs=100)
                logger.info(f"[ML-Train] Neural V8 complete — val_loss={val_loss:.4f}")
        except Exception as e:
            logger.warning(f"[ML-Train] Neural V8 training failed: {e}")
    else:
        logger.info("[ML-Train] Neural V8 skipped (no sequences or torch unavailable)")

    y_pred  = model.predict(X_test_ens)
    y_prob  = model.predict_proba(X_test_ens)[:, 1]
    calibration = _build_calibration_profile(y_test, y_prob)
    acc     = accuracy_score(y_test, y_pred)
    auc     = roc_auc_score(y_test, y_prob) if len(set(y_test)) > 1 else 0.5

    # Isotonic regression calibrator — improves probability reliability (Brier score)
    isotonic_calibrator = None
    try:
        from sklearn.isotonic import IsotonicRegression
        _iso = IsotonicRegression(out_of_bounds="clip")
        _iso.fit(y_prob, y_test)
        isotonic_calibrator = _iso
        iso_probs = _iso.transform(y_prob)
        from sklearn.metrics import brier_score_loss
        brier_before = brier_score_loss(y_test, y_prob)
        brier_after  = brier_score_loss(y_test, iso_probs)
        logger.info(f"[ML-Train] Isotonic calibration: Brier {brier_before:.4f} → {brier_after:.4f}")
        calibration["brier_score"] = round(float(brier_after), 6)
        calibration["brier_score_raw"] = round(float(brier_before), 6)
    except Exception as e:
        logger.warning(f"[ML-Train] Isotonic calibration failed: {e}")
    win_rate_train = float(np.mean(y_train))
    win_rate_test  = float(np.mean(y_test))

    # Feature importances: HGBM exposes feature_importances_ only in sklearn >= 1.4
    # Fall back to RF-only importances when unavailable (still meaningful)
    voting_clf = model.named_steps["clf"]
    hgbm = voting_clf.named_estimators_["hgbm"]
    rf   = voting_clf.named_estimators_["rf"]

    try:
        importances = (hgbm.feature_importances_ + rf.feature_importances_) / 2.0
    except AttributeError:
        importances = rf.feature_importances_

    feat_imp   = sorted(
        [{"feature": available[i], "importance": round(float(importances[i]), 6)}
         for i in range(len(available))],
        key=lambda x: x["importance"], reverse=True
    )

    # Human-readable labels for display
    FEAT_LABELS = {
        "rsi":             "RSI (14)",
        "adx":             "ADX Strength",
        "atr_pct":         "ATR % (Volatility)",
        "price_vs_ema20":  "Price vs EMA20",
        "price_vs_ema50":  "Price vs EMA50",
        "price_vs_ema200": "Price vs EMA200",
        "ema20_vs_ema50":  "EMA20 vs EMA50",
        "ema20_slope":     "EMA20 Slope",
        "bullish_align":   "Bullish EMA Stack",
        "bearish_align":   "Bearish EMA Stack",
        "macd_hist_norm":  "MACD Histogram",
        "bb_pct":          "BB Position",
        "vol_ratio":       "Volume Ratio",
        "regime_enc":      "Market Regime",
        "hour":            "Hour of Day",
        "dow":             "Day of Week",
        "session":         "Trading Session",
        "asset_class_enc": "Asset Class",
        "side_enc":        "Trade Direction",
        "sentiment_score": "Market Sentiment",
        "cmf":             "Institutional Flow (CMF)",
        "rvi":             "Volatility Direction (RVI)",
        "hurst_exponent":  "Fractal Efficiency (Hurst)",
        "vol_skew":        "Return Skewness (Asym Risk)",
    }
    for f in feat_imp:
        f["label"] = FEAT_LABELS.get(f["feature"], f["feature"])

    # Count paper trade outcomes at retrain time (used by auto-retrain trigger)
    _outcomes_count = 0
    try:
        _oc = sqlite3.connect(str(PAPER_DB_PATH))
        _oc.execute("SELECT COUNT(*) FROM paper_trades WHERE outcome IS NOT NULL AND status='CLOSED'")
        _outcomes_count = _oc.execute(
            "SELECT COUNT(*) FROM paper_trades WHERE outcome IS NOT NULL AND status='CLOSED'"
        ).fetchone()[0]
        _oc.close()
    except Exception:
        pass

    paper_label_quality = get_paper_label_quality_report(force_refresh=False)
    dataset_report = _build_dataset_report(dataset)
    sufficiency = _build_sufficiency_status(dataset, _outcomes_count, dataset_report)
    promotion_gate = _model_promotion_gate(acc, auc, walk_forward)

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not promotion_gate["promote"]:
        logger.warning(
            "[ML-Train] Rejected weak model promotion | blockers=%s | acc=%.1f%% auc=%.3f n=%d",
            promotion_gate["blockers"],
            acc * 100.0,
            auc,
            len(X_ens),
        )
        return {
            "status": "rejected",
            "reason": "promotion_gate_failed",
            "promotion_gate": promotion_gate,
            "n_samples": len(X_ens),
            "accuracy": round(acc, 4),
            "roc_auc": round(auc, 4),
            "model_path": str(MODEL_PATH),
        }

    backup_path = None
    if MODEL_PATH.exists():
        backup_path = MODEL_PATH.with_name(
            f"{MODEL_PATH.stem}.backup.{pd.Timestamp.now():%Y%m%d%H%M%S}{MODEL_PATH.suffix}"
        )
        try:
            shutil.copy2(MODEL_PATH, backup_path)
        except Exception as exc:
            logger.warning(f"[ML-Train] Could not backup current model before promotion: {exc}")
            backup_path = None
    with open(MODEL_PATH, "wb") as f:
        pickle.dump({
            "model":               model,
            "feature_cols":        available,
            "feature_importance":  feat_imp,
            "n_samples":           len(X_ens),
            "train_size":          len(X_train_ens),
            "test_size":           len(X_test_ens),
            "split_method":        split_method,
            "dataset_quality":     {
                "symbols": int(dataset["symbol"].nunique()) if "symbol" in dataset.columns else 0,
                "timeframes": sorted(dataset["timeframe"].dropna().unique().tolist()) if "timeframe" in dataset.columns else [],
                "win_rate_full": round(float(np.mean(y)), 4),
            },
            "dataset_report":      dataset_report,
            "slice_pruning":       {
                "available": True,
                "pruned_count": len(pruned_slices),
                "pruned": pruned_slices,
            },
            "paper_label_quality":  paper_label_quality,
            "walk_forward":        walk_forward,
            "calibration":         calibration,
            "isotonic_calibrator": isotonic_calibrator,
            "sufficiency":         sufficiency,
            "promotion_gate":      promotion_gate,
            "accuracy":            round(acc, 4),
            "roc_auc":             round(auc, 4),
            "win_rate_train":      round(win_rate_train, 4),
            "win_rate_test":       round(win_rate_test, 4),
            "trained_at":          pd.Timestamp.now().isoformat(),
            "outcomes_at_retrain": _outcomes_count,
        }, f)

    logger.info(f"[ML-Train] Saved Intelligence V8 model → {MODEL_PATH} | acc={acc:.1%} | auc={auc:.3f} | n={len(X_ens)}")

    # Persist feature distribution stats so drift_monitor uses real training data
    _stats_path = MODEL_PATH.parent / "training_stats.json"
    try:
        _weights = {"rsi": 1.0, "atr_pct": 2.0, "macd_hist_norm": 1.0, "vol_ratio": 1.5}
        _X_df = pd.DataFrame(X_ens, columns=available)
        _training_stats: Dict[str, Any] = {}
        for _feat in _weights:
            if _feat in _X_df.columns:
                _col = _X_df[_feat].replace([np.inf, -np.inf], np.nan).dropna()
                if len(_col) > 0:
                    _training_stats[_feat] = {
                        "mean":   round(float(_col.mean()), 6),
                        "std":    max(round(float(_col.std()), 6), 1e-6),
                        "weight": _weights[_feat],
                    }
        if _training_stats:
            with open(_stats_path, "w") as _sf:
                json.dump(_training_stats, _sf, indent=2)
            logger.info(f"[ML-Train] Training stats saved → {_stats_path}")
            try:
                from intelligence.ml.drift_monitor import update_baseline
                update_baseline(_training_stats)
            except Exception:
                pass
    except Exception as _se:
        logger.warning(f"[ML-Train] Could not save training stats: {_se}")

    return {
        "status":    "trained",
        "n_samples": len(X_ens),
        "train_size": len(X_train_ens),
        "test_size": len(X_test_ens),
        "split_method": split_method,
        "accuracy":  round(acc, 4),
        "roc_auc":   round(auc, 4),
        "win_rate":  round(win_rate_train, 4),
        "win_rate_test": round(win_rate_test, 4),
        "pruned_slices": len(pruned_slices),
        "paper_label_quality": paper_label_quality,
        "promotion_gate": promotion_gate,
        "backup_model_path": str(backup_path) if backup_path else None,
        "calibration": calibration,
        "walk_forward": walk_forward,
        "sufficiency": sufficiency,
        "model_path":str(MODEL_PATH),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Inference
# ─────────────────────────────────────────────────────────────────────────────

_MODEL_CACHE: Optional[Dict] = None

def _load_model() -> Optional[Dict]:
    global _MODEL_CACHE
    if _MODEL_CACHE is not None:
        return _MODEL_CACHE
    if not MODEL_PATH.exists():
        return None
    try:
        with open(MODEL_PATH, "rb") as f:
            _MODEL_CACHE = pickle.load(f)
        logger.info(f"[ML] Model loaded — n={_MODEL_CACHE.get('n_samples')} | auc={_MODEL_CACHE.get('roc_auc')}")
    except Exception as e:
        logger.warning(f"[ML] Model load failed: {e}")
        _MODEL_CACHE = None
    return _MODEL_CACHE


def predict_win_probability(features: Dict[str, float]) -> Dict[str, Any]:
    """
    Given a feature dict (from extract_features), return win probability.

    Returns:
      {
        "win_probability": 0.67,       # 0–1
        "win_pct": 67.3,               # human-readable
        "n_samples": 1247,
        "accuracy": 0.62,
        "model_age": "2h ago",
        "available": True
      }
    """
    bundle = _load_model()
    if bundle is None:
        return {
            "win_probability": 0.5,
            "win_pct": 50.0,
            "n_samples": 0,
            "available": False,
            "note": "Model not trained yet. Run train_model() first.",
        }

    model        = bundle["model"]
    feat_cols    = bundle["feature_cols"]
    x_row        = np.array([[features.get(c, 0.0) for c in feat_cols]])

    raw_prob = float(model.predict_proba(x_row)[0][1])
    iso_cal = bundle.get("isotonic_calibrator")
    if iso_cal is not None:
        try:
            calibrated_prob = float(np.clip(iso_cal.transform([raw_prob])[0], 0.0, 1.0))
        except Exception:
            calibrated_prob = _apply_calibration(raw_prob, bundle.get("calibration", {}))
    else:
        calibrated_prob = _apply_calibration(raw_prob, bundle.get("calibration", {}))

    # Model freshness
    trained_at = bundle.get("trained_at", "")
    try:
        from datetime import datetime, timezone
        delta = datetime.now(timezone.utc) - pd.Timestamp(trained_at, tz="UTC")
        h = int(delta.total_seconds() // 3600)
        age_str = f"{h}h ago" if h < 48 else f"{h//24}d ago"
    except Exception:
        age_str = "unknown"

    # Explainability: why does the AI like/dislike this?
    # We look at the features that are most "present" relative to the training importance
    # and map them to human reasons.
    reasons = []
    importance_map = {f["feature"]: f["label"] for f in bundle.get("feature_importance", [])}

    # Simple logic: Top 3 features that are notably far from 'neutral' (0 for many scaled ones)
    sorted_feats = sorted(features.items(), key=lambda x: abs(x[1]), reverse=True)
    for f_key, f_val in sorted_feats:
        label = importance_map.get(f_key)
        if label:
            reasons.append(f"{label}")
            if len(reasons) >= 3:
                break

    return {
        "win_probability": round(calibrated_prob, 4),
        "raw_win_probability": round(raw_prob, 4),
        "win_pct":         round(calibrated_prob * 100, 1),
        "raw_win_pct":     round(raw_prob * 100, 1),
        "n_samples":       bundle.get("n_samples", 0),
        "accuracy":        bundle.get("accuracy", 0),
        "roc_auc":         bundle.get("roc_auc", 0),
        "calibration":     bundle.get("calibration", {}),
        "model_age":       age_str,
        "rationale":       reasons,
        "hurst_exponent":  features.get("hurst_exponent", 0.5),
        "vol_skew":        features.get("vol_skew", 0.0),
        "available":       True,
    }


def invalidate_model_cache():
    """Call after retraining to reload the model on next predict."""
    global _MODEL_CACHE
    _MODEL_CACHE = None


def predict_with_neural_consensus(
    df: pd.DataFrame,
    idx: int,
    side: str = "BUY",
    symbol: str = "UNKNOWN",
    asset_class: str = "CRYPTO",
    sentiment_score: float = 0.0,
) -> Dict[str, Any]:
    """
    High-fidelity inference combining Ensemble + Deep Learning.
    Phase 8: Logic for Intelligence V6 Hybrid Attention Brain.
    """
    # ── V6 Adaptive Retrain Check ──────────────────────────────────────────
    # If the model is older than 24h OR performance has decayed, trigger background train
    _consider_auto_retrain()

    # Fetch daily context once for the current bar (multi-timeframe enrichment)
    _dc_lookup: Dict = {}
    _daily_ctx: Optional[Dict] = None
    try:
        _dc_lookup = _build_daily_context(symbol, asset_class)
        _ts_now = df.index[idx]
        if _dc_lookup and hasattr(_ts_now, "date"):
            _daily_ctx = _dc_lookup.get(_ts_now.date())
    except Exception:
        pass

    # Compute SMC context for CRYPTO/MACRO (used by both ensemble and neural features)
    _smc_ctx = None
    if asset_class in ("CRYPTO", "MACRO"):
        try:
            from intelligence.technical_engine import (
                get_smart_money_analysis as _get_smc,
            )
            _smc_ctx = _get_smc(df)
        except Exception:
            pass

    # 1. Ensemble V6 Opinion (Technical + Sentiment Snapshot)
    features = extract_features(df, idx, side, symbol, asset_class, sentiment_score, daily_context=_daily_ctx, smc_context=_smc_ctx)
    v3_result = predict_win_probability(features)

    # 2. Neural V8 Opinion (Deep Sequence Analysis)
    v8_prob = None
    v8_weights = []

    if TORCH_AVAILABLE:
        try:
            # Neural V8 requires sequence data (last 20 bars)
            if len(df) >= 20:
                seq_data = []
                for i in range(idx - 19, idx + 1):
                    _ts_i = df.index[i]
                    _dc_i = _dc_lookup.get(_ts_i.date()) if _dc_lookup and hasattr(_ts_i, "date") else None
                    seq_data.append(extract_features(df, i, symbol=symbol, asset_class=asset_class, daily_context=_dc_i, smc_context=_smc_ctx if i == idx else None))

                # Convert list of dicts to a 2D numpy array of values
                seq_arr = np.array([[f.get(c, 0.0) for c in FEATURE_COLS] for f in seq_data])

                from .neural_optimizer import get_neural_trainer
                trainer = get_neural_trainer(input_size=len(FEATURE_COLS))
                if trainer:
                    v8_prob, v8_weights = trainer.predict(seq_arr)
                    logger.info(f"🧠 Neural V8 Analysis: {v8_prob*100:.1f}% confidence")
        except Exception as ne:
            logger.debug(f"Neural inference failed: {ne}")

    # 3. Multi-timeframe gate: 4h + Daily alignment + VIX macro regime
    if _daily_ctx and v3_result.get("direction") in ("BUY", "SELL"):
        direction    = v3_result["direction"]
        d_bullish    = bool(_daily_ctx.get("d_bullish",   False))
        d_bearish    = bool(_daily_ctx.get("d_bearish",   False))
        h4_bullish   = bool(_daily_ctx.get("h4_bullish",  False))
        h4_bearish   = bool(_daily_ctx.get("h4_bearish",  False))
        vix_crisis   = bool(_daily_ctx.get("vix_crisis",  False))
        vix_risk_off = bool(_daily_ctx.get("vix_risk_off", False))
        vix_val      = float(_daily_ctx.get("vix", 0) or 0)

        mtf_blocked = False
        mtf_reason  = ""

        if vix_crisis:
            mtf_blocked = True
            mtf_reason  = f"VIX crisis ({vix_val:.0f} > 35) — all signals blocked"
        elif direction == "BUY":
            if not d_bullish or not h4_bullish:
                mtf_blocked = True
                mtf_reason  = f"BUY blocked: daily={'✓' if d_bullish else '✗'} 4h={'✓' if h4_bullish else '✗'}"
            elif vix_risk_off and asset_class.upper() == "CRYPTO":
                mtf_blocked = True
                mtf_reason  = f"CRYPTO BUY blocked: VIX risk-off ({vix_val:.0f} > 25)"
        elif direction == "SELL":
            if not d_bearish or not h4_bearish:
                mtf_blocked = True
                mtf_reason  = f"SELL blocked: daily={'✓' if d_bearish else '✗'} 4h={'✓' if h4_bearish else '✗'}"

        if mtf_blocked:
            v3_result.update({
                "direction":       "HOLD",
                "win_probability":  0.0,
                "win_pct":          0.0,
                "confidence":       0,
                "mtf_blocked":      True,
                "mtf_reason":       mtf_reason,
            })
            return v3_result

    # 4. Decision Stacking
    final_prob = v3_result["win_probability"]
    neural_alignment = False

    if v8_prob is not None:
        # Weighted Consensus: Ensemble (50%) + Neural (50%)
        final_prob = (v3_result["win_probability"] * 0.5) + (v8_prob * 0.5)

        # Unified Convergence: Both models agree > 75% on the signal (Sniper Threshold)
        if v3_result["win_probability"] > 0.75 and v8_prob > 0.75:
            neural_alignment = True

    # 4. Neural Metadata
    v3_result.update({
        "win_probability": round(final_prob, 4),
        "win_pct":         round(final_prob * 100, 1),
        "neural_alignment": neural_alignment,
        "v8_prob":         round(v8_prob, 4) if v8_prob is not None else 0.0,
        "attention_impact": v8_weights,
        "hybrid_active":   True,
    })

    # 5. Institutional Risk Checks (correlation, drawdown, funding rate, sizing)
    try:
        from .risk_manager import full_risk_check
        atr_pct = float(features.get("atr_pct", 1.0))
        vix_val = float((_daily_ctx or {}).get("vix", 0) or 0)
        risk = full_risk_check(
            symbol=symbol,
            side=side,
            win_probability=final_prob,
            atr_pct=atr_pct,
            vix=vix_val,
            asset_class=asset_class,
        )
        v3_result["risk"] = risk
        if not risk["ok"] and v3_result.get("direction") in ("BUY", "SELL"):
            v3_result["direction"]       = "HOLD"
            v3_result["win_probability"] = 0.0
            v3_result["win_pct"]         = 0.0
            v3_result["risk_blocked"]    = True
            v3_result["risk_reason"]     = ", ".join(risk["blocked_by"])
    except Exception as re:
        logger.debug(f"Risk check failed: {re}")

    return v3_result


_LAST_AUTO_RETRAIN_CHECK = 0


def get_auto_retrain_status(bundle: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Summarize whether the current model should be retrained soon."""
    if bundle is None:
        bundle = _load_model()

    if bundle is None:
        return {
            "available": False,
            "recommended": False,
            "reasons": [],
            "thresholds": {
                "recent_outcomes": AUTO_RETRAIN_MIN_RECENT_OUTCOMES,
                "decay_win_rate": AUTO_RETRAIN_DECAY_WIN_RATE,
                "new_outcomes_since_retrain": AUTO_RETRAIN_NEW_OUTCOMES_THRESHOLD,
                "max_model_age_days": AUTO_RETRAIN_MAX_AGE_DAYS,
            },
        }

    status: Dict[str, Any] = {
        "available": True,
        "recommended": False,
        "reasons": [],
        "thresholds": {
            "recent_outcomes": AUTO_RETRAIN_MIN_RECENT_OUTCOMES,
            "decay_win_rate": AUTO_RETRAIN_DECAY_WIN_RATE,
            "new_outcomes_since_retrain": AUTO_RETRAIN_NEW_OUTCOMES_THRESHOLD,
            "max_model_age_days": AUTO_RETRAIN_MAX_AGE_DAYS,
        },
        "recent_outcomes": 0,
        "recent_win_rate": None,
        "current_outcomes": 0,
        "outcomes_at_retrain": int(bundle.get("outcomes_at_retrain") or 0),
        "outcomes_since_retrain": 0,
        "model_age_days": None,
        "trained_at": bundle.get("trained_at"),
    }

    trained_at_raw = bundle.get("trained_at")
    if trained_at_raw:
        try:
            trained_at_dt = pd.to_datetime(trained_at_raw, utc=True, errors="coerce")
            if pd.notna(trained_at_dt):
                age_days = (pd.Timestamp.now(tz="UTC") - trained_at_dt).total_seconds() / 86400.0
                status["model_age_days"] = round(float(max(age_days, 0.0)), 2)
                if age_days >= AUTO_RETRAIN_MAX_AGE_DAYS:
                    status["recommended"] = True
                    status["reasons"].append("model_age")
        except Exception:
            pass

    try:
        conn = sqlite3.connect(str(PAPER_DB_PATH))
        recent_trades = pd.read_sql_query(
            """
            SELECT outcome FROM paper_trades
            WHERE status='CLOSED' AND outcome IS NOT NULL
            ORDER BY closed_at DESC LIMIT 50
            """,
            conn,
        )
        total_outcomes = pd.read_sql_query(
            """
            SELECT COUNT(*) AS total_count FROM paper_trades
            WHERE status='CLOSED' AND outcome IS NOT NULL
            """,
            conn,
        )
        conn.close()

        status["recent_outcomes"] = int(len(recent_trades))
        status["current_outcomes"] = int(total_outcomes["total_count"].iloc[0] or 0)
        status["outcomes_since_retrain"] = max(
            status["current_outcomes"] - status["outcomes_at_retrain"],
            0,
        )

        if len(recent_trades) >= AUTO_RETRAIN_MIN_RECENT_OUTCOMES:
            win_rate = float((recent_trades["outcome"] == "WIN").mean())
            status["recent_win_rate"] = round(win_rate, 4)
            if win_rate < AUTO_RETRAIN_DECAY_WIN_RATE:
                status["recommended"] = True
                status["reasons"].append("performance_decay")

        if status["outcomes_since_retrain"] >= AUTO_RETRAIN_NEW_OUTCOMES_THRESHOLD:
            status["recommended"] = True
            status["reasons"].append("new_labels")
    except Exception:
        pass

    return status

_AUTO_RETRAIN_RUNNING = False


def _consider_auto_retrain():
    """
    Intelligence V6: Adaptive Performance Trigger.
    Triggers retraining if:
    1. Current accuracy on paper trades is < 60% with enough samples.
    2. Significant number of new paper outcomes (50+) since last train.
    3. Model is older than 7 days anyway.
    """
    import threading
    import time
    global _LAST_AUTO_RETRAIN_CHECK, _AUTO_RETRAIN_RUNNING
    now = time.time()
    if now - _LAST_AUTO_RETRAIN_CHECK < 3600:
        return
    _LAST_AUTO_RETRAIN_CHECK = now

    status = get_auto_retrain_status()
    if not status.get("available") or not status.get("recommended"):
        return

    if _AUTO_RETRAIN_RUNNING:
        logger.info("[AutoRetrain] Retrain already running — skipping duplicate trigger")
        return

    reasons = status.get("reasons", [])
    outcome_reasons = [reason for reason in reasons if reason != "model_age"]
    if not outcome_reasons:
        logger.info(
            "[AutoRetrain] Model age warning only (%.2f days); waiting for new closed paper labels before retraining.",
            float(status.get("model_age_days") or 0.0),
        )
        return

    logger.warning(f"[AutoRetrain] Triggering background retrain. Reasons: {reasons}")

    def _retrain_worker():
        global _AUTO_RETRAIN_RUNNING
        _AUTO_RETRAIN_RUNNING = True
        try:
            dataset = None
            if str(os.getenv("ML_AUTO_RETRAIN_USE_CACHED_DATASET", "1")).strip().lower() not in {"0", "false", "no", "off"}:
                dataset = _cached_dataset_with_fresh_paper_labels()
            result = train_model(dataset=dataset) if dataset is not None else train_model()
            if "error" in result:
                logger.error(f"[AutoRetrain] Background retrain failed: {result['error']}")
            else:
                logger.info(
                    f"[AutoRetrain] Complete — "
                    f"acc={result.get('accuracy')} auc={result.get('roc_auc')} "
                    f"n={result.get('n_samples')}"
                )
                invalidate_model_cache()
        except Exception as exc:
            logger.error(f"[AutoRetrain] Exception: {exc}")
        finally:
            _AUTO_RETRAIN_RUNNING = False

    threading.Thread(target=_retrain_worker, name="auto-retrain", daemon=True).start()

    if "model_age" in status.get("reasons", []):
        logger.info(
            "V6 MODEL AGE: model is %.2f days old. Recommend retraining.",
            float(status.get("model_age_days") or 0.0),
        )
