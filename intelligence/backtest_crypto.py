"""
CryptoStream AI — Backtest Engine v4
Ported & adapted from QuantAgent backtest_engine.py + original logic.

Improvements over v3:
  - Regime-aware signal generation (TRENDING / RANGING / TRANSITIONING)
    ported from QuantAgent _signal_from_series()
  - Ambiguous bar handling: if SL & TP both hit in same candle → SL wins (conservative)
  - optimize_backtest(): grid-search best params via 70/30 train-test split
  - walk_forward_backtest(): rolling out-of-sample validation (gold standard)
  - Trailing Stop Loss (lets winners run)
  - Partial TP: 50% out at TP1, trail remainder
  - Portfolio mode: trade multiple assets simultaneously
  - Leverage simulation
  - Full metrics: PF, expectancy, max drawdown, annualized Sharpe, CAGR
"""

import itertools
import logging
import pandas as pd
import numpy as np
from intelligence.technical_engine import get_kline_data, compute_indicators
try:
    from intelligence.ml.signal_model import predict_win_probability
except Exception:
    def predict_win_probability(*a, **kw): return {"win_probability": 0.5, "direction": "HOLD", "confidence": 0}
from intelligence.ml.feature_extractor import extract_features

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Bars-per-year lookup (for CAGR & annualized Sharpe)
# ─────────────────────────────────────────────────────────────────────────────
_BARS_PER_YEAR = {
    "1m":  525_600,
    "3m":  175_200,
    "5m":  105_120,
    "15m":  35_040,
    "30m":  17_520,
    "1h":   8_760,
    "2h":   4_380,
    "4h":   2_190,
    "1d":     365,
    "1w":      52,
}

# ─────────────────────────────────────────────────────────────────────────────
# Default parameter set  (matches QuantAgent DEFAULT_CONFIG spirit)
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_PARAMS = {
    "adx_trending_threshold": 25,   # ADX > 25  → TRENDING regime
    "adx_ranging_threshold":  20,   # ADX < 20  → RANGING  regime
    "adx_trade_min":          22,   # Trending trades require at least this ADX
    "rsi_oversold":           35,   # RANGING: buy signal
    "rsi_overbought":         65,   # RANGING: sell signal
    "rsi_long_block":         75,   # Hard block: never go LONG above this RSI
    "rsi_short_block":        25,   # Hard block: never go SHORT below this RSI
    "sl_atr_mult":           1.5,   # Stop Loss  = entry ± ATR × mult
    "tp1_atr_mult":          2.0,   # Take Profit 1 (partial exit)
    "tp2_atr_mult_base":     3.0,   # TP2 base multiple (scaled by ADX)
    "risk_reward_min":       1.5,   # Minimum R:R before a trade is taken
    "max_hold_bars":          30,   # Time-stop (bars)
    "risk_pct":              2.0,   # % of balance risked per trade
    "leverage":              1.0,
}


# ─────────────────────────────────────────────────────────────────────────────
# Regime-aware Signal Generation  (ported from QuantAgent backtest_engine.py)
# ─────────────────────────────────────────────────────────────────────────────

def _classify_regime(adx_val: float, params: dict) -> str:
    if adx_val >= params["adx_trending_threshold"]:
        return "TRENDING"
    if adx_val <= params["adx_ranging_threshold"]:
        return "RANGING"
    return "TRANSITIONING"


def generate_backtest_signals(df: pd.DataFrame, params: dict = None, asset_class: str = "crypto") -> pd.DataFrame:
    """
    Regime-aware signal generation:

    TRENDING  (ADX ≥ 25): Fire on MACD histogram zero-cross ONLY, with EMA alignment.
                           Skip if ADX < adx_trade_min (weak trend → noise).
    RANGING   (ADX ≤ 20): Fire on RSI oversold/overbought mean-reversion.
    TRANSITIONING (20–25): Both modes valid but require both conditions to agree.

    Hard blocks (ported from QuantAgent guard_layer):
      - Never LONG if RSI > rsi_long_block
      - Never SHORT if RSI < rsi_short_block

    ML Enhancement:
      - If use_ml_filter in params is True, calculates an 'ml_edge' for each signal.
    """
    p = {**DEFAULT_PARAMS, **(params or {})}
    use_ml = p.get("use_ml_filter", False)
    df = df.copy()
    required = {"macd", "macd_signal", "rsi_14", "ema_20", "ema_50", "adx_14", "hurst_100"}
    if not required.issubset(df.columns):
        logger.warning(f"generate_backtest_signals: missing columns {required - set(df.columns)}, returning empty")
        return pd.DataFrame()

    macd   = df["macd"].values
    sig    = df["macd_signal"].values
    hist   = macd - sig           # MACD histogram
    rsi    = df["rsi_14"].values
    close  = df["Close"].values
    ema20  = df["ema_20"].values
    ema50  = df["ema_50"].values
    adx    = df["adx_14"].values
    n      = len(df)

    signals = np.zeros(n, dtype=int)

    for i in range(1, n):
        adx_i   = adx[i]   if not np.isnan(adx[i])   else 0
        rsi_i   = rsi[i]   if not np.isnan(rsi[i])   else 50
        hist_i  = hist[i]  if not np.isnan(hist[i])  else 0
        hist_p  = hist[i-1] if not np.isnan(hist[i-1]) else 0

        regime = _classify_regime(adx_i, p)

        direction = None

        # Intelligence V5/V6: Hurst Regime Filter
        # If mean-reverting (H<0.45), we block trend-following signals and favor RSI extremes.
        # If trending (H>0.55), we block RSI mean-reversion and favor EMA/MACD momentum.
        h_i = df["hurst_100"].values[i]
        is_trending_h = h_i > 0.55
        is_reverting_h = h_i < 0.45

        if regime == "TRENDING":
            if adx_i < p["adx_trade_min"] or is_reverting_h:
                continue                    # weak trend or mean-reverting regime — skip trend signals
            
            # MACD histogram zero-cross  +  EMA alignment
            if hist_p <= 0 < hist_i and close[i] > ema20[i] > ema50[i]:
                direction = 1   # LONG
            elif hist_p >= 0 > hist_i and close[i] < ema20[i] < ema50[i]:
                direction = -1  # SHORT

        elif regime == "RANGING":
            if is_trending_h: 
                continue # Strong trend regime — skip RSI mean-reversion signals
            
            # RSI mean-reversion with EMA sanity check
            if rsi_i <= p["rsi_oversold"] and close[i] > ema50[i]:
                direction = 1
            elif rsi_i >= p["rsi_overbought"] and close[i] < ema50[i]:
                direction = -1

        else:  # TRANSITIONING — need both MACD momentum AND RSI confirmation
            if hist_p <= 0 < hist_i and rsi_i < 55 and close[i] > ema20[i]:
                direction = 1
            elif hist_p >= 0 > hist_i and rsi_i > 45 and close[i] < ema20[i]:
                direction = -1

        # Hard RSI blocks (ported from QuantAgent guard_layer)
        if direction == 1  and rsi_i > p["rsi_long_block"]:
            direction = None
        if direction == -1 and rsi_i < p["rsi_short_block"]:
            direction = None

        # Fire only on first bar entering signal (no repeat)
        if direction is not None and signals[i-1] != direction:
            signals[i] = direction
            
            if use_ml:
                side = "BUY" if direction == 1 else "SELL"
                try:
                    feats = extract_features(df, i, side=side, asset_class=asset_class)
                    res   = predict_win_probability(feats)
                    df.at[df.index[i], "ml_edge"] = res.get("win_pct", 0)
                except:
                    df.at[df.index[i], "ml_edge"] = 0

    df["signal"] = signals
    df["regime"] = [_classify_regime(a if not np.isnan(a) else 0, p) for a in adx]
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Core Simulator
# ─────────────────────────────────────────────────────────────────────────────

def simulate_trades(df: pd.DataFrame,
                    initial_balance: float = 100.0,
                    risk_pct: float = 2.0,
                    leverage: float = 1.0,
                    use_trailing_stop: bool = True,
                    partial_tp: bool = True,
                    max_bars: int = 30,
                    timeframe: str = "15m",
                    sl_atr_mult: float = 1.5,
                    tp1_atr_mult: float = 2.0,
                    tp2_atr_mult_base: float = 3.0,
                    min_ml_edge: float = 0.0) -> dict:
    """
    Bar-by-bar trade simulator.

    Key improvements over v3:
      - Ambiguous bar: if SL and TP both hit in the same candle → SL is taken
        (conservative — worst-case fills, ported from QuantAgent)
      - tp2_atr_mult scales with ADX (stronger trend → wider TP2)
    """
    if df.empty or "signal" not in df.columns or "atr_14" not in df.columns:
        return {"error": "Insufficient data/indicators for simulation"}

    bars_per_year = _BARS_PER_YEAR.get(timeframe, 35_040)

    trades       = []
    balance      = initial_balance
    peak_balance = initial_balance
    in_position  = False
    partial_done = False

    entry_price = stop_loss = take_profit1 = take_profit2 = 0.0
    pos_type = 0
    pos_size = 0.0
    bars_held = 0
    best_price = 0.0

    records = df.reset_index(drop=True).to_dict("records")

    for row in records:
        price = float(row["Close"])
        high  = float(row["High"])
        low   = float(row["Low"])
        atr   = float(row.get("atr_14", 0) or 0)
        adx_v = float(row.get("adx_14", 20) or 20)

        # ── Manage open position ──────────────────────────────────────────────
        if in_position:
            bars_held += 1

            # Trailing stop update
            if use_trailing_stop and atr > 0:
                if pos_type == 1:
                    best_price = max(best_price, high)
                    trail_sl   = best_price - atr * sl_atr_mult
                    stop_loss  = max(stop_loss, trail_sl)
                else:
                    best_price = min(best_price, low)
                    trail_sl   = best_price + atr * sl_atr_mult
                    stop_loss  = min(stop_loss, trail_sl)

            pnl_pct      = 0.0
            closed       = False
            close_reason = ""

            if pos_type == 1:  # LONG
                hit_sl = low  <= stop_loss
                hit_tp = high >= take_profit2
                hit_tp1 = high >= take_profit1

                # Partial TP1 (before checking ambiguous bar)
                if partial_tp and not partial_done and hit_tp1 and not hit_sl:
                    half_profit  = (take_profit1 - entry_price) / entry_price * (pos_size * 0.5) * leverage
                    balance     += half_profit
                    peak_balance = max(peak_balance, balance)
                    pos_size    *= 0.5
                    partial_done = True

                # Ambiguous bar: SL and TP both hit → conservative (SL)
                if hit_sl and hit_tp:
                    pnl_pct = (stop_loss - entry_price) / entry_price
                    closed, close_reason = True, "SL"
                elif hit_sl:
                    pnl_pct = (stop_loss - entry_price) / entry_price
                    closed, close_reason = True, "SL"
                elif hit_tp:
                    pnl_pct = (take_profit2 - entry_price) / entry_price
                    closed, close_reason = True, "TP2"
                elif bars_held >= max_bars:
                    pnl_pct = (price - entry_price) / entry_price
                    closed, close_reason = True, "TIME"

            elif pos_type == -1:  # SHORT
                hit_sl  = high >= stop_loss
                hit_tp  = low  <= take_profit2
                hit_tp1 = low  <= take_profit1

                if partial_tp and not partial_done and hit_tp1 and not hit_sl:
                    half_profit  = (entry_price - take_profit1) / entry_price * (pos_size * 0.5) * leverage
                    balance     += half_profit
                    peak_balance = max(peak_balance, balance)
                    pos_size    *= 0.5
                    partial_done = True

                # Ambiguous bar → SL wins
                if hit_sl and hit_tp:
                    pnl_pct = (entry_price - stop_loss) / entry_price
                    closed, close_reason = True, "SL"
                elif hit_sl:
                    pnl_pct = (entry_price - stop_loss) / entry_price
                    closed, close_reason = True, "SL"
                elif hit_tp:
                    pnl_pct = (entry_price - take_profit2) / entry_price
                    closed, close_reason = True, "TP2"
                elif bars_held >= max_bars:
                    pnl_pct = (entry_price - price) / entry_price
                    closed, close_reason = True, "TIME"

            if closed:
                profit       = pnl_pct * pos_size * leverage
                balance     += profit
                peak_balance = max(peak_balance, balance)
                trades.append({
                    "type":    "LONG" if pos_type == 1 else "SHORT",
                    "reason":  close_reason,
                    "pnl_pct": round(pnl_pct * leverage * 100, 3),
                    "profit":  round(profit, 4),
                    "balance": round(balance, 4),
                    "bars":    bars_held,
                    "partial": partial_done,
                    "regime":  row.get("regime", "?"),
                })
                in_position  = False
                partial_done = False
                bars_held    = 0

        # ── New entry ─────────────────────────────────────────────────────────
        if not in_position and row.get("signal", 0) != 0 and atr > 0 and balance > 0:
            # ML Filter check
            if min_ml_edge > 0:
                edge = row.get("ml_edge", 0)
                if edge < min_ml_edge:
                    continue  # Filtered by AI!

            pos_type    = int(row["signal"])
            entry_price = price

            # TP2 widens with trend strength (from QuantAgent concept)
            tp2_mult = (tp2_atr_mult_base + 1.0) if adx_v > 30 else \
                       (tp2_atr_mult_base + 0.5) if adx_v > 22 else tp2_atr_mult_base

            if pos_type == 1:
                stop_loss    = entry_price - atr * sl_atr_mult
                take_profit1 = entry_price + atr * tp1_atr_mult
                take_profit2 = entry_price + atr * tp2_mult
                best_price   = entry_price
            else:
                stop_loss    = entry_price + atr * sl_atr_mult
                take_profit1 = entry_price - atr * tp1_atr_mult
                take_profit2 = entry_price - atr * tp2_mult
                best_price   = entry_price

            sl_dist  = abs(entry_price - stop_loss)
            
            # V6 Dynamic Sizing (Kelly Criterion)
            current_risk_pct = risk_pct
            if False:  # Kelly sizing disabled (p not in scope here)
                # Simplified Kelly for backtest: uses win probability (from ml_edge or default)
                # K = p - (1-p)/RR
                win_prob = row.get("ml_edge", 55.0) / 100.0 # Default 55% edge
                rr_est = (tp1_atr_mult + tp2_atr_mult_base) / 2 / sl_atr_mult
                k_pct = (win_prob * (rr_est + 1) - 1) / rr_est if rr_est > 0 else 0.02
                # Fractional Kelly (0.25) + Cap at 5%
                current_risk_pct = min(max(0.01, k_pct * 0.25) * 100, 5.0) 

            risk_amt = balance * (current_risk_pct / 100)
            pos_size = (risk_amt / (sl_dist / entry_price)) if sl_dist > 0 else 0
            pos_size = min(pos_size, balance * leverage)

            in_position  = True
            partial_done = False
            bars_held    = 0
            pass  # active_risk_pct annotation removed (i not in scope)

    # ── Metrics ───────────────────────────────────────────────────────────────
    if not trades:
        return {
            "status":          "no_trades",
            "message":         "No signals generated",
            "candles_analyzed": len(df),
        }

    wins   = [t for t in trades if t["profit"] > 0]
    losses = [t for t in trades if t["profit"] <= 0]
    total  = len(trades)

    win_rate     = len(wins) / total * 100
    avg_win_pct  = np.mean([t["pnl_pct"] for t in wins])          if wins   else 0.0
    avg_loss_pct = abs(np.mean([t["pnl_pct"] for t in losses]))   if losses else 0.0
    gross_profit = sum(t["profit"] for t in wins)
    gross_loss   = abs(sum(t["profit"] for t in losses))

    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else float("inf")
    expectancy    = round((win_rate/100 * avg_win_pct) - ((1 - win_rate/100) * avg_loss_pct), 3)

    # Max drawdown
    balances = [initial_balance] + [t["balance"] for t in trades]
    max_dd, peak = 0.0, balances[0]
    for b in balances:
        peak   = max(peak, b)
        max_dd = max(max_dd, (peak - b) / peak * 100)

    # Annualized Sharpe (trade-frequency adjusted)
    rets            = [t["pnl_pct"] for t in trades]
    trades_per_year = total / max(len(df), 1) * bars_per_year
    sharpe_raw      = np.mean(rets) / np.std(rets) if len(rets) > 1 and np.std(rets) > 0 else 0
    sharpe          = round(sharpe_raw * np.sqrt(trades_per_year), 2)

    # CAGR
    years_tested = len(df) / bars_per_year
    cagr = round(((balance / initial_balance) ** (1 / years_tested) - 1) * 100, 2) \
        if years_tested > 0 and balance > 0 else 0.0

    net_return_pct = round((balance - initial_balance) / initial_balance * 100, 2)

    # Regime breakdown
    regime_counts = {}
    for t in trades:
        r = t.get("regime", "?")
        regime_counts[r] = regime_counts.get(r, 0) + 1

    return {
        "status":            "success",
        "initial_balance":   round(initial_balance, 2),
        "final_balance":     round(balance, 2),
        "net_profit":        round(balance - initial_balance, 2),
        "net_return_pct":    net_return_pct,
        "cagr_pct":          cagr,
        "years_tested":      round(years_tested, 2),
        "total_trades":      total,
        "win_rate_pct":      round(win_rate, 1),
        "profit_factor":     profit_factor,
        "expectancy_pct":    expectancy,
        "avg_win_pct":       round(avg_win_pct, 2),
        "avg_loss_pct":      round(avg_loss_pct, 2),
        "max_drawdown_pct":  round(max_dd, 2),
        "sharpe_ratio":      sharpe,
        "wins":              len(wins),
        "losses":            len(losses),
        "exits_sl":          sum(1 for t in trades if t["reason"] == "SL"),
        "exits_tp":          sum(1 for t in trades if "TP" in t["reason"]),
        "exits_time":        sum(1 for t in trades if t["reason"] == "TIME"),
        "best_trade_pct":    round(max(t["pnl_pct"] for t in trades), 2),
        "worst_trade_pct":   round(min(t["pnl_pct"] for t in trades), 2),
        "regime_breakdown":  regime_counts,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Single-asset entry point
# ─────────────────────────────────────────────────────────────────────────────

def run_crypto_backtest(symbol: str, timeframe: str = "15m", limit: int = 500,
                        risk_pct: float = 2.0, leverage: float = 1.0,
                        params: dict = None, asset_class: str = "crypto",
                        initial_balance: float = 100.0) -> dict:
    df_raw = get_kline_data(symbol, timeframe, limit)
    if df_raw is None or df_raw.empty:
        return {"error": f"No data found for {symbol}"}
    # Guard: speculative placeholder or too few rows for indicator windows
    if "is_speculative" in df_raw.columns or len(df_raw) < 30:
        return {"error": f"Insufficient data for {symbol} — try a longer candle limit or different timeframe"}

    df         = compute_indicators(df_raw)
    df_signals = generate_backtest_signals(df, params=params, asset_class=asset_class)
    if df_signals.empty:
        return {"error": f"Signal generation failed for {symbol} — missing indicators"}

    p = {**DEFAULT_PARAMS, **(params or {})}
    results = simulate_trades(
        df_signals,
        initial_balance=initial_balance,
        risk_pct=risk_pct,
        leverage=leverage,
        timeframe=timeframe,
        sl_atr_mult=p["sl_atr_mult"],
        tp1_atr_mult=p["tp1_atr_mult"],
        tp2_atr_mult_base=p["tp2_atr_mult_base"],
        min_ml_edge=p.get("min_ml_edge", 0.0)
    )
    results["symbol"]            = symbol
    results["timeframe"]         = timeframe
    results["candles_analyzed"]  = len(df)
    results["risk_pct"]          = risk_pct
    results["leverage"]          = leverage
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Parameter Optimization  (ported from QuantAgent optimize_backtest)
# 70% train / 30% test split — prevents overfitting
# ─────────────────────────────────────────────────────────────────────────────

_OPTIMIZE_GRID = {
    "adx_trending_threshold": [23, 25, 28],
    "adx_trade_min":          [20, 23, 25],
    "rsi_oversold":           [30, 35, 40],
    "rsi_overbought":         [60, 65, 70],
    "sl_atr_mult":            [1.2, 1.5, 1.8],
    "tp2_atr_mult_base":      [2.5, 3.0, 3.5],
}


def _score(summary: dict) -> float:
    """Optimization objective: maximize net_profit, penalize drawdown, reward PF."""
    if summary.get("status") != "success":
        return -9999.0
    return (
        summary["net_return_pct"]
        - summary["max_drawdown_pct"] * 2.0
        + (summary["profit_factor"] - 1.0) * 50.0
        + summary["win_rate_pct"] * 0.5
    )


def optimize_backtest(symbol: str, timeframe: str = "15m", limit: int = 1000,
                      risk_pct: float = 2.0, leverage: float = 1.0) -> dict:
    """
    Grid-search best parameters on 70% of data, validate on held-out 30%.
    Returns best_params, train_summary, test_summary.
    (Ported from QuantAgent optimize_backtest — adapted for yfinance/postgres data)
    """
    logger.info(f"optimize_backtest: fetching {limit} bars for {symbol} {timeframe}")
    df_raw = get_kline_data(symbol, timeframe, limit)
    if df_raw is None or df_raw.empty:
        return {"error": f"No data for {symbol}"}

    df = compute_indicators(df_raw)
    n  = len(df)
    split = int(n * 0.70)
    min_train = 100

    if split <= min_train + 20:
        return {"error": f"Not enough bars for optimization (got {n}, need ≥ {min_train + 20})"}

    df_train = df.iloc[:split].reset_index(drop=True)
    df_test  = df.iloc[split:].reset_index(drop=True)

    best_score  = None
    best_params = None
    best_train  = None
    keys = list(_OPTIMIZE_GRID.keys())

    for values in itertools.product(*(_OPTIMIZE_GRID[k] for k in keys)):
        p = {**DEFAULT_PARAMS, **dict(zip(keys, values))}
        p["adx_ranging_threshold"] = min(20, p["adx_trending_threshold"] - 2)

        df_sig = generate_backtest_signals(df_train, params=p)
        if df_sig.empty:
            continue

        s = simulate_trades(df_sig, risk_pct=risk_pct, leverage=leverage,
                            timeframe=timeframe,
                            sl_atr_mult=p["sl_atr_mult"],
                            tp1_atr_mult=p["tp1_atr_mult"],
                            tp2_atr_mult_base=p["tp2_atr_mult_base"])
        if s.get("total_trades", 0) < 10:
            continue

        sc = _score(s)
        if best_score is None or sc > best_score:
            best_score  = sc
            best_params = p
            best_train  = s

    if best_params is None:
        return {"error": "No valid parameter set found — try larger limit or different symbol"}

    df_sig_test = generate_backtest_signals(df_test, params=best_params)
    test_summary = simulate_trades(df_sig_test, risk_pct=risk_pct, leverage=leverage,
                                   timeframe=timeframe,
                                   sl_atr_mult=best_params["sl_atr_mult"],
                                   tp1_atr_mult=best_params["tp1_atr_mult"],
                                   tp2_atr_mult_base=best_params["tp2_atr_mult_base"])

    return {
        "status":        "success",
        "symbol":        symbol,
        "timeframe":     timeframe,
        "best_params":   best_params,
        "train_summary": best_train,
        "test_summary":  test_summary,
        "train_bars":    split,
        "test_bars":     n - split,
        "overfitting_note": (
            "If test_summary metrics are significantly worse than train_summary, "
            "the strategy is likely overfitting this dataset."
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Walk-Forward Validation  (ported from QuantAgent walk_forward_backtest)
# Gold standard: rolling re-optimize then out-of-sample test
# ─────────────────────────────────────────────────────────────────────────────

def walk_forward_backtest(symbol: str, timeframe: str = "1h", limit: int = 2000,
                          risk_pct: float = 2.0, leverage: float = 1.0) -> dict:
    """
    Rolling walk-forward:
      - Train window: 50% of total bars (re-optimized each window)
      - Test  window: 15% of total bars (out-of-sample)
      - Advance by one test window each iteration
    Returns equity curve and per-window stats.
    """
    logger.info(f"walk_forward_backtest: {symbol} {timeframe} limit={limit}")
    df_raw = get_kline_data(symbol, timeframe, limit)
    if df_raw is None or df_raw.empty:
        return {"error": f"No data for {symbol}"}

    df  = compute_indicators(df_raw)
    n   = len(df)
    train_size = max(200, int(n * 0.50))
    test_size  = max(50,  int(n * 0.15))

    if train_size + test_size > n:
        return {"error": f"Not enough bars for walk-forward (got {n})"}

    current_balance = 100.0
    equity_curve    = [current_balance]
    windows         = []
    start           = 0

    while start + train_size + test_size <= n:
        df_train = df.iloc[start : start + train_size].reset_index(drop=True)
        df_test  = df.iloc[start + train_size : start + train_size + test_size].reset_index(drop=True)

        # Mini optimize on this train window
        best_score  = None
        best_params = None
        for adx_min in [22, 25, 28]:
            for sl_mult in [1.2, 1.5, 1.8]:
                p = {**DEFAULT_PARAMS, "adx_trade_min": adx_min, "sl_atr_mult": sl_mult}
                df_sig = generate_backtest_signals(df_train, params=p)
                if df_sig.empty:
                    continue
                s = simulate_trades(df_sig, risk_pct=risk_pct, leverage=leverage, timeframe=timeframe,
                                    sl_atr_mult=p["sl_atr_mult"])
                sc = _score(s)
                if best_score is None or sc > best_score:
                    best_score  = sc
                    best_params = p

        if best_params is None:
            best_params = DEFAULT_PARAMS

        df_sig_test = generate_backtest_signals(df_test, params=best_params)
        test_result = simulate_trades(
            df_sig_test,
            initial_balance=current_balance,
            risk_pct=risk_pct,
            leverage=leverage,
            timeframe=timeframe,
            sl_atr_mult=best_params["sl_atr_mult"],
        )

        current_balance = test_result.get("final_balance", current_balance)
        equity_curve.append(round(current_balance, 4))

        windows.append({
            "window_start_bar": start,
            "train_bars":       train_size,
            "test_bars":        test_size,
            "best_adx_min":     best_params.get("adx_trade_min"),
            "best_sl_mult":     best_params.get("sl_atr_mult"),
            "test_return_pct":  test_result.get("net_return_pct", 0),
            "test_win_rate":    test_result.get("win_rate_pct", 0),
            "test_trades":      test_result.get("total_trades", 0),
            "test_max_dd":      test_result.get("max_drawdown_pct", 0),
        })

        start += test_size

    total_return = round((current_balance - 100.0) / 100.0 * 100, 2)
    avg_win_rate = round(np.mean([w["test_win_rate"] for w in windows]), 1) if windows else 0
    max_dd_any   = round(max((w["test_max_dd"] for w in windows), default=0), 2)

    return {
        "status":          "success",
        "symbol":          symbol,
        "timeframe":       timeframe,
        "windows_run":     len(windows),
        "starting_balance": 100.0,
        "ending_balance":  round(current_balance, 2),
        "total_return_pct": total_return,
        "avg_win_rate_pct": avg_win_rate,
        "worst_window_dd_pct": max_dd_any,
        "equity_curve":    equity_curve,
        "window_results":  windows,
        "interpretation": (
            "Walk-forward result is out-of-sample. "
            "Positive total_return_pct with consistent window returns = robust strategy. "
            "High variance across windows = curve-fitted or unstable edge."
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Portfolio backtest — trade multiple assets simultaneously
# ─────────────────────────────────────────────────────────────────────────────

def run_portfolio_backtest(symbols: list, timeframe: str = "1h", limit: int = 500,
                           risk_pct: float = 1.5, leverage: float = 1.0,
                           initial_balance: float = 100.0,
                           params: dict = None) -> dict:
    """Split capital equally across symbols, run each independently, combine P&L."""
    per_symbol_balance = initial_balance / len(symbols)
    results_all = []

    for sym in symbols:
        r = run_crypto_backtest(sym, timeframe, limit, risk_pct, leverage, params, initial_balance=per_symbol_balance)
        if r.get("status") == "success":
            results_all.append(r)

    if not results_all:
        return {"error": "No data for any symbol"}

    num_traded   = len(results_all)
    idle_capital = (len(symbols) - num_traded) * per_symbol_balance
    total_final  = sum(r["final_balance"] for r in results_all) + idle_capital
    total_net    = round(total_final - initial_balance, 2)
    total_return = round(total_net / initial_balance * 100, 2)
    total_trades = sum(r["total_trades"] for r in results_all)
    avg_winrate  = round(np.mean([r["win_rate_pct"] for r in results_all]), 1)
    avg_pf       = round(np.mean([r["profit_factor"] for r in results_all
                                  if r["profit_factor"] != float("inf")]), 2)

    avg_years = np.mean([r.get("years_tested", 0) for r in results_all])
    portfolio_cagr = round(((total_final / initial_balance) ** (1 / avg_years) - 1) * 100, 2) \
        if avg_years > 0 and total_final > 0 else 0.0

    max_dd = round(max(r["max_drawdown_pct"] for r in results_all), 2)

    return {
        "status":            "success",
        "mode":              "PORTFOLIO",
        "symbols":           symbols,
        "initial_balance":   initial_balance,
        "final_balance":     round(total_final, 2),
        "net_profit":        total_net,
        "net_return_pct":    total_return,
        "cagr_pct":          portfolio_cagr,
        "years_tested":      round(avg_years, 2),
        "total_trades":      total_trades,
        "avg_win_rate":      avg_winrate,
        "avg_profit_factor": avg_pf,
        "max_drawdown_pct":  max_dd,
        "per_asset": [{
            "symbol":        r["symbol"],
            "final":         r["final_balance"],
            "return_pct":    r["net_return_pct"],
            "cagr_pct":      r.get("cagr_pct", 0),
            "trades":        r["total_trades"],
            "win_rate":      r["win_rate_pct"],
            "profit_factor": r["profit_factor"],
            "sharpe_ratio":  r.get("sharpe_ratio", 0),
            "max_dd":        r["max_drawdown_pct"],
        } for r in results_all],
    }
