from __future__ import annotations

from typing import Any, Dict


def _summarize_stock_fundamentals(ticker: str, info: dict[str, Any], sqlite_fallback: dict[str, Any] | None = None) -> Dict[str, Any]:
    sqlite_fallback = sqlite_fallback or {}
    price = info.get("currentPrice") or info.get("regularMarketPrice") or sqlite_fallback.get("price_sq")
    if not price:
        return {}

    pe = info.get("trailingPE")
    fpe = info.get("forwardPE")
    pb = info.get("priceToBook")
    ps = info.get("priceToSalesTrailing12Months")
    eps = info.get("trailingEps")
    eg = info.get("earningsGrowth")
    rg = info.get("revenueGrowth")
    pm = info.get("profitMargins")
    roe = info.get("returnOnEquity")
    de = info.get("debtToEquity")
    w52h = info.get("fiftyTwoWeekHigh")
    w52l = info.get("fiftyTwoWeekLow")
    mktcap = info.get("marketCap")
    target = info.get("targetMeanPrice")
    analyst_cnt = info.get("numberOfAnalystOpinions", 0)
    upside_pct = round(((target - price) / price) * 100, 1) if target and price else None

    pe_signal = (
        "CHEAP" if pe and pe < 15 else
        "FAIR" if pe and pe < 25 else
        "EXPENSIVE" if pe else "N/A"
    )

    range_pct = None
    range_signal = "UNKNOWN"
    w52h = w52h or (
        price / (1 + (sqlite_fallback.get("pct_52wh_sq", 0) / 100))
        if sqlite_fallback.get("pct_52wh_sq") is not None
        else None
    )
    if w52l and w52h and w52h > w52l:
        range_pct = round(((price - w52l) / (w52h - w52l)) * 100, 1)
        range_signal = (
            "NEAR_LOW_BUY_ZONE" if range_pct < 25 else
            "LOWER_MID_RANGE" if range_pct < 45 else
            "MID_RANGE" if range_pct < 65 else
            "NEAR_HIGH_CAUTION"
        )

    sell_targets = {}
    sell_logic = []
    if target and price and price > 0:
        sell_t1 = round(target, 2)
        sell_t2 = round(target * 1.10, 2)
        upside_t1 = round(((sell_t1 - price) / price) * 100, 1)
        upside_t2 = round(((sell_t2 - price) / price) * 100, 1)
        sell_targets["T1_analyst_target"] = sell_t1
        sell_targets["T1_upside_pct"] = upside_t1
        sell_targets["T2_full_value_premium"] = sell_t2
        sell_targets["T2_upside_pct"] = upside_t2
        if upside_t1 > 0:
            sell_logic.append(f"TP1: ${sell_t1} is the average analyst target from {analyst_cnt} analysts (Upside +{upside_t1}%)")
        else:
            sell_logic.append("Current price is already above the analyst target. Watch for profit-taking pressure.")
        sell_logic.append(f"TP2: ${sell_t2} is a premium momentum overshoot zone (+10% above target).")

    if w52h and price:
        sell_targets["T3_52w_high_resistance"] = round(w52h, 2)
        upside_52h = round(((w52h - price) / price) * 100, 1) if price > 0 else None
        if upside_52h is not None:
            sell_targets["T3_upside_pct"] = upside_52h
        if price < w52h:
            sell_logic.append(f"TP3: ${w52h:.2f} is the prior 52-week high resistance zone.")
        else:
            sell_logic.append("Price is already at or above the 52-week high and is in price discovery.")

    return {
        "company": info.get("longName", ticker),
        "sector": info.get("sector", "N/A"),
        "industry": info.get("industry", "N/A"),
        "market_cap_b": round(mktcap / 1e9, 2) if mktcap else None,
        "current_price": price,
        "pe_trailing": round(pe, 2) if pe else None,
        "pe_forward": round(fpe, 2) if fpe else None,
        "pb_ratio": round(pb, 2) if pb else None,
        "ps_ratio": round(ps, 2) if ps else None,
        "pe_signal": pe_signal,
        "eps": round(eps, 4) if eps else None,
        "eps_growth_yoy": f"{eg * 100:.1f}%" if eg else "N/A",
        "revenue_growth_yoy": f"{rg * 100:.1f}%" if rg else "N/A",
        "profit_margin": f"{pm * 100:.1f}%" if pm else "N/A",
        "roe": f"{roe * 100:.1f}%" if roe else "N/A",
        "debt_to_equity": round(de, 2) if de else None,
        "52w_low": w52l,
        "52w_high": w52h,
        "range_pct": range_pct,
        "range_signal": range_signal,
        "analyst_target": target,
        "analyst_upside_pct": upside_pct,
        "analyst_count": analyst_cnt,
        "sell_targets": sell_targets,
        "sell_logic": sell_logic,
    }
