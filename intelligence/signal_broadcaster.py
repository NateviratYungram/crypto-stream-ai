"""
CryptoStream AI — Signal Broadcaster
Sends trading signals and alerts via LINE Notify and/or Telegram.

Ported from QuantAgent signal_broadcaster.py — adapted for CryptoStream:
  - format_trade_signal() updated to use CryptoStream field names
    (symbol, entry_zone, stop_loss, take_profit, master_decision, etc.)
  - Env-var fallbacks: LINE_NOTIFY_TOKEN, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
  - enable_notifications defaults to True if any token is set
  - Thread-safe (each call creates its own HTTP session)

Configuration (pass as config dict or set env vars):
    LINE_NOTIFY_TOKEN    — free, unlimited, see https://notify-bot.line.me
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
    """
    Sends trading signals and alerts via LINE Notify (free) and/or Telegram (free).

    Priority: LINE first (simpler auth), then Telegram.
    Both channels can be active simultaneously.
    """

    def __init__(self, config: dict = None):
        self.config = config or {}

    # ── Config helpers ─────────────────────────────────────────────────────────

    def _line_token(self) -> str:
        return (self.config.get("line_notify_token") or
                os.getenv("LINE_NOTIFY_TOKEN", ""))

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
        # Auto-enable if any token is configured
        return bool(self._line_token() or self._tg_token())

    # ── Public API ─────────────────────────────────────────────────────────────

    def send_signal(self, message: str, image_path: Optional[str] = None) -> dict:
        """
        Send a message to all configured channels.

        Args:
            message    : Plain text / Markdown message
            image_path : Optional local path to a chart image

        Returns:
            Dict with channel → result mapping, or status string
        """
        if not self._enabled():
            return {"status": "Notifications disabled"}

        results = {}
        line_token = self._line_token()
        if line_token:
            results["line"] = self._send_line(line_token, message, image_path)

        tg_token = self._tg_token()
        tg_chat  = self._tg_chat()
        if tg_token and tg_chat:
            results["telegram"] = self._send_telegram(tg_token, tg_chat, message, image_path)

        if not results:
            return {"status": "No notification channels configured"}

        return results

    # ── Channel senders ────────────────────────────────────────────────────────

    def _send_line(self, token: str, message: str, image_path: Optional[str] = None) -> dict:
        """POST to LINE Notify endpoint."""
        try:
            import requests
            url     = "https://notify-api.line.me/api/notify"
            headers = {"Authorization": f"Bearer {token}"}
            data    = {"message": f"\n{message}"}
            files   = None

            if image_path:
                try:
                    files = {"imageFile": open(image_path, "rb")}
                except Exception:
                    pass

            resp = requests.post(url, headers=headers, data=data,
                                 files=files, timeout=10)
            if files:
                files["imageFile"].close()

            if resp.status_code == 200:
                return {"status": "OK", "channel": "LINE"}
            return {"status": "FAILED", "channel": "LINE", "error": resp.text[:120]}
        except Exception as e:
            return {"status": "ERROR", "channel": "LINE", "error": str(e)[:120]}

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
        """
        Format an AI analysis result into a human-readable signal message.
        Handles CryptoStream state field names.
        """
        decision   = state.get("master_decision", "NO_TRADE")
        confidence = state.get("master_confidence", 0)
        symbol     = state.get("symbol", "?")
        timeframe  = state.get("timeframe", "?")
        reasoning  = state.get("master_reasoning", "")
        sentiment  = state.get("sentiment_label", "")
        fg_index   = state.get("fear_greed_index", None)

        entry_zone = state.get("entry_zone", {})
        sl_data    = state.get("stop_loss", {})
        tp_data    = state.get("take_profit", {})
        rr         = state.get("risk_reward_ratio", 0)

        entry_low  = entry_zone.get("low", "?")
        entry_high = entry_zone.get("high", "?")
        sl_price   = sl_data.get("price", "?")
        tp1        = tp_data.get("tp1", "?")
        tp2        = tp_data.get("tp2", "?")

        # Confidence as percentage
        conf_pct = confidence * 100 if isinstance(confidence, float) and confidence <= 1 else confidence

        # Extract extra ML metadata for Sniper V8
        v8_precision = state.get("ml_precision_score", "High")
        is_sniper = conf_pct >= 85

        if decision == "LONG":
            emoji = "🎯 SNIPER LONG" if is_sniper else "📈 LONG"
        elif decision == "SHORT":
            emoji = "🎯 SNIPER SHORT" if is_sniper else "📉 SHORT"
        else:
            emoji = "⏳ HOLD"

        lines = [
            f"[{emoji}] {symbol} {timeframe}",
            f"{'=' * 22}",
            f"Neural Confidence : {conf_pct:.1f}%",
            f"Clinical Precision : {v8_precision}",
            f"Entry Zone : {entry_low} - {entry_high}",
            f"Stop Loss  : {sl_price}",
            f"Take Profit: TP1={tp1}  TP2={tp2}",
            f"Risk/Reward: 1:{rr}",
        ]

        # ── Sniper Chart Link (Visual Confirmation) ──
        # Provide a quick TradingView link for visual double-check
        tv_sym = f"FX:{symbol}" if asset_class == "FOREX" else symbol
        if symbol == "GOLD": tv_sym = "OANDA:XAUUSD"
        if symbol == "BTCUSD": tv_sym = "BINANCE:BTCUSDT"

        chart_link = f"https://www.tradingview.com/chart/?symbol={tv_sym}"
        lines.append(f"🔍 View Chart: [TradingView]({chart_link})")

        if sentiment:
            lines.append(f"Sentiment  : {sentiment}")
        if fg_index is not None:
            lines.append(f"Fear/Greed : {fg_index}")

        lines += [
            f"{'=' * 22}",
            reasoning[:280] if reasoning else "(no reasoning)",
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
            lines += [
                f"Volume  : {details.get('volume', '?')} lot",
                f"Entry   : {details.get('entry_price', '?')}",
                f"SL      : {details.get('sl', '?')}",
                f"TP      : {details.get('tp', '?')}",
                f"Risk    : ${details.get('risk_usd', '?')} ({details.get('risk_pct', '?')}%)",
            ]

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
