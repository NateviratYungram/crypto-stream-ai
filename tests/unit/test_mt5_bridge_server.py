import importlib
import io
import json
from datetime import datetime
from types import SimpleNamespace


def _load_module():
    return importlib.import_module("intelligence.mt5_bridge_server")


def _make_handler(module, path="/health", headers=None, body=b""):
    handler = module.Handler.__new__(module.Handler)
    handler.path = path
    handler.headers = headers or {}
    handler.rfile = io.BytesIO(body)
    handler.wfile = io.BytesIO()
    handler.response_status = None
    handler.response_headers = []
    handler.client_address = ("127.0.0.1", 12345)
    handler.command = "GET"
    handler.request_version = "HTTP/1.1"
    handler.requestline = ""
    handler.server = None
    handler.send_response = lambda status: setattr(handler, "response_status", status)
    handler.send_header = lambda key, value: handler.response_headers.append((key, value))
    handler.end_headers = lambda: None
    handler.address_string = lambda: "127.0.0.1"
    return handler


def test_default_host_uses_all_interfaces_for_docker_bridge(monkeypatch):
    monkeypatch.delenv("MT5_BRIDGE_HOST", raising=False)
    monkeypatch.setenv("MT5_BRIDGE_URL", "http://host.docker.internal:8765")

    module = _load_module()
    module = importlib.reload(module)

    assert module.HOST == "0.0.0.0"


def test_default_host_stays_local_without_docker_bridge(monkeypatch):
    monkeypatch.delenv("MT5_BRIDGE_HOST", raising=False)
    monkeypatch.setenv("MT5_BRIDGE_URL", "http://localhost:8765")

    module = _load_module()
    module = importlib.reload(module)

    assert module.HOST == "127.0.0.1"


def test_default_host_prefers_explicit_host(monkeypatch):
    monkeypatch.setenv("MT5_BRIDGE_HOST", "192.168.1.10")
    monkeypatch.setenv("MT5_BRIDGE_URL", "http://host.docker.internal:8765")

    module = _load_module()
    module = importlib.reload(module)

    assert module.HOST == "192.168.1.10"


def test_asdict_and_json_safe_helpers():
    module = _load_module()

    class FakeAsDict:
        def _asdict(self):
            return {"value": 1}

    assert module._asdict(None) == {}
    assert module._asdict({"a": 1}) == {"a": 1}
    assert module._asdict(FakeAsDict()) == {"value": 1}
    assert module._asdict([("k", 2)]) == {"k": 2}

    payload = module._json_safe(
        {
            "when": datetime(2026, 5, 26, 12, 0, 0),
            "items": (1, {"nested": True}),
            "other": object(),
        }
    )

    assert payload["when"] == "2026-05-26T12:00:00"
    assert payload["items"] == [1, {"nested": True}]
    assert isinstance(payload["other"], str)


def test_initialize_returns_import_error_when_mt5_missing(monkeypatch):
    module = _load_module()
    monkeypatch.setattr(module, "mt5", None)
    monkeypatch.setattr(module, "MT5_IMPORT_ERROR", "missing package")

    ok, error = module.initialize()

    assert ok is False
    assert "missing package" in error


def test_initialize_builds_kwargs_and_succeeds(monkeypatch):
    module = _load_module()
    captured = {}
    fake_mt5 = SimpleNamespace(
        initialize=lambda **kwargs: captured.setdefault("kwargs", kwargs) or True,
        account_info=lambda: {"login": 1},
    )
    monkeypatch.setattr(module, "mt5", fake_mt5)
    monkeypatch.setattr(module, "TERMINAL_PATH", "terminal.exe")
    monkeypatch.setattr(module, "LOGIN", "123")
    monkeypatch.setattr(module, "PASSWORD", "secret")
    monkeypatch.setattr(module, "SERVER", "Broker-Demo")

    ok, error = module.initialize()

    assert ok is True
    assert error is None
    assert captured["kwargs"] == {
        "path": "terminal.exe",
        "login": 123,
        "password": "secret",
        "server": "Broker-Demo",
    }


def test_initialize_returns_error_on_init_failure(monkeypatch):
    module = _load_module()
    fake_mt5 = SimpleNamespace(
        initialize=lambda **kwargs: False,
        last_error=lambda: (500, "init failed"),
    )
    monkeypatch.setattr(module, "mt5", fake_mt5)
    monkeypatch.setattr(module, "TERMINAL_PATH", "")
    monkeypatch.setattr(module, "LOGIN", "")
    monkeypatch.setattr(module, "PASSWORD", "")
    monkeypatch.setattr(module, "SERVER", "")

    ok, error = module.initialize()

    assert ok is False
    assert "init failed" in error


def test_initialize_returns_error_when_account_missing(monkeypatch):
    module = _load_module()
    fake_mt5 = SimpleNamespace(
        initialize=lambda **kwargs: True,
        account_info=lambda: None,
        last_error=lambda: (404, "no account"),
    )
    monkeypatch.setattr(module, "mt5", fake_mt5)

    ok, error = module.initialize()

    assert ok is False
    assert "account unavailable" in error


def test_account_and_positions_return_initialize_error(monkeypatch):
    module = _load_module()
    monkeypatch.setattr(module, "initialize", lambda: (False, "down"))

    assert module.account() == {"error": "down"}
    assert module.positions() == {"error": "down"}


def test_account_and_positions_success(monkeypatch):
    module = _load_module()

    class FakeRow:
        def __init__(self, payload):
            self.payload = payload

        def _asdict(self):
            return self.payload

    fake_mt5 = SimpleNamespace(
        account_info=lambda: {"login": 42},
        positions_get=lambda: [FakeRow({"ticket": 1}), FakeRow({"ticket": 2})],
    )
    monkeypatch.setattr(module, "initialize", lambda: (True, None))
    monkeypatch.setattr(module, "mt5", fake_mt5)

    assert module.account() == {"login": 42}
    assert module.positions() == {"positions": [{"ticket": 1}, {"ticket": 2}]}


def test_quote_errors_and_success(monkeypatch):
    module = _load_module()
    monkeypatch.setattr(module, "initialize", lambda: (False, "down"))
    assert module.quote("GOLD") == {"error": "down"}

    fake_mt5 = SimpleNamespace(
        symbol_select=lambda symbol, visible: False,
        last_error=lambda: (1, "bad symbol"),
    )
    monkeypatch.setattr(module, "initialize", lambda: (True, None))
    monkeypatch.setattr(module, "mt5", fake_mt5)
    assert module.quote("GOLD")["error"] == "Failed to select symbol GOLD"

    fake_mt5 = SimpleNamespace(
        symbol_select=lambda symbol, visible: True,
        symbol_info=lambda symbol: None,
        symbol_info_tick=lambda symbol: None,
        last_error=lambda: (2, "no quote"),
    )
    monkeypatch.setattr(module, "mt5", fake_mt5)
    assert module.quote("GOLD")["error"] == "Quote unavailable for GOLD"

    fake_info = SimpleNamespace(
        digits=2,
        point=0.01,
        volume_min=0.01,
        volume_max=1.0,
        volume_step=0.01,
        trade_mode=1,
        trade_contract_size=100,
    )
    fake_tick = SimpleNamespace(bid=100.0, ask=101.0, last=100.5, time=123456)
    fake_mt5 = SimpleNamespace(
        symbol_select=lambda symbol, visible: True,
        symbol_info=lambda symbol: fake_info,
        symbol_info_tick=lambda symbol: fake_tick,
        last_error=lambda: (0, ""),
    )
    monkeypatch.setattr(module, "mt5", fake_mt5)

    result = module.quote("GOLD")

    assert result["spread"] == 1.0
    assert result["trade_contract_size"] == 100


def test_rates_errors_and_success(monkeypatch):
    module = _load_module()
    monkeypatch.setattr(module, "initialize", lambda: (False, "down"))
    assert module.rates("GOLD", "15m", 10) == {"error": "down"}

    fake_mt5 = SimpleNamespace(
        TIMEFRAME_M1=1,
        TIMEFRAME_M5=5,
        TIMEFRAME_M15=15,
        TIMEFRAME_M30=30,
        TIMEFRAME_H1=60,
        TIMEFRAME_H4=240,
        TIMEFRAME_D1=1440,
        symbol_select=lambda symbol, visible: False,
        last_error=lambda: (1, "bad symbol"),
    )
    monkeypatch.setattr(module, "initialize", lambda: (True, None))
    monkeypatch.setattr(module, "mt5", fake_mt5)
    assert module.rates("GOLD", "15m", 10)["error"] == "Failed to select symbol GOLD"

    fake_mt5.symbol_select = lambda symbol, visible: True
    fake_mt5.copy_rates_from_pos = lambda symbol, timeframe, start, count: None
    assert module.rates("GOLD", "15m", 10)["error"] == "Failed to fetch rates for GOLD"

    fake_mt5.copy_rates_from_pos = lambda symbol, timeframe, start, count: [
        {"time": 1700000000, "open": 1, "high": 2, "low": 0.5, "close": 1.5, "tick_volume": 10}
    ]
    result = module.rates("GOLD", "1h", 1)

    assert result["symbol"] == "GOLD"
    assert result["timeframe"] == "1h"
    assert result["rates"][0]["Close"] == 1.5


def test_trade_enforces_live_trading_and_validation(monkeypatch):
    module = _load_module()
    monkeypatch.setattr(module, "LIVE_TRADING_ENABLED", False)
    assert "disabled" in module.trade({})["error"]

    monkeypatch.setattr(module, "LIVE_TRADING_ENABLED", True)
    monkeypatch.setattr(module, "initialize", lambda: (False, "down"))
    assert module.trade({}) == {"error": "down"}

    monkeypatch.setattr(module, "initialize", lambda: (True, None))
    assert module.trade({"action": "HOLD", "volume": 1}) == {"error": "action must be BUY or SELL"}
    assert module.trade({"action": "BUY", "volume": 0}) == {"error": "volume must be greater than 0"}


def test_trade_handles_broker_limits_and_success(monkeypatch):
    module = _load_module()
    monkeypatch.setattr(module, "LIVE_TRADING_ENABLED", True)
    monkeypatch.setattr(module, "REQUIRE_STOP_LOSS", True)
    monkeypatch.setattr(module, "MAX_LIVE_VOLUME", 1.0)
    monkeypatch.setattr(module, "initialize", lambda: (True, None))

    state = {"symbol_select": True, "tick": SimpleNamespace(ask=101.0, bid=99.0)}
    fake_info = SimpleNamespace(volume_min=0.1, volume_max=2.0, volume_step=0.1)
    fake_mt5 = SimpleNamespace(
        symbol_select=lambda symbol, visible: state["symbol_select"],
        symbol_info=lambda symbol: fake_info,
        symbol_info_tick=lambda symbol: state["tick"],
        order_send=lambda request: SimpleNamespace(
            retcode=999,
            order=11,
            deal=22,
            price=request["price"],
            volume=request["volume"],
            comment="ok",
            _asdict=lambda: {"retcode": 999},
        ),
        last_error=lambda: (0, ""),
        ORDER_TYPE_BUY=0,
        ORDER_TYPE_SELL=1,
        ORDER_FILLING_FOK=10,
        ORDER_FILLING_IOC=11,
        ORDER_FILLING_RETURN=12,
        TRADE_ACTION_DEAL=20,
        ORDER_TIME_GTC=30,
        TRADE_RETCODE_DONE=999,
    )
    monkeypatch.setattr(module, "mt5", fake_mt5)

    assert "exceeds" in module.trade({"symbol": "gold", "action": "BUY", "volume": 2, "sl": 1})["error"]
    assert "stop loss" in module.trade({"symbol": "gold", "action": "BUY", "volume": 0.5, "sl": 0})["error"]

    state["symbol_select"] = False
    assert module.trade({"symbol": "gold", "action": "BUY", "volume": 0.5, "sl": 1})["error"] == "Failed to select symbol GOLD"

    state["symbol_select"] = True
    fake_info.volume_min = 0.6
    assert "below broker minimum" in module.trade({"symbol": "gold", "action": "BUY", "volume": 0.5, "sl": 1})["error"]

    fake_info.volume_min = 0.1
    fake_info.volume_max = 0.4
    assert "above broker maximum" in module.trade({"symbol": "gold", "action": "BUY", "volume": 0.5, "sl": 1})["error"]

    fake_info.volume_max = 2.0
    fake_info.volume_step = 0.25
    assert "follow broker step" in module.trade({"symbol": "gold", "action": "BUY", "volume": 0.3, "sl": 1})["error"]

    fake_info.volume_step = 0.1
    state["tick"] = None
    assert module.trade({"symbol": "gold", "action": "BUY", "volume": 0.5, "sl": 1})["error"] == "Tick unavailable for GOLD"

    state["tick"] = SimpleNamespace(ask=101.0, bid=99.0)
    result = module.trade({"symbol": "gold", "action": "BUY", "volume": 0.5, "sl": 1, "comment": "A" * 40})

    assert result["status"] == "SUCCESS"
    assert result["request"]["comment"] == "A" * 31


def test_trade_handles_symbol_info_missing_order_send_none_and_failed_result(monkeypatch):
    module = _load_module()
    monkeypatch.setattr(module, "LIVE_TRADING_ENABLED", True)
    monkeypatch.setattr(module, "REQUIRE_STOP_LOSS", False)
    monkeypatch.setattr(module, "MAX_LIVE_VOLUME", 1.0)
    monkeypatch.setattr(module, "initialize", lambda: (True, None))

    state = {
        "info": None,
        "tick": SimpleNamespace(ask=101.0, bid=99.0),
        "order_result": None,
    }

    fake_mt5 = SimpleNamespace(
        symbol_select=lambda symbol, visible: True,
        symbol_info=lambda symbol: state["info"],
        symbol_info_tick=lambda symbol: state["tick"],
        order_send=lambda request: state["order_result"],
        last_error=lambda: (7, "bridge issue"),
        ORDER_TYPE_BUY=0,
        ORDER_TYPE_SELL=1,
        ORDER_FILLING_FOK=10,
        ORDER_FILLING_IOC=11,
        ORDER_FILLING_RETURN=12,
        TRADE_ACTION_DEAL=20,
        ORDER_TIME_GTC=30,
        TRADE_RETCODE_DONE=999,
    )
    monkeypatch.setattr(module, "mt5", fake_mt5)

    assert module.trade({"symbol": "gold", "action": "BUY", "volume": 0.5})["error"] == "Symbol info unavailable for GOLD"

    state["info"] = SimpleNamespace(volume_min=0.0, volume_max=0.0, volume_step=0.0)
    none_result = module.trade({"symbol": "gold", "action": "BUY", "volume": 0.5, "price": 100.0})
    assert none_result["status"] == "FAILED"
    assert none_result["error"] == "order_send returned None"

    state["order_result"] = SimpleNamespace(
        retcode=321,
        comment="rejected",
        _asdict=lambda: {"retcode": 321, "comment": "rejected"},
    )
    failed_result = module.trade({"symbol": "gold", "action": "BUY", "volume": 0.5, "price": 100.0})
    assert failed_result["status"] == "FAILED"
    assert failed_result["retcode"] == 321


def test_close_and_modify_position_paths(monkeypatch):
    module = _load_module()
    monkeypatch.setattr(module, "LIVE_TRADING_ENABLED", False)
    assert "disabled" in module.close_position(1)["error"]

    monkeypatch.setattr(module, "LIVE_TRADING_ENABLED", True)
    monkeypatch.setattr(module, "initialize", lambda: (False, "down"))
    assert module.close_position(1) == {"error": "down"}
    assert module.modify_position(1, 1.0) == {"error": "down"}

    monkeypatch.setattr(module, "initialize", lambda: (True, None))
    fake_mt5 = SimpleNamespace(
        positions_get=lambda ticket: [],
        last_error=lambda: (0, ""),
        ORDER_TYPE_BUY=0,
        ORDER_TYPE_SELL=1,
        TRADE_ACTION_DEAL=20,
        ORDER_TIME_GTC=30,
        ORDER_FILLING_IOC=11,
        TRADE_ACTION_SLTP=21,
        TRADE_RETCODE_DONE=999,
    )
    monkeypatch.setattr(module, "mt5", fake_mt5)
    assert module.close_position(1) == {"error": "Position 1 not found"}
    assert module.modify_position(1, 1.0) == {"error": "Position 1 not found"}

    fake_position = SimpleNamespace(symbol="GOLD", type=0, volume=0.5, tp=4.0)
    fake_mt5.positions_get = lambda ticket: [fake_position]
    fake_mt5.symbol_info_tick = lambda symbol: SimpleNamespace(bid=99.0, ask=101.0)
    fake_mt5.order_send = lambda request: SimpleNamespace(retcode=999, deal=77, _asdict=lambda: {"retcode": 999})

    close_result = module.close_position(1)
    modify_result = module.modify_position(1, 2.0)

    assert close_result["status"] == "SUCCESS"
    assert modify_result["status"] == "SUCCESS"


def test_close_and_modify_position_failed_results(monkeypatch):
    module = _load_module()
    monkeypatch.setattr(module, "LIVE_TRADING_ENABLED", True)
    monkeypatch.setattr(module, "initialize", lambda: (True, None))

    fake_position = SimpleNamespace(symbol="GOLD", type=0, volume=0.5, tp=4.0)
    state = {"order_result": None}
    fake_mt5 = SimpleNamespace(
        positions_get=lambda ticket: [fake_position],
        symbol_info_tick=lambda symbol: SimpleNamespace(bid=99.0, ask=101.0),
        order_send=lambda request: state["order_result"],
        last_error=lambda: (9, "bad send"),
        ORDER_TYPE_BUY=0,
        ORDER_TYPE_SELL=1,
        TRADE_ACTION_DEAL=20,
        ORDER_TIME_GTC=30,
        ORDER_FILLING_IOC=11,
        TRADE_ACTION_SLTP=21,
        TRADE_RETCODE_DONE=999,
    )
    monkeypatch.setattr(module, "mt5", fake_mt5)

    assert module.close_position(1)["status"] == "FAILED"
    assert module.modify_position(1, 1.0)["status"] == "FAILED"

    state["order_result"] = SimpleNamespace(retcode=123, _asdict=lambda: {"retcode": 123})
    assert module.close_position(1)["status"] == "FAILED"
    assert module.modify_position(1, 1.0)["status"] == "FAILED"


def test_handler_auth_json_and_endpoints(monkeypatch):
    module = _load_module()
    monkeypatch.setattr(module, "API_KEY", "secret")

    unauthorized = _make_handler(module, "/health", headers={})
    unauthorized.do_GET()
    assert unauthorized.response_status == 401

    monkeypatch.setattr(module, "API_KEY", "")
    monkeypatch.setattr(module, "initialize", lambda: (True, None))
    monkeypatch.setattr(module, "LIVE_TRADING_ENABLED", True)
    monkeypatch.setattr(module, "REQUIRE_STOP_LOSS", True)
    monkeypatch.setattr(module, "MAX_LIVE_VOLUME", 0.5)
    monkeypatch.setattr(module, "account", lambda: {"login": 1})
    monkeypatch.setattr(module, "positions", lambda: {"positions": []})
    monkeypatch.setattr(module, "quote", lambda symbol: {"symbol": symbol})
    monkeypatch.setattr(module, "rates", lambda symbol, timeframe, count: {"symbol": symbol, "rates": []})

    health = _make_handler(module, "/health")
    health.do_GET()
    payload = json.loads(health.wfile.getvalue().decode("utf-8"))
    assert health.response_status == 200
    assert payload["connected"] is True

    account = _make_handler(module, "/account")
    account.do_GET()
    assert account.response_status == 200

    positions = _make_handler(module, "/positions")
    positions.do_GET()
    assert positions.response_status == 200

    quote = _make_handler(module, "/quote?symbol=btcusd")
    quote.do_GET()
    quote_payload = json.loads(quote.wfile.getvalue().decode("utf-8"))
    assert quote_payload["symbol"] == "BTCUSD"

    missing = _make_handler(module, "/missing")
    missing.do_GET()
    assert missing.response_status == 404


def test_handler_get_returns_error_status_for_positions_and_rates(monkeypatch):
    module = _load_module()
    monkeypatch.setattr(module, "API_KEY", "")
    monkeypatch.setattr(module, "positions", lambda: {"error": "positions down"})
    monkeypatch.setattr(module, "rates", lambda symbol, timeframe, count: {"error": "rates down"})

    positions = _make_handler(module, "/positions")
    positions.do_GET()
    assert positions.response_status == 400

    rates = _make_handler(module, "/rates?symbol=gold&timeframe=1h&count=5")
    rates.do_GET()
    assert rates.response_status == 400


def test_handler_post_routes_and_errors(monkeypatch):
    module = _load_module()
    monkeypatch.setattr(module, "API_KEY", "")
    monkeypatch.setattr(module, "trade", lambda payload: {"status": "SUCCESS"})
    monkeypatch.setattr(module, "close_position", lambda ticket: {"status": "FAILED"})
    monkeypatch.setattr(module, "modify_position", lambda ticket, sl, tp: {"ticket": ticket, "sl": sl, "tp": tp})

    trade_handler = _make_handler(
        module,
        "/trade",
        headers={"Content-Length": "18"},
        body=b'{"symbol":"GOLD"}',
    )
    trade_handler.do_POST()
    assert trade_handler.response_status == 200

    close_handler = _make_handler(
        module,
        "/close",
        headers={"Content-Length": "12"},
        body=b'{"ticket":1}',
    )
    close_handler.do_POST()
    assert close_handler.response_status == 400

    modify_handler = _make_handler(
        module,
        "/modify",
        headers={"Content-Length": "28"},
        body=b'{"ticket":1,"sl":2,"tp":3}',
    )
    modify_handler.do_POST()
    assert modify_handler.response_status == 200

    not_found = _make_handler(module, "/unknown", headers={"Content-Length": "2"}, body=b"{}")
    not_found.do_POST()
    assert not_found.response_status == 404

    broken = _make_handler(module, "/trade", headers={"Content-Length": "7"}, body=b"{oops}")
    broken.do_POST()
    assert broken.response_status == 500


def test_handler_post_unauthorized_and_read_json_defaults(monkeypatch):
    module = _load_module()
    monkeypatch.setattr(module, "API_KEY", "secret")

    unauthorized = _make_handler(module, "/trade", headers={"Content-Length": "0"}, body=b"")
    unauthorized.do_POST()
    assert unauthorized.response_status == 401

    reader = _make_handler(module, "/trade", headers={"Content-Length": "0"}, body=b"")
    assert reader._read_json() == {}


def test_handler_log_message_and_main(monkeypatch):
    module = _load_module()
    printed = []
    served = []

    handler = _make_handler(module)
    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: printed.append(" ".join(str(arg) for arg in args)))
    handler.log_message("%s %s", "hello", "world")

    class FakeServer:
        def __init__(self, addr, handler_cls):
            served.append((addr, handler_cls))

        def serve_forever(self):
            served.append("serve_forever")

    monkeypatch.setattr(module, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr(module, "HOST", "127.0.0.1")
    monkeypatch.setattr(module, "PORT", 8765)
    monkeypatch.setattr(module, "LIVE_TRADING_ENABLED", True)
    monkeypatch.setattr(module, "mt5", object())

    module.main()

    assert any("127.0.0.1 - hello world" in line for line in printed)
    assert any("CryptoStream MT5 bridge listening on http://127.0.0.1:8765" in line for line in printed)
    assert served[0][0] == ("127.0.0.1", 8765)
    assert served[-1] == "serve_forever"
