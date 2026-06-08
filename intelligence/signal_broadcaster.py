"""
CryptoStream AI — Signal Broadcaster
Sends trading signals and alerts via Telegram.

Configuration (pass as config dict or set env vars):
    TELEGRAM_BOT_TOKEN   — from @BotFather
    TELEGRAM_CHAT_ID     — numeric chat/channel ID

Usage:
    from intelligence.signal_broadcaster import get_signal_broadcaster

    sb = get_signal_broadcaster()
    sb.send_signal(sb.format_trade_signal(state))
    sb.send_execution_alert(state, execution)
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


class SignalBroadcaster:
    """Sends trading signals and alerts via Telegram."""

    def __init__(self, config: dict = None):
        self.config = config or {}

    # ── Config helpers ─────────────────────────────────────────────────────────

    def _tg_token(self) -> str:
        return (self.config.get("telegram_bot_token") or
                os.getenv("TELEGRAM_BOT_TOKEN", ""))

    def _tg_chat(self) -> str:
        return (self.config.get("telegram_chat_id") or
                os.getenv("TELEGRAM_CHAT_ID", ""))

    def _enabled(self) -> bool:
        explicit = self.config.get("enable_notifications")
        if explicit is not None:
            return bool(explicit)
        return bool(self._tg_token())

    # ── Public API ─────────────────────────────────────────────────────────────

    def send_signal(self, message: str, image_path: Optional[str] = None) -> dict:
        if not self._enabled():
            return {"status": "Notifications disabled"}

        tg_token = self._tg_token()
        tg_chat  = self._tg_chat()
        if tg_token and tg_chat:
            return {"telegram": self._send_telegram(tg_token, tg_chat, message, image_path)}

        return {"status": "No notification channels configured"}

    # ── Channel senders ────────────────────────────────────────────────────────

    def _send_telegram(self, token: str, chat_id: str,
                       message: str, image_path: Optional[str] = None) -> dict:
        """POST to Telegram Bot API."""
        try:
            import requests
            if image_path:
                url   = f"https://api.telegram.org/bot{token}/sendPhoto"
                files = {"photo": open(image_path, "rb")}
                data  = {"chat_id": chat_id, "caption": message[:1024]}
                resp  = requests.post(url, data=data, files=files, timeout=10)
                files["photo"].close()
            else:
                url  = f"https://api.telegram.org/bot{token}/sendMessage"
                data = {
                    "chat_id":    chat_id,
                    "text":       message[:4096],
                    "parse_mode": "Markdown",
                }
                resp = requests.post(url, data=data, timeout=10)

            if resp.status_code == 200:
                return {"status": "OK", "channel": "Telegram"}
            return {"status": "FAILED", "channel": "Telegram", "error": resp.text[:120]}
        except Exception as e:
            return {"status": "ERROR", "channel": "Telegram", "error": str(e)[:120]}

    # ── Message formatters ─────────────────────────────────────────────────────

    def format_trade_signal(self, state: dict) -> str:
        """Format an AI analysis result into a human-readable Telegram signal message."""
        decision    = state.get("master_decision", "NO_TRADE")
        confidence  = state.get("master_confidence", 0)
        symbol      = state.get("symbol", "?")
        timeframe   = state.get("timeframe", "?")
        reasoning   = state.get("master_reasoning", "")
        sentiment   = state.get("sentiment_label", "")
        asset_class = state.get("asset_class", "")

        entry_zone = state.get("entry_zone", {})
        sl_data    = state.get("stop_loss", {})
        tp_data    = state.get("take_profit", {})
        rr         = state.get("risk_reward_ratio", 0)

        entry_low  = entry_zone.get("low", "?")
        entry_high = entry_zone.get("high", "?")
        sl_price   = sl_data.get("price", "?")
        tp1        = tp_data.get("tp1", "?")
        tp2        = tp_data.get("tp2", "?")

        conf_pct     = confidence * 100 if isinstance(confidence, float) and confidence <= 1 else confidence
        signal_grade = state.get("signal_grade", "")
        size_mult    = state.get("size_multiplier", 1.0)

        # ML probability
        ml_sig    = state.get("ml_signal", {})
        ml_buy    = ml_sig.get("buy_pct", None)
        ml_sell   = ml_sig.get("sell_pct", None)
        ml_neural = ml_sig.get("neural_alignment", False)

        # Confluence
        confluence_score = state.get("confluence_score", None)
        confluence_bd    = state.get("confluence_breakdown", "")

        # Filter notes (MTF, funding, entry confirmation, cooldown)
        filter_notes = state.get("filter_notes", [])

        # Intermarket context
        im         = state.get("intermarket", {})
        macro_bias = state.get("macro_bias") or im.get("macro_bias", "")
        vix_level  = im.get("vix", {}).get("level", "")
        dxy_trend  = im.get("dxy", {}).get("trend", "")
        fg_val     = im.get("fear_greed", {}).get("value", None)
        funding    = im.get("funding", {})
        fr_pct     = funding.get("rate_pct", None)
        fr_bias    = funding.get("bias", "")

        grade_icon = {"A+": "🥇", "A": "🥈", "B": "🥉"}.get(signal_grade, "")
        macro_icon = {"RISK_ON": "🟢", "RISK_OFF": "🔴", "NEUTRAL": "🟡"}.get(macro_bias, "")

        if decision == "LONG":
            dir_emoji = "📈 LONG"
        elif decision == "SHORT":
            dir_emoji = "📉 SHORT"
        else:
            dir_emoji = "⏳ HOLD"

        lines = [
            f"[{dir_emoji}] *{symbol}* {timeframe}",
            f"{'─' * 24}",
            f"Confidence : *{conf_pct:.1f}%*",
        ]

        if signal_grade:
            lines.append(f"Grade      : {grade_icon} *{signal_grade}*  (size {size_mult:.0%})")

        lines += [
            f"Entry Zone : `{entry_low} – {entry_high}`",
            f"Stop Loss  : `{sl_price}`",
            f"TP1 / TP2  : `{tp1}` / `{tp2}`",
            f"Risk/Reward: 1:{rr}",
        ]

        # ML probability block
        if ml_buy is not None or ml_sell is not None:
            ml_parts = []
            if ml_buy is not None:
                ml_parts.append(f"Buy={ml_buy:.1f}%")
            if ml_sell is not None:
                ml_parts.append(f"Sell={ml_sell:.1f}%")
            if ml_neural:
                ml_parts.append("Neural✓")
            lines.append(f"ML Prob    : {' | '.join(ml_parts)}")

        # Confluence score
        if confluence_score is not None:
            cf_str = f"Confluence : {confluence_score:.0f}/100"
            if confluence_bd:
                cf_str += f"  [{confluence_bd[:60]}]"
            lines.append(cf_str)

        if macro_bias:
            macro_parts = [f"{macro_icon} {macro_bias}"]
            if vix_level:
                macro_parts.append(f"VIX={vix_level}")
            if dxy_trend:
                macro_parts.append(f"DXY={dxy_trend}")
            if fg_val is not None:
                macro_parts.append(f"F&G={fg_val}")
            if fr_pct is not None:
                macro_parts.append(f"FR={fr_pct:.3f}%")
            elif fr_bias:
                macro_parts.append(f"Funding={fr_bias}")
            lines.append(f"Macro      : {' | '.join(macro_parts)}")

        if sentiment:
            lines.append(f"Sentiment  : {sentiment}")

        # Filter notes — show which guards the signal passed/triggered
        if filter_notes:
            lines.append(f"Filters    : {' · '.join(filter_notes[:3])}")

        tv_sym = f"FX:{symbol}" if asset_class == "FOREX" else symbol
        if symbol == "GOLD":
            tv_sym = "OANDA:XAUUSD"
        elif symbol in ("BTC", "BTCUSD"):
            tv_sym = "BINANCE:BTCUSDT"

        chart_link = f"https://www.tradingview.com/chart/?symbol={tv_sym}"
        lines += [
            f"{'─' * 24}",
            reasoning[:280] if reasoning else "(no reasoning)",
            f"🔍 [TradingView]({chart_link})",
        ]

        return "\n".join(lines)

    def format_execution_alert(self, state: dict, execution: dict) -> str:
        """
        Format execution_bridge output into a brief notification.
        """
        status     = execution.get("status", "?")
        symbol     = state.get("symbol", "?")
        decision   = state.get("master_decision", "?")
        details    = execution.get("trade_details", {})
        reason     = execution.get("reason", "")

        lines = [
            f"[EXECUTION] {symbol} {decision}",
            f"Status  : {status}",
        ]

        if details:
            grade = details.get('signal_grade', '')
            mult  = details.get('size_mult', 1.0)
            lines += [
                f"Volume  : {details.get('volume', '?')} lot",
                f"Entry   : {details.get('entry_price', '?')}",
                f"SL      : {details.get('sl', '?')}",
                f"TP      : {details.get('tp', '?')}",
                f"Risk    : ${details.get('risk_usd', '?')} ({details.get('risk_pct', '?')}%)",
            ]
            if grade:
                lines.append(f"Grade   : {grade} (size {mult:.0%})")

        if reason:
            lines.append(f"Note    : {reason[:120]}")

        if status == "BLOCKED":
            cb  = execution.get("cb_status", {})
            grd = execution.get("guard_result", {})
            if cb:
                lines.append(f"CB      : daily={cb.get('daily_pnl','?')}, weekly={cb.get('weekly_pnl','?')}")
            if grd:
                lines.append(f"Guard   : {grd.get('guard_override_reason','?')[:80]}")

        return "\n".join(lines)

    def send_execution_alert(self, state: dict, execution: dict) -> dict:
        """Convenience: format + send execution result."""
        msg = self.format_execution_alert(state, execution)
        return self.send_signal(msg)


# ── Module-level singleton ─────────────────────────────────────────────────────
_sb_instance: SignalBroadcaster | None = None


def get_signal_broadcaster(config: dict = None) -> SignalBroadcaster:
    """Return (or create) the process-wide SignalBroadcaster singleton."""
    global _sb_instance
    if _sb_instance is None:
        _sb_instance = SignalBroadcaster(config=config)
    return _sb_instance
