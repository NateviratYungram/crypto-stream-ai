"""
CryptoStream AI — Crypto Risk Calculator
Adapts QuantAgent risk_calculator.py logic for crypto spot/futures trading.
Crypto has no pip system — uses percentage-based risk and USDT amounts.
"""

import math


def calculate_crypto_risk(
    entry_price: float,
    stop_loss_price: float,
    account_balance_usdt: float,
    risk_percent: float = 1.0,
    leverage: float = 1.0,
) -> dict:
    """
    Calculate position sizing and risk metrics for a crypto trade.

    Args:
        entry_price:          Planned entry price (USDT)
        stop_loss_price:      Stop loss price (USDT)
        account_balance_usdt: Total account balance in USDT
        risk_percent:         Max % of account to risk on this trade (default 1%)
        leverage:             Leverage multiplier (1 = spot, 10 = 10x futures)

    Returns:
        dict with position_size, risk_usdt, risk_percent, margin_required, etc.
    """
    if entry_price <= 0 or account_balance_usdt <= 0:
        return {"error": "Invalid entry price or balance"}

    if stop_loss_price >= entry_price:
        direction = "SHORT"
        sl_distance_pct = (stop_loss_price - entry_price) / entry_price * 100
    else:
        direction = "LONG"
        sl_distance_pct = (entry_price - stop_loss_price) / entry_price * 100

    sl_distance_pct = abs(sl_distance_pct)

    # Max USDT to risk on this trade
    max_risk_usdt = account_balance_usdt * (risk_percent / 100)

    # Position size = risk / SL distance
    sl_distance_per_unit = abs(entry_price - stop_loss_price)
    if sl_distance_per_unit == 0:
        return {"error": "Stop loss equals entry price"}

    position_size_units = max_risk_usdt / sl_distance_per_unit
    position_value_usdt = position_size_units * entry_price

    # Margin required (for futures leverage)
    margin_required = position_value_usdt / leverage

    # Risk level classification
    if risk_percent <= 1.0:
        risk_level, risk_emoji = "LOW", "🟢"
    elif risk_percent <= 2.0:
        risk_level, risk_emoji = "MEDIUM", "🟡"
    elif risk_percent <= 5.0:
        risk_level, risk_emoji = "HIGH", "🔴"
    else:
        risk_level, risk_emoji = "EXTREME", "💀"

    # Trades to wipeout
    trades_to_wipeout = math.floor(account_balance_usdt / max_risk_usdt) if max_risk_usdt > 0 else 999

    return {
        "direction": direction,
        "entry_price": round(entry_price, 4),
        "stop_loss_price": round(stop_loss_price, 4),
        "sl_distance_pct": round(sl_distance_pct, 3),
        "sl_distance_usdt": round(sl_distance_per_unit, 4),
        "account_balance_usdt": round(account_balance_usdt, 2),
        "risk_percent": round(risk_percent, 2),
        "risk_usdt": round(max_risk_usdt, 2),
        "position_size_units": round(position_size_units, 6),
        "position_value_usdt": round(position_value_usdt, 2),
        "leverage": leverage,
        "margin_required_usdt": round(margin_required, 2),
        "trades_to_wipeout": trades_to_wipeout,
        "risk_level": risk_level,
        "risk_emoji": risk_emoji,
    }


def get_risk_advice_thai(risk_data: dict) -> str:
    """
    Generate Thai-language risk advice based on calculated risk metrics.
    Rule-based (no LLM) for consistency — ported from QuantAgent get_risk_advice().
    """
    level = risk_data.get("risk_level", "MEDIUM")
    risk_pct = risk_data.get("risk_percent", 1.0)
    risk_usdt = risk_data.get("risk_usdt", 0)
    wipeout = risk_data.get("trades_to_wipeout", 100)
    pos_value = risk_data.get("position_value_usdt", 0)
    balance = risk_data.get("account_balance_usdt", 0)
    sl_pct = risk_data.get("sl_distance_pct", 0)
    lev = risk_data.get("leverage", 1)

    lines = []

    if level == "LOW":
        lines.append(f"✅ ความเสี่ยง {risk_pct:.1f}% (${risk_usdt:.2f}) ต่อเทรด — เหมาะสม")
        lines.append(f"📊 ขนาด Position: ${pos_value:.0f} ({pos_value/balance*100:.0f}% ของพอร์ต)")
        lines.append(f"🔒 SL ห่าง {sl_pct:.2f}% จาก Entry")
        if lev > 1:
            lines.append(f"⚡ Leverage {lev}x — ระวัง Liquidation!")
        lines.append(f"🧮 ต้องแพ้ {wipeout} ครั้งติดกันกว่าพอร์ตจะหมด")
        lines.append("💡 แนะนำ: เหมาะสำหรับเทรดระยะยาว")

    elif level == "MEDIUM":
        lines.append(f"⚠️ ความเสี่ยง {risk_pct:.1f}% (${risk_usdt:.2f}) ต่อเทรด — ระวัง")
        lines.append(f"แพ้ 5 ครั้งติด = เสีย ${risk_usdt * 5:.0f} ({risk_pct * 5:.0f}% ของพอร์ต)")
        lines.append("💡 แนะนำ: ใช้ได้ถ้ามั่นใจในระบบ แต่จำกัด ≤3 เทรด/วัน")

    elif level == "HIGH":
        lines.append(f"🔴 ความเสี่ยง {risk_pct:.1f}% — สูงเกินไป!")
        lines.append(f"แพ้ 3 ครั้ง = เสีย {risk_pct * 3:.0f}% ของพอร์ต — ฟื้นยาก")
        lines.append("💡 แนะนำ: ลดความเสี่ยงลงเหลือ ≤2% ต่อเทรด")

    else:  # EXTREME
        lines.append(f"💀 ความเสี่ยง {risk_pct:.1f}% — อันตรายมาก! ห้ามเทรด!")
        lines.append(f"แค่ {wipeout} เทรดก็หมดพอร์ต!")
        lines.append("💡 แนะนำ: ลดขนาด Position ทันที หรือเพิ่มทุน")

    return "\n".join(lines)


def calculate_position_scenarios(
    entry_price: float,
    stop_loss_price: float,
    account_balance_usdt: float,
    leverage: float = 1.0,
) -> list:
    """
    Show risk comparison for different risk % scenarios (0.5%, 1%, 2%, 5%).
    For the UI to display a risk table.
    """
    scenarios = [0.5, 1.0, 1.5, 2.0, 3.0, 5.0]
    results = []

    for rp in scenarios:
        r = calculate_crypto_risk(entry_price, stop_loss_price, account_balance_usdt, rp, leverage)
        if "error" not in r:
            results.append({
                "risk_percent": rp,
                "risk_usdt": r["risk_usdt"],
                "position_value_usdt": r["position_value_usdt"],
                "position_size_units": r["position_size_units"],
                "risk_level": r["risk_level"],
                "risk_emoji": r["risk_emoji"],
                "trades_to_wipeout": r["trades_to_wipeout"],
                "advice": get_risk_advice_thai(r).split("\n")[0],
            })

    return results
