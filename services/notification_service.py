import logging
import os
from typing import Any

import httpx
from dotenv import load_dotenv


class NotificationService:
    def __init__(self):
        load_dotenv()
        self.telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        self.default_chat_id = os.environ.get("TELEGRAM_CHAT_ID")
        allowed = os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "")
        self.allowed_chat_ids = {item.strip() for item in allowed.split(",") if item.strip()}
        if self.default_chat_id:
            self.allowed_chat_ids.add(str(self.default_chat_id))
        self.tg_api_base = "https://api.telegram.org"
        self.last_error = None
        self.last_update_id = None

    def _telegram_url(self, method: str) -> str | None:
        if not self.telegram_token:
            return None
        return f"{self.tg_api_base}/bot{self.telegram_token}/{method}"

    def _make_async_client(self, timeout: float | None = None) -> httpx.AsyncClient:
        if timeout is None:
            return httpx.AsyncClient()
        return httpx.AsyncClient(timeout=timeout)

    def _extract_response_error(self, response) -> dict[str, Any]:
        description = None
        error_code = None
        try:
            data = response.json()
            description = data.get("description")
            error_code = data.get("error_code")
        except Exception:
            description = response.text[:160]
        return {
            "status_code": response.status_code,
            "error_code": error_code,
            "description": description,
        }

    def _set_missing_target_error(self, reason: str = "missing_token_or_chat_id") -> None:
        self.last_error = {"reason": reason}

    def _alert_text(self, message: str) -> str:
        return f"CryptoStream AI Alert\n\n{message}"

    def _build_message_payload(self, chat_id: str, message: str, reply_markup: dict | None = None) -> dict[str, Any]:
        payload = {
            "chat_id": chat_id,
            "text": message[:3900],
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return payload

    def telegram_status(self):
        missing = []
        if not self.telegram_token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not self.default_chat_id:
            missing.append("TELEGRAM_CHAT_ID")
        return {
            "configured": len(missing) == 0,
            "missing": missing,
            "token_format_ok": bool(self.telegram_token and ":" in self.telegram_token and len(self.telegram_token) > 30),
            "chat_id_format_ok": bool(self.default_chat_id and str(self.default_chat_id).lstrip("-").isdigit()),
            "allowed_chat_count": len(self.allowed_chat_ids),
            "polling_ready": bool(self.telegram_token and self.allowed_chat_ids),
            "last_error": self.last_error,
        }

    def is_chat_allowed(self, chat_id) -> bool:
        if not self.allowed_chat_ids:
            return False
        return str(chat_id) in self.allowed_chat_ids

    async def send_telegram_alert(self, message: str, chat_id: str = None, reply_markup: dict = None):
        target_chat_id = chat_id or self.default_chat_id
        api_url = self._telegram_url("sendMessage")
        if not api_url or not target_chat_id:
            safe_msg = message.encode("ascii", "ignore").decode("ascii")
            logging.info("Telegram alert skipped (Token/ChatID missing): %s", safe_msg)
            self._set_missing_target_error()
            return False

        payload = {
            "chat_id": target_chat_id,
            "text": self._alert_text(message),
            "parse_mode": "Markdown",
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        try:
            async with self._make_async_client() as client:
                response = await client.post(api_url, json=payload, timeout=5)
            if response.status_code == 200:
                self.last_error = None
                return True
            self.last_error = self._extract_response_error(response)
            logging.error(
                "Telegram notification failed: status=%s error_code=%s description=%s",
                self.last_error["status_code"],
                self.last_error["error_code"],
                self.last_error["description"],
            )
            return False
        except Exception as e:
            self.last_error = {"reason": "exception", "description": str(e)}
            logging.error("Telegram notification error: %s", e)
            return False

    async def send_telegram_message(self, chat_id: str, message: str, reply_markup: dict = None):
        api_url = self._telegram_url("sendMessage")
        if not api_url or not chat_id:
            self._set_missing_target_error()
            return False

        payload = self._build_message_payload(chat_id, message, reply_markup=reply_markup)

        try:
            async with self._make_async_client() as client:
                response = await client.post(api_url, json=payload, timeout=8)
            if response.status_code == 200:
                self.last_error = None
                return True
            self.last_error = self._extract_response_error(response)
            logging.error(
                "Telegram message failed: status=%s error_code=%s description=%s",
                self.last_error["status_code"],
                self.last_error["error_code"],
                self.last_error["description"],
            )
            return False
        except Exception as e:
            self.last_error = {"reason": "exception", "description": str(e)}
            logging.error("Telegram message error: %s", e)
            return False

    async def answer_callback_query(self, callback_query_id: str, text: str = ""):
        api_url = self._telegram_url("answerCallbackQuery")
        if not api_url:
            return False
        try:
            async with self._make_async_client() as client:
                response = await client.post(
                    api_url,
                    json={"callback_query_id": callback_query_id, "text": text[:180]},
                    timeout=5,
                )
            if response.status_code == 200:
                self.last_error = None
                return True
            self.last_error = self._extract_response_error(response)
            return False
        except Exception as e:
            self.last_error = {"reason": "exception", "description": str(e)}
            logging.error("Telegram callback answer error: %s", e)
            return False

    async def delete_webhook(self):
        api_url = self._telegram_url("deleteWebhook")
        if not api_url:
            return False
        try:
            async with self._make_async_client() as client:
                response = await client.post(api_url, json={"drop_pending_updates": False}, timeout=8)
            if response.status_code == 200:
                self.last_error = None
                return True
            self.last_error = self._extract_response_error(response)
            return False
        except Exception as e:
            self.last_error = {"reason": "exception", "description": str(e)}
            logging.error("Telegram deleteWebhook error: %s", e)
            return False

    async def get_updates(self, timeout: int = 20, limit: int = 20):
        api_url = self._telegram_url("getUpdates")
        if not api_url:
            self._set_missing_target_error("missing_token")
            return []

        params = {"timeout": timeout, "limit": limit}
        if self.last_update_id is not None:
            params["offset"] = self.last_update_id + 1

        try:
            async with self._make_async_client(timeout=timeout + 8) as client:
                response = await client.get(api_url, params=params)
            if response.status_code != 200:
                self.last_error = self._extract_response_error(response)
                return []

            data = response.json()
            updates = data.get("result", [])
            for update in updates:
                update_id = update.get("update_id")
                if isinstance(update_id, int):
                    self.last_update_id = update_id
            self.last_error = None
            return updates
        except Exception as e:
            self.last_error = {"reason": "exception", "description": str(e)}
            logging.error("Telegram getUpdates error: %s", e)
            return []

    async def broadcast(self, message: str, image_url: str = None):
        return await self.send_telegram_alert(message)

    async def notify_paper_trade_opened(self, symbol: str, side: str, price: float, confidence: float, trade_id: str):
        arrow = "UP" if side == "BUY" else "DOWN"
        msg = (
            f"{arrow} *Paper Trade Opened*\n"
            f"`{symbol}` {side} @ {price:,.4f}\n"
            f"Confidence: {confidence:.0%} | ID: `{trade_id[:8]}`"
        )
        return await self.send_telegram_alert(msg)

    async def notify_paper_trade_closed(
        self,
        symbol: str,
        outcome: str,
        close_reason: str,
        exit_price: float = 0.0,
        pnl_usd: float = None,
    ):
        icon = "OK" if outcome == "WIN" else "FAIL"
        lines = [f"{icon} *Paper Trade Closed*", f"`{symbol}` -> {outcome}"]
        if exit_price:
            lines.append(f"Exit: {exit_price:,.4f}")
        if pnl_usd is not None:
            lines.append(f"PnL: ${pnl_usd:+.2f}")
        lines.append(f"Reason: {close_reason}")
        return await self.send_telegram_alert("\n".join(lines))

    async def notify_whale(self, data: dict):
        symbol = data.get("symbol", "UNKNOWN")
        qty = float(data.get("quantity", 0))
        price = float(data.get("price", 0))
        msg = (
            f"WHALE INBOUND\n"
            f"Symbol: {symbol}\n"
            f"Amount: {qty:.4f}\n"
            f"Price: ${price:,.2f}\n"
            f"Value: ${qty * price:,.2f}"
        )
        return await self.broadcast(msg)

    async def notify_risk(self, detail: str):
        msg = f"RISK ALERT\n{detail}"
        return await self.broadcast(msg)

    async def notify_trade_draft(self, symbol: str, side: str, draft_id: str, price: float = 0):
        msg = (
            f"TV Alert -> Trade Draft Created\n"
            f"Symbol: {symbol} | Side: {side}\n"
            f"Price: {price}\n"
            f"Draft ID: {draft_id}\n"
            f"Confirm in chat: 'confirm {draft_id}'"
        )
        return await self.broadcast(msg)

    async def notify_alert_triggered(self, symbol: str, condition: str, current_val: str):
        msg = (
            f"Alert Triggered!\n"
            f"Symbol: {symbol}\n"
            f"Condition: {condition}\n"
            f"Current Value: {current_val}"
        )
        return await self.broadcast(msg)

    async def notify_market_opened(self, market_name: str):
        msg = (
            f"*MARKET OPENED*\n"
            f"The {market_name} market is now open for trading!\n"
            f"Volatility and institutional volume are expected to rise. Trade with caution."
        )
        return await self.broadcast(msg)

    async def notify_market_closed(self, market_name: str, reason: str = "Regular Close"):
        msg = (
            f"*MARKET CLOSED*\n"
            f"The {market_name} market is now closed. ({reason})\n"
            f"Stay mindful of widening spreads and weekend gaps."
        )
        return await self.broadcast(msg)

    async def notify_system_startup(self):
        msg = (
            "*System Online*\n"
            "CryptoStream AI Backend is up and running. All monitoring systems and market tracking are active."
        )
        return await self.broadcast(msg)
