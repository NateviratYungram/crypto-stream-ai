import asyncio
import sys
from types import ModuleType
from types import SimpleNamespace

from intelligence.sentinel import alpha_sentinel as module


class FakeNotifier:
    def __init__(self):
        self.messages = []

    async def broadcast(self, message):
        self.messages.append(message)
        return True


def test_helper_functions_cover_basic_branches():
    assert module._asset_class_for_symbol("BTC") == "CRYPTO"
    assert module._asset_class_for_symbol("GOLD") == "MACRO"
    assert module._is_high_confidence_opportunity({"win_probability": 0.81, "whale_pulse": {}}) is True
    assert module._is_high_confidence_opportunity({"win_probability": 0.71, "whale_pulse": {"injections": True}}) is True
    assert module._is_high_confidence_opportunity({"win_probability": 0.69, "whale_pulse": {"injections": True}}) is False


def test_position_helpers_detect_profit_break_even_and_threat():
    mt5 = SimpleNamespace(POSITION_TYPE_BUY=0)
    buy_pos = SimpleNamespace(type=0, price_open=100.0, price_current=105.0, sl=100.0)
    sell_pos = SimpleNamespace(type=1, price_open=100.0, price_current=95.0, sl=100.0)

    assert module._is_position_in_profit(buy_pos, mt5) is True
    assert module._already_at_break_even(buy_pos, mt5) is True
    assert module._is_position_in_profit(sell_pos, mt5) is True
    assert module._already_at_break_even(sell_pos, mt5) is True

    buy_threat = module._detect_counter_wall_threat(
        SimpleNamespace(type=0, price_open=100.0, price_current=110.0, sl=0),
        {"walls": {"sell": [{"price": "105"}]}},
        mt5,
    )
    sell_threat = module._detect_counter_wall_threat(
        SimpleNamespace(type=1, price_open=100.0, price_current=90.0, sl=0),
        {"walls": {"buy": [{"price": "120"}]}},
        mt5,
    )
    assert buy_threat is True
    assert sell_threat is False


def test_scan_for_alpha_notifies_only_high_confidence_symbols():
    notifier = FakeNotifier()

    def analysis_fn(symbol, timeframe, asset_class):
        if symbol == "BTC":
            return {"signal": "BUY", "win_probability": 0.82, "whale_pulse": {"bias": "BULL"}}
        if symbol == "ETH":
            return {"signal": "SELL", "win_probability": 0.71, "whale_pulse": {"injections": True, "bias": "BEAR"}}
        return {"signal": "HOLD", "win_probability": 0.9, "whale_pulse": {}}

    sentinel = module.AlphaSentinel(interval_seconds=1, notifier=notifier, analysis_fn=analysis_fn)
    sentinel.target_symbols = ["BTC", "ETH", "SOL"]

    asyncio.run(sentinel.scan_for_alpha())

    assert len(notifier.messages) == 2
    assert any("BTC" in item for item in notifier.messages)
    assert any("ETH" in item for item in notifier.messages)


def test_scan_for_alpha_swallow_symbol_errors():
    notifier = FakeNotifier()

    def analysis_fn(symbol, timeframe, asset_class):
        if symbol == "BTC":
            raise RuntimeError("boom")
        return {"signal": "BUY", "win_probability": 0.9, "whale_pulse": {"bias": "BULL"}}

    sentinel = module.AlphaSentinel(interval_seconds=1, notifier=notifier, analysis_fn=analysis_fn)
    sentinel.target_symbols = ["BTC", "ETH"]

    asyncio.run(sentinel.scan_for_alpha())

    assert len(notifier.messages) == 1
    assert "ETH" in notifier.messages[0]


def test_default_mt5_loader_imports_module(monkeypatch):
    fake_mt5 = ModuleType("MetaTrader5")
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake_mt5)
    sentinel = module.AlphaSentinel(notifier=FakeNotifier())

    assert sentinel._default_mt5_loader() is fake_mt5


def test_guard_active_trades_handles_missing_mt5_and_init_failure():
    notifier = FakeNotifier()
    sentinel = module.AlphaSentinel(notifier=notifier, mt5_loader=lambda: (_ for _ in ()).throw(ImportError("missing")))
    asyncio.run(sentinel.guard_active_trades())
    assert notifier.messages == []

    mt5 = SimpleNamespace(initialize=lambda: False)
    sentinel = module.AlphaSentinel(notifier=notifier, mt5_loader=lambda: mt5)
    asyncio.run(sentinel.guard_active_trades())
    assert notifier.messages == []


def test_guard_active_trades_returns_when_no_positions():
    notifier = FakeNotifier()
    mt5 = SimpleNamespace(
        POSITION_TYPE_BUY=0,
        initialize=lambda: True,
        positions_get=lambda: [],
    )
    sentinel = module.AlphaSentinel(notifier=notifier, mt5_loader=lambda: mt5)

    asyncio.run(sentinel.guard_active_trades())

    assert notifier.messages == []


def test_guard_active_trades_actions_success_and_failure():
    notifier = FakeNotifier()
    positions = [
        SimpleNamespace(symbol="BTC", ticket=1, price_current=110.0, price_open=100.0, type=0, sl=0.0, tp=120.0),
        SimpleNamespace(symbol="ETH", ticket=2, price_current=110.0, price_open=100.0, type=0, sl=0.0, tp=120.0),
    ]
    mt5 = SimpleNamespace(
        POSITION_TYPE_BUY=0,
        initialize=lambda: True,
        positions_get=lambda: positions,
    )

    def analysis_fn(symbol, timeframe, asset_class):
        return {"whale_pulse": {"walls": {"sell": [{"price": "105"}]}}}

    calls = []

    def modify_position_fn(**kwargs):
        calls.append(kwargs)
        if kwargs["ticket"] == 1:
            return {"status": "SUCCESS"}
        return {"status": "ERROR", "comment": "broker reject"}

    sentinel = module.AlphaSentinel(
        notifier=notifier,
        analysis_fn=analysis_fn,
        modify_position_fn=modify_position_fn,
        mt5_loader=lambda: mt5,
    )

    asyncio.run(sentinel.guard_active_trades())

    assert len(calls) == 2
    assert len(notifier.messages) == 2
    assert any("ACTIONED" in msg for msg in notifier.messages)
    assert any("Action failed" in msg for msg in notifier.messages)


def test_guard_active_trades_skips_unthreatened_or_break_even_positions():
    notifier = FakeNotifier()
    positions = [
        SimpleNamespace(symbol="BTC", ticket=1, price_current=90.0, price_open=100.0, type=0, sl=0.0, tp=120.0),
        SimpleNamespace(symbol="ETH", ticket=2, price_current=110.0, price_open=100.0, type=0, sl=100.0, tp=120.0),
    ]
    mt5 = SimpleNamespace(
        POSITION_TYPE_BUY=0,
        initialize=lambda: True,
        positions_get=lambda: positions,
    )

    def analysis_fn(symbol, timeframe, asset_class):
        return {"whale_pulse": {"walls": {"sell": [{"price": "105"}]}}}

    calls = []
    sentinel = module.AlphaSentinel(
        notifier=notifier,
        analysis_fn=analysis_fn,
        modify_position_fn=lambda **kwargs: calls.append(kwargs) or {"status": "SUCCESS"},
        mt5_loader=lambda: mt5,
    )

    asyncio.run(sentinel.guard_active_trades())

    assert calls == []
    assert notifier.messages == []


def test_guard_active_trades_swallow_runtime_errors():
    notifier = FakeNotifier()
    sentinel = module.AlphaSentinel(
        notifier=notifier,
        analysis_fn=lambda *args: (_ for _ in ()).throw(RuntimeError("analysis failed")),
        mt5_loader=lambda: SimpleNamespace(
            POSITION_TYPE_BUY=0,
            initialize=lambda: True,
            positions_get=lambda: [SimpleNamespace(symbol="BTC", ticket=1, price_current=110.0, price_open=100.0, type=0, sl=0.0, tp=120.0)],
        ),
    )

    asyncio.run(sentinel.guard_active_trades())

    assert notifier.messages == []


def test_notify_alpha_and_run_cancelled_flow():
    notifier = FakeNotifier()
    sentinel = module.AlphaSentinel(interval_seconds=1, notifier=notifier, analysis_fn=lambda *args: {})

    asyncio.run(sentinel.notify_alpha("BTC", {"signal": "BUY", "win_probability": 0.88, "whale_pulse": {"bias": "BULL"}}))
    assert "ALPHA SENTINEL TRIGGER" in notifier.messages[0]

    state = {"scan": 0, "guard": 0, "sleep": 0}

    async def fake_scan():
        state["scan"] += 1

    async def fake_guard():
        state["guard"] += 1

    async def fake_sleep(seconds):
        state["sleep"] += 1
        raise asyncio.CancelledError()

    sentinel.scan_for_alpha = fake_scan
    sentinel.guard_active_trades = fake_guard

    original_sleep = module.asyncio.sleep
    module.asyncio.sleep = fake_sleep
    try:
        asyncio.run(sentinel.run())
    finally:
        module.asyncio.sleep = original_sleep

    assert state == {"scan": 1, "guard": 1, "sleep": 1}


def test_run_recovers_from_loop_error():
    notifier = FakeNotifier()
    sentinel = module.AlphaSentinel(interval_seconds=1, notifier=notifier, analysis_fn=lambda *args: {})
    state = {"scan": 0, "guard": 0, "sleep_calls": []}

    async def fake_scan():
        state["scan"] += 1
        if state["scan"] == 1:
            raise RuntimeError("loop boom")
        raise asyncio.CancelledError()

    async def fake_guard():
        state["guard"] += 1

    async def fake_sleep(seconds):
        state["sleep_calls"].append(seconds)
        return None

    sentinel.scan_for_alpha = fake_scan
    sentinel.guard_active_trades = fake_guard
    original_sleep = module.asyncio.sleep
    module.asyncio.sleep = fake_sleep
    try:
        asyncio.run(sentinel.run())
    finally:
        module.asyncio.sleep = original_sleep

    assert state["scan"] == 2
    assert state["sleep_calls"] == [60]
