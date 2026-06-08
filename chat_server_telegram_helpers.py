from __future__ import annotations

import re


def _telegram_extract_profile_patch(text: str, symbols_from_text, user: dict | None = None) -> dict:
    raw = str(text or "")
    lower = raw.lower()
    patch: dict = {}
    if user:
        patch["username"] = user.get("username")
        patch["first_name"] = user.get("first_name")
    if re.search(r"[\u0E00-\u0E7F]", raw):
        patch["language"] = "th"
    elif any(word in lower for word in ("english", "en only", "answer in english")):
        patch["language"] = "en"
    if any(word in lower for word in ("สั้น", "สรุป", "brief", "short", "concise")):
        patch["answer_style"] = "concise"
    if any(word in lower for word in ("ละเอียด", "full", "detail", "deep")):
        patch["answer_style"] = "detailed"

    symbols = symbols_from_text(raw)
    if symbols and any(word in lower for word in ("ชอบ", "สนใจ", "watch", "ติดตาม", "จำ", "remember", "/watch", "/remember")):
        patch["preferred_symbols"] = symbols

    lot_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:lot|ล็อต|ลอต)", lower)
    if not lot_match:
        lot_match = re.search(r"(?:lot|ล็อต|ลอต)[^\d]{0,8}(\d+(?:\.\d+)?)", lower)
    if lot_match:
        patch["default_lot"] = max(float(lot_match.group(1)), 0.001)

    risk_match = re.search(r"(?:risk|เสี่ยง|ความเสี่ยง)[^\d]{0,12}(\d+(?:\.\d+)?)\s*%?", lower)
    if not risk_match:
        risk_match = re.search(r"(\d+(?:\.\d+)?)\s*%\s*(?:risk|เสี่ยง|ความเสี่ยง)", lower)
    if risk_match:
        patch["risk_pct"] = min(max(float(risk_match.group(1)), 0.1), 10.0)
    return patch


def _telegram_profile_text(profile: dict) -> str:
    symbols = ", ".join(profile.get("preferred_symbols") or []) or "ยังไม่ได้ตั้ง"
    lot = profile.get("default_lot")
    risk = profile.get("risk_pct")
    return (
        "Telegram finance profile\n"
        f"- Symbols: {symbols}\n"
        f"- Default lot: {lot if lot is not None else 'ยังไม่ได้ตั้ง'}\n"
        f"- Risk per trade: {str(risk) + '%' if risk is not None else 'ยังไม่ได้ตั้ง'}\n"
        f"- Language: {profile.get('language', 'th')}\n"
        f"- Style: {profile.get('answer_style', 'concise')}\n\n"
        "ตั้งค่าได้ เช่น:\n"
        "/watch BTC GOLD EURUSD\n"
        "/setlot 0.01\n"
        "/setrisk 1\n"
        "หรือพิมพ์ธรรมชาติ: จำไว้ว่า ฉันชอบ BTC GOLD ใช้ lot 0.01 เสี่ยง 1%"
    )


def _telegram_format_readiness(readiness: dict) -> str:
    checks = readiness.get("checks", {})
    ai = checks.get("ai_trading_quality", {})
    mt5 = checks.get("mt5", {})
    return (
        "System status\n"
        f"- Overall: {readiness.get('overall_percent')}%\n"
        f"- User chat: {'READY' if readiness.get('ready_for_users') else 'NOT READY'}\n"
        f"- Telegram: {'READY' if readiness.get('ready_for_notifications') else 'NOT READY'}\n"
        f"- MT5 execution infra: {'READY' if readiness.get('ready_for_mt5_execution') else 'NOT READY'}\n"
        f"- Live AI trading: {'READY' if readiness.get('ready_for_live_ai_trading') else 'BLOCKED'}\n"
        f"- MT5 connected: {bool(mt5.get('connected'))}\n"
        f"- AI mode: {ai.get('mode', 'unknown')}\n"
        f"- Blockers: {', '.join(ai.get('blockers', [])[:6]) or 'none'}"
    )
