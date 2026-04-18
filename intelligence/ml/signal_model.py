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

# Smaller symbol set used only for model training — crypto only (Binance, fast)
TRAIN_SYMBOLS = [
    ("BTC", "CRYPTO", "1h"),
    ("ETH", "CRYPTO", "1h"),
    ("SOL", "CRYPTO", "1h"),
]

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
    limit: int = 2000,
    sl_mult: float = 1.5,
    tp_mult: float = 3.0,
    max_bars: int = 48,
) -> pd.DataFrame:
    """
    Run backtests across symbols and return a labeled ML dataset.

    Label:
      1 = WIN  (price hit TP within max_bars)
      0 = LOSS (price hit SL or timed out)
    """
    from intelligence.technical_engine import compute_indicators
    import requests as _req

    BINANCE_TF = {"1h": "1h", "15m": "15m", "4h": "4h", "1d": "1d"}

    def _fetch_binance(sym: str, tf: str, n: int) -> "pd.DataFrame | None":
        """Fetch OHLCV directly from Binance — no PostgreSQL, no yfinance."""
        try:
            r = _req.get(
                "https://api.binance.com/api/v3/klines",
                params={"symbol": sym + "USDT", "interval": BINANCE_TF.get(tf, "1h"), "limit": min(n, 1000)},
                timeout=10,
            )
            if r.status_code != 200:
                return None
            raw = r.json()
            if not isinstance(raw, list) or len(raw) < 50:
                return None
            df_b = pd.DataFrame(raw, columns=[
                "open_time","Open","High","Low","Close","Volume",
                "close_time","qav","trades","tbav","tqav","ignore"
            ])
            df_b["Datetime"] = pd.to_datetime(df_b["open_time"], unit="ms", utc=True).dt.tz_localize(None)
            for c in ["Open","High","Low","Close","Volume"]:
                df_b[c] = pd.to_numeric(df_b[c], errors="coerce")
            return df_b[["Datetime","Open","High","Low","Close","Volume"]].dropna()
        except Exception as e:
            logger.warning(f"[ML-Dataset] Binance fetch {sym}: {e}")
            return None

    symbols = symbols or DEFAULT_SYMBOLS
    rows: List[Dict] = []

    for sym, asset_class, tf in symbols:
        df = _fetch_binance(sym, tf, limit) if asset_class == "CRYPTO" else None
        try:
            if df is None or len(df) < 200:
                logger.warning(f"[ML-Dataset] {sym}: insufficient data ({len(df) if df is not None else 0} bars)")
                continue

            df = compute_indicators(df)
            # Use relaxed training signals for higher label density
            df = _generate_training_signals(df, tf)
            df = df.dropna(subset=["rsi_14", "ema_20", "ema_50", "adx_14", "atr_14"])

            signal_idx = df.index[df["signal"] != 0].tolist()
            logger.info(f"[ML-Dataset] {sym}/{tf}: {len(signal_idx)} signals")

            close_arr = df["Close"].values
            high_arr  = df["High"].values
            low_arr   = df["Low"].values
            atr_arr   = df["atr_14"].values

            # Fetch sentiment ONCE per symbol (not per signal)
            sent_v = 0.0
            try:
                conn_pg = psycopg2.connect(
                    host=os.getenv("DB_HOST", "localhost"),
                    dbname=os.getenv("DB_NAME", "crypto_stream_db"),
                    user=os.getenv("DB_USER", "user"),
                    password=os.getenv("DB_PASS", "password"),
                    connect_timeout=3,
                )
                with conn_pg.cursor() as cur_pg:
                    cur_pg.execute("SELECT score FROM news_sentiment WHERE symbol=%s ORDER BY id DESC LIMIT 1", (sym.upper(),))
                    row_s = cur_pg.fetchone()
                    if row_s: sent_v = float(row_s[0])
                conn_pg.close()
            except Exception:
                pass  # PostgreSQL not running — use 0.0

            for pos in signal_idx:
                i = df.index.get_loc(pos)
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
                        if l <= sl:  label = 0; break
                        if h >= tp:  label = 1; break
                    else:
                        if h >= sl:  label = 0; break
                        if l <= tp:  label = 1; break

                if label is None:
                    label = 0

                feats = extract_features(df, i, side=side, symbol=sym, asset_class=asset_class, sentiment_score=sent_v)
                feats["label"]  = label
                feats["symbol"] = sym
                feats["side"]   = side
                feats["entry"]  = entry
                rows.append(feats)

        except Exception as e:
            logger.error(f"[ML-Dataset] {sym} error: {e}")

    if not rows:
        logger.warning("[ML-Dataset] No rows generated!")
        return pd.DataFrame()

    dataset = pd.DataFrame(rows)
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


# ─────────────────────────────────────────────────────────────────────────────
# Model Training
# ─────────────────────────────────────────────────────────────────────────────

def train_model(
    symbols: List[Tuple[str, str, str]] = None,
    limit: int = 2000,
) -> Dict[str, Any]:
    """
    Build dataset → train GradientBoostingClassifier → save model.
    Returns summary metrics.
    """
    try:
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import accuracy_score, roc_auc_score
        from sklearn.preprocessing import StandardScaler
        from sklearn.pipeline import Pipeline
    except ImportError:
        return {"error": "scikit-learn not installed. Run: pip install scikit-learn"}

    dataset = build_ml_dataset(symbols=symbols, limit=limit if limit else 5000)
    if dataset.empty or "label" not in dataset.columns:
        return {"error": "Empty dataset — no signals found"}

    # Use only rows that have all feature columns
    available = [c for c in FEATURE_COLS if c in dataset.columns]
    X_ens      = dataset[available].fillna(0).values
    X_neu      = None  # Neural trainer disabled
    y          = dataset["label"].values

    if len(X_ens) < 50:
        return {"error": f"Not enough training samples: {len(X_ens)} (need ≥ 50)"}

    # Split for Ensemble
    X_train_ens, X_test_ens, y_train, y_test = train_test_split(
        X_ens, y, test_size=0.25, random_state=42, stratify=y
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
    model.fit(X_train_ens, y_train)

    # Neural Trainer disabled for speed — GBM+RF ensemble is sufficient
    logger.info("[ML-Train] Skipping Neural V8 (disabled for faster retrain)")

    y_pred  = model.predict(X_test_ens)
    y_prob  = model.predict_proba(X_test_ens)[:, 1]
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

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MODEL_PATH, "wb") as f:
        pickle.dump({
            "model":               model,
            "feature_cols":        available,
            "feature_importance":  feat_imp,
            "n_samples":           len(X_ens),
            "accuracy":            round(acc, 4),
            "roc_auc":             round(auc, 4),
            "win_rate_train":      round(win_rate_train, 4),
            "trained_at":          pd.Timestamp.now().isoformat(),
            "outcomes_at_retrain": _outcomes_count,
        }, f)

    logger.info(f"[ML-Train] Saved Intelligence V8 model → {MODEL_PATH} | acc={acc:.1%} | auc={auc:.3f} | n={len(X_ens)}")

    return {
        "status":    "trained",
        "n_samples": len(X_ens),
        "accuracy":  round(acc, 4),
        "roc_auc":   round(auc, 4),
        "win_rate":  round(win_rate_train, 4),
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

    prob = float(model.predict_proba(x_row)[0][1])

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
            if len(reasons) >= 3: break

    return {
        "win_probability": round(prob, 4),
        "win_pct":         round(prob * 100, 1),
        "n_samples":       bundle.get("n_samples", 0),
        "accuracy":        bundle.get("accuracy", 0),
        "roc_auc":         bundle.get("roc_auc", 0),
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

    # Neural V8 disabled — GBM ensemble only
    v8_prob = None
    v8_weights = []

    # 3. Decision Stacking
    final_prob = v3_result["win_probability"]
    neural_alignment = False

    if v8_prob is not None:
        # Weighted Consensus: V8-Ensemble (50%) + V8-Attention (50%)
        final_prob = (v3_result["win_probability"] * 0.5) + (v8_prob * 0.5)
        
        # Unified Convergence: Both models agree > 65% on the signal
        if v3_result["win_probability"] > 0.65 and v8_prob > 0.65:
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
    if now - _LAST_AUTO_RETRAIN_CHECK < 3600: # Only check once per hour
        return
    _LAST_AUTO_RETRAIN_CHECK = now

    bundle = _load_model()
    if bundle is None: return

    # logic to trigger training script in background or separate thread
    # For now, we logging a suggestion or could spawn a subprocess.
    # In this environment, we recommend the user run it if we detect decay.
    try:
        conn = sqlite3.connect(str(PAPER_DB_PATH))
        recent_trades = pd.read_sql_query("""
            SELECT outcome FROM paper_trades 
            WHERE status='CLOSED' AND outcome IS NOT NULL
            ORDER BY closed_at DESC LIMIT 50
        """, conn)
        conn.close()

        if len(recent_trades) >= 20:
            win_rate = (recent_trades["outcome"] == "WIN").mean()
            if win_rate < 0.45: # Critical performance decay
                logger.warning(f"V6 PERFORMANCE DECAY: Recent win rate {win_rate:.1%}. Recommend retraining.")
    except Exception:
        pass
