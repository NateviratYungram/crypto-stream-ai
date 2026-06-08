from types import SimpleNamespace

import pandas as pd
import pytest

from services import yfinance_ingestion_service as service


class FakeCursor:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeConn:
    def __init__(self):
        self.cursor_obj = FakeCursor()
        self.committed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True


def test_upsert_ohlcv_returns_zero_for_empty_rows():
    assert service.upsert_ohlcv(FakeConn(), []) == 0


def test_load_symbols_extracts_unique_tickers(monkeypatch):
    fake_module = SimpleNamespace(TRADE_TRAIN_SYMBOLS=[("BTCUSD", "crypto", "1h"), ("BTCUSD", "crypto", "4h"), ("ETHUSD", "crypto", "1h")])
    monkeypatch.setitem(__import__("sys").modules, "intelligence.ml.signal_model", fake_module)

    symbols = service._load_symbols()

    assert set(symbols) == {"BTCUSD", "ETHUSD"}


def test_get_conn_delegates_to_psycopg(monkeypatch):
    monkeypatch.setattr(service.psycopg2, "connect", lambda **kwargs: kwargs)

    result = service.get_conn()

    assert result == service.DB_CONFIG


def test_upsert_ohlcv_executes_bulk_insert(monkeypatch):
    conn = FakeConn()
    captured = {}

    def fake_execute_values(cur, sql, tuples, page_size):
        captured["sql"] = sql
        captured["tuples"] = tuples
        captured["page_size"] = page_size

    monkeypatch.setattr(service.psycopg2.extras, "execute_values", fake_execute_values)
    rows = [
        {
            "symbol": "BTCUSD",
            "timeframe": "15m",
            "ts": pd.Timestamp("2026-05-26T00:00:00Z").to_pydatetime(),
            "open": 1.0,
            "high": 2.0,
            "low": 0.5,
            "close": 1.5,
            "volume": 10.0,
        }
    ]

    result = service.upsert_ohlcv(conn, rows)

    assert result == 1
    assert conn.committed is True
    assert captured["page_size"] == 500
    assert captured["tuples"][0][0] == "BTCUSD"


def test_with_backoff_retries_then_succeeds(monkeypatch):
    sleeps = []
    attempts = {"count": 0}

    def flaky():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("temporary")
        return "ok"

    monkeypatch.setattr(service.time, "sleep", lambda delay: sleeps.append(delay))

    result = service._with_backoff(flaky, max_retries=4, base_delay=5.0)

    assert result == "ok"
    assert attempts["count"] == 3
    assert sleeps == [5.0, 10.0]


def test_with_backoff_raises_after_final_failure(monkeypatch):
    monkeypatch.setattr(service.time, "sleep", lambda delay: None)

    def always_fail():
        raise ValueError("bad")

    try:
        service._with_backoff(always_fail, max_retries=2, base_delay=1.0)
    except ValueError as exc:
        assert str(exc) == "bad"
    else:
        raise AssertionError("expected ValueError")


def test_df_to_rows_handles_adj_close_and_bad_values():
    df = pd.DataFrame(
        {
            "Open": [1.0, "bad"],
            "High": [2.0, 2.0],
            "Low": [0.5, 0.5],
            "Adj Close": [1.5, 2.5],
            "Volume": [10, 20],
        },
        index=["2026-05-26T00:00:00Z", "2026-05-26T01:00:00Z"],
    )

    rows = service._df_to_rows(df, "BTCUSD", "1h")

    assert len(rows) == 1
    assert rows[0]["symbol"] == "BTCUSD"
    assert rows[0]["close"] == 1.5


def test_fetch_ohlcv_returns_empty_for_no_symbols():
    assert service.fetch_ohlcv([], period="2d", interval="15m") == []


def test_fetch_ohlcv_handles_download_error(monkeypatch):
    monkeypatch.setattr(service, "_with_backoff", lambda fn: (_ for _ in ()).throw(RuntimeError("down")))

    result = service.fetch_ohlcv(["BTCUSD"], period="2d", interval="15m")

    assert result == []


def test_fetch_ohlcv_returns_empty_when_download_returns_none(monkeypatch):
    monkeypatch.setattr(service, "_with_backoff", lambda fn: None)

    assert service.fetch_ohlcv(["BTCUSD"], period="2d", interval="15m") == []


def test_fetch_ohlcv_returns_empty_when_download_returns_empty_frame(monkeypatch):
    monkeypatch.setattr(service, "_with_backoff", lambda fn: pd.DataFrame())

    assert service.fetch_ohlcv(["BTCUSD"], period="2d", interval="15m") == []


def test_fetch_ohlcv_downloads_through_yfinance_when_backoff_runs_normally(monkeypatch):
    captured = {}
    raw = pd.DataFrame(
        {"Open": [1.0], "High": [2.0], "Low": [0.5], "Close": [1.5], "Volume": [10]},
        index=[pd.Timestamp("2026-05-26T00:00:00Z")],
    )

    monkeypatch.setattr(service.yf, "download", lambda tickers, **kwargs: captured.update({"tickers": tickers, **kwargs}) or raw)

    rows = service.fetch_ohlcv(["BTCUSD"], period="2d", interval="15m")

    assert rows[0]["symbol"] == "BTCUSD"
    assert captured["interval"] == "15m"


def test_fetch_ohlcv_single_ticker(monkeypatch):
    raw = pd.DataFrame(
        {"Open": [1.0], "High": [2.0], "Low": [0.5], "Close": [1.5], "Volume": [10]},
        index=[pd.Timestamp("2026-05-26T00:00:00Z")],
    )
    monkeypatch.setattr(service, "_with_backoff", lambda fn: raw)

    rows = service.fetch_ohlcv(["BTCUSD"], period="2d", interval="15m")

    assert len(rows) == 1
    assert rows[0]["symbol"] == "BTCUSD"


def test_fetch_ohlcv_multi_ticker(monkeypatch):
    columns = pd.MultiIndex.from_product(
        [["AAA", "BBB"], ["Open", "High", "Low", "Close", "Volume"]]
    )
    raw = pd.DataFrame(
        [[1.0, 2.0, 0.5, 1.5, 10, 3.0, 4.0, 2.5, 3.5, 20]],
        index=[pd.Timestamp("2026-05-26T00:00:00Z")],
        columns=columns,
    )
    monkeypatch.setattr(service, "_with_backoff", lambda fn: raw)

    rows = service.fetch_ohlcv(["AAA", "BBB"], period="2d", interval="15m")

    assert {row["symbol"] for row in rows} == {"AAA", "BBB"}


def test_fetch_ohlcv_multi_ticker_ignores_extraction_errors(monkeypatch):
    class BrokenColumns:
        def get_level_values(self, idx):
            raise RuntimeError("broken columns")

    raw = SimpleNamespace(columns=BrokenColumns(), empty=False)
    monkeypatch.setattr(service, "_with_backoff", lambda fn: raw)

    assert service.fetch_ohlcv(["AAA", "BBB"], period="2d", interval="15m") == []


def test_fetch_ohlcv_multi_ticker_skips_missing_symbol_columns(monkeypatch):
    columns = pd.MultiIndex.from_product(
        [["AAA"], ["Open", "High", "Low", "Close", "Volume"]]
    )
    raw = pd.DataFrame(
        [[1.0, 2.0, 0.5, 1.5, 10]],
        index=[pd.Timestamp("2026-05-26T00:00:00Z")],
        columns=columns,
    )
    monkeypatch.setattr(service, "_with_backoff", lambda fn: raw)

    rows = service.fetch_ohlcv(["AAA", "BBB"], period="2d", interval="15m")

    assert rows == [
        {
            "symbol": "AAA",
            "timeframe": "15m",
            "ts": pd.Timestamp("2026-05-26T00:00:00Z").to_pydatetime(),
            "open": 1.0,
            "high": 2.0,
            "low": 0.5,
            "close": 1.5,
            "volume": 10.0,
        }
    ]


def test_backfill_calls_expected_periods(monkeypatch):
    fetched = []
    upserted = []
    monkeypatch.setattr(
        service,
        "fetch_ohlcv",
        lambda symbols, period, interval: fetched.append((tuple(symbols), period, interval)) or [{"symbol": "BTCUSD"}],
    )
    monkeypatch.setattr(service, "upsert_ohlcv", lambda conn, rows: upserted.append(list(rows)) or len(rows))

    service.backfill(object(), ["BTCUSD", "ETHUSD"])

    assert fetched == [
        (("BTCUSD", "ETHUSD"), "60d", "15m"),
        (("BTCUSD", "ETHUSD"), "730d", "1h"),
        (("BTCUSD", "ETHUSD"), "730d", "4h"),
        (("BTCUSD", "ETHUSD"), "10y", "1d"),
    ]
    assert len(upserted) == 4


def test_refresh_assets_skips_empty_batches(monkeypatch):
    fetched = []
    monkeypatch.setattr(
        service,
        "fetch_ohlcv",
        lambda symbols, period, interval: fetched.append((period, interval)) or ([] if interval == "1h" else [{"symbol": "BTCUSD"}]),
    )
    calls = []
    monkeypatch.setattr(service, "upsert_ohlcv", lambda conn, rows: calls.append(rows) or len(rows))

    service.refresh_assets(object(), ["BTCUSD"])

    assert fetched == [("2d", "15m"), ("7d", "1h"), ("14d", "4h"), ("30d", "1d")]
    assert len(calls) == 3


def test_backfill_and_refresh_cover_empty_branches(monkeypatch):
    calls = []
    payloads = {
        ("60d", "15m"): [{"symbol": "BTCUSD"}],
        ("730d", "1h"): [],
        ("730d", "4h"): [{"symbol": "BTCUSD"}],
        ("10y", "1d"): [],
        ("2d", "15m"): [],
        ("7d", "1h"): [{"symbol": "BTCUSD"}],
        ("14d", "4h"): [],
        ("30d", "1d"): [{"symbol": "BTCUSD"}],
    }
    monkeypatch.setattr(service, "fetch_ohlcv", lambda symbols, period, interval: payloads[(period, interval)])
    monkeypatch.setattr(service, "upsert_ohlcv", lambda conn, rows: calls.append((rows[0]["symbol"], len(rows))) or len(rows))

    service.backfill(object(), ["BTCUSD"])
    service.refresh_assets(object(), ["BTCUSD"])

    assert calls == [("BTCUSD", 1), ("BTCUSD", 1), ("BTCUSD", 1), ("BTCUSD", 1)]


def test_connect_with_retry_succeeds_after_retries(monkeypatch):
    sleeps = []
    attempts = {"count": 0}

    def fake_get_conn():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("db down")
        return "CONN"

    monkeypatch.setattr(service, "get_conn", fake_get_conn)

    result = service._connect_with_retry(max_attempts=4, sleep_fn=lambda delay: sleeps.append(delay))

    assert result == "CONN"
    assert sleeps == [5, 5]


def test_connect_with_retry_returns_none_after_exhaustion(monkeypatch):
    monkeypatch.setattr(service, "get_conn", lambda: (_ for _ in ()).throw(RuntimeError("db down")))

    result = service._connect_with_retry(max_attempts=2, sleep_fn=lambda delay: None)

    assert result is None


def test_run_refresh_cycle_updates_timestamp(monkeypatch):
    calls = []
    monkeypatch.setattr(service, "refresh_assets", lambda conn, tickers: calls.append((conn, tickers)))
    monkeypatch.setattr(service, "MT5_POLL_INTERVAL", 60)

    updated = service._run_refresh_cycle("conn", ["BTCUSD"], 0.0, now=120.0)
    unchanged = service._run_refresh_cycle("conn", ["BTCUSD"], 100.0, now=120.0)

    assert updated == 120.0
    assert unchanged == 100.0
    assert calls == [("conn", ["BTCUSD"])]


def test_main_returns_when_connection_never_established(monkeypatch):
    monkeypatch.setattr(service, "_connect_with_retry", lambda: None)
    monkeypatch.setattr(service, "_load_symbols", lambda: ["BTCUSD"])

    assert service.main() is None


def test_main_runs_startup_and_exits_after_one_loop(monkeypatch):
    monkeypatch.setattr(service, "_load_symbols", lambda: ["BTCUSD"])
    monkeypatch.setattr(service, "_connect_with_retry", lambda: "CONN")
    monkeypatch.setattr(service, "backfill", lambda conn, tickers: None)
    monkeypatch.setattr(service, "_run_refresh_cycle", lambda conn, tickers, last_refresh, now=None: now or 0.0)
    monkeypatch.setattr(service.time, "time", lambda: 120.0)
    monkeypatch.setattr(service.time, "sleep", lambda delay: (_ for _ in ()).throw(KeyboardInterrupt()))

    with pytest.raises(KeyboardInterrupt):
        service.main()


def test_main_logs_backfill_error_then_handles_reconnect_and_refresh_errors(monkeypatch):
    monkeypatch.setattr(service, "_load_symbols", lambda: ["BTCUSD"])
    monkeypatch.setattr(service, "_connect_with_retry", lambda: "CONN")

    class FakeOperationalError(Exception):
        pass

    monkeypatch.setattr(service.psycopg2, "OperationalError", FakeOperationalError)

    state = {"loop": 0, "reconnects": 0}

    def fake_backfill(conn, tickers):
        raise RuntimeError("backfill boom")

    def fake_run_refresh_cycle(conn, tickers, last_refresh, now=None):
        state["loop"] += 1
        if state["loop"] == 1:
            raise FakeOperationalError("lost")
        raise RuntimeError("refresh boom")

    def fake_get_conn():
        state["reconnects"] += 1
        if state["reconnects"] == 1:
            raise RuntimeError("still down")
        return "RECONNECTED"

    sleeps = {"count": 0}

    def fake_sleep(delay):
        sleeps["count"] += 1
        if sleeps["count"] >= 2:
            raise KeyboardInterrupt()

    errors = []
    monkeypatch.setattr(service, "backfill", fake_backfill)
    monkeypatch.setattr(service, "_run_refresh_cycle", fake_run_refresh_cycle)
    monkeypatch.setattr(service, "get_conn", fake_get_conn)
    monkeypatch.setattr(service.time, "time", lambda: 120.0)
    monkeypatch.setattr(service.time, "sleep", fake_sleep)
    monkeypatch.setattr(service.logger, "error", lambda message, exc_info=False: errors.append((message, exc_info)))

    with pytest.raises(KeyboardInterrupt):
        service.main()

    assert ("Backfill error: backfill boom", True) in errors
    assert ("Reconnect failed: still down", False) in errors
    assert ("Refresh error: refresh boom", True) in errors
