import builtins
from types import SimpleNamespace

from intelligence import execution_bridge as eb
from intelligence import position_monitor as pm


def test_execution_bridge_helper_functions_and_post_hooks(monkeypatch):
    monkeypatch.setattr(eb, "_MT5_AVAILABLE", False)
    monkeypatch.setattr(eb, "normalize_broker_symbol", lambda symbol: [f"{symbol}.a", f"{symbol}.b"])
    assert eb._to_mt5_symbol("BTCUSD") == "BTCUSD.a"

    assert eb._calculate_lot_size(1000, 1, 100, 95, contract_size=1.0) == 2.0
    assert eb._calculate_lot_size(1000, 1, 0, 95) == 0.01
    assert eb._get_contract_size("XAUUSD") == 100.0
    assert eb._get_contract_size("BTCUSD") == 1.0
    assert eb._get_contract_size("NAS100") == 1.0
    assert eb._harden_sniper_v8({"symbol": "BTCUSD", "master_confidence": 0.9}) is True
    assert eb._harden_sniper_v8({"symbol": "", "master_confidence": 0.4}) is False

    logs = []
    alerts = []
    monkeypatch.setitem(
        __import__("sys").modules,
        "intelligence.trade_logger",
        SimpleNamespace(get_trade_logger=lambda: SimpleNamespace(log_trade=lambda entry: logs.append(entry))),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "intelligence.signal_broadcaster",
        SimpleNamespace(get_signal_broadcaster=lambda: SimpleNamespace(send_execution_alert=lambda state, result: alerts.append((state, result)))),
    )
    eb._post_execution_hooks({"symbol": "BTCUSD"}, {"status": "DRY_RUN", "mt5_result": {"ticket": 1}}, {"symbol": "BTCUSD", "volume": 1})
    assert logs and logs[0]["mt5_ticket"] == 1
    assert alerts and alerts[0][0]["symbol"] == "BTCUSD"


def test_execute_signal_paths(monkeypatch):
    base_state = {
        "master_decision": "LONG",
        "symbol": "BTCUSD",
        "timeframe": "1h",
        "master_confidence": 0.9,
        "entry_zone": {"low": 100.0, "high": 110.0},
        "stop_loss": {"price": 95.0},
        "take_profit": {"tp1": 120.0, "tp2": 130.0},
        "risk_reward_ratio": 2.5,
        "master_reasoning": "strong setup",
        "indicator_summary": {"price": 105.0, "rsi": {"value": 55}, "smart_money": {"regime": "TREND"}},
        "size_multiplier": 1.2,
        "signal_grade": "A",
    }

    monkeypatch.setattr(eb, "_harden_sniper_v8", lambda state: False)
    blocked = eb.execute_signal(dict(base_state))
    assert blocked["status"] == "BLOCKED"

    monkeypatch.setattr(eb, "_harden_sniper_v8", lambda state: True)
    no_trade = eb.execute_signal({**base_state, "master_decision": "NO_TRADE"})
    assert no_trade["status"] == "BLOCKED"

    monkeypatch.setattr(eb, "paper_entry_performance_gate", lambda symbol, side, source: {"ok": False})
    perf_block = eb.execute_signal(dict(base_state))
    assert perf_block["status"] == "BLOCKED"
    assert "Paper-performance gate" in perf_block["reason"]

    monkeypatch.setattr(eb, "paper_entry_performance_gate", lambda symbol, side, source: {"ok": True})
    monkeypatch.setattr(eb, "get_symbol_policy", lambda symbol, side, force_refresh=True: {"action": "block"})
    policy_block = eb.execute_signal(dict(base_state))
    assert policy_block["status"] == "BLOCKED"

    monkeypatch.setattr(eb, "get_symbol_policy", lambda symbol, side, force_refresh=True: {"action": "allow", "size_multiplier": 1.0})
    monkeypatch.setattr(eb, "live_execution_gate", lambda state: (False, {"why": "not ready"}))
    readiness_block = eb.execute_signal(dict(base_state), dry_run=False, confirmation_required=False)
    assert readiness_block["status"] == "BLOCKED"
    assert readiness_block["readiness"] == {"why": "not ready"}

    stock_hodl = eb.execute_signal({**base_state, "symbol": "AAPL123", "indicator_summary": {"asset_class": "STOCK", "price": 100.0, "rsi": {"value": 55}, "smart_money": {"regime": "TREND"}}})
    assert stock_hodl["status"] == "HODL"

    monkeypatch.setitem(
        __import__("sys").modules,
        "intelligence.guard_layer",
        SimpleNamespace(create_guard_agent=lambda config=None: (lambda state: {"guard_passed": False, "guard_override_reason": "too hot"})),
    )
    guard_block = eb.execute_signal(dict(base_state))
    assert guard_block["status"] == "BLOCKED"
    assert "too hot" in guard_block["reason"]

    monkeypatch.setitem(
        __import__("sys").modules,
        "intelligence.guard_layer",
        SimpleNamespace(create_guard_agent=lambda config=None: (lambda state: {"guard_passed": True, "guard_override_reason": ""})),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "intelligence.guards.macro_shield",
        SimpleNamespace(is_in_danger_zone=lambda: {"blocked": True, "event": "CPI"}),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "intelligence.guards.correlation_guardian",
        SimpleNamespace(check_correlation_safety=lambda symbol: {"passed": True}),
    )
    macro_block = eb.execute_signal(dict(base_state))
    assert macro_block["status"] == "BLOCKED"
    assert "Macro News Shield" in macro_block["reason"]

    monkeypatch.setitem(
        __import__("sys").modules,
        "intelligence.guards.macro_shield",
        SimpleNamespace(is_in_danger_zone=lambda: {"blocked": False, "event": ""}),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "intelligence.guards.correlation_guardian",
        SimpleNamespace(check_correlation_safety=lambda symbol: {"passed": False, "reason": "clustered"}),
    )
    corr_warning = eb.execute_signal(dict(base_state))
    assert corr_warning["status"] == "DRAFT_WARNING"

    fake_cb = SimpleNamespace(config={}, can_trade=lambda: (False, "daily loss"), get_status=lambda: {"status": "blocked"}, record_trade_result=lambda pnl_usd, is_win: None)
    monkeypatch.setitem(
        __import__("sys").modules,
        "intelligence.circuit_breaker",
        SimpleNamespace(get_circuit_breaker=lambda config=None: fake_cb),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "intelligence.guards.correlation_guardian",
        SimpleNamespace(check_correlation_safety=lambda symbol: {"passed": True}),
    )
    cb_block = eb.execute_signal(dict(base_state), account_balance=1000.0)
    assert cb_block["status"] == "BLOCKED"
    assert cb_block["cb_status"] == {"status": "blocked"}

    ok_cb = SimpleNamespace(config={}, can_trade=lambda: (True, ""), get_status=lambda: {"status": "ok"}, record_trade_result=lambda pnl_usd, is_win: None)
    monkeypatch.setitem(
        __import__("sys").modules,
        "intelligence.circuit_breaker",
        SimpleNamespace(get_circuit_breaker=lambda config=None: ok_cb),
    )
    monkeypatch.setattr(eb, "_to_mt5_symbol", lambda symbol: symbol)
    monkeypatch.setattr(eb, "_post_execution_hooks", lambda state, exec_result, trade_details: exec_result.setdefault("hooked", True))

    missing_prices = eb.execute_signal({**base_state, "entry_zone": {}, "stop_loss": {}}, account_balance=1000.0)
    assert missing_prices["status"] == "ERROR"

    dry = eb.execute_signal(dict(base_state), dry_run=True, account_balance=1000.0)
    assert dry["status"] == "DRY_RUN"
    assert dry["trade_details"]["risk_usd"] > 0

    saved = []
    monkeypatch.setattr(eb, "save_trade_draft", lambda **kwargs: saved.append(kwargs))
    draft = eb.execute_signal(dict(base_state), dry_run=False, confirmation_required=True, account_balance=1000.0)
    assert draft["status"] == "DRAFT"
    assert saved and saved[0]["symbol"] == "BTCUSD"

    monkeypatch.setitem(
        __import__("sys").modules,
        "intelligence.mt5_connector",
        SimpleNamespace(
            mt5_execute_trade=lambda **kwargs: {"status": "SUCCESS", "ticket": 42},
            get_mt5_account_info=lambda: {"balance": 1000.0},
        ),
    )
    monkeypatch.setattr(eb, "live_execution_gate", lambda state: (True, {"why": "ready"}))
    monkeypatch.setitem(
        __import__("sys").modules,
        "intelligence.guards.macro_shield",
        SimpleNamespace(is_in_danger_zone=lambda: {"blocked": False, "event": ""}),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "intelligence.guards.correlation_guardian",
        SimpleNamespace(check_correlation_safety=lambda symbol: {"passed": True}),
    )
    live = eb.execute_signal(dict(base_state), dry_run=False, confirmation_required=False, account_balance=1000.0)
    assert live["status"] == "EXECUTED"
    assert live["mt5_result"]["ticket"] == 42

    monkeypatch.setitem(
        __import__("sys").modules,
        "intelligence.mt5_connector",
        SimpleNamespace(
            mt5_execute_trade=lambda **kwargs: {"status": "FAIL", "comment": "rejected"},
            get_mt5_account_info=lambda: {"balance": 1000.0},
        ),
    )
    failed = eb.execute_signal(dict(base_state), dry_run=False, confirmation_required=False, account_balance=1000.0)
    assert failed["status"] == "ERROR"
    assert "rejected" in failed["reason"]


def test_record_trade_close_and_position_monitor_paths(monkeypatch):
    status_payload = {"status": "ok"}
    recorded = []
    monkeypatch.setitem(
        __import__("sys").modules,
        "intelligence.circuit_breaker",
        SimpleNamespace(get_circuit_breaker=lambda config=None: SimpleNamespace(record_trade_result=lambda pnl_usd, is_win: recorded.append((pnl_usd, is_win)), get_status=lambda: status_payload)),
    )
    assert eb.record_trade_close(12.5, True) == status_payload
    assert recorded == [(12.5, True)]

    monitor = pm.PositionMonitor(
        {
            "max_hold_hours": 1,
            "be_buffer_pips": 2,
            "trail_ratio": 0.5,
            "trail_trigger_rr": 0.5,
        }
    )

    real_import = builtins.__import__

    def _import_fail(name, *args, **kwargs):
        if name == "MetaTrader5":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _import_fail)
    no_mt5 = monitor.check_positions()
    assert "MT5" in no_mt5["status"]
    monkeypatch.setattr(builtins, "__import__", real_import)

    class FakeMT5:
        ORDER_TYPE_SELL = 1
        ORDER_TYPE_BUY = 0
        TRADE_ACTION_DEAL = 2
        TRADE_ACTION_SLTP = 3
        ORDER_TIME_GTC = 4
        ORDER_FILLING_IOC = 5
        TRADE_RETCODE_DONE = 100

        def __init__(self):
            self._positions = []

        def initialize(self):
            return True

        def shutdown(self):
            return True

        def positions_get(self, symbol=None):
            if symbol:
                return [p for p in self._positions if p.symbol == symbol]
            return self._positions

        def symbol_info(self, symbol):
            return SimpleNamespace(point=0.01, digits=2)

        def symbol_info_tick(self, symbol):
            return SimpleNamespace(bid=110.0, ask=111.0)

        def order_send(self, request):
            return SimpleNamespace(retcode=self.TRADE_RETCODE_DONE)

    fake_mt5 = FakeMT5()
    monkeypatch.setitem(__import__("sys").modules, "MetaTrader5", fake_mt5)

    old_time = __import__("time").time() - 7200
    recent_time = __import__("time").time() - 600
    pos_close = SimpleNamespace(ticket=1, symbol="BTCUSD", magic=789456, type=0, price_open=100.0, sl=95.0, tp=120.0, time=old_time, profit=15.0, volume=1.0)
    pos_be = SimpleNamespace(ticket=2, symbol="BTCUSD", magic=789456, type=0, price_open=100.0, sl=95.0, tp=120.0, time=recent_time, profit=5.0, volume=1.0)
    pos_trail = SimpleNamespace(ticket=3, symbol="BTCUSD", magic=789456, type=1, price_open=120.0, sl=130.0, tp=100.0, time=recent_time, profit=8.0, volume=1.0)
    pos_hold = SimpleNamespace(ticket=4, symbol="BTCUSD", magic=789456, type=0, price_open=109.5, sl=100.0, tp=130.0, time=recent_time, profit=1.0, volume=1.0)
    pos_skip = SimpleNamespace(ticket=5, symbol="BTCUSD", magic=111111, type=0, price_open=100.0, sl=95.0, tp=120.0, time=recent_time, profit=0.0, volume=1.0)
    fake_mt5._positions = [pos_close, pos_be, pos_trail, pos_hold, pos_skip]

    monkeypatch.setattr(pm.PositionMonitor, "_record_close", lambda self, pos: recorded.append(("close", pos.ticket)))
    result = monitor.check_positions()
    actions = {item["ticket"]: item for item in result["actions"]}
    assert result["status"] == "OK"
    assert actions[1]["action"] == "CLOSED"
    assert actions[2]["action"] == "BREAK_EVEN"
    assert actions[3]["action"] == "TRAILING_SL"
    assert actions[4]["action"] == "HOLDING"

    pm_hold = pm.PositionMonitor({"filter_symbol": "ETHUSD"})
    assert pm_hold.check_positions()["status"] == "No open positions"
