import io
import sys
from types import ModuleType
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pandas as pd

from intelligence import mt5_connector


class DummyContextResponse:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._payload


def test_bridge_enabled_reflects_config(monkeypatch):
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")
    assert mt5_connector._bridge_enabled() is False

    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "http://bridge")
    assert mt5_connector._bridge_enabled() is True


def test_bridge_request_returns_config_error_without_url(monkeypatch):
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")

    result = mt5_connector._bridge_request("GET", "/health")

    assert result == {"error": "MT5 bridge is not configured"}


def test_bridge_request_success_includes_payload_and_headers(monkeypatch):
    captured = {}
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "http://bridge")
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_API_KEY", "secret")

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["data"] = req.data
        captured["headers"] = dict(req.header_items())
        captured["timeout"] = timeout
        return DummyContextResponse(b'{"status":"ok"}')

    monkeypatch.setattr(mt5_connector, "urlopen", fake_urlopen)

    result = mt5_connector._bridge_request("post", "/trade", {"symbol": "BTCUSD"})

    assert result == {"status": "ok"}
    assert captured["url"] == "http://bridge/trade"
    assert captured["method"] == "POST"
    assert b"BTCUSD" in captured["data"]
    assert captured["headers"]["X-mt5-bridge-key"] == "secret"


def test_bridge_request_handles_http_error_payload(monkeypatch):
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "http://bridge")
    error = HTTPError(
        url="http://bridge/health",
        code=503,
        msg="bad gateway",
        hdrs=None,
        fp=io.BytesIO(b'{"detail":"bridge down"}'),
    )
    monkeypatch.setattr(mt5_connector, "urlopen", lambda req, timeout: (_ for _ in ()).throw(error))

    result = mt5_connector._bridge_request("GET", "/health")

    assert result == {"error": "bridge down", "status_code": 503}


def test_bridge_request_handles_transport_errors(monkeypatch):
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "http://bridge")
    monkeypatch.setattr(
        mt5_connector,
        "urlopen",
        lambda req, timeout: (_ for _ in ()).throw(URLError("offline")),
    )

    result = mt5_connector._bridge_request("GET", "/health")

    assert "MT5 bridge unavailable" in result["error"]


def test_bridge_request_handles_generic_exception(monkeypatch):
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "http://bridge")
    monkeypatch.setattr(
        mt5_connector,
        "urlopen",
        lambda req, timeout: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    result = mt5_connector._bridge_request("GET", "/health")

    assert "MT5 bridge request failed" in result["error"]


def test_bridge_get_and_post_delegate(monkeypatch):
    calls = []

    def fake_bridge_request(method, path, payload=None):
        calls.append((method, path, payload))
        return {"ok": True}

    monkeypatch.setattr(mt5_connector, "_bridge_request", fake_bridge_request)

    get_result = mt5_connector._bridge_get("/quote", {"symbol": "XAUUSD"})
    post_result = mt5_connector._bridge_post("/trade", {"symbol": "XAUUSD"})

    assert get_result == {"ok": True}
    assert post_result == {"ok": True}
    assert calls == [
        ("GET", "/quote?symbol=XAUUSD", None),
        ("POST", "/trade", {"symbol": "XAUUSD"}),
    ]


def test_get_guard_pipeline_constructs_expected_guards(monkeypatch):
    created = {}

    class FakeMaxPositionSizeGuard:
        def __init__(self, max_equity_pct):
            created["max_equity_pct"] = max_equity_pct

    class FakeCooldownGuard:
        def __init__(self, cooldown_seconds):
            created["cooldown_seconds"] = cooldown_seconds

    class FakeGuardPipeline:
        def __init__(self, guards):
            self.guards = guards

    guards_module = ModuleType("intelligence.guards")
    guards_module.CooldownGuard = FakeCooldownGuard
    guards_module.GuardPipeline = FakeGuardPipeline
    guards_module.MaxPositionSizeGuard = FakeMaxPositionSizeGuard
    monkeypatch.setitem(__import__("sys").modules, "intelligence.guards", guards_module)

    pipeline = mt5_connector._get_guard_pipeline()

    assert isinstance(pipeline, FakeGuardPipeline)
    assert len(pipeline.guards) == 2
    assert created == {"max_equity_pct": 2.0, "cooldown_seconds": 300}


def test_initialize_mt5_uses_bridge_health(monkeypatch):
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "http://bridge")
    monkeypatch.setattr(mt5_connector, "_bridge_get", lambda path: {"connected": True})

    assert mt5_connector.initialize_mt5() is True


def test_initialize_mt5_handles_missing_mt5_package(monkeypatch):
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", False)

    assert mt5_connector.initialize_mt5() is False


def test_initialize_mt5_handles_native_init_failure(monkeypatch):
    fake_mt5 = SimpleNamespace(
        initialize=lambda: False,
        last_error=lambda: (500, "init failed"),
    )
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", True)
    monkeypatch.setattr(mt5_connector, "mt5", fake_mt5)

    assert mt5_connector.initialize_mt5() is False


def test_get_mt5_account_info_bridge_success(monkeypatch):
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "http://bridge")

    def fake_bridge_get(path):
        if path == "/health":
            return {"connected": True, "live_trading_enabled": False}
        return {"company": "Bridge Broker", "login": 1234}

    monkeypatch.setattr(mt5_connector, "_bridge_get", fake_bridge_get)

    result = mt5_connector.get_mt5_account_info()

    assert result["company"] == "Bridge Broker"
    assert result["bridge_connected"] is True
    assert result["bridge_live_trading_enabled"] is False
    assert result["bridge_url"] == "http://bridge"


def test_get_mt5_account_info_bridge_returns_health_error(monkeypatch):
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "http://bridge")
    monkeypatch.setattr(mt5_connector, "_bridge_get", lambda path: {"error": "health-down"})

    result = mt5_connector.get_mt5_account_info()

    assert result == {"error": "health-down"}


def test_get_mt5_account_info_bridge_returns_account_error(monkeypatch):
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "http://bridge")

    def fake_bridge_get(path):
        if path == "/health":
            return {"connected": True}
        return {"error": "account-down"}

    monkeypatch.setattr(mt5_connector, "_bridge_get", fake_bridge_get)

    result = mt5_connector.get_mt5_account_info()

    assert result == {"error": "account-down"}


def test_get_mt5_account_info_returns_error_when_mt5_missing(monkeypatch):
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", False)

    result = mt5_connector.get_mt5_account_info()

    assert "MetaTrader5 not installed" in result["error"]


def test_get_mt5_account_info_native_errors(monkeypatch):
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", True)
    monkeypatch.setattr(mt5_connector, "initialize_mt5", lambda: False)

    result = mt5_connector.get_mt5_account_info()

    assert result == {"error": "Failed to connect to MT5"}


def test_get_mt5_account_info_native_handles_missing_account(monkeypatch):
    fake_mt5 = SimpleNamespace(
        account_info=lambda: None,
        last_error=lambda: (1, "missing"),
    )
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", True)
    monkeypatch.setattr(mt5_connector, "initialize_mt5", lambda: True)
    monkeypatch.setattr(mt5_connector, "mt5", fake_mt5)

    result = mt5_connector.get_mt5_account_info()

    assert "Failed to get account info" in result["error"]


def test_get_mt5_account_info_native_success(monkeypatch):
    class FakeAccount:
        def _asdict(self):
            return {"company": "XM Global", "login": 99}

    fake_mt5 = SimpleNamespace(account_info=lambda: FakeAccount())
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", True)
    monkeypatch.setattr(mt5_connector, "initialize_mt5", lambda: True)
    monkeypatch.setattr(mt5_connector, "mt5", fake_mt5)

    result = mt5_connector.get_mt5_account_info()

    assert result == {"company": "XM Global", "login": 99}


def test_get_mt5_positions_bridge_error_returns_empty_list(monkeypatch):
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "http://bridge")
    monkeypatch.setattr(mt5_connector, "_bridge_get", lambda path: {"error": "down"})

    assert mt5_connector.get_mt5_positions() == []


def test_get_mt5_positions_bridge_success(monkeypatch):
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "http://bridge")
    monkeypatch.setattr(mt5_connector, "_bridge_get", lambda path: {"positions": [{"ticket": 1}]})

    assert mt5_connector.get_mt5_positions() == [{"ticket": 1}]


def test_get_mt5_positions_returns_empty_without_mt5(monkeypatch):
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", False)

    assert mt5_connector.get_mt5_positions() == []


def test_get_mt5_positions_returns_empty_when_init_fails(monkeypatch):
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", True)
    monkeypatch.setattr(mt5_connector, "initialize_mt5", lambda: False)

    assert mt5_connector.get_mt5_positions() == []


def test_get_mt5_positions_returns_empty_when_native_positions_missing(monkeypatch):
    fake_mt5 = SimpleNamespace(positions_get=lambda: None)
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", True)
    monkeypatch.setattr(mt5_connector, "initialize_mt5", lambda: True)
    monkeypatch.setattr(mt5_connector, "mt5", fake_mt5)

    assert mt5_connector.get_mt5_positions() == []


def test_get_mt5_positions_native_success(monkeypatch):
    class FakePosition:
        def __init__(self, ticket):
            self.ticket = ticket

        def _asdict(self):
            return {"ticket": self.ticket}

    fake_mt5 = SimpleNamespace(positions_get=lambda: [FakePosition(7), FakePosition(8)])
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", True)
    monkeypatch.setattr(mt5_connector, "initialize_mt5", lambda: True)
    monkeypatch.setattr(mt5_connector, "mt5", fake_mt5)

    result = mt5_connector.get_mt5_positions()

    assert result == [{"ticket": 7}, {"ticket": 8}]


def test_get_mt5_quote_native_success(monkeypatch):
    fake_info = SimpleNamespace(
        digits=2,
        point=0.01,
        volume_min=0.01,
        volume_max=10.0,
        volume_step=0.01,
        trade_mode=1,
        trade_contract_size=100,
    )
    fake_tick = SimpleNamespace(bid=100.0, ask=101.0, last=100.5, time=123456)
    fake_mt5 = SimpleNamespace(
        symbol_select=lambda symbol, visible: True,
        symbol_info=lambda symbol: fake_info,
        symbol_info_tick=lambda symbol: fake_tick,
    )
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", True)
    monkeypatch.setattr(mt5_connector, "initialize_mt5", lambda: True)
    monkeypatch.setattr(mt5_connector, "mt5", fake_mt5)

    result = mt5_connector.get_mt5_quote("XAUUSD")

    assert result["symbol"] == "XAUUSD"
    assert result["spread"] == 1.0
    assert result["digits"] == 2


def test_get_mt5_quote_bridge_mode(monkeypatch):
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "http://bridge")
    monkeypatch.setattr(mt5_connector, "_bridge_get", lambda path, params: {"symbol": params["symbol"], "bid": 1.0})

    result = mt5_connector.get_mt5_quote("BTCUSD")

    assert result == {"symbol": "BTCUSD", "bid": 1.0}


def test_get_mt5_quote_returns_error_without_mt5(monkeypatch):
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", False)

    result = mt5_connector.get_mt5_quote("BTCUSD")

    assert "MetaTrader5 not installed" in result["error"]


def test_get_mt5_quote_returns_error_when_init_fails(monkeypatch):
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", True)
    monkeypatch.setattr(mt5_connector, "initialize_mt5", lambda: False)

    result = mt5_connector.get_mt5_quote("BTCUSD")

    assert result == {"error": "Failed to connect to MT5"}


def test_get_mt5_quote_returns_error_when_symbol_select_fails(monkeypatch):
    fake_mt5 = SimpleNamespace(symbol_select=lambda symbol, visible: False)
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", True)
    monkeypatch.setattr(mt5_connector, "initialize_mt5", lambda: True)
    monkeypatch.setattr(mt5_connector, "mt5", fake_mt5)

    result = mt5_connector.get_mt5_quote("BTCUSD")

    assert result == {"error": "Failed to select symbol BTCUSD"}


def test_get_mt5_quote_returns_error_when_quote_unavailable(monkeypatch):
    fake_mt5 = SimpleNamespace(
        symbol_select=lambda symbol, visible: True,
        symbol_info=lambda symbol: None,
        symbol_info_tick=lambda symbol: None,
        last_error=lambda: (2, "no quote"),
    )
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", True)
    monkeypatch.setattr(mt5_connector, "initialize_mt5", lambda: True)
    monkeypatch.setattr(mt5_connector, "mt5", fake_mt5)

    result = mt5_connector.get_mt5_quote("BTCUSD")

    assert result["error"] == "Quote unavailable for BTCUSD"


def test_is_positive_number_filters_invalid_values():
    assert mt5_connector._is_positive_number("1.5") is True
    assert mt5_connector._is_positive_number(0) is False
    assert mt5_connector._is_positive_number("nan") is False
    assert mt5_connector._is_positive_number("bad") is False


def test_validate_live_order_requires_stop_loss(monkeypatch):
    monkeypatch.setattr(mt5_connector, "MT5_REQUIRE_STOP_LOSS", True)

    result = mt5_connector.validate_live_order_request(
        symbol="GOLD",
        action="BUY",
        volume=0.01,
        sl=0,
        tp=2500,
    )

    assert result["passed"] is False
    assert "stop_loss_required_for_live_order" in result["issues"]


def test_validate_live_order_blocks_oversized_volume(monkeypatch):
    monkeypatch.setattr(mt5_connector, "MT5_MAX_LIVE_VOLUME", 0.10)

    result = mt5_connector.validate_live_order_request(
        symbol="EURUSD",
        action="SELL",
        volume=0.20,
        sl=1.12,
        tp=1.10,
    )

    assert result["passed"] is False
    assert "volume_exceeds_max_0.1" in result["issues"]


def test_validate_live_order_collects_multiple_issues(monkeypatch):
    monkeypatch.setattr(mt5_connector, "MT5_REQUIRE_STOP_LOSS", True)
    monkeypatch.setattr(mt5_connector, "MT5_MAX_LIVE_VOLUME", 0.10)

    result = mt5_connector.validate_live_order_request(
        symbol="",
        action="hold",
        volume=-1,
        sl=-2,
        tp=-3,
        price=-4,
    )

    assert result["passed"] is False
    assert set(result["issues"]) == {
        "symbol_required",
        "side_must_be_buy_or_sell",
        "volume_must_be_positive",
        "stop_loss_required_for_live_order",
        "price_must_be_positive",
        "take_profit_must_be_positive",
    }


def test_resolve_broker_symbol_returns_first_successful_candidate(monkeypatch):
    monkeypatch.setattr(mt5_connector, "normalize_broker_symbol", lambda symbol: ["BAD", "GOOD"])
    monkeypatch.setattr(
        mt5_connector,
        "get_mt5_quote",
        lambda symbol: {"error": "missing"} if symbol == "BAD" else {"bid": 1.0},
    )

    result = mt5_connector.resolve_broker_symbol("gold")

    assert result["status"] == "SUCCESS"
    assert result["symbol"] == "GOOD"


def test_resolve_broker_symbol_returns_last_error(monkeypatch):
    monkeypatch.setattr(mt5_connector, "normalize_broker_symbol", lambda symbol: ["A", "B"])
    monkeypatch.setattr(mt5_connector, "get_mt5_quote", lambda symbol: {"error": f"{symbol}-down"})

    result = mt5_connector.resolve_broker_symbol("gold")

    assert result["status"] == "ERROR"
    assert result["error"] == "B-down"


def test_mt5_execute_trade_blocks_failed_preflight(monkeypatch):
    monkeypatch.setattr(
        mt5_connector,
        "validate_live_order_request",
        lambda *args, **kwargs: {"passed": False, "issues": ["blocked"]},
    )

    result = mt5_connector.mt5_execute_trade("BTCUSD", "BUY", 0.1, sl=1.0)

    assert result["status"] == "GUARD_BLOCKED"
    assert result["preflight"]["issues"] == ["blocked"]


def test_mt5_execute_trade_blocks_when_execution_guards_fail(monkeypatch):
    fake_mt5 = SimpleNamespace(symbol_info=lambda symbol: SimpleNamespace(visible=True))
    guard_failures = []
    monkeypatch.setattr(
        mt5_connector,
        "validate_live_order_request",
        lambda *args, **kwargs: {"passed": True},
    )
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", True)
    monkeypatch.setattr(mt5_connector, "initialize_mt5", lambda: True)
    monkeypatch.setattr(mt5_connector, "get_mt5_account_info", lambda: {"company": "Paper"})
    monkeypatch.setattr(
        mt5_connector,
        "_get_guard_pipeline",
        lambda: SimpleNamespace(run=lambda params, account: (False, ["cooldown"])),
    )
    monkeypatch.setattr(mt5_connector, "log_guard_failure", lambda **kwargs: guard_failures.append(kwargs))
    monkeypatch.setattr(mt5_connector, "mt5", fake_mt5)

    result = mt5_connector.mt5_execute_trade("BTCUSD", "BUY", 0.1, sl=1.0)

    assert result["status"] == "GUARD_BLOCKED"
    assert result["results"] == ["cooldown"]
    assert guard_failures[0]["guard_name"] == "GuardPipeline"


def test_mt5_execute_trade_guard_exception_proceeds_to_symbol_lookup(monkeypatch):
    fake_mt5 = SimpleNamespace(symbol_info=lambda symbol: None)
    monkeypatch.setattr(
        mt5_connector,
        "validate_live_order_request",
        lambda *args, **kwargs: {"passed": True},
    )
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", True)
    monkeypatch.setattr(mt5_connector, "initialize_mt5", lambda: True)
    monkeypatch.setattr(mt5_connector, "get_mt5_account_info", lambda: (_ for _ in ()).throw(RuntimeError("guard fail")))
    monkeypatch.setattr(mt5_connector, "mt5", fake_mt5)

    result = mt5_connector.mt5_execute_trade("BTCUSD", "BUY", 0.1, sl=1.0)

    assert result == {"error": "Symbol BTCUSD not found"}


def test_mt5_execute_trade_bridge_mode_posts_payload(monkeypatch):
    monkeypatch.setattr(
        mt5_connector,
        "validate_live_order_request",
        lambda *args, **kwargs: {"passed": True},
    )
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "http://bridge")
    monkeypatch.setattr(mt5_connector, "_bridge_post", lambda path, payload: {"path": path, "payload": payload})

    result = mt5_connector.mt5_execute_trade("BTCUSD", "BUY", 0.1, sl=1.0, tp=2.0)

    assert result["path"] == "/trade"
    assert result["payload"]["symbol"] == "BTCUSD"
    assert result["payload"]["tp"] == 2.0


def test_mt5_execute_trade_returns_error_without_mt5(monkeypatch):
    monkeypatch.setattr(
        mt5_connector,
        "validate_live_order_request",
        lambda *args, **kwargs: {"passed": True},
    )
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", False)

    result = mt5_connector.mt5_execute_trade("BTCUSD", "BUY", 0.1, sl=1.0)

    assert "MetaTrader5 not installed" in result["error"]


def test_mt5_execute_trade_returns_error_when_init_fails(monkeypatch):
    monkeypatch.setattr(
        mt5_connector,
        "validate_live_order_request",
        lambda *args, **kwargs: {"passed": True},
    )
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", True)
    monkeypatch.setattr(mt5_connector, "initialize_mt5", lambda: False)

    result = mt5_connector.mt5_execute_trade("BTCUSD", "BUY", 0.1, sl=1.0)

    assert result == {"error": "Failed to connect to MT5"}


def test_mt5_execute_trade_native_pending_order_requires_price(monkeypatch):
    fake_mt5 = SimpleNamespace(
        symbol_info=lambda symbol: SimpleNamespace(visible=True),
        symbol_select=lambda symbol, visible: True,
        ORDER_TYPE_BUY=0,
        ORDER_TYPE_SELL=1,
        ORDER_TYPE_BUY_LIMIT=2,
        ORDER_TYPE_SELL_LIMIT=3,
        ORDER_TYPE_BUY_STOP=4,
        ORDER_TYPE_SELL_STOP=5,
        ORDER_TYPE_BUY_STOP_LIMIT=6,
        ORDER_TYPE_SELL_STOP_LIMIT=7,
        ORDER_FILLING_FOK=10,
        ORDER_FILLING_IOC=11,
        ORDER_FILLING_RETURN=12,
        TRADE_ACTION_DEAL=20,
        TRADE_ACTION_PENDING=21,
        ORDER_TIME_GTC=30,
        ORDER_TIME_SPECIFIED=31,
    )
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", True)
    monkeypatch.setattr(mt5_connector, "initialize_mt5", lambda: True)
    monkeypatch.setattr(
        mt5_connector,
        "validate_live_order_request",
        lambda *args, **kwargs: {"passed": True},
    )
    monkeypatch.setattr(mt5_connector, "get_mt5_account_info", lambda: {})
    monkeypatch.setattr(mt5_connector, "_get_guard_pipeline", lambda: SimpleNamespace(run=lambda params, account: (True, [])))
    monkeypatch.setattr(mt5_connector, "log_trade_attempt", lambda **kwargs: None)
    monkeypatch.setattr(mt5_connector, "mt5", fake_mt5)

    result = mt5_connector.mt5_execute_trade("BTCUSD", "BUY_LIMIT", 0.1, sl=1.0, order_kind="PENDING")

    assert result == {"error": "Pending orders require a valid entry price"}


def test_mt5_execute_trade_native_rejects_unsupported_pending_action(monkeypatch):
    fake_mt5 = SimpleNamespace(
        symbol_info=lambda symbol: SimpleNamespace(visible=True),
        symbol_select=lambda symbol, visible: True,
        ORDER_TYPE_BUY=0,
        ORDER_TYPE_SELL=1,
        ORDER_TYPE_BUY_LIMIT=2,
        ORDER_TYPE_SELL_LIMIT=3,
        ORDER_TYPE_BUY_STOP=4,
        ORDER_TYPE_SELL_STOP=5,
        ORDER_TYPE_BUY_STOP_LIMIT=6,
        ORDER_TYPE_SELL_STOP_LIMIT=7,
        ORDER_FILLING_FOK=10,
        ORDER_FILLING_IOC=11,
        ORDER_FILLING_RETURN=12,
        TRADE_ACTION_DEAL=20,
        TRADE_ACTION_PENDING=21,
        ORDER_TIME_GTC=30,
        ORDER_TIME_SPECIFIED=31,
    )
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", True)
    monkeypatch.setattr(mt5_connector, "initialize_mt5", lambda: True)
    monkeypatch.setattr(
        mt5_connector,
        "validate_live_order_request",
        lambda *args, **kwargs: {"passed": True},
    )
    monkeypatch.setattr(mt5_connector, "get_mt5_account_info", lambda: {})
    monkeypatch.setattr(mt5_connector, "_get_guard_pipeline", lambda: SimpleNamespace(run=lambda params, account: (True, [])))
    monkeypatch.setattr(mt5_connector, "log_trade_attempt", lambda **kwargs: None)
    monkeypatch.setattr(mt5_connector, "mt5", fake_mt5)

    result = mt5_connector.mt5_execute_trade("BTCUSD", "HOLD", 0.1, price=100.0, sl=1.0, order_kind="PENDING")

    assert result == {"error": "Unsupported pending order type: HOLD"}


def test_mt5_execute_trade_returns_error_when_symbol_select_fails(monkeypatch):
    fake_mt5 = SimpleNamespace(
        symbol_info=lambda symbol: SimpleNamespace(visible=False),
        symbol_select=lambda symbol, visible: False,
    )
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", True)
    monkeypatch.setattr(mt5_connector, "initialize_mt5", lambda: True)
    monkeypatch.setattr(
        mt5_connector,
        "validate_live_order_request",
        lambda *args, **kwargs: {"passed": True},
    )
    monkeypatch.setattr(mt5_connector, "get_mt5_account_info", lambda: {})
    monkeypatch.setattr(mt5_connector, "_get_guard_pipeline", lambda: SimpleNamespace(run=lambda params, account: (True, [])))
    monkeypatch.setattr(mt5_connector, "log_trade_attempt", lambda **kwargs: None)
    monkeypatch.setattr(mt5_connector, "mt5", fake_mt5)

    result = mt5_connector.mt5_execute_trade("BTCUSD", "BUY", 0.1, sl=1.0)

    assert result == {"error": "Failed to select symbol BTCUSD"}


def test_mt5_execute_trade_native_success(monkeypatch):
    sent_requests = []
    fake_mt5 = SimpleNamespace(
        symbol_info=lambda symbol: SimpleNamespace(visible=True),
        symbol_select=lambda symbol, visible: True,
        symbol_info_tick=lambda symbol: SimpleNamespace(ask=101.0, bid=99.0),
        order_send=lambda request: sent_requests.append(request)
        or SimpleNamespace(
            retcode=999,
            order=11,
            deal=22,
            price=request["price"],
            volume=request["volume"],
            comment="ok",
        ),
        ORDER_TYPE_BUY=0,
        ORDER_TYPE_SELL=1,
        ORDER_TYPE_BUY_LIMIT=2,
        ORDER_TYPE_SELL_LIMIT=3,
        ORDER_TYPE_BUY_STOP=4,
        ORDER_TYPE_SELL_STOP=5,
        ORDER_TYPE_BUY_STOP_LIMIT=6,
        ORDER_TYPE_SELL_STOP_LIMIT=7,
        ORDER_FILLING_FOK=10,
        ORDER_FILLING_IOC=11,
        ORDER_FILLING_RETURN=12,
        TRADE_ACTION_DEAL=20,
        TRADE_ACTION_PENDING=21,
        ORDER_TIME_GTC=30,
        ORDER_TIME_SPECIFIED=31,
        TRADE_RETCODE_DONE=999,
    )
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", True)
    monkeypatch.setattr(mt5_connector, "initialize_mt5", lambda: True)
    monkeypatch.setattr(
        mt5_connector,
        "validate_live_order_request",
        lambda *args, **kwargs: {"passed": True},
    )
    monkeypatch.setattr(mt5_connector, "get_mt5_account_info", lambda: {"company": "Paper"})
    monkeypatch.setattr(mt5_connector, "_get_guard_pipeline", lambda: SimpleNamespace(run=lambda params, account: (True, [])))
    monkeypatch.setattr(mt5_connector, "log_trade_attempt", lambda **kwargs: None)
    monkeypatch.setattr(mt5_connector, "mt5", fake_mt5)

    result = mt5_connector.mt5_execute_trade("BTCUSD", "BUY", 0.1, sl=90.0, tp=120.0, comment="A" * 50)

    assert result["status"] == "SUCCESS"
    assert result["price"] == 101.0
    assert sent_requests[0]["comment"] == "A" * 31


def test_mt5_execute_trade_native_pending_success_with_expiration(monkeypatch):
    sent_requests = []
    fake_mt5 = SimpleNamespace(
        symbol_info=lambda symbol: SimpleNamespace(visible=False),
        symbol_select=lambda symbol, visible: True,
        order_send=lambda request: sent_requests.append(request)
        or SimpleNamespace(
            retcode=999,
            order=44,
            deal=55,
            price=request["price"],
            volume=request["volume"],
            comment="ok",
        ),
        ORDER_TYPE_BUY=0,
        ORDER_TYPE_SELL=1,
        ORDER_TYPE_BUY_LIMIT=2,
        ORDER_TYPE_SELL_LIMIT=3,
        ORDER_TYPE_BUY_STOP=4,
        ORDER_TYPE_SELL_STOP=5,
        ORDER_TYPE_BUY_STOP_LIMIT=6,
        ORDER_TYPE_SELL_STOP_LIMIT=7,
        ORDER_FILLING_FOK=10,
        ORDER_FILLING_IOC=11,
        ORDER_FILLING_RETURN=12,
        TRADE_ACTION_DEAL=20,
        TRADE_ACTION_PENDING=21,
        ORDER_TIME_GTC=30,
        ORDER_TIME_SPECIFIED=31,
        TRADE_RETCODE_DONE=999,
    )
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", True)
    monkeypatch.setattr(mt5_connector, "initialize_mt5", lambda: True)
    monkeypatch.setattr(
        mt5_connector,
        "validate_live_order_request",
        lambda *args, **kwargs: {"passed": True},
    )
    monkeypatch.setattr(mt5_connector, "get_mt5_account_info", lambda: {"company": "Paper"})
    monkeypatch.setattr(mt5_connector, "_get_guard_pipeline", lambda: SimpleNamespace(run=lambda params, account: (True, [])))
    monkeypatch.setattr(mt5_connector, "log_trade_attempt", lambda **kwargs: None)
    monkeypatch.setattr(mt5_connector, "mt5", fake_mt5)

    result = mt5_connector.mt5_execute_trade(
        "BTCUSD",
        "BUY_LIMIT",
        0.1,
        price=99.5,
        sl=90.0,
        tp=120.0,
        order_kind="PENDING",
        filling_policy="UNKNOWN",
        expiration=1234567890,
    )

    assert result["status"] == "SUCCESS"
    assert sent_requests[0]["type_time"] == fake_mt5.ORDER_TIME_SPECIFIED
    assert sent_requests[0]["expiration"] == 1234567890
    assert sent_requests[0]["type_filling"] == fake_mt5.ORDER_FILLING_IOC


def test_mt5_execute_trade_native_returns_failed_status(monkeypatch):
    fake_mt5 = SimpleNamespace(
        symbol_info=lambda symbol: SimpleNamespace(visible=False),
        symbol_select=lambda symbol, visible: True,
        symbol_info_tick=lambda symbol: SimpleNamespace(ask=101.0, bid=99.0),
        order_send=lambda request: SimpleNamespace(retcode=123, comment="denied"),
        ORDER_TYPE_BUY=0,
        ORDER_TYPE_SELL=1,
        ORDER_TYPE_BUY_LIMIT=2,
        ORDER_TYPE_SELL_LIMIT=3,
        ORDER_TYPE_BUY_STOP=4,
        ORDER_TYPE_SELL_STOP=5,
        ORDER_TYPE_BUY_STOP_LIMIT=6,
        ORDER_TYPE_SELL_STOP_LIMIT=7,
        ORDER_FILLING_FOK=10,
        ORDER_FILLING_IOC=11,
        ORDER_FILLING_RETURN=12,
        TRADE_ACTION_DEAL=20,
        TRADE_ACTION_PENDING=21,
        ORDER_TIME_GTC=30,
        ORDER_TIME_SPECIFIED=31,
        TRADE_RETCODE_DONE=999,
    )
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", True)
    monkeypatch.setattr(mt5_connector, "initialize_mt5", lambda: True)
    monkeypatch.setattr(
        mt5_connector,
        "validate_live_order_request",
        lambda *args, **kwargs: {"passed": True},
    )
    monkeypatch.setattr(mt5_connector, "get_mt5_account_info", lambda: {})
    monkeypatch.setattr(mt5_connector, "_get_guard_pipeline", lambda: SimpleNamespace(run=lambda params, account: (True, [])))
    monkeypatch.setattr(mt5_connector, "log_trade_attempt", lambda **kwargs: None)
    monkeypatch.setattr(mt5_connector, "mt5", fake_mt5)

    result = mt5_connector.mt5_execute_trade("BTCUSD", "SELL", 0.1, sl=105.0)

    assert result["status"] == "FAILED"
    assert result["comment"] == "denied"


def test_mt5_close_position_bridge_mode(monkeypatch):
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "http://bridge")
    monkeypatch.setattr(mt5_connector, "_bridge_post", lambda path, payload: {"path": path, "payload": payload})

    result = mt5_connector.mt5_close_position(77)

    assert result == {"path": "/close", "payload": {"ticket": 77}}


def test_mt5_close_position_returns_error_without_mt5(monkeypatch):
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", False)

    result = mt5_connector.mt5_close_position(77)

    assert "MetaTrader5 not installed" in result["error"]


def test_mt5_close_position_returns_error_when_init_fails(monkeypatch):
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", True)
    monkeypatch.setattr(mt5_connector, "initialize_mt5", lambda: False)

    result = mt5_connector.mt5_close_position(77)

    assert result == {"error": "Failed to connect to MT5"}


def test_mt5_close_position_returns_error_when_position_missing(monkeypatch):
    fake_mt5 = SimpleNamespace(positions_get=lambda **kwargs: [])
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", True)
    monkeypatch.setattr(mt5_connector, "initialize_mt5", lambda: True)
    monkeypatch.setattr(mt5_connector, "mt5", fake_mt5)

    result = mt5_connector.mt5_close_position(77)

    assert result == {"error": "Position 77 not found"}


def test_mt5_close_position_native_failed_status(monkeypatch):
    fake_position = SimpleNamespace(symbol="BTCUSD", type=0, volume=0.3)
    fake_mt5 = SimpleNamespace(
        positions_get=lambda **kwargs: [fake_position],
        symbol_info_tick=lambda symbol: SimpleNamespace(bid=100.0, ask=101.0),
        order_send=lambda request: SimpleNamespace(retcode=123, comment="denied"),
        ORDER_TYPE_BUY=0,
        ORDER_TYPE_SELL=1,
        TRADE_ACTION_DEAL=20,
        ORDER_TIME_GTC=30,
        ORDER_FILLING_IOC=11,
        TRADE_RETCODE_DONE=999,
    )
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", True)
    monkeypatch.setattr(mt5_connector, "initialize_mt5", lambda: True)
    monkeypatch.setattr(mt5_connector, "mt5", fake_mt5)

    result = mt5_connector.mt5_close_position(77)

    assert result == {"status": "FAILED", "comment": "denied"}


def test_mt5_close_position_native_success(monkeypatch):
    fake_position = SimpleNamespace(symbol="BTCUSD", type=0, volume=0.3)
    fake_mt5 = SimpleNamespace(
        positions_get=lambda **kwargs: [fake_position],
        symbol_info_tick=lambda symbol: SimpleNamespace(bid=100.0, ask=101.0),
        order_send=lambda request: SimpleNamespace(retcode=999, deal=55),
        ORDER_TYPE_BUY=0,
        ORDER_TYPE_SELL=1,
        TRADE_ACTION_DEAL=20,
        ORDER_TIME_GTC=30,
        ORDER_FILLING_IOC=11,
        TRADE_RETCODE_DONE=999,
    )
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", True)
    monkeypatch.setattr(mt5_connector, "initialize_mt5", lambda: True)
    monkeypatch.setattr(mt5_connector, "mt5", fake_mt5)

    result = mt5_connector.mt5_close_position(77)

    assert result == {"status": "SUCCESS", "deal": 55}


def test_mt5_modify_position_bridge_mode(monkeypatch):
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "http://bridge")
    monkeypatch.setattr(mt5_connector, "_bridge_post", lambda path, payload: {"path": path, "payload": payload})

    result = mt5_connector.mt5_modify_position(77, 10.0, 20.0)

    assert result == {"path": "/modify", "payload": {"ticket": 77, "sl": 10.0, "tp": 20.0}}


def test_mt5_modify_position_native_success(monkeypatch):
    fake_position = SimpleNamespace(symbol="BTCUSD", tp=25.0)
    fake_mt5 = SimpleNamespace(
        positions_get=lambda **kwargs: [fake_position],
        order_send=lambda request: SimpleNamespace(
            retcode=999,
            comment="ok",
            request=SimpleNamespace(sl=request["sl"], tp=request["tp"]),
        ),
        TRADE_ACTION_SLTP=20,
        TRADE_RETCODE_DONE=999,
    )
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", True)
    monkeypatch.setattr(mt5_connector, "initialize_mt5", lambda: True)
    monkeypatch.setattr(mt5_connector, "mt5", fake_mt5)

    result = mt5_connector.mt5_modify_position(77, 10.0)

    assert result == {"status": "SUCCESS", "ticket": 77, "sl": 10.0, "tp": 25.0}


def test_mt5_modify_position_returns_error_without_mt5(monkeypatch):
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", False)

    result = mt5_connector.mt5_modify_position(77, 10.0)

    assert result == {"error": "MetaTrader5 not installed."}


def test_mt5_modify_position_returns_error_when_init_fails(monkeypatch):
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", True)
    monkeypatch.setattr(mt5_connector, "initialize_mt5", lambda: False)

    result = mt5_connector.mt5_modify_position(77, 10.0)

    assert result == {"error": "Failed to connect to MT5"}


def test_mt5_modify_position_returns_error_when_position_missing(monkeypatch):
    fake_mt5 = SimpleNamespace(positions_get=lambda **kwargs: [])
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", True)
    monkeypatch.setattr(mt5_connector, "initialize_mt5", lambda: True)
    monkeypatch.setattr(mt5_connector, "mt5", fake_mt5)

    result = mt5_connector.mt5_modify_position(77, 10.0)

    assert result == {"error": "Position 77 not found"}


def test_mt5_modify_position_native_failed_status(monkeypatch):
    fake_position = SimpleNamespace(symbol="BTCUSD", tp=25.0)
    fake_mt5 = SimpleNamespace(
        positions_get=lambda **kwargs: [fake_position],
        order_send=lambda request: SimpleNamespace(retcode=111, comment="nope", request=SimpleNamespace(sl=request["sl"], tp=request["tp"])),
        TRADE_ACTION_SLTP=20,
        TRADE_RETCODE_DONE=999,
    )
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", True)
    monkeypatch.setattr(mt5_connector, "initialize_mt5", lambda: True)
    monkeypatch.setattr(mt5_connector, "mt5", fake_mt5)

    result = mt5_connector.mt5_modify_position(77, 10.0)

    assert result == {"status": "FAILED", "retcode": 111, "comment": "nope"}


def test_mt5_get_rates_bridge_returns_dataframe(monkeypatch):
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "http://bridge")
    monkeypatch.setattr(
        mt5_connector,
        "_bridge_get",
        lambda path, params: {
            "rates": [
                {
                    "Datetime": "2026-05-26T00:00:00Z",
                    "Open": 1.0,
                    "High": 2.0,
                    "Low": 0.5,
                    "Close": 1.5,
                    "Volume": 10,
                }
            ]
        },
    )

    result = mt5_connector.mt5_get_rates("BTCUSD", "15m", 1)

    assert list(result.columns) == ["Datetime", "Open", "High", "Low", "Close", "Volume"]
    assert isinstance(result, pd.DataFrame)
    assert str(result.iloc[0]["Datetime"].tzinfo) == "UTC"


def test_mt5_get_rates_bridge_returns_none_without_rows(monkeypatch):
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "http://bridge")
    monkeypatch.setattr(mt5_connector, "_bridge_get", lambda path, params: {"rates": []})

    assert mt5_connector.mt5_get_rates("BTCUSD") is None


def test_mt5_get_rates_bridge_returns_dataframe_without_datetime_column(monkeypatch):
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "http://bridge")
    monkeypatch.setattr(
        mt5_connector,
        "_bridge_get",
        lambda path, params: {
            "rates": [
                {
                    "Datetime": "2026-05-26T00:00:00Z",
                    "Open": 1.0,
                    "High": 2.0,
                    "Low": 0.5,
                    "Close": 1.5,
                    "Volume": 10,
                }
            ]
        },
    )

    result = mt5_connector.mt5_get_rates("BTCUSD")

    assert str(result.iloc[0]["Datetime"].tzinfo) == "UTC"


def test_mt5_get_rates_bridge_handles_frames_without_datetime_branch(monkeypatch):
    class FakeFrame:
        columns = ["Open", "High", "Low", "Close", "Volume"]

        def __getitem__(self, key):
            if key == ["Datetime", "Open", "High", "Low", "Close", "Volume"]:
                return "subset-without-datetime-conversion"
            raise AssertionError(f"unexpected key: {key}")

    fake_pandas = ModuleType("pandas")
    fake_pandas.DataFrame = lambda rows: FakeFrame()
    fake_pandas.to_datetime = lambda value: (_ for _ in ()).throw(AssertionError("should not convert datetime"))

    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "http://bridge")
    monkeypatch.setattr(
        mt5_connector,
        "_bridge_get",
        lambda path, params: {
            "rates": [{"Open": 1.0, "High": 2.0, "Low": 0.5, "Close": 1.5, "Volume": 10}]
        },
    )
    monkeypatch.setitem(sys.modules, "pandas", fake_pandas)

    result = mt5_connector.mt5_get_rates("BTCUSD")

    assert result == "subset-without-datetime-conversion"


def test_mt5_get_rates_returns_none_without_mt5(monkeypatch):
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", False)

    assert mt5_connector.mt5_get_rates("BTCUSD") is None


def test_mt5_get_rates_returns_none_when_init_fails(monkeypatch):
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", True)
    monkeypatch.setattr(mt5_connector, "initialize_mt5", lambda: False)

    assert mt5_connector.mt5_get_rates("BTCUSD") is None


def test_mt5_get_rates_native_success(monkeypatch):
    fake_mt5 = SimpleNamespace(
        symbol_select=lambda symbol, visible: symbol == "BTCUSD",
        copy_rates_from_pos=lambda symbol, tf, start, count: [
            {"time": 1700000000, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "tick_volume": 10}
        ],
        TIMEFRAME_M1=1,
        TIMEFRAME_M5=5,
        TIMEFRAME_M15=15,
        TIMEFRAME_M30=30,
        TIMEFRAME_H1=60,
        TIMEFRAME_H4=240,
        TIMEFRAME_D1=1440,
    )
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", True)
    monkeypatch.setattr(mt5_connector, "initialize_mt5", lambda: True)
    monkeypatch.setattr(mt5_connector, "normalize_broker_symbol", lambda symbol: ["BAD", "BTCUSD"])
    monkeypatch.setattr(mt5_connector, "mt5", fake_mt5)

    result = mt5_connector.mt5_get_rates("BTC", "1h", 1)

    assert list(result.columns) == ["Datetime", "Open", "High", "Low", "Close", "Volume"]
    assert float(result.iloc[0]["Close"]) == 1.5


def test_mt5_get_rates_returns_none_when_symbol_cannot_be_selected(monkeypatch):
    fake_mt5 = SimpleNamespace(
        symbol_select=lambda symbol, visible: False,
        TIMEFRAME_M1=1,
        TIMEFRAME_M5=5,
        TIMEFRAME_M15=15,
        TIMEFRAME_M30=30,
        TIMEFRAME_H1=60,
        TIMEFRAME_H4=240,
        TIMEFRAME_D1=1440,
    )
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", True)
    monkeypatch.setattr(mt5_connector, "initialize_mt5", lambda: True)
    monkeypatch.setattr(mt5_connector, "normalize_broker_symbol", lambda symbol: ["BAD", "WORSE"])
    monkeypatch.setattr(mt5_connector, "mt5", fake_mt5)

    assert mt5_connector.mt5_get_rates("BTC") is None


def test_mt5_get_rates_returns_none_when_native_rates_missing(monkeypatch):
    fake_mt5 = SimpleNamespace(
        symbol_select=lambda symbol, visible: symbol == "BTCUSD",
        copy_rates_from_pos=lambda symbol, tf, start, count: [],
        last_error=lambda: (1, "no rates"),
        TIMEFRAME_M1=1,
        TIMEFRAME_M5=5,
        TIMEFRAME_M15=15,
        TIMEFRAME_M30=30,
        TIMEFRAME_H1=60,
        TIMEFRAME_H4=240,
        TIMEFRAME_D1=1440,
    )
    monkeypatch.setattr(mt5_connector, "MT5_BRIDGE_URL", "")
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", True)
    monkeypatch.setattr(mt5_connector, "initialize_mt5", lambda: True)
    monkeypatch.setattr(mt5_connector, "normalize_broker_symbol", lambda symbol: ["BTCUSD"])
    monkeypatch.setattr(mt5_connector, "mt5", fake_mt5)

    assert mt5_connector.mt5_get_rates("BTC") is None


def test_normalize_broker_symbol_adds_common_cfd_aliases():
    nasdaq_candidates = mt5_connector.normalize_broker_symbol("NAS100")
    gold_candidates = mt5_connector.normalize_broker_symbol("GOLD")

    assert "US100Cash" in nasdaq_candidates
    assert "US100" in nasdaq_candidates
    assert "XAUUSD" in gold_candidates


def test_normalize_broker_symbol_adds_xm_specific_candidates(monkeypatch):
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", True)
    monkeypatch.setattr(mt5_connector, "get_mt5_account_info", lambda: {"company": "XM Global Limited"})

    candidates = mt5_connector.normalize_broker_symbol("NVDA")

    assert candidates[0] == "NVDA#"
    assert "NVDAUSD" in candidates


def test_normalize_broker_symbol_handles_account_lookup_failure(monkeypatch):
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", True)
    monkeypatch.setattr(
        mt5_connector,
        "get_mt5_account_info",
        lambda: (_ for _ in ()).throw(RuntimeError("unavailable")),
    )

    candidates = mt5_connector.normalize_broker_symbol("ADA")

    assert "ADAUSD" in candidates
    assert "ADAUSDT" in candidates


def test_normalize_broker_symbol_without_mt5_uses_fallbacks_once(monkeypatch):
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", False)

    candidates = mt5_connector.normalize_broker_symbol("BTC")

    assert candidates.count("BTCUSD") == 1
    assert candidates.count("BTCUSDT") == 1
    assert "BTC." in candidates


def test_normalize_broker_symbol_non_xm_account_uses_standard_fallbacks(monkeypatch):
    monkeypatch.setattr(mt5_connector, "_MT5_AVAILABLE", True)
    monkeypatch.setattr(mt5_connector, "get_mt5_account_info", lambda: {"company": "Pepperstone"})

    candidates = mt5_connector.normalize_broker_symbol("SOL")

    assert candidates[0] == "SOL"
    assert "SOLUSD" in candidates
    assert "SOLUSDT" in candidates
