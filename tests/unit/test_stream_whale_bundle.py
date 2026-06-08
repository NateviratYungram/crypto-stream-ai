import importlib
import sys
from types import SimpleNamespace

import pandas as pd

from intelligence import chart_generator, whale_engine


def test_whale_engine_paths(monkeypatch):
    engine = whale_engine.WhalePulseEngine()

    macro = engine.get_whale_walls("XAUUSD")
    assert macro["bias"] == "NEUTRAL"
    assert "Macro assets" in macro["message"]

    class FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    payload = {
        "bids": [[str(100 - i), "1"] for i in range(99)] + [["1", "10"]],
        "asks": [[str(101 + i), "1"] for i in range(99)] + [["999", "12"]],
    }
    monkeypatch.setattr(whale_engine.requests, "get", lambda url, params, timeout=5: FakeResponse(200, payload))
    walls = engine.get_whale_walls("BTCUSDT")
    assert walls["bias"] == "NEUTRAL"
    assert len(walls["buy_walls"]) == 1
    assert len(walls["sell_walls"]) == 1

    monkeypatch.setattr(whale_engine.requests, "get", lambda url, params, timeout=5: FakeResponse(500, {}))
    unavailable = engine.get_whale_walls("BTC")
    assert unavailable["error"] == "Order Book unavailable"

    monkeypatch.setattr(whale_engine.requests, "get", lambda url, params, timeout=5: (_ for _ in ()).throw(RuntimeError("boom")))
    assert engine.get_whale_walls("BTC")["bias"] == "NEUTRAL"

    df = pd.DataFrame(
        {
            "Datetime": pd.date_range("2026-01-01", periods=25, freq="h"),
            "Open": [100.0] * 25,
            "Close": [101.0] * 24 + [110.0],
            "Volume": [10.0] * 24 + [50.0],
        }
    )
    injections = engine.detect_volume_injections(df)
    assert injections and injections[-1]["type"] == "BULLISH_INJECTION"
    assert engine.detect_volume_injections(pd.DataFrame()) == []

    bearish_df = df.copy()
    bearish_df.loc[bearish_df.index[-1], "Close"] = 90.0
    monkeypatch.setattr(engine, "get_whale_walls", lambda symbol: {"bias": "ACCUMULATION", "buy_walls": [{"x": 1}], "sell_walls": []})
    bias = engine.get_institutional_bias("BTC", bearish_df)
    assert bias["bias"] == "FIGHTING"
    assert bias["institutional_confidence"] == "HIGH"


def test_chart_generator_success_paths(monkeypatch):
    plots = []

    class FakeAxes:
        def __init__(self):
            self.ylabel = None
            self.legend_args = None

        def set_ylabel(self, label, color=None):
            self.ylabel = (label, color)

        def legend(self, *args, **kwargs):
            self.legend_args = (args, kwargs)

    class FakeFig:
        def savefig(self, buf, format="png", dpi=120, bbox_inches="tight", pad_inches=0.1):
            buf.write(b"chart-bytes")

    fake_axes = [FakeAxes()]

    fake_mpf = SimpleNamespace(
        make_mpf_style=lambda **kwargs: {"style": kwargs},
        make_addplot=lambda data, **kwargs: {"data": list(data) if hasattr(data, "__iter__") else data, **kwargs},
        plot=lambda *args, **kwargs: (plots.append(kwargs) or (FakeFig(), fake_axes)),
    )
    fake_pyplot = SimpleNamespace(close=lambda fig: None)
    monkeypatch.setitem(sys.modules, "mplfinance", fake_mpf)
    monkeypatch.setitem(sys.modules, "matplotlib.pyplot", fake_pyplot)
    monkeypatch.setitem(sys.modules, "matplotlib", SimpleNamespace(use=lambda backend: None, pyplot=fake_pyplot))

    df = pd.DataFrame(
        {
            "Datetime": pd.date_range("2026-01-01", periods=60, freq="h"),
            "Open": [100 + i for i in range(60)],
            "High": [101 + i for i in range(60)],
            "Low": [99 + i for i in range(60)],
            "Close": [100.5 + i for i in range(60)],
            "Volume": [1000 + i for i in range(60)],
            "ema_20": [100 + i for i in range(60)],
            "ema_50": [95 + i for i in range(60)],
            "rsi_14": [50 + (i % 10) for i in range(60)],
            "macd_hist": [(-1) ** i * 0.5 for i in range(60)],
        }
    )

    kline = chart_generator.generate_kline_chart(df, "BTC")
    trend = chart_generator.generate_trend_chart(df, "BTC")
    indicator = chart_generator.generate_indicator_chart(df, "BTC")

    assert kline and trend and indicator
    assert plots[0]["volume"] is True
    assert plots[1]["volume"] is False
    assert plots[2]["panel_ratios"] == (3, 1, 1)


def test_flink_processor_main_with_fakes(monkeypatch):
    fake_datastream = SimpleNamespace(
        StreamExecutionEnvironment=SimpleNamespace(get_execution_environment=lambda: None),
        TimeCharacteristic=SimpleNamespace(EventTime="EVENT_TIME"),
    )
    fake_table = SimpleNamespace(
        EnvironmentSettings=SimpleNamespace(new_instance=lambda: None),
        StreamTableEnvironment=SimpleNamespace(create=lambda env, environment_settings=None: None),
    )
    monkeypatch.setitem(sys.modules, "pyflink", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "pyflink.datastream", fake_datastream)
    monkeypatch.setitem(sys.modules, "pyflink.table", fake_table)
    if "streaming.flink_processor" in sys.modules:
        del sys.modules["streaming.flink_processor"]
    flink_processor = importlib.import_module("streaming.flink_processor")

    executed_sql = []
    inserts = []

    class FakeStatementSet:
        def add_insert_sql(self, sql):
            inserts.append(sql)

        def execute(self):
            return SimpleNamespace(get_job_client=lambda: SimpleNamespace(get_job_id=lambda: "job-123"))

    class FakeTableEnv:
        def execute_sql(self, sql):
            executed_sql.append(sql)

        def create_statement_set(self):
            return FakeStatementSet()

    class FakeEnv:
        def __init__(self):
            self.parallelism = None
            self.time_characteristic = None

        def set_parallelism(self, value):
            self.parallelism = value

        def set_stream_time_characteristic(self, value):
            self.time_characteristic = value

    fake_env = FakeEnv()
    monkeypatch.setattr(
        flink_processor.StreamExecutionEnvironment,
        "get_execution_environment",
        lambda: fake_env,
    )
    monkeypatch.setattr(
        flink_processor.EnvironmentSettings,
        "new_instance",
        lambda: SimpleNamespace(in_streaming_mode=lambda: SimpleNamespace(build=lambda: "settings")),
    )
    monkeypatch.setattr(
        flink_processor.StreamTableEnvironment,
        "create",
        lambda env, environment_settings=None: FakeTableEnv(),
    )
    monkeypatch.setattr(flink_processor, "TimeCharacteristic", SimpleNamespace(EventTime="EVENT_TIME"))

    flink_processor.main()

    assert fake_env.parallelism == 1
    assert fake_env.time_characteristic == "EVENT_TIME"
    assert any("CREATE TABLE trade_stream" in sql for sql in executed_sql)
    assert any("CREATE VIEW tagged_trades" in sql for sql in executed_sql)
    assert len(inserts) == 8
