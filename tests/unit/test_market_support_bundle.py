import base64
import builtins
import io
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from intelligence import chart_generator, hyperliquid_price, trade_replay
from streaming import load_tester


def test_hyperliquid_price_paths(monkeypatch):
    assert hyperliquid_price._normalise("BTCUSDT") == "BTC"
    assert hyperliquid_price._normalise("eth-usd") == "ETH"
    assert hyperliquid_price._normalise("sol/usdt") == "SOL/"
    assert hyperliquid_price._normalise("dex:BTC") == "dex:BTC"

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    calls = []
    monkeypatch.setattr(
        "requests.post",
        lambda url, json, timeout: calls.append((url, json, timeout)) or FakeResponse({"ok": True}),
    )
    assert hyperliquid_price._post({"type": "x"}) == {"ok": True}
    assert calls

    sleeps = []
    attempts = {"n": 0}

    def flaky_post(url, json, timeout):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("temp")
        return FakeResponse({"done": True})

    monkeypatch.setattr("requests.post", flaky_post)
    monkeypatch.setattr(hyperliquid_price.time, "sleep", lambda delay: sleeps.append(delay))
    assert hyperliquid_price._post({"type": "retry"}) == {"done": True}
    assert sleeps == [0.35, 0.7]

    monkeypatch.setattr("requests.post", lambda url, json, timeout: (_ for _ in ()).throw(RuntimeError("fail")))
    monkeypatch.setattr(hyperliquid_price.time, "sleep", lambda delay: None)
    with pytest.raises(RuntimeError):
        hyperliquid_price._post({"type": "boom"})

    monkeypatch.setattr(
        hyperliquid_price,
        "_post",
        lambda payload: {"levels": [[{"px": "100"}], [{"px": "102"}]]},
    )
    assert hyperliquid_price.get_hl_mid_price("BTC") == 101.0
    monkeypatch.setattr(hyperliquid_price, "_post", lambda payload: {"levels": [[{"px": "100"}], []]})
    assert hyperliquid_price.get_hl_mid_price("BTC") == 100.0
    monkeypatch.setattr(hyperliquid_price, "_post", lambda payload: {"levels": []})
    assert hyperliquid_price.get_hl_mid_price("BTC") is None
    monkeypatch.setattr(hyperliquid_price, "_post", lambda payload: (_ for _ in ()).throw(RuntimeError("x")))
    assert hyperliquid_price.get_hl_mid_price("BTC") is None

    assert hyperliquid_price._parse_utc("2025-01-01T10:00:00Z").tzinfo is not None
    assert hyperliquid_price._parse_utc("bad-ts") is None

    monkeypatch.setattr(
        hyperliquid_price,
        "_post",
        lambda payload: [
            {"t": payload["req"]["startTime"], "c": "100.5"},
            {"t": payload["req"]["endTime"], "c": "101.5"},
        ],
    )
    assert hyperliquid_price.get_hl_price_at("ETHUSDT", "2025-01-01T10:00:00Z") == 100.5
    monkeypatch.setattr(hyperliquid_price, "_post", lambda payload: [])
    assert hyperliquid_price.get_hl_price_at("ETH", "2025-01-01T10:00:00Z") is None
    assert hyperliquid_price.get_hl_price_at("ETH", "bad") is None

    monkeypatch.setattr(hyperliquid_price, "get_hl_price_at", lambda symbol, executed_at: 77.7)
    monkeypatch.setattr(hyperliquid_price, "get_hl_mid_price", lambda symbol: 88.8)
    assert hyperliquid_price.fill_trade_price("BTC", "2025-01-01T10:00:00Z") == 77.7
    monkeypatch.setattr(hyperliquid_price, "get_hl_price_at", lambda symbol, executed_at: None)
    assert hyperliquid_price.fill_trade_price("BTC", "2025-01-01T10:00:00Z") == 88.8
    assert hyperliquid_price.fill_trade_price("BTC") == 88.8


def test_trade_replay_paths(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "intelligence.trade_logger",
        SimpleNamespace(get_trade_logger=lambda config=None: (_ for _ in ()).throw(RuntimeError("no history"))),
    )
    load_fail = trade_replay.analyze_past_trades(SimpleNamespace())
    assert "Cannot load trade history" in load_fail["analysis"]

    monkeypatch.setitem(
        sys.modules,
        "intelligence.trade_logger",
        SimpleNamespace(get_trade_logger=lambda config=None: SimpleNamespace(_load=lambda: [])),
    )
    no_history = trade_replay.analyze_past_trades(SimpleNamespace())
    assert no_history["trades_analyzed"] == 0

    history = [
        {"status": "EXECUTED", "profit": 10, "symbol": "BTCUSD"},
        {"status": "EXECUTED", "profit": -5, "symbol": "ETHUSD", "action": "BUY", "confidence": 61, "entry_price": 1, "sl": 0.9, "tp": 1.2, "reasoning": "late entry", "timestamp": "now"},
        {"status": "DRY_RUN", "pnl": -2, "symbol": "XAUUSD", "direction": "SELL", "confidence": 55, "entry_price": 2, "sl": 3, "tp": 1, "reasoning": "bad regime", "timestamp": "later"},
    ]
    monkeypatch.setitem(
        sys.modules,
        "intelligence.trade_logger",
        SimpleNamespace(
            get_trade_logger=lambda config=None: SimpleNamespace(
                _load=lambda: history,
                get_recent_trades=lambda count=20: history[-count:],
            )
        ),
    )

    no_losers = trade_replay.analyze_past_trades(SimpleNamespace(), num_trades=1)
    assert no_losers["trades_analyzed"] == 1

    fake_response = SimpleNamespace(
        text='{"common_patterns":"late entries","specific_mistakes":[{"trade":1,"mistake":"chased move"}],"lessons":[{"rule":"Raise threshold","reason":"weak setups","action":"increase min confidence"}],"suggested_improvements":"tighten filter","overall_assessment":"IMPROVABLE"}'
    )
    client = SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kwargs: fake_response))
    analyzed = trade_replay.analyze_past_trades(client, num_trades=5)
    assert analyzed["trades_analyzed"] == 2
    assert analyzed["assessment"] == "IMPROVABLE"
    assert "Lessons Learned" in analyzed["analysis"]

    broken_client = SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("llm fail"))))
    failed = trade_replay.analyze_past_trades(broken_client, num_trades=2)
    assert failed["error"] == "llm fail"

    summary = trade_replay.get_trade_summary(count=5)
    assert len(summary) == 3
    assert summary[1]["win"] is False

    monkeypatch.setitem(
        sys.modules,
        "intelligence.trade_logger",
        SimpleNamespace(get_trade_logger=lambda config=None: (_ for _ in ()).throw(RuntimeError("bad summary"))),
    )
    assert trade_replay.get_trade_summary() == []


def test_load_tester_paths(monkeypatch):
    class FakeProducer:
        def __init__(self):
            self.sent = []
            self.flushed = 0
            self.closed = False

        def send(self, topic, value):
            self.sent.append((topic, value))

        def flush(self):
            self.flushed += 1

        def close(self):
            self.closed = True

    monkeypatch.setattr(load_tester, "KafkaProducer", lambda **kwargs: FakeProducer())
    producer = load_tester.get_kafka_producer()
    assert producer is not None

    monkeypatch.setattr(load_tester, "KafkaProducer", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("kafka down")))
    assert load_tester.get_kafka_producer() is None

    monkeypatch.setattr(load_tester.random, "randint", lambda a, b: 123)
    monkeypatch.setattr(load_tester.random, "choice", lambda xs: True)
    monkeypatch.setattr(load_tester.random, "uniform", lambda a, b: (a + b) / 2)
    normal = load_tester.generate_mock_trade("normal")
    whale = load_tester.generate_mock_trade("whale")
    invalid_qty = load_tester.generate_mock_trade("invalid_null_qty")
    invalid_price = load_tester.generate_mock_trade("invalid_negative_price")
    assert normal["symbol"] == "BTCUSDT"
    assert whale["quantity"] > 0.5
    assert invalid_qty["quantity"] is None
    assert invalid_price["price"] < 0

    monkeypatch.setattr(load_tester, "get_kafka_producer", lambda: None)
    with pytest.raises(SystemExit) as exit_info:
        load_tester.run_load_test()
    assert exit_info.value.code == 1

    fake = FakeProducer()
    monkeypatch.setattr(load_tester, "get_kafka_producer", lambda: fake)
    monkeypatch.setattr(load_tester, "TARGET_TPS", 2)
    monkeypatch.setattr(load_tester, "DURATION_SECONDS", 1)
    seq = iter([0.1, 0.92])
    monkeypatch.setattr(load_tester.random, "random", lambda: next(seq))
    monkeypatch.setattr(
        load_tester,
        "generate_mock_trade",
        lambda scenario="normal": {"symbol": scenario, "price": 1, "quantity": 1, "timestamp": 1, "trade_id": 1, "is_buyer_maker": False},
    )
    t = {"v": 0.0}
    monkeypatch.setattr(load_tester.time, "time", lambda: t.update(v=t["v"] + 0.6) or t["v"])
    monkeypatch.setattr(load_tester.time, "sleep", lambda delay: None)
    load_tester.run_load_test()
    assert len(fake.sent) == 2
    assert fake.closed is True


def test_chart_generator_helpers(monkeypatch):
    close = pd.Series([10, 11, 12, 13, 14, 15], dtype=float)
    high = close + 1
    low = close - 1

    assert chart_generator._check_trend_line(True, 2, 1.0, low) >= 0
    assert chart_generator._check_trend_line(False, 2, 1.0, high) >= 0

    slope, intercept = chart_generator._optimize_slope(True, 1, 0.1, low)
    assert isinstance(slope, float)
    assert isinstance(intercept, float)

    support, resist = chart_generator._fit_trendlines_high_low(high, low, close)
    assert len(support) == 2
    assert len(resist) == 2

    df = pd.DataFrame(
        {
            "Datetime": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "Open": [1.0, 2.0],
            "High": [2.0, 3.0],
            "Low": [0.5, 1.5],
            "Close": [1.5, 2.5],
            "Volume": [10, 20],
        }
    )
    mpf_df = chart_generator._df_to_mpf(df)
    assert list(mpf_df.columns) == ["Open", "High", "Low", "Close", "Volume"]

    closed = []

    class FakeFig:
        def savefig(self, buf, format="png", dpi=120, bbox_inches="tight", pad_inches=0.1):
            buf.write(b"png-bytes")

    monkeypatch.setitem(sys.modules, "matplotlib.pyplot", SimpleNamespace(close=lambda fig: closed.append(fig)))
    encoded = chart_generator._fig_to_base64(FakeFig())
    assert base64.b64decode(encoded) == b"png-bytes"
    assert closed

    real_import = builtins.__import__

    def _import_fail(name, *args, **kwargs):
        if name == "mplfinance":
            raise ImportError("no mplfinance")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _import_fail)
    assert chart_generator.generate_kline_chart(df, "BTC") == ""
    assert chart_generator.generate_trend_chart(df, "BTC") == ""
    assert chart_generator.generate_indicator_chart(df, "BTC") == ""
