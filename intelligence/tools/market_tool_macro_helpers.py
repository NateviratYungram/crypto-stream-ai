from __future__ import annotations

from typing import Any, Dict


def _build_sector_rotation_response(perf: dict[str, float]) -> dict[str, Any]:
    sorted_perf = sorted(perf.items(), key=lambda item: item[1], reverse=True)
    return {
        "instruction": "Identify which sectors are attracting institutional capital (Leading) and which are being sold (Lagging).",
        "leading_sectors": sorted_perf[:3],
        "lagging_sectors": sorted_perf[-3:],
        "full_rotation": sorted_perf,
        "market_summary": "Institutional flow favors " + sorted_perf[0][0] if sorted_perf else "Neutral",
    }


def _build_risk_parameters_response(
    *,
    account_size: float,
    entry: float,
    stop_loss: float,
    risk_pct: float,
) -> dict[str, Any]:
    if entry == stop_loss:
        return {"error": "Entry and Stop Loss cannot be the same price."}

    risk_amount = account_size * (risk_pct / 100)
    distance = abs(entry - stop_loss)
    position_size = risk_amount / distance
    suggested_tp = entry + (distance * 2) if entry > stop_loss else entry - (distance * 2)

    return {
        "account_size": account_size,
        "risk_percentage": f"{risk_pct}%",
        "risk_amount_dollars": round(risk_amount, 2),
        "position_size": round(position_size, 4),
        "distance_to_sl": round(distance, 4),
        "trade_instructions": f"To risk {risk_pct}% (${round(risk_amount, 2)}), enter at {entry} with a {round(position_size, 4)} lot/share size. SL at {stop_loss}.",
        "suggested_tp_1_2": round(suggested_tp, 4),
    }


def _build_market_climate_response(vix: float, dxy: float, tnx: float) -> Dict[str, Any]:
    vix_score = min(100, max(0, (vix - 10) / 25 * 100))
    dxy_score = min(100, max(0, (dxy - 95) / 10 * 100))
    tnx_score = min(100, max(0, (tnx - 3.0) / 2.0 * 100))

    global_risk_score = (vix_score * 0.4) + (dxy_score * 0.3) + (tnx_score * 0.3)

    regime = "NEUTRAL"
    threat_level = "LOW"
    color = "emerald"

    if global_risk_score > 70:
        regime, threat_level, color = "EXTREME TURBULENCE", "DANGER", "rose"
    elif global_risk_score > 50:
        regime, threat_level, color = "RISK OFF", "ALERT", "amber"
    elif global_risk_score < 30:
        regime, threat_level, color = "RISK ON", "OPTIMAL", "emerald"

    return {
        "global_risk_score": round(global_risk_score, 2),
        "regime": regime,
        "threat_level": threat_level,
        "color": color,
        "indicators": {
            "vix": round(vix, 2),
            "dxy": round(dxy, 2),
            "tnx_yield": round(tnx, 2),
        },
        "summary": f"Vol: {vix:.2f} | DXY: {dxy:.2f} | 10Y: {tnx:.2f}%",
    }


def _build_market_regime_response(
    *,
    regime_date: str | None,
    regime: str,
    confidence: float,
    drivers: list[str] | None,
    sp500_vol: float | None,
    crypto_vol: float | None,
    btc_corr: float | None,
    sp500_ma: float | None,
    btc_ma: float | None,
    emoji_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    def fmt(value: float | None, pct: bool = True) -> str:
        if value is None:
            return "N/A"
        return f"{float(value) * 100:.1f}%" if pct else f"{float(value):.2f}"

    emoji = (emoji_map or {"RISK_ON": "RISK_ON", "RISK_OFF": "RISK_OFF", "NEUTRAL": "NEUTRAL"}).get(regime, "NEUTRAL")
    driver_list = list(drivers or [])
    interpretation = (
        f"Current market regime is {emoji} {regime} ({confidence:.0f}% confidence). "
        + (f"SP500 is {'above' if sp500_ma and float(sp500_ma) > 0 else 'below'} its 200MA. " if sp500_ma is not None else "")
        + (f"BTC/SP500 correlation is {float(btc_corr):.2f} (30d). " if btc_corr is not None else "")
        + (f"Key drivers: {', '.join(driver_list)}." if driver_list else "")
    )

    return {
        "as_of": regime_date,
        "regime": regime,
        "regime_emoji": emoji,
        "confidence": f"{confidence:.0f}%",
        "drivers": driver_list,
        "market_stress": {
            "sp500_vol_30d_annualized": fmt(sp500_vol),
            "crypto_vol_30d_annualized": fmt(crypto_vol),
            "btc_sp500_correlation_30d": fmt(btc_corr, pct=False),
        },
        "trend_context": {
            "sp500_vs_200ma": fmt(sp500_ma) if sp500_ma is not None else "N/A",
            "btc_vs_200ma": fmt(btc_ma) if btc_ma is not None else "N/A",
        },
        "interpretation": interpretation,
    }
