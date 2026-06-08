"""Windows-host MT5 bridge for Docker-hosted CryptoStream AI.

Run this on the Windows machine where MetaTrader 5 is installed and logged in.
The Linux Docker container calls this bridge through host.docker.internal.
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

try:
    import MetaTrader5 as mt5
except Exception as exc:  # pragma: no cover - depends on Windows host package
    mt5 = None
    MT5_IMPORT_ERROR = str(exc)
else:
    MT5_IMPORT_ERROR = ""


def _default_host() -> str:
    explicit = os.getenv("MT5_BRIDGE_HOST", "").strip()
    if explicit:
        return explicit
    bridge_url = os.getenv("MT5_BRIDGE_URL", "").strip().lower()
    if "host.docker.internal" in bridge_url:
        return "0.0.0.0"
    return "127.0.0.1"


HOST = _default_host()
PORT = int(os.getenv("MT5_BRIDGE_PORT", "8765"))
API_KEY = os.getenv("MT5_BRIDGE_API_KEY", "")
TERMINAL_PATH = os.getenv("MT5_TERMINAL_PATH", "")
LOGIN = os.getenv("MT5_LOGIN", "")
PASSWORD = os.getenv("MT5_PASSWORD", "")
SERVER = os.getenv("MT5_SERVER", "")
LIVE_TRADING_ENABLED = os.getenv("MT5_BRIDGE_ENABLE_LIVE_TRADING", "0") == "1"
REQUIRE_STOP_LOSS = os.getenv("MT5_BRIDGE_REQUIRE_SL", "1").strip().lower() not in {"0", "false", "no"}
MAX_LIVE_VOLUME = float(os.getenv("MT5_BRIDGE_MAX_LIVE_VOLUME", os.getenv("MT5_MAX_LIVE_VOLUME", "0.10")))


def _asdict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "_asdict"):
        return value._asdict()
    if isinstance(value, dict):
        return value
    return dict(value)


def _json_safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return str(value)


def initialize() -> tuple[bool, str | None]:
    if mt5 is None:
        return False, f"MetaTrader5 package is not installed: {MT5_IMPORT_ERROR}"

    kwargs: dict[str, Any] = {}
    if TERMINAL_PATH:
        kwargs["path"] = TERMINAL_PATH
    if LOGIN:
        kwargs["login"] = int(LOGIN)
    if PASSWORD:
        kwargs["password"] = PASSWORD
    if SERVER:
        kwargs["server"] = SERVER

    ok = mt5.initialize(**kwargs)
    if not ok:
        return False, f"MT5 initialize failed: {mt5.last_error()}"
    if mt5.account_info() is None:
        return False, f"MT5 account unavailable: {mt5.last_error()}"
    return True, None


def account() -> dict[str, Any]:
    ok, error = initialize()
    if not ok:
        return {"error": error}
    return _asdict(mt5.account_info())


def positions() -> dict[str, Any]:
    ok, error = initialize()
    if not ok:
        return {"error": error}
    rows = mt5.positions_get()
    return {"positions": [_asdict(row) for row in rows or []]}


def quote(symbol: str) -> dict[str, Any]:
    ok, error = initialize()
    if not ok:
        return {"error": error}
    if not mt5.symbol_select(symbol, True):
        return {"error": f"Failed to select symbol {symbol}", "last_error": mt5.last_error()}
    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if info is None or tick is None:
        return {"error": f"Quote unavailable for {symbol}", "last_error": mt5.last_error()}
    return {
        "symbol": symbol,
        "bid": tick.bid,
        "ask": tick.ask,
        "last": tick.last,
        "spread": (tick.ask - tick.bid) if tick.ask and tick.bid else 0.0,
        "time": tick.time,
        "digits": info.digits,
        "point": info.point,
        "volume_min": info.volume_min,
        "volume_max": info.volume_max,
        "volume_step": info.volume_step,
        "trade_mode": info.trade_mode,
        "trade_contract_size": info.trade_contract_size,
    }


def rates(symbol: str, timeframe: str, count: int) -> dict[str, Any]:
    ok, error = initialize()
    if not ok:
        return {"error": error}
    tf_map = {
        "1m": mt5.TIMEFRAME_M1,
        "5m": mt5.TIMEFRAME_M5,
        "15m": mt5.TIMEFRAME_M15,
        "30m": mt5.TIMEFRAME_M30,
        "1h": mt5.TIMEFRAME_H1,
        "4h": mt5.TIMEFRAME_H4,
        "1d": mt5.TIMEFRAME_D1,
    }
    if not mt5.symbol_select(symbol, True):
        return {"error": f"Failed to select symbol {symbol}", "last_error": mt5.last_error()}
    data = mt5.copy_rates_from_pos(symbol, tf_map.get(timeframe, mt5.TIMEFRAME_M15), 0, int(count))
    if data is None:
        return {"error": f"Failed to fetch rates for {symbol}", "last_error": mt5.last_error()}
    rows = []
    for row in data:
        rows.append({
            "Datetime": datetime.fromtimestamp(int(row["time"])).isoformat(),
            "Open": float(row["open"]),
            "High": float(row["high"]),
            "Low": float(row["low"]),
            "Close": float(row["close"]),
            "Volume": float(row["tick_volume"]),
        })
    return {"symbol": symbol, "timeframe": timeframe, "rates": rows}


def trade(payload: dict[str, Any]) -> dict[str, Any]:
    if not LIVE_TRADING_ENABLED:
        return {"error": "Live trading is disabled. Set MT5_BRIDGE_ENABLE_LIVE_TRADING=1 on the bridge host."}
    ok, error = initialize()
    if not ok:
        return {"error": error}

    symbol = str(payload.get("symbol", "")).upper().strip()
    action = str(payload.get("action", payload.get("side", ""))).upper().strip()
    volume = float(payload.get("volume") or 0)
    if action not in {"BUY", "SELL"}:
        return {"error": "action must be BUY or SELL"}
    if not math.isfinite(volume) or volume <= 0:
        return {"error": "volume must be greater than 0"}
    if MAX_LIVE_VOLUME > 0 and volume > MAX_LIVE_VOLUME:
        return {"error": f"volume exceeds MT5_BRIDGE_MAX_LIVE_VOLUME={MAX_LIVE_VOLUME:g}"}
    sl_value = float(payload.get("sl") or 0.0)
    tp_value = float(payload.get("tp") or 0.0)
    if REQUIRE_STOP_LOSS and sl_value <= 0:
        return {"error": "stop loss is required for live trading"}
    if not mt5.symbol_select(symbol, True):
        return {"error": f"Failed to select symbol {symbol}", "last_error": mt5.last_error()}

    info = mt5.symbol_info(symbol)
    if info is None:
        return {"error": f"Symbol info unavailable for {symbol}", "last_error": mt5.last_error()}
    if getattr(info, "volume_min", 0) and volume < info.volume_min:
        return {"error": f"volume below broker minimum {info.volume_min}"}
    if getattr(info, "volume_max", 0) and volume > info.volume_max:
        return {"error": f"volume above broker maximum {info.volume_max}"}
    step = float(getattr(info, "volume_step", 0) or 0)
    if step > 0:
        steps = round(volume / step)
        if abs(volume - (steps * step)) > 1e-9:
            return {"error": f"volume must follow broker step {step}"}

    order_type = mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return {"error": f"Tick unavailable for {symbol}", "last_error": mt5.last_error()}
    price = payload.get("price")
    if not price:
        price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid

    filling_map = {
        "FOK": mt5.ORDER_FILLING_FOK,
        "IOC": mt5.ORDER_FILLING_IOC,
        "RETURN": mt5.ORDER_FILLING_RETURN,
    }
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "price": float(price),
        "sl": sl_value,
        "tp": tp_value,
        "deviation": int(payload.get("deviation") or 20),
        "magic": 123456,
        "comment": str(payload.get("comment") or "CryptoStream AI Trade")[:31],
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling_map.get(str(payload.get("filling_policy") or "IOC").upper(), mt5.ORDER_FILLING_IOC),
    }
    result = mt5.order_send(request)
    if result is None:
        return {"status": "FAILED", "error": "order_send returned None", "last_error": mt5.last_error()}
    result_dict = _asdict(result)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        return {"status": "FAILED", "retcode": result.retcode, "comment": result.comment, "result": result_dict}
    return {
        "status": "SUCCESS",
        "order_id": result.order,
        "deal_id": result.deal,
        "price": result.price,
        "volume": result.volume,
        "comment": result.comment,
        "request": request,
        "result": result_dict,
    }


def close_position(ticket: int) -> dict[str, Any]:
    if not LIVE_TRADING_ENABLED:
        return {"error": "Live trading is disabled. Set MT5_BRIDGE_ENABLE_LIVE_TRADING=1 on the bridge host."}
    ok, error = initialize()
    if not ok:
        return {"error": error}
    position = mt5.positions_get(ticket=int(ticket))
    if not position:
        return {"error": f"Position {ticket} not found"}
    pos = position[0]
    order_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
    tick = mt5.symbol_info_tick(pos.symbol)
    price = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": pos.symbol,
        "volume": pos.volume,
        "type": order_type,
        "position": int(ticket),
        "price": price,
        "magic": 123456,
        "comment": "Close via CryptoStream AI",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        return {"status": "FAILED", "result": _asdict(result), "last_error": mt5.last_error()}
    return {"status": "SUCCESS", "deal": result.deal, "result": _asdict(result)}


def modify_position(ticket: int, sl: float, tp: float = 0.0) -> dict[str, Any]:
    ok, error = initialize()
    if not ok:
        return {"error": error}
    position = mt5.positions_get(ticket=int(ticket))
    if not position:
        return {"error": f"Position {ticket} not found"}
    pos = position[0]
    request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "symbol": pos.symbol,
        "position": int(ticket),
        "sl": float(sl),
        "tp": float(tp) if tp else float(pos.tp),
    }
    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        return {"status": "FAILED", "result": _asdict(result), "last_error": mt5.last_error()}
    return {"status": "SUCCESS", "ticket": int(ticket), "result": _asdict(result)}


class Handler(BaseHTTPRequestHandler):
    server_version = "CryptoStreamMT5Bridge/1.0"

    def _authorized(self) -> bool:
        if not API_KEY:
            return True
        return self.headers.get("X-MT5-Bridge-Key") == API_KEY

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(_json_safe(payload), ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self) -> None:
        if not self._authorized():
            self._send_json({"error": "unauthorized"}, 401)
            return
        parsed = urlparse(self.path)
        params = {key: values[-1] for key, values in parse_qs(parsed.query).items()}

        if parsed.path == "/health":
            ok, error = initialize()
            self._send_json({
                "status": "ok" if ok else "error",
                "connected": ok,
                "live_trading_enabled": LIVE_TRADING_ENABLED,
                "requires_stop_loss": REQUIRE_STOP_LOSS,
                "max_live_volume": MAX_LIVE_VOLUME,
                "error": error,
            })
        elif parsed.path == "/account":
            payload = account()
            self._send_json(payload, 400 if "error" in payload else 200)
        elif parsed.path == "/positions":
            payload = positions()
            self._send_json(payload, 400 if "error" in payload else 200)
        elif parsed.path == "/quote":
            payload = quote(str(params.get("symbol", "GOLD")).upper())
            self._send_json(payload, 400 if "error" in payload else 200)
        elif parsed.path == "/rates":
            payload = rates(str(params.get("symbol", "GOLD")).upper(), str(params.get("timeframe", "15m")), int(params.get("count", 100)))
            self._send_json(payload, 400 if "error" in payload else 200)
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        if not self._authorized():
            self._send_json({"error": "unauthorized"}, 401)
            return
        try:
            payload = self._read_json()
            if self.path == "/trade":
                result = trade(payload)
            elif self.path == "/close":
                result = close_position(int(payload.get("ticket")))
            elif self.path == "/modify":
                result = modify_position(int(payload.get("ticket")), float(payload.get("sl")), float(payload.get("tp") or 0.0))
            else:
                self._send_json({"error": "not found"}, 404)
                return
            self._send_json(result, 400 if "error" in result or result.get("status") == "FAILED" else 200)
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.address_string()} - {fmt % args}")


def main() -> None:
    print(f"CryptoStream MT5 bridge listening on http://{HOST}:{PORT}")
    print(f"MT5 package installed: {mt5 is not None}")
    print(f"Live trading enabled: {LIVE_TRADING_ENABLED}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
