"""
Intermarket Context Agent — pure Python, no LLM.

Fetches macro context in parallel:
  - DXY (DX=F futures) — USD strength
  - VIX (^VIX) — fear gauge
  - Crypto Fear & Greed (alternative.me) — CRYPTO only
  - BTC Dominance (CoinGecko) — CRYPTO only
  - Perpetual Funding Rate (Binance) — CRYPTO only

STOCK assets are always skipped — they are not MT5-tradeable.
MACRO (forex/metals) assets skip crypto-specific feeds.
"""

import logging
import threading
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _fetch_dxy() -> Dict[str, Any]:
    try:
        import yfinance as yf
        df = yf.download("DX=F", period="5d", interval="1h", progress=False, auto_adjust=True)
        if df is None or len(df) < 10:
            return {"value": None, "trend": "UNKNOWN"}
        close = df["Close"].squeeze()
        price = float(close.iloc[-1])
        ema20 = float(close.ewm(span=20).mean().iloc[-1])
        return {"value": round(price, 2), "trend": "UP" if price > ema20 else "DOWN"}
    except Exception as e:
        logger.debug(f"Intermarket: DXY fetch failed: {e}")
        return {"value": None, "trend": "UNKNOWN"}


def _fetch_vix() -> Dict[str, Any]:
    try:
        import yfinance as yf
        df = yf.download("^VIX", period="5d", interval="1h", progress=False, auto_adjust=True)
        if df is None or len(df) < 2:
            return {"value": None, "level": "UNKNOWN"}
        vix = float(df["Close"].squeeze().iloc[-1])
        level = "HIGH" if vix > 25 else "MEDIUM" if vix > 15 else "LOW"
        return {"value": round(vix, 2), "level": level}
    except Exception as e:
        logger.debug(f"Intermarket: VIX fetch failed: {e}")
        return {"value": None, "level": "UNKNOWN"}


def _fetch_fear_greed() -> Dict[str, Any]:
    try:
        import requests
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=6)
        d = r.json()["data"][0]
        return {"value": int(d["value"]), "label": d["value_classification"]}
    except Exception as e:
        logger.debug(f"Intermarket: Fear&Greed fetch failed: {e}")
        return {"value": 50, "label": "Neutral"}


def _fetch_btc_dominance() -> Dict[str, Any]:
    try:
        import requests
        r = requests.get(
            "https://api.coingecko.com/api/v3/global",
            timeout=8,
            headers={"Accept": "application/json"},
        )
        pct = r.json()["data"]["market_cap_percentage"]["btc"]
        return {"value": round(pct, 1)}
    except Exception as e:
        logger.debug(f"Intermarket: BTC dominance fetch failed: {e}")
        return {"value": None}


def _fetch_funding_rate(symbol: str) -> Dict[str, Any]:
    """Binance perpetual funding rate. Positive = longs pay (bearish pressure on longs)."""
    try:
        import requests
        base = symbol.upper().replace("USD", "").replace("USDT", "")
        sym = base + "USDT"
        r = requests.get(
            f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={sym}&limit=1",
            timeout=5,
        )
        data = r.json()
        if isinstance(data, list) and data:
            rate = float(data[0]["fundingRate"]) * 100
            bias = "BEARISH" if rate > 0.05 else "BULLISH" if rate < -0.01 else "NEUTRAL"
            return {"rate_pct": round(rate, 4), "bias": bias}
    except Exception as e:
        logger.debug(f"Intermarket: funding rate fetch failed: {e}")
    return {"rate_pct": None, "bias": "NEUTRAL"}


def _compute_macro_bias(dxy: dict, vix: dict, fear_greed: dict, asset_class: str) -> str:
    risk_on = 0
    risk_off = 0

    if dxy.get("trend") == "DOWN":
        risk_on += 1
    elif dxy.get("trend") == "UP":
        risk_off += 1

    level = vix.get("level", "UNKNOWN")
    if level == "LOW":
        risk_on += 1
    elif level == "HIGH":
        risk_off += 2  # VIX spike is a stronger signal

    if asset_class == "CRYPTO":
        fg = fear_greed.get("value", 50)
        if fg >= 65:
            risk_on += 1
        elif fg <= 30:
            risk_off += 1

    if risk_on > risk_off:
        return "RISK_ON"
    if risk_off > risk_on:
        return "RISK_OFF"
    return "NEUTRAL"


def create_intermarket_agent():
    """
    Returns an intermarket_agent_node that populates state["intermarket"].
    All fetches run in parallel threads with a 10s timeout.
    """
    def intermarket_agent_node(state: dict) -> dict:
        asset_class = state.get("asset_class", "CRYPTO")
        symbol      = state.get("symbol", "BTC")

        if asset_class == "STOCK":
            return {"intermarket": {
                "macro_bias": "NEUTRAL",
                "dxy": {}, "vix": {}, "fear_greed": {},
                "btc_dominance": {}, "funding": {},
                "forex_context": "", "metals_context": "",
                "skipped": True,
            }}

        results: Dict[str, Any] = {}

        def run(key, fn):
            try:
                results[key] = fn()
            except Exception:
                results[key] = {}

        threads = [
            threading.Thread(target=run, args=("dxy", _fetch_dxy)),
            threading.Thread(target=run, args=("vix", _fetch_vix)),
        ]
        if asset_class == "CRYPTO":
            threads += [
                threading.Thread(target=run, args=("fear_greed", _fetch_fear_greed)),
                threading.Thread(target=run, args=("btc_dominance", _fetch_btc_dominance)),
                threading.Thread(target=run, args=("funding", lambda: _fetch_funding_rate(symbol))),
            ]

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        dxy        = results.get("dxy",        {"trend": "UNKNOWN"})
        vix        = results.get("vix",        {"level": "UNKNOWN"})
        fear_greed = results.get("fear_greed", {"value": 50, "label": "Neutral"})
        btc_dom    = results.get("btc_dominance", {"value": None})
        funding    = results.get("funding",    {"rate_pct": None, "bias": "NEUTRAL"})

        macro_bias = _compute_macro_bias(dxy, vix, fear_greed, asset_class)

        # Asset-class specific context notes (consumed by Master Agent)
        forex_context = ""
        if asset_class == "MACRO":
            if dxy.get("trend") == "UP":
                forex_context = "DXY rising → USD bullish (USDJPY/USDCHF up, EURUSD/GBPUSD/AUDUSD under pressure)"
            elif dxy.get("trend") == "DOWN":
                forex_context = "DXY falling → EUR/GBP/AUD/NZD tailwind, USDJPY/USDCHF under pressure"

        metals_context = ""
        if asset_class == "MACRO":
            if dxy.get("trend") == "UP":
                metals_context = "DXY UP → headwind for Gold/Silver (inverse correlation)"
            elif dxy.get("trend") == "DOWN":
                metals_context = "DXY DOWN → tailwind for Gold/Silver"

        intermarket = {
            "macro_bias":     macro_bias,
            "dxy":            dxy,
            "vix":            vix,
            "fear_greed":     fear_greed,
            "btc_dominance":  btc_dom,
            "funding":        funding,
            "forex_context":  forex_context,
            "metals_context": metals_context,
            "skipped":        False,
        }

        logger.info(
            f"Intermarket [{asset_class}]: macro={macro_bias} "
            f"DXY={dxy.get('trend','?')} VIX={vix.get('level','?')} "
            f"F&G={fear_greed.get('value','?')} Funding={funding.get('bias','?')}"
        )

        return {"intermarket": intermarket}

    return intermarket_agent_node
