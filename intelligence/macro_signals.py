"""
CryptoStream AI — Macro Signals
Computes macro regime verdict and BTC ETF flow estimates from real market data.

Ported from AI-Trader market_intel.py — adapted for CryptoStream:
  - Replaced Alpha Vantage with yfinance (CryptoStream already uses yfinance)
  - No additional API key required
  - Added in-memory caching (macro regime is slow-moving, refresh hourly)
  - Results feed directly into the Sentiment Agent's Gemini prompt

Signals produced:
  btc_trend       — BTC 7-day momentum  (bullish / neutral / defensive)
  qqq_trend       — QQQ 20-day momentum (bullish / neutral / defensive)
  qqq_vs_xlp      — Growth vs defensive spread (risk-on / neutral / risk-off)
  safe_haven      — GLD + UUP strength  (defensive / neutral / bullish risk)
  btc_etf_flows   — IBIT,FBTC,ARKB… estimated inflow/outflow

Usage:
    from intelligence.macro_signals import get_macro_regime, get_btc_etf_flows

    regime = get_macro_regime()
    print(regime["verdict"])      # "bullish" | "defensive" | "neutral"
    print(regime["signals"])      # list of individual signal dicts

    etf = get_btc_etf_flows()
    print(etf["direction"])       # "inflow" | "outflow" | "mixed"
"""

import logging
import time
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ── BTC ETF symbols tracked ────────────────────────────────────────────────────
BTC_ETF_SYMBOLS = ["IBIT", "FBTC", "ARKB", "BITB", "HODL", "BRRR", "EZBC", "BTCW"]

# ── Macro benchmark symbols ────────────────────────────────────────────────────
MACRO_SYMBOLS = {
    "growth":    "QQQ",   # Nasdaq-100 ETF — risk-on proxy
    "defensive": "XLP",   # Consumer staples ETF — risk-off proxy
    "safe_haven":"GLD",   # Gold ETF — safe-haven demand
    "dollar":    "UUP",   # USD bull ETF — dollar strength
}

# ── Cache (in-memory, TTL in seconds) ─────────────────────────────────────────
_MACRO_TTL  = 3600   # 1 hour — macro regime is slow-moving
_ETF_TTL    = 3600   # 1 hour
_macro_cache: dict = {}
_etf_cache:   dict = {}


# ── yfinance helper ────────────────────────────────────────────────────────────

def _fetch_daily_close(ticker: str, period: str = "3mo") -> list[dict]:
    """
    Fetch daily OHLCV from yfinance and return list of {date, close, volume}
    sorted most-recent-first. Returns [] on failure.
    """
    try:
        import yfinance as yf
        df = yf.download(ticker, period=period, interval="1d",
                         progress=False, auto_adjust=True)
        if df is None or df.empty:
            return []

        # Handle MultiIndex columns (yfinance 0.2+)
        if hasattr(df.columns, "levels"):
            df.columns = df.columns.droplevel(1)

        rows = []
        for idx in df.index:
            try:
                close  = float(df.loc[idx, "Close"])
                volume = float(df.loc[idx, "Volume"]) if "Volume" in df.columns else 0.0
                date   = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
                rows.append({"date": date, "close": close, "volume": volume})
            except Exception:
                continue

        rows.sort(key=lambda r: r["date"], reverse=True)
        return rows
    except Exception as e:
        logger.warning(f"macro_signals._fetch_daily_close({ticker}): {e}")
        return []


def _return_pct(series: list[dict], lookback: int) -> Optional[float]:
    """Percentage return from lookback days ago to today."""
    if len(series) <= lookback:
        return None
    latest   = float(series[0]["close"])
    previous = float(series[lookback]["close"])
    if previous == 0:
        return None
    return ((latest / previous) - 1.0) * 100.0


def _avg_volume(series: list[dict], start: int, count: int) -> Optional[float]:
    window = [float(r["volume"]) for r in series[start:start + count]
              if float(r.get("volume", 0)) > 0]
    return sum(window) / len(window) if window else None


# ── Macro regime ───────────────────────────────────────────────────────────────

def get_macro_regime(lookback_days: int = 20, btc_lookback: int = 7) -> dict:
    """
    Compute macro regime verdict from QQQ / XLP / GLD / UUP / BTC daily returns.

    Returns:
        {
          "verdict":       "bullish" | "defensive" | "neutral",
          "summary":       str,
          "bullish_count": int,
          "defensive_count": int,
          "signals":       list[dict],
          "latest_prices": dict,
          "as_of":         str (ISO timestamp),
          "cached":        bool,
        }
    """
    now = time.time()
    if _macro_cache.get("ts", 0) + _MACRO_TTL > now:
        return {**_macro_cache["data"], "cached": True}

    signals = []

    # Fetch series
    qqq = _fetch_daily_close("QQQ")
    xlp = _fetch_daily_close("XLP")
    gld = _fetch_daily_close("GLD")
    uup = _fetch_daily_close("UUP")
    btc = _fetch_daily_close("BTC-USD")

    qqq_ret = _return_pct(qqq, lookback_days)
    xlp_ret = _return_pct(xlp, lookback_days)
    gld_ret = _return_pct(gld, lookback_days)
    uup_ret = _return_pct(uup, lookback_days)
    btc_ret = _return_pct(btc, btc_lookback)

    # ── BTC 7-day trend ────────────────────────────────────────────────────────
    if btc_ret is not None:
        if btc_ret >= 4:
            status = "bullish"
            explanation = f"BTC +{btc_ret:.1f}% over {btc_lookback}d — momentum positive."
        elif btc_ret <= -4:
            status = "defensive"
            explanation = f"BTC {btc_ret:.1f}% over {btc_lookback}d — momentum negative."
        else:
            status = "neutral"
            explanation = f"BTC {btc_ret:+.1f}% over {btc_lookback}d — mixed."
        signals.append({
            "id": "btc_trend", "label": "BTC Trend",
            "status": status, "value": round(btc_ret, 2), "unit": "%",
            "lookback_days": btc_lookback, "explanation": explanation,
        })

    # ── QQQ 20-day trend ───────────────────────────────────────────────────────
    if qqq_ret is not None:
        if qqq_ret >= 3:
            status = "bullish"
            explanation = f"QQQ +{qqq_ret:.1f}% — growth equities trending higher."
        elif qqq_ret <= -3:
            status = "defensive"
            explanation = f"QQQ {qqq_ret:.1f}% — growth equities losing momentum."
        else:
            status = "neutral"
            explanation = f"QQQ {qqq_ret:+.1f}% — mixed."
        signals.append({
            "id": "qqq_trend", "label": "QQQ Trend",
            "status": status, "value": round(qqq_ret, 2), "unit": "%",
            "lookback_days": lookback_days, "explanation": explanation,
        })

    # ── QQQ vs XLP spread (growth vs defensive) ────────────────────────────────
    if qqq_ret is not None and xlp_ret is not None:
        spread = qqq_ret - xlp_ret
        if spread >= 2:
            status = "bullish"
            explanation = f"Growth outperforming defensive staples by {spread:.1f}pp — risk-on."
        elif spread <= -2:
            status = "defensive"
            explanation = f"Defensive staples outperforming growth by {abs(spread):.1f}pp — risk-off."
        else:
            status = "neutral"
            explanation = f"QQQ vs XLP spread {spread:+.1f}pp — balanced."
        signals.append({
            "id": "qqq_vs_xlp", "label": "QQQ vs XLP",
            "status": status, "value": round(spread, 2), "unit": "spread_pct",
            "lookback_days": lookback_days, "explanation": explanation,
        })

    # ── Safe-haven pressure (GLD + UUP) ───────────────────────────────────────
    if gld_ret is not None and uup_ret is not None:
        sh_strength = max(gld_ret, uup_ret)
        if sh_strength >= 3:
            status = "defensive"
            explanation = f"Safe-haven bid (GLD {gld_ret:+.1f}%, UUP {uup_ret:+.1f}%)."
        elif sh_strength <= 0:
            status = "bullish"
            explanation = "Safe-haven demand subdued — risk appetite intact."
        else:
            status = "neutral"
            explanation = "Safe-haven demand present but not dominant."
        signals.append({
            "id": "safe_haven", "label": "Safe-Haven Pressure",
            "status": status, "value": round(sh_strength, 2), "unit": "%",
            "lookback_days": lookback_days, "explanation": explanation,
        })

    # ── Verdict ────────────────────────────────────────────────────────────────
    bull_n = sum(1 for s in signals if s["status"] == "bullish")
    def_n  = sum(1 for s in signals if s["status"] == "defensive")

    if bull_n >= def_n + 2:
        verdict = "bullish"
        summary = "Risk appetite is leading across the macro snapshot."
    elif def_n >= bull_n + 2:
        verdict = "defensive"
        summary = "Defensive pressure dominates the macro snapshot."
    else:
        verdict = "neutral"
        summary = "Macro signals are mixed — no clear regime."

    latest_prices = {
        "BTC":  btc[0]["close"] if btc else None,
        "QQQ":  qqq[0]["close"] if qqq else None,
        "XLP":  xlp[0]["close"] if xlp else None,
        "GLD":  gld[0]["close"] if gld else None,
        "UUP":  uup[0]["close"] if uup else None,
    }

    data = {
        "verdict":         verdict,
        "summary":         summary,
        "bullish_count":   bull_n,
        "defensive_count": def_n,
        "signals":         signals,
        "latest_prices":   latest_prices,
        "as_of":           datetime.now(timezone.utc).isoformat(),
        "cached":          False,
    }

    _macro_cache["ts"]   = now
    _macro_cache["data"] = data
    logger.info(f"macro_signals: regime={verdict} (bull={bull_n}, def={def_n})")
    return data


# ── BTC ETF flow estimates ─────────────────────────────────────────────────────

def get_btc_etf_flows(lookback_days: int = 1, baseline_days: int = 5) -> dict:
    """
    Estimate BTC ETF capital flows from price × volume changes.

    Tracks: IBIT, FBTC, ARKB, BITB, HODL, BRRR, EZBC, BTCW

    Returns:
        {
          "direction":    "inflow" | "outflow" | "mixed",
          "summary":      str,
          "net_score":    float,
          "inflow_count": int,
          "outflow_count": int,
          "etfs":         list[dict],
          "as_of":        str,
          "cached":       bool,
        }
    """
    now = time.time()
    if _etf_cache.get("ts", 0) + _ETF_TTL > now:
        return {**_etf_cache["data"], "cached": True}

    etf_rows = []

    for symbol in BTC_ETF_SYMBOLS:
        series = _fetch_daily_close(symbol, period="1mo")
        if len(series) <= baseline_days:
            continue

        latest   = series[0]
        previous = series[lookback_days] if len(series) > lookback_days else series[-1]

        latest_close   = float(latest["close"])
        previous_close = float(previous["close"])
        latest_vol     = float(latest.get("volume") or 0)
        avg_vol        = _avg_volume(series, 1, baseline_days) or latest_vol or 1.0

        if previous_close == 0:
            continue

        price_chg_pct = ((latest_close / previous_close) - 1.0) * 100.0
        vol_ratio     = latest_vol / avg_vol if avg_vol else 1.0
        flow_score    = price_chg_pct * max(vol_ratio, 0.1)

        if flow_score >= 2.5:
            direction = "inflow"
        elif flow_score <= -2.5:
            direction = "outflow"
        else:
            direction = "mixed"

        etf_rows.append({
            "symbol":       symbol,
            "price_chg_pct": round(price_chg_pct, 2),
            "volume_ratio":  round(vol_ratio, 2),
            "flow_score":    round(flow_score, 2),
            "direction":     direction,
            "as_of":         latest["date"],
        })

    etf_rows.sort(key=lambda r: abs(r["flow_score"]), reverse=True)

    inflow_n  = sum(1 for r in etf_rows if r["direction"] == "inflow")
    outflow_n = sum(1 for r in etf_rows if r["direction"] == "outflow")
    net_score = round(sum(r["flow_score"] for r in etf_rows), 2)

    if inflow_n >= outflow_n + 2 and net_score > 0:
        direction = "inflow"
        summary   = f"BTC ETF flows lean positive — {inflow_n}/{len(etf_rows)} ETFs showing inflow."
    elif outflow_n >= inflow_n + 2 and net_score < 0:
        direction = "outflow"
        summary   = f"BTC ETF flows lean negative — {outflow_n}/{len(etf_rows)} ETFs showing outflow."
    else:
        direction = "mixed"
        summary   = f"BTC ETF flows mixed ({inflow_n} inflow, {outflow_n} outflow)."

    data = {
        "direction":    direction,
        "summary":      summary,
        "net_score":    net_score,
        "inflow_count": inflow_n,
        "outflow_count": outflow_n,
        "tracked_count": len(etf_rows),
        "etfs":         etf_rows,
        "as_of":        datetime.now(timezone.utc).isoformat(),
        "cached":       False,
    }

    _etf_cache["ts"]   = now
    _etf_cache["data"] = data
    logger.info(f"macro_signals: etf_flows={direction} net={net_score:+.1f}")
    return data


def format_macro_for_prompt(regime: dict, etf_flows: dict) -> str:
    """
    Format macro regime + ETF flows into a compact text block for Gemini prompts.
    """
    lines = [
        "=== Macro Regime Overlay ===",
        f"Overall Verdict : {regime.get('verdict','?').upper()}",
        f"Summary         : {regime.get('summary','')}",
        "",
    ]
    for sig in regime.get("signals", []):
        status_tag = {"bullish": "[+]", "defensive": "[-]", "neutral": "[ ]"}.get(
            sig.get("status", "neutral"), "[ ]"
        )
        lines.append(f"  {status_tag} {sig['label']:20s} {sig.get('explanation','')}")

    if etf_flows and etf_flows.get("tracked_count", 0) > 0:
        lines += [
            "",
            f"BTC ETF Flows   : {etf_flows.get('direction','?').upper()} "
            f"(net_score={etf_flows.get('net_score',0):+.1f}, "
            f"{etf_flows.get('tracked_count',0)} ETFs tracked)",
            f"  {etf_flows.get('summary','')}",
        ]

    return "\n".join(lines)
