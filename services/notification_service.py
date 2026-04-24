import os
import json
import httpx
import logging

class NotificationService:
    def __init__(self):
        # ── Telegram ──────────────────────────────────────────────
        self.telegram_token   = os.environ.get("TELEGRAM_BOT_TOKEN")
        self.default_chat_id  = os.environ.get("TELEGRAM_CHAT_ID")
        self.tg_api_url = (
            f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            if self.telegram_token else None
        )
        # ── Line Notify ───────────────────────────────────────────
        # Generate token at https://notify-bot.line.me/my/
        self.line_token = os.environ.get("LINE_NOTIFY_TOKEN")
        self._LINE_URL  = "https://notify-api.line.me/api/notify"

    # ── Telegram ─────────────────────────────────────────────────
    async def send_telegram_alert(self, message: str, chat_id: str = None):
        target_chat_id = chat_id or self.default_chat_id
        if not self.tg_api_url or not target_chat_id:
            safe_msg = message.encode("ascii", "ignore").decode("ascii")
            logging.info(f"Telegram alert skipped (Token/ChatID missing): {safe_msg}")
            return False

        try:
            async with httpx.AsyncClient() as client:
                payload = {
                    "chat_id":    target_chat_id,
                    "text":       f"🛸 *CryptoStream AI Alert*\n\n{message}",
                    "parse_mode": "Markdown"
                }
                response = await client.post(self.tg_api_url, json=payload, timeout=5)
                return response.status_code == 200
        except Exception as e:
            logging.error(f"Telegram notification error: {e}")
            return False

    # ── Line Notify ───────────────────────────────────────────────
    async def send_line_alert(self, message: str, image_url: str = None):
        """
        Push a message via LINE Notify.
        Set LINE_NOTIFY_TOKEN in .env (get from https://notify-bot.line.me/my/).
        Supports optional image_url for chart screenshots.
        """
        if not self.line_token:
            logging.info("Line Notify skipped (LINE_NOTIFY_TOKEN missing)")
            return False
        try:
            async with httpx.AsyncClient() as client:
                headers = {"Authorization": f"Bearer {self.line_token}"}
                data    = {"message": f"\n🛸 CryptoStream AI\n{message}"}
                if image_url:
                    data["imageThumbnail"] = image_url
                    data["imageFullsize"]  = image_url
                r = await client.post(self._LINE_URL, headers=headers, data=data, timeout=8)
                ok = r.status_code == 200
                if not ok:
                    logging.warning(f"Line Notify failed: {r.status_code} {r.text}")
                return ok
        except Exception as e:
            logging.error(f"Line Notify error: {e}")
            return False

    # ── Broadcast (Telegram + Line) ───────────────────────────────
    async def broadcast(self, message: str, image_url: str = None):
        """Send to all configured channels simultaneously."""
        tg_ok   = await self.send_telegram_alert(message)
        line_ok = await self.send_line_alert(message, image_url=image_url)
        return {"telegram": tg_ok, "line": line_ok}

    # ── Preset templates ──────────────────────────────────────────
    async def notify_whale(self, data: dict):
        symbol = data.get("symbol", "UNKNOWN")
        qty    = float(data.get("quantity", 0))
        price  = float(data.get("price", 0))
        msg = (
            f"🐋 WHALE INBOUND\n"
            f"Symbol: {symbol}\n"
            f"Amount: {qty:.4f}\n"
            f"Price: ${price:,.2f}\n"
            f"Value: ${qty * price:,.2f}"
        )
        return await self.broadcast(msg)

    async def notify_risk(self, detail: str):
        msg = f"⚠️ RISK ALERT\n{detail}"
        return await self.broadcast(msg)

    async def notify_trade_draft(self, symbol: str, side: str, draft_id: str, price: float = 0):
        """Called after TradingView webhook creates a draft."""
        msg = (
            f"📡 TV Alert → Trade Draft Created\n"
            f"Symbol: {symbol} | Side: {side}\n"
            f"Price: {price}\n"
            f"Draft ID: {draft_id}\n"
            f"ยืนยันใน Chat: 'ยืนยัน {draft_id}'"
        )
        return await self.broadcast(msg)

    async def notify_alert_triggered(self, symbol: str, condition: str, current_val: str):
        """Called when a smart alert fires."""
        msg = (
            f"🔔 Alert Triggered!\n"
            f"Symbol: {symbol}\n"
            f"Condition: {condition}\n"
            f"Current Value: {current_val}"
        )
        return await self.broadcast(msg)
        
    async def notify_market_opened(self, market_name: str):
        """Called when a major market transitions to OPEN."""
        msg = (
            f"🟢 *MARKET OPENED*\n"
            f"The {market_name} market is now open for trading!\n"
            f"Volatility and institutional volume are expected to rise. Trade with caution."
        )
        return await self.broadcast(msg)

    async def notify_market_closed(self, market_name: str, reason: str = "Regular Close"):
        """Called when a major market transitions to CLOSED/HOLIDAY."""
        msg = (
            f"🔴 *MARKET CLOSED*\n"
            f"The {market_name} market is now closed. ({reason})\n"
            f"Stay mindful of widening spreads and weekend gaps."
        )
        return await self.broadcast(msg)

    async def notify_system_startup(self):
        """Called when the backend fully initializes."""
        msg = (
            f"🚀 *System Online*\n"
            f"CryptoStream AI Backend is up and running. All monitoring systems and market tracking are active."
        )
        return await self.broadcast(msg)
