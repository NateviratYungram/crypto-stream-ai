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
import os
import json
import logging
import sqlite3
import psycopg2
from dotenv import load_dotenv
import pickle
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any

import numpy as np
import pandas as pd

from .feature_extractor import extract_features, FEATURE_COLS
try:
    from .neural_optimizer import get_neural_optimizer, TORCH_AVAILABLE
except (ImportError, SyntaxError, Exception):
    TORCH_AVAILABLE = False
    def get_neural_optimizer(*a, **kw): return None

load_dotenv()

logger = logging.getLogger(__name__)

MODEL_PATH    = Path(os.getenv("ML_MODEL_PATH", "data/signal_model.pkl"))
DATASET_PATH  = Path(os.getenv("ML_DATASET_PATH", "data/ml_dataset.parquet"))
PAPER_DB_PATH = os.getenv("PAPER_TRADE_DB", "persistence.db")

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
# Covers: Crypto, Forex, Commodities across 3 timeframes for rich ML coverage
# Only includes symbols confirmed available in XM Global MT5 terminal
TRADE_TRAIN_SYMBOLS = [
    # ── Crypto ──────────────────────────────────────────────────────────────
    ("BTCUSD", "CRYPTO", "15m"),
    ("BTCUSD", "CRYPTO", "1h"),
    ("BTCUSD", "CRYPTO", "4h"),
    ("ETHUSD", "CRYPTO", "15m"),
    ("ETHUSD", "CRYPTO", "1h"),
    ("ETHUSD", "CRYPTO", "4h"),
    ("SOLUSD", "CRYPTO", "1h"),
    ("SOLUSD", "CRYPTO", "4h"),
    ("XRPUSD", "CRYPTO", "1h"),
    ("XRPUSD", "CRYPTO", "4h"),
    # ── Commodities ──────────────────────────────────────────────────────────
    ("GOLD",   "MACRO",  "15m"),
    ("GOLD",   "MACRO",  "1h"),
    ("GOLD",   "MACRO",  "4h"),
    ("SILVER", "MACRO",  "1h"),
    ("SILVER", "MACRO",  "4h"),
    # ── Major Forex ──────────────────────────────────────────────────────────
    ("EURUSD", "MACRO",  "15m"),
    ("EURUSD", "MACRO",  "1h"),
    ("EURUSD", "MACRO",  "4h"),
    ("GBPUSD", "MACRO",  "1h"),
    ("GBPUSD", "MACRO",  "4h"),
    ("USDJPY", "MACRO",  "1h"),
    ("USDJPY", "MACRO",  "4h"),
    ("USDCHF", "MACRO",  "1h"),
    ("AUDUSD", "MACRO",  "1h"),
    ("NZDUSD", "MACRO",  "1h"),
]

# Expanded symbol set for model training — full tradeable universe
TRAIN_SYMBOLS = [item for item in TRADE_TRAIN_SYMBOLS if item[2] in ("15m", "1h")]
DEFAULT_TRAIN_LIMIT = 5000
ML_CORE_SYMBOLS = ["BTCUSD", "ETHUSD", "GOLD", "EURUSD"]
ML_SUFFICIENCY_TARGETS = {
    "paper_labels": 100,
    "training_samples": 1500,
    "core_symbols": len(ML_CORE_SYMBOLS),
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

def _generate_training_signals(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    """
    Relaxed signal generator specifically for ML training data.
    Produces more labeled examples than the strict live-trading version.

    Rules (per bar, no consecutive same-direction signals):
      BUY  when: price > ema50 AND rsi < 55 AND (adx > 18 OR rsi < 40)
      SELL when: price < ema50 AND rsi > 45 AND (adx > 18 OR rsi > 60)

    Timeframe-specific RSI tuning:
      1d  → wider bands (rsi 42 / 58) to capture multi-week moves
      15m → tighter bands (rsi 48 / 52) to capture intraday momentum
    """
    import numpy as np
    df = df.copy()
    required = {"rsi_14", "ema_50", "adx_14", "atr_14"}
    if not required.issubset(df.columns):
        return df

    is_daily  = tf in ("1d", "1w")
    rsi_long  = 42 if is_daily else 48
    rsi_short = 58 if is_daily else 52
    adx_min   = 15

    close = df["Close"].values
    ema50 = df["ema_50"].values
    rsi   = df["rsi_14"].values
    adx   = df["adx_14"].values
    n     = len(df)

    signals = np.zeros(n, dtype=int)
    for i in range(1, n):
        r = float(rsi[i]) if not np.isnan(rsi[i]) else 50
        a = float(adx[i]) if not np.isnan(adx[i]) else 0
        c = float(close[i])
        e = float(ema50[i]) if not np.isnan(ema50[i]) else c

        buy_cond  = c > e and r < rsi_long  and (a > adx_min or r < 35)
        sell_cond = c < e and r > rsi_short and (a > adx_min or r > 65)

        if buy_cond  and signals[i-1] != 1:
            signals[i] = 1
        elif sell_cond and signals[i-1] != -1:
            signals[i] = -1

    df["signal"] = signals
    return df


def build_ml_dataset(
    symbols: List[Tuple[str, str, str]] = None,
    limit: int = DEFAULT_TRAIN_LIMIT,
    sl_mult: float = 1.5,
    tp_mult: float = 3.0,
    max_bars: int = 48,
    sequence_length: int = 20, # Number of bars for neural temporal memory
) -> pd.DataFrame:
    """
    Run backtests across symbols and return a labeled ML dataset.

    Label:
      1 = WIN  (price hit TP within max_bars)
      0 = LOSS (price hit SL or timed out)
    """
    from intelligence.technical_engine import compute_indicators, get_kline_data
    import requests as _req

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

            # Compute indicators and generate relaxed training signals
            df = compute_indicators(df)
            df = _generate_training_signals(df, tf)
            df = df.dropna(subset=["rsi_14", "ema_20", "ema_50", "adx_14", "atr_14"])

            signal_idx = df.index[df["signal"] != 0].tolist()
            logger.info(f"[ML-Dataset] {sym}/{tf}: {len(signal_idx)} signals found in {len(df)} bars")

            close_arr = df["Close"].values
            high_arr  = df["High"].values
            low_arr   = df["Low"].values
            atr_arr   = df["atr_14"].values

            # Pre-calculate features for all rows to speed up sequence synthesis
            # This is faster than calling extract_features in a loop
            feature_list = []
            for i in range(len(df)):
                feature_list.append(extract_features(df, i, symbol=sym, asset_class=asset_class))

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
                    l = float(low_arr[j])
                    if side == "BUY":
                        if l <= sl:
                            label = 0
                            break
                        if h >= tp:
                            label = 1
                            break
                    else:
                        if h >= sl:
                            label = 0
                            break
                        if l <= tp:
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


def _load_paper_trade_outcomes() -> List[Dict]:
    """Load closed paper trades that have SL/TP outcome labels."""
    rows = []
    try:
        con = sqlite3.connect(PAPER_DB_PATH)
        cur = con.cursor()
        cur.execute("""
            SELECT symbol, side, entry_price, sl, tp, outcome, features_json, closed_at
            FROM paper_trades
            WHERE status='CLOSED' AND outcome IS NOT NULL AND features_json IS NOT NULL
        """)
        for r in cur.fetchall():
            sym, side, entry, sl, tp, outcome, feat_json, _ = r
            if outcome not in ("WIN", "LOSS"):
                continue
            try:
                feats = json.loads(feat_json or "{}")
            except Exception:
                feats = {}
            feats["label"]  = 1 if outcome == "WIN" else 0
            feats["symbol"] = sym
            feats["side"]   = side
            feats["entry"]  = entry
            rows.append(feats)
        con.close()
    except Exception:
        pass
    return rows


def _build_dataset_report(dataset: pd.DataFrame) -> List[Dict[str, Any]]:
    """Summarize dataset quality per symbol/timeframe slice."""
    if dataset is None or dataset.empty:
        return []

    required = {"symbol", "timeframe", "label"}
    if not required.issubset(dataset.columns):
        return []

    report_rows: List[Dict[str, Any]] = []
    grouped = dataset.groupby(["symbol", "timeframe"], dropna=False)
    for (symbol, timeframe), frame in grouped:
        labels = pd.to_numeric(frame["label"], errors="coerce").dropna()
        if labels.empty:
            continue
        report_rows.append({
            "symbol": str(symbol),
            "timeframe": str(timeframe),
            "samples": int(len(frame)),
            "wins": int(labels.sum()),
            "losses": int(len(labels) - labels.sum()),
            "win_rate": round(float(labels.mean()), 4),
        })

    report_rows.sort(key=lambda row: (-row["samples"], row["symbol"], row["timeframe"]))
    return report_rows


def _build_sufficiency_status(
    dataset: pd.DataFrame,
    outcomes_count: int,
    dataset_report: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Track whether data is sufficient enough to trust iterative model improvement."""
    dataset_report = dataset_report or _build_dataset_report(dataset)
    present_symbols = sorted({str(row["symbol"]) for row in dataset_report})
    core_covered = [symbol for symbol in ML_CORE_SYMBOLS if symbol in present_symbols]
    training_samples = int(len(dataset)) if dataset is not None else 0

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
    report = _build_dataset_report(dataset)
    if not report:
        return dataset, []

    keep_keys = set()
    pruned: List[Dict[str, Any]] = []
    for row in report:
        enough_samples = row["samples"] >= min_samples
        enough_balance = row["wins"] >= min_wins and row["losses"] >= min_losses
        if enough_samples and enough_balance:
            keep_keys.add((row["symbol"], row["timeframe"]))
        else:
            reasons = []
            if not enough_samples:
                reasons.append(f"samples<{min_samples}")
            if row["wins"] < min_wins:
                reasons.append(f"wins<{min_wins}")
            if row["losses"] < min_losses:
                reasons.append(f"losses<{min_losses}")
            pruned.append({**row, "reason": ", ".join(reasons)})

    if not keep_keys:
        return dataset, pruned

    mask = dataset.apply(
        lambda row: (str(row.get("symbol")), str(row.get("timeframe"))) in keep_keys,
        axis=1,
    )
    filtered = dataset.loc[mask].copy()
    return filtered, pruned


def _build_calibration_profile(y_true: np.ndarray, y_prob: np.ndarray, bins: int = 6) -> Dict[str, Any]:
    """Create a simple quantile-based calibration map from holdout predictions."""
    if len(y_true) == 0 or len(y_true) != len(y_prob):
        return {"available": False}

    order = np.argsort(y_prob)
    sorted_true = y_true[order]
    sorted_prob = y_prob[order]
    edges = np.linspace(0, len(sorted_prob), bins + 1, dtype=int)
    bucket_rows: List[Dict[str, Any]] = []

    for start, end in zip(edges[:-1], edges[1:]):
        if end <= start:
            continue
        p_slice = sorted_prob[start:end]
        y_slice = sorted_true[start:end]
        bucket_rows.append({
            "pred_mean": round(float(np.mean(p_slice)), 4),
            "actual_rate": round(float(np.mean(y_slice)), 4),
            "count": int(len(p_slice)),
        })

    if not bucket_rows:
        return {"available": False}

    brier = float(np.mean((y_prob - y_true) ** 2))
    ece = float(np.mean([abs(bucket["pred_mean"] - bucket["actual_rate"]) * bucket["count"] for bucket in bucket_rows]) / len(y_prob))
    return {
        "available": True,
        "method": "quantile_bin_empirical_rate",
        "bins": bucket_rows,
        "brier_score": round(brier, 4),
        "ece": round(ece, 4),
    }


def _apply_calibration(prob: float, calibration: Dict[str, Any]) -> float:
    """Map raw probability to empirical holdout win rate."""
    if not calibration or not calibration.get("available"):
        return float(np.clip(prob, 0.0, 1.0))

    bins = calibration.get("bins") or []
    if not bins:
        return float(np.clip(prob, 0.0, 1.0))

    pred_means = np.array([float(bucket["pred_mean"]) for bucket in bins], dtype=float)
    actual_rates = np.array([float(bucket["actual_rate"]) for bucket in bins], dtype=float)
    if len(pred_means) == 1:
        return float(np.clip(actual_rates[0], 0.0, 1.0))

    calibrated = float(np.interp(prob, pred_means, actual_rates, left=actual_rates[0], right=actual_rates[-1]))
    return float(np.clip(calibrated, 0.0, 1.0))


def _walk_forward_evaluate(
    base_model,
    X: np.ndarray,
    y: np.ndarray,
    min_train_size: int = 200,
    test_window: int = 80,
    max_folds: int = 4,
) -> Dict[str, Any]:
    """Evaluate with expanding-window folds to reduce one-split bias."""
    if len(X) < (min_train_size + test_window):
        return {"available": False, "folds": [], "summary": None}

    from sklearn.base import clone
    from sklearn.metrics import accuracy_score, roc_auc_score

    folds: List[Dict[str, Any]] = []
    train_end = min_train_size

    while train_end + test_window <= len(X) and len(folds) < max_folds:
        X_train = X[:train_end]
        y_train = y[:train_end]
        X_test = X[train_end:train_end + test_window]
        y_test = y[train_end:train_end + test_window]

        class_counts = pd.Series(y_train).value_counts()
        sample_weights = np.array(
            [len(y_train) / max(class_counts.get(label, 1) * len(class_counts), 1) for label in y_train],
            dtype=float,
        )

        fold_model = clone(base_model)
        fold_model.fit(X_train, y_train, clf__sample_weight=sample_weights)
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
        train_end += test_window

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
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.metrics import accuracy_score, roc_auc_score
        from sklearn.preprocessing import StandardScaler
        from sklearn.pipeline import Pipeline
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
    X_neu = None  # Neural trainer disabled
    y = dataset["label"].values

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

    # Split for Neural
    X_train_neu = X_test_neu = None
    if X_neu is not None:
        X_train_neu = X_neu[:len(X_train_ens)]
        X_test_neu  = X_neu[len(X_train_ens):]

    from sklearn.ensemble import VotingClassifier, RandomForestClassifier

    model = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", VotingClassifier(
            estimators=[
                ("gbm", GradientBoostingClassifier(
                    n_estimators=100, max_depth=3, learning_rate=0.05,
                    subsample=0.8, random_state=42
                )),
                ("rf", RandomForestClassifier(
                    n_estimators=100, max_depth=8, random_state=42,
                    class_weight="balanced", n_jobs=-1
                ))
            ],
            voting="soft"
        )),
    ])

    logger.info(f"[ML-Train] Training Ensemble V3 on {len(X_train_ens)} samples...")
    model.fit(X_train_ens, y_train, clf__sample_weight=sample_weights)
    walk_forward = _walk_forward_evaluate(model, X_ens, y)

    # Neural Trainer disabled for speed — GBM+RF ensemble is sufficient
    logger.info("[ML-Train] Skipping Neural V8 (disabled for faster retrain)")

    y_pred  = model.predict(X_test_ens)
    y_prob  = model.predict_proba(X_test_ens)[:, 1]
    calibration = _build_calibration_profile(y_test, y_prob)
    acc     = accuracy_score(y_test, y_pred)
    auc     = roc_auc_score(y_test, y_prob) if len(set(y_test)) > 1 else 0.5
    win_rate_train = float(np.mean(y_train))
    win_rate_test  = float(np.mean(y_test))

    # Feature importances averaged from the ensemble (GBM + RF)
    voting_clf = model.named_steps["clf"]
    gbm = voting_clf.named_estimators_["gbm"]
    rf  = voting_clf.named_estimators_["rf"]

    # Average the feature importances from both models
    importances = (gbm.feature_importances_ + rf.feature_importances_) / 2.0

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

    dataset_report = _build_dataset_report(dataset)
    sufficiency = _build_sufficiency_status(dataset, _outcomes_count, dataset_report)

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
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
            "walk_forward":        walk_forward,
            "calibration":         calibration,
            "sufficiency":         sufficiency,
            "accuracy":            round(acc, 4),
            "roc_auc":             round(auc, 4),
            "win_rate_train":      round(win_rate_train, 4),
            "win_rate_test":       round(win_rate_test, 4),
            "trained_at":          pd.Timestamp.now().isoformat(),
            "outcomes_at_retrain": _outcomes_count,
        }, f)

    logger.info(f"[ML-Train] Saved Intelligence V8 model → {MODEL_PATH} | acc={acc:.1%} | auc={auc:.3f} | n={len(X_ens)}")

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

    # 1. Ensemble V6 Opinion (Technical + Sentiment Snapshot)
    features = extract_features(df, idx, side, symbol, asset_class, sentiment_score)
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
                    seq_data.append(extract_features(df, i, symbol=symbol, asset_class=asset_class))

                # Convert list of dicts to a 2D numpy array of values
                seq_arr = np.array([[f.get(c, 0.0) for c in FEATURE_COLS] for f in seq_data])

                from .neural_optimizer import get_neural_trainer
                trainer = get_neural_trainer(input_size=len(FEATURE_COLS))
                if trainer:
                    v8_prob, v8_weights = trainer.predict(seq_arr)
                    logger.info(f"🧠 Neural V8 Analysis: {v8_prob*100:.1f}% confidence")
        except Exception as ne:
            logger.debug(f"Neural inference failed: {ne}")

    # 3. Decision Stacking
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

def _consider_auto_retrain():
    """
    Intelligence V6: Adaptive Performance Trigger.
    Triggers retraining if:
    1. Current accuracy on paper trades is < 60% with enough samples.
    2. Significant number of new paper outcomes (50+) since last train.
    3. Model is older than 7 days anyway.
    """
    import time
    global _LAST_AUTO_RETRAIN_CHECK
    now = time.time()
    if now - _LAST_AUTO_RETRAIN_CHECK < 3600:
        return
    _LAST_AUTO_RETRAIN_CHECK = now

    status = get_auto_retrain_status()
    if not status.get("available"):
        return

    if "performance_decay" in status.get("reasons", []):
        logger.warning(
            "V6 PERFORMANCE DECAY: Recent win rate %s. Recommend retraining.",
            f"{(status.get('recent_win_rate') or 0.0):.1%}",
        )

    if "new_labels" in status.get("reasons", []):
        logger.info(
            "V6 DATA SUFFICIENCY: %s new labeled outcomes since last train.",
            status.get("outcomes_since_retrain", 0),
        )

    if "model_age" in status.get("reasons", []):
        logger.info(
            "V6 MODEL AGE: model is %.2f days old. Recommend retraining.",
            float(status.get("model_age_days") or 0.0),
        )
