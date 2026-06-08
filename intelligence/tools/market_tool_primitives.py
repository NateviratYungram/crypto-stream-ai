from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


def _safe_num(value: Any, default: Optional[float] = None, digits: int = 4) -> Optional[float]:
    try:
        num = float(value)
        if pd.isna(num):
            return default
        return round(num, digits)
    except Exception:
        return default


def _build_chart_analysis(df_with_indicators: pd.DataFrame) -> Dict[str, Any]:
    if df_with_indicators is None or len(df_with_indicators) < 2:
        return {}

    try:
        last = df_with_indicators.iloc[-1]
        prev = df_with_indicators.iloc[-2]

        rsi_val = _safe_num(last.get("rsi_14"))
        macd_hist = _safe_num(last.get("macd_hist"))
        macd_hist_prev = _safe_num(prev.get("macd_hist"))
        ema20 = _safe_num(last.get("ema_20"))
        ema50 = _safe_num(last.get("ema_50"))
        ema200 = _safe_num(last.get("ema_200"))
        price_now = _safe_num(last.get("Close"))
        atr = _safe_num(last.get("atr_14"))

        recent_high = _safe_num(df_with_indicators["High"].tail(20).max(), digits=2)
        recent_low = _safe_num(df_with_indicators["Low"].tail(20).min(), digits=2)

        rsi_signal = (
            "OVERSOLD (โซนซื้อ)" if rsi_val is not None and rsi_val < 35 else
            "OVERBOUGHT (โซนขาย)" if rsi_val is not None and rsi_val > 70 else
            "NEUTRAL"
        )

        macd_cross = None
        if macd_hist is not None and macd_hist_prev is not None:
            if macd_hist > 0 and macd_hist_prev <= 0:
                macd_cross = "BULLISH_CROSS (สัญญาณซื้อ)"
            elif macd_hist < 0 and macd_hist_prev >= 0:
                macd_cross = "BEARISH_CROSS (สัญญาณขาย)"
            else:
                macd_cross = "BULLISH_MOMENTUM" if macd_hist > 0 else "BEARISH_MOMENTUM"

        ema_trend = (
            "BULLISH (ราคาเหนือ EMA20 > EMA50)" if price_now and ema20 and ema50 and price_now > ema20 > ema50 else
            "BEARISH (ราคาต่ำกว่า EMA20 < EMA50)" if price_now and ema20 and ema50 and price_now < ema20 < ema50 else
            "SIDEWAYS"
        )

        buy_zone_low = recent_low
        buy_zone_high = round(recent_low * 1.02, 2) if recent_low else None
        sell_zone_low = round(recent_high * 0.98, 2) if recent_high else None
        sell_zone_high = recent_high

        action_summary = "WATCH: รอราคาเข้าโซนที่ชัดเจนก่อน"
        if rsi_val is not None and price_now and recent_low and rsi_val < 40 and price_now < recent_low * 1.03:
            action_summary = "BUY_ZONE: ราคาใกล้แนวรับ + RSI Oversold"
        elif rsi_val is not None and price_now and recent_high and rsi_val > 65 and price_now > recent_high * 0.97:
            action_summary = "SELL_ZONE: ราคาใกล้แนวต้าน + RSI Overbought"

        return {
            "rsi": {"value": rsi_val, "signal": rsi_signal},
            "macd": {"histogram": macd_hist, "signal": macd_cross},
            "ema_trend": ema_trend,
            "ema20": ema20,
            "ema50": ema50,
            "ema200": ema200,
            "support_20bar": recent_low,
            "resistance_20bar": recent_high,
            "chart_buy_zone": {
                "low": buy_zone_low,
                "high": buy_zone_high,
                "note": "โซนซื้อทางเทคนิค (แนวรับรอบ 20 แท่ง)",
            },
            "chart_sell_zone": {
                "low": sell_zone_low,
                "high": sell_zone_high,
                "note": "โซนขายทางเทคนิค (แนวต้านรอบ 20 แท่ง)",
            },
            "atr": atr,
            "action_summary": action_summary,
        }
    except Exception as exc:
        logger.warning("Chart analysis builder failed: %s", exc)
        return {}


def _bias_from_label(raw: Any) -> str:
    if raw is None:
        return "NEUTRAL"

    text = str(raw).upper()
    bullish_tokens = ["BULL", "BUY", "LONG", "ACCUMULATION", "OVERSOLD"]
    bearish_tokens = ["BEAR", "SELL", "SHORT", "DISTRIBUTION", "OVERBOUGHT"]

    if any(token in text for token in bullish_tokens):
        return "BULLISH"
    if any(token in text for token in bearish_tokens):
        return "BEARISH"
    return "NEUTRAL"


def _derive_trade_signal(analysis: Dict[str, Any], ml_stats: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    bull_score = 0
    bear_score = 0
    evidence: List[str] = []
    blockers: List[str] = []

    def add_vote(label: str, weight: int, detail: str) -> None:
        nonlocal bull_score, bear_score
        if label == "BULLISH":
            bull_score += weight
            evidence.append(f"BULLISH x{weight}: {detail}")
        elif label == "BEARISH":
            bear_score += weight
            evidence.append(f"BEARISH x{weight}: {detail}")

    chart = analysis.get("chart_analysis", {})
    htf = analysis.get("higher_timeframe", {})
    smc = analysis.get("smart_money", analysis.get("price_structure", {}))
    structure = smc.get("structure", {}) if isinstance(smc.get("structure"), dict) else {}
    historical = analysis.get("historical_pulse", {})
    whale = analysis.get("whale_pulse", {})
    retail = analysis.get("retail_fomo", {})
    ema_data = analysis.get("ema", {})

    htf_bias = _bias_from_label(htf.get("bias"))
    structure_bias = _bias_from_label(structure.get("structure"))
    bos_bias = _bias_from_label(structure.get("last_bos"))
    ema_bias = _bias_from_label(ema_data.get("signal") or chart.get("ema_trend"))
    chart_bias = _bias_from_label(chart.get("action_summary"))
    historical_bias = _bias_from_label(historical.get("statistical_bias"))
    whale_bias = _bias_from_label(whale.get("bias"))
    retail_bias = _bias_from_label(retail.get("institutional_bias"))
    ml_bias = _bias_from_label((ml_stats or {}).get("side"))

    add_vote(htf_bias, 3, f"higher timeframe bias = {htf.get('bias', 'N/A')}")
    add_vote(structure_bias, 2, f"market structure = {structure.get('structure', 'N/A')}")
    add_vote(bos_bias, 2, f"last BOS = {structure.get('last_bos', 'N/A')}")
    add_vote(ema_bias, 2, f"EMA trend = {ema_data.get('signal') or chart.get('ema_trend') or 'N/A'}")
    add_vote(chart_bias, 1, f"chart action = {chart.get('action_summary', 'N/A')}")
    add_vote(historical_bias, 1, f"historical pulse = {historical.get('statistical_bias', 'N/A')}")
    add_vote(whale_bias, 1, f"whale bias = {whale.get('bias', 'N/A')}")
    add_vote(retail_bias, 1, f"retail contrarian bias = {retail.get('institutional_bias', 'N/A')}")
    add_vote(ml_bias, 2, f"institutional ML side = {(ml_stats or {}).get('side', 'N/A')}")

    raw_ml_prob = (ml_stats or {}).get("neural_win_probability")
    ml_prob = _safe_num(raw_ml_prob, default=None) if isinstance(raw_ml_prob, (int, float)) else None
    raw_edge_score = (ml_stats or {}).get("edge_score")
    edge_score = _safe_num(raw_edge_score, default=None) if isinstance(raw_edge_score, (int, float)) else None
    htf_adx = _safe_num(htf.get("adx"), default=0.0)

    leader = "BULLISH" if bull_score > bear_score else "BEARISH" if bear_score > bull_score else "NEUTRAL"
    leader_score = max(bull_score, bear_score)
    diff = abs(bull_score - bear_score)

    if htf_bias == "NEUTRAL":
        blockers.append("Higher timeframe bias is neutral")
    if htf_adx < 18:
        blockers.append(f"HTF ADX is weak at {htf_adx}")
    if leader_score < 5:
        blockers.append("Confluence score is still too light")
    if diff <= 1:
        blockers.append("Bull/Bear evidence is too close")
    if isinstance(ml_prob, (int, float)) and 0.48 <= ml_prob <= 0.52:
        blockers.append(f"ML probability is undecided at {ml_prob:.2f}")
    elif not isinstance(ml_prob, (int, float)):
        blockers.append("ML model is unavailable for this setup")

    if leader_score >= 6 and diff >= 2:
        action = "BUY" if leader == "BULLISH" else "SELL"
    elif leader_score >= 5 and diff >= 2 and htf_bias == leader:
        action = "BUY" if leader == "BULLISH" else "SELL"
    elif (
        leader_score >= 5
        and diff >= 1
        and htf_bias == leader
        and structure_bias == leader
        and isinstance(ml_prob, (int, float))
        and ml_prob >= 0.50
    ):
        action = "BUY" if leader == "BULLISH" else "SELL"
    else:
        action = "HOLD"

    confidence = 48 + (leader_score * 4) + (diff * 6)
    if action == "HOLD":
        confidence = 40 + (leader_score * 3)
    if edge_score is not None:
        confidence += int((edge_score - 0.5) * 30)
    confidence = max(35, min(92, confidence))

    return {
        "action": action,
        "bias": leader,
        "bull_score": bull_score,
        "bear_score": bear_score,
        "confidence": confidence,
        "evidence": evidence,
        "blockers": blockers,
        "ml_probability": ml_prob,
        "edge_score": edge_score,
    }


_CONTRACT_SIZES: Dict[str, float] = {
    "GOLD": 100.0,
    "XAUUSD": 100.0,
    "XAUEUR": 100.0,
    "SILVER": 5000.0,
    "XAGUSD": 5000.0,
    "OIL": 1000.0,
    "USOIL": 1000.0,
    "UKOIL": 1000.0,
    "DEFAULT_FX": 100_000.0,
    "NAS100": 10.0,
    "US30": 10.0,
    "SP500": 50.0,
    "SPX500": 50.0,
}


def calculate_trade_pnl(
    symbol: str,
    action: str,
    volume: float,
    entry_price: float,
    target_price: float,
    account_balance: Optional[float] = None,
) -> Dict[str, Any]:
    try:
        sym_upper = symbol.strip().upper()
        contract_size = _CONTRACT_SIZES.get(sym_upper, _CONTRACT_SIZES["DEFAULT_FX"])
        if len(sym_upper) == 6 and sym_upper.isalpha() and sym_upper not in _CONTRACT_SIZES:
            contract_size = _CONTRACT_SIZES["DEFAULT_FX"]

        action_upper = action.strip().upper()
        if action_upper == "BUY":
            pnl_per_lot = (target_price - entry_price) * contract_size
        elif action_upper == "SELL":
            pnl_per_lot = (entry_price - target_price) * contract_size
        else:
            return {"error": f"Invalid action: {action}. Must be BUY or SELL."}

        pnl_usd = round(pnl_per_lot * volume, 2)
        points_moved = round(abs(target_price - entry_price), 4)
        direction_label = "profit" if pnl_usd > 0 else "loss"

        result: Dict[str, Any] = {
            "symbol": sym_upper,
            "action": action_upper,
            "volume_lots": volume,
            "entry_price": entry_price,
            "target_price": target_price,
            "points_moved": points_moved,
            "contract_size_per_lot": contract_size,
            "pnl_usd": pnl_usd,
            "direction": direction_label,
            "summary": (
                f"{action_upper} {volume} lot {sym_upper}: "
                f"if price moves from {entry_price} to {target_price} "
                f"({points_moved} pts), P&L = {'+' if pnl_usd >= 0 else ''}{pnl_usd} USD ({direction_label})"
            ),
        }

        if account_balance and account_balance > 0:
            result["pct_of_balance"] = round(abs(pnl_usd) / account_balance * 100, 2)
            result["balance_after"] = round(account_balance + pnl_usd, 2)

        return result
    except Exception as exc:
        logger.error("Error in calculate_trade_pnl: %s", exc)
        return {"error": str(exc)}
