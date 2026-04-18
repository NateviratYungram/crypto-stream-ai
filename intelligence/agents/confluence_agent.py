"""
CryptoStream AI — Confluence Agent (Multi-Timeframe)
Pure Python indicator analysis across N timeframes. Zero LLM calls — fast and free.

Ported from QuantAgent confluence_agent.py — adapted for CryptoStream:
  - Replaced MT5 data fetching with get_kline_data() from technical_engine
  - Removed timeframe_registry dependency (uses built-in TF hierarchy)
  - Plugs into CryptoStream pipeline as a node between Chart Generation and Indicator Agent

Concept:
  If 15m shows BULLISH but 1h and 4h also show BULLISH → high confluence → confidence boost
  If 15m shows BULLISH but 4h shows BEARISH → mixed → lower confidence, proceed with caution

Usage (standalone):
    from intelligence.agents.confluence_agent import create_confluence_agent

    agent = create_confluence_agent()
    result = agent({
        "symbol": "BTC",
        "timeframe": "15m",
        "asset_class": "CRYPTO",
    })
    print(result["confluence_report"])
    print(result["confluence_score"])   # 0–100
"""

import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Higher-timeframe hierarchy ─────────────────────────────────────────────────
# For each trading TF, which 2 HTFs to check for confluence
_HTF_MAP = {
    "1m":  ("5m",  "15m"),
    "5m":  ("15m", "1h"),
    "15m": ("1h",  "4h"),
    "30m": ("1h",  "4h"),
    "1h":  ("4h",  "1d"),
    "2h":  ("4h",  "1d"),
    "4h":  ("1d",  "1d"),   # only one meaningful HTF above 4h
    "1d":  ("1d",  "1d"),   # daily is already the top
}

_DEFAULT_HTF = ("1h", "4h")


def _get_htfs(timeframe: str) -> tuple:
    """Return (htf1, htf2) for the given base timeframe."""
    tf = timeframe.lower().replace(" ", "")
    htfs = _HTF_MAP.get(tf, _DEFAULT_HTF)
    # De-duplicate: if both HTFs are the same (e.g. 4h case), use just one
    if htfs[0] == htfs[1]:
        return (htfs[0],)
    return htfs


# ── Single-TF indicator analysis (pure Python, no LLM) ─────────────────────────

def _analyze_single_tf(df: pd.DataFrame) -> dict:
    """
    Compute RSI / MACD / ADX / EMA and derive a directional bias.
    Returns a dict with direction, strength (0–100), and raw values.
    """
    if df is None or len(df) < 30:
        return {
            "direction": "NEUTRAL", "strength": 0,
            "rsi": 50, "macd_signal": "NEUTRAL",
            "adx": 0, "ema_trend": "NEUTRAL",
        }

    close = df["Close"].astype(float).values
    high  = df["High"].astype(float).values
    low   = df["Low"].astype(float).values

    # ── RSI ────────────────────────────────────────────────────────────────────
    try:
        import talib
        rsi_arr = talib.RSI(close, timeperiod=14)
        current_rsi = float(rsi_arr[-1]) if not np.isnan(rsi_arr[-1]) else 50.0

        # ── MACD ───────────────────────────────────────────────────────────────
        _, _, hist = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
        cur_h = float(hist[-1]) if not np.isnan(hist[-1]) else 0.0
        prv_h = float(hist[-2]) if len(hist) > 1 and not np.isnan(hist[-2]) else 0.0

        # ── ADX ────────────────────────────────────────────────────────────────
        adx_arr = talib.ADX(high, low, close, timeperiod=14)
        current_adx = float(adx_arr[-1]) if not np.isnan(adx_arr[-1]) else 0.0

        # ── EMA 20 / 50 ────────────────────────────────────────────────────────
        ema20 = talib.EMA(close, timeperiod=20)
        ema50 = talib.EMA(close, timeperiod=50)
        cur_p   = float(close[-1])
        cur_e20 = float(ema20[-1]) if not np.isnan(ema20[-1]) else cur_p
        cur_e50 = float(ema50[-1]) if not np.isnan(ema50[-1]) else cur_p

    except ImportError:
        # talib not available: use pandas rolling as fallback
        s = pd.Series(close)
        delta = s.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rs    = gain / loss.replace(0, np.nan)
        rsi_s = 100 - (100 / (1 + rs))
        current_rsi = float(rsi_s.iloc[-1]) if not np.isnan(rsi_s.iloc[-1]) else 50.0

        ema12 = s.ewm(span=12, adjust=False).mean()
        ema26 = s.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        hist_s = macd_line - signal_line
        cur_h = float(hist_s.iloc[-1]) if not np.isnan(hist_s.iloc[-1]) else 0.0
        prv_h = float(hist_s.iloc[-2]) if len(hist_s) > 1 and not np.isnan(hist_s.iloc[-2]) else 0.0

        current_adx = 0.0  # too expensive to compute without talib

        e20 = s.ewm(span=20, adjust=False).mean()
        e50 = s.ewm(span=50, adjust=False).mean()
        cur_p   = float(close[-1])
        cur_e20 = float(e20.iloc[-1])
        cur_e50 = float(e50.iloc[-1])

    # ── MACD signal string ─────────────────────────────────────────────────────
    if prv_h <= 0 and cur_h > 0:
        macd_signal = "BULLISH_CROSS"
    elif prv_h >= 0 and cur_h < 0:
        macd_signal = "BEARISH_CROSS"
    elif cur_h > 0:
        macd_signal = "BULLISH"
    elif cur_h < 0:
        macd_signal = "BEARISH"
    else:
        macd_signal = "NEUTRAL"

    # ── EMA trend ──────────────────────────────────────────────────────────────
    if cur_p > cur_e20 > cur_e50:
        ema_trend = "BULLISH"
    elif cur_p < cur_e20 < cur_e50:
        ema_trend = "BEARISH"
    else:
        ema_trend = "NEUTRAL"

    # ── Directional scoring ────────────────────────────────────────────────────
    bull = bear = 0

    if current_rsi > 55:
        bull += 1
    elif current_rsi < 45:
        bear += 1

    if macd_signal in ("BULLISH_CROSS", "BULLISH"):
        bull += 2 if "CROSS" in macd_signal else 1
    elif macd_signal in ("BEARISH_CROSS", "BEARISH"):
        bear += 2 if "CROSS" in macd_signal else 1

    if ema_trend == "BULLISH":
        bull += 1
    elif ema_trend == "BEARISH":
        bear += 1

    if bull > bear:
        direction = "BULLISH"
        strength  = min(100, bull * 25)
    elif bear > bull:
        direction = "BEARISH"
        strength  = min(100, bear * 25)
    else:
        direction = "NEUTRAL"
        strength  = 0

    return {
        "direction":   direction,
        "strength":    strength,
        "rsi":         round(current_rsi, 1),
        "macd_signal": macd_signal,
        "adx":         round(current_adx, 1),
        "ema_trend":   ema_trend,
    }


# ── Confluence scoring ─────────────────────────────────────────────────────────

def _calculate_confluence(tf_results: dict) -> tuple[str, float]:
    """
    Given per-TF analysis results, compute overall consensus + score (0–100).
    Returns (consensus: str, score: float).
    """
    directions = [r["direction"] for r in tf_results.values()]
    strengths  = [r["strength"]  for r in tf_results.values()]
    n = len(directions)
    if n == 0:
        return "MIXED", 0.0

    bull_n = directions.count("BULLISH")
    bear_n = directions.count("BEARISH")
    avg_s  = sum(strengths) / n

    if bull_n == n:
        return "BULLISH", min(100.0, avg_s + 20)
    if bear_n == n:
        return "BEARISH", min(100.0, avg_s + 20)
    if n >= 2 and bull_n >= n - 1:
        return "BULLISH", min(80.0, avg_s)
    if n >= 2 and bear_n >= n - 1:
        return "BEARISH", min(80.0, avg_s)
    return "MIXED", 0.0


# ── Agent factory ──────────────────────────────────────────────────────────────

def create_confluence_agent():
    """
    Returns a confluence_agent_node function compatible with CryptoStream's pipeline.

    Reads from state:
      symbol, timeframe, asset_class

    Writes to state:
      confluence_data   — per-TF analysis dict
      confluence_score  — 0–100
      confluence_report — human-readable text
    """

    def confluence_agent_node(state: dict) -> dict:
        from intelligence.technical_engine import get_kline_data, compute_indicators

        symbol     = state.get("symbol", "BTC")
        timeframe  = state.get("timeframe", "15m")
        asset_class = state.get("asset_class", "CRYPTO")

        htfs = _get_htfs(timeframe)
        all_tfs = (timeframe,) + htfs  # base TF first, then HTFs

        tf_results: dict = {}

        for tf in all_tfs:
            # Reuse already-computed data for the base timeframe
            if tf == timeframe and state.get("kline_data") is not None:
                df = state["kline_data"]
            else:
                try:
                    df_raw = get_kline_data(symbol, tf, limit=60, asset_class=asset_class)
                    df = compute_indicators(df_raw) if df_raw is not None and not df_raw.empty else None
                except Exception as e:
                    logger.warning(f"ConfluenceAgent: failed to fetch {symbol}/{tf}: {e}")
                    df = None

            tf_results[tf] = _analyze_single_tf(df)

        consensus, score = _calculate_confluence(tf_results)

        # ── Build human-readable report ────────────────────────────────────────
        lines = [
            f"=== Multi-Timeframe Confluence — {symbol} ===",
            f"Consensus: {consensus}  |  Score: {score:.0f}/100",
            f"Timeframes: {' → '.join(all_tfs)}",
            "",
        ]
        for tf, res in tf_results.items():
            label = "(base)" if tf == timeframe else "(HTF) "
            lines.append(
                f"  {tf.upper():5s} {label}: {res['direction']:7s} "
                f"(RSI={res['rsi']:.0f}, MACD={res['macd_signal']}, "
                f"ADX={res['adx']:.0f}, EMA={res['ema_trend']})"
            )

        if consensus == "MIXED":
            lines.append("\nTimeframes disagree — LOW confluence, reduce position size")
        elif score >= 80:
            lines.append(f"\nStrong {consensus} confluence — all TFs aligned")
        else:
            lines.append(f"\nModerate {consensus} confluence")

        report = "\n".join(lines)
        logger.info(f"ConfluenceAgent: {symbol} {timeframe} → {consensus} score={score:.0f}")

        return {
            "confluence_data":   tf_results,
            "confluence_score":  score,
            "confluence_report": report,
        }

    return confluence_agent_node
