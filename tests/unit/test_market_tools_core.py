import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from intelligence.tools import market_tools


class FakeCursor:
    def __init__(self, *, fetchone=None, fetchall=None):
        self._fetchone = fetchone
        self._fetchall = fetchall or []
        self.executed = []
        self.closed = False

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchone(self):
        return self._fetchone

    def fetchall(self):
        return self._fetchall

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


class FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False
        self.closed = False

    def cursor(self, *args, **kwargs):
        return self._cursor

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


def _init_persistence_db(path: Path):
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                title TEXT,
                updated_at TEXT
            );
            CREATE TABLE working_memory (
                session_id TEXT PRIMARY KEY,
                memory TEXT,
                emotion TEXT,
                updated_at TEXT
            );
            CREATE TABLE active_alerts (
                symbol TEXT,
                condition TEXT,
                message TEXT,
                created_at TEXT
            );
            """
        )
        conn.commit()


def test_cache_helpers_and_load_index_data_fallback(monkeypatch):
    monkeypatch.setattr(market_tools, "_REDIS_AVAILABLE", False)
    monkeypatch.setattr(market_tools, "_REDIS", None)
    monkeypatch.setattr(market_tools, "_CACHE", {})
    monkeypatch.setattr(market_tools, "_INDEX_CACHE", {"data": None, "timestamp": 0})
    monkeypatch.setattr(market_tools.os.path, "exists", lambda _path: False)

    market_tools._cache_set("k", {"value": 1}, ttl=60)
    assert market_tools._cache_get("k") == {"value": 1}

    data = market_tools._load_index_data()
    assert "SP500" in data["indices"]
    assert "NASDAQ_100" in data["indices"]


def test_trade_memory_remember_and_recall_paths(monkeypatch):
    monkeypatch.setattr(market_tools, "_REDIS_AVAILABLE", False)
    monkeypatch.setattr(market_tools, "_REDIS", None)
    remember_cursor = FakeCursor(fetchone=[123])
    remember_conn = FakeConn(remember_cursor)
    monkeypatch.setattr(market_tools, "_get_embedding", lambda text: [0.1, 0.2] if "BTC" in text else None)
    monkeypatch.setattr(market_tools, "_get_db_conn", lambda: remember_conn)

    remembered = market_tools.remember_trade(
        symbol="btc",
        side="long",
        entry_price=101.5,
        reasoning="Breakout with volume",
        outcome="WIN",
        pnl_pct=2.5,
        market_conditions={"regime": "TREND"},
    )

    assert remembered["status"] == "SUCCESS"
    assert remembered["trade_id"] == 123
    assert remember_conn.committed is True
    assert "INSERT INTO trade_memory" in remember_cursor.executed[0][0]

    recall_rows = [
        {
            "side": "LONG",
            "entry_price": 100.0,
            "outcome": "WIN",
            "pnl_pct": 3.4,
            "reasoning": "Trend follow",
            "timestamp": datetime(2026, 1, 1, 12, 0, 0),
            "similarity": 0.91,
        }
    ]
    recall_cursor = FakeCursor(fetchall=recall_rows)
    monkeypatch.setattr(market_tools, "_get_db_conn", lambda: FakeConn(recall_cursor))

    recalled = market_tools.recall_memories("BTC", context="BTC bullish breakout", limit=1)
    assert recalled["search_type"] == "semantic"
    assert recalled["memory_count"] == 1
    assert recalled["past_trades"][0]["timestamp"].startswith("2026-01-01T12:00:00")

    recency_cursor = FakeCursor(
        fetchall=[
            {
                "side": "SHORT",
                "entry_price": 98.0,
                "outcome": "LOSS",
                "pnl_pct": -1.2,
                "reasoning": "Failed fade",
                "timestamp": datetime(2026, 1, 2, 9, 0, 0),
                "similarity": None,
            }
        ]
    )
    monkeypatch.setattr(market_tools, "_get_db_conn", lambda: FakeConn(recency_cursor))
    recency = market_tools.recall_memories("BTC", context=None, limit=1)
    assert recency["search_type"] == "recency"


def test_market_regime_and_top_movers_formatting(monkeypatch):
    monkeypatch.setattr(market_tools, "_REDIS_AVAILABLE", False)
    monkeypatch.setattr(market_tools, "_REDIS", None)
    market_tools._CACHE.clear()
    regime_row = {
        "date": datetime(2026, 6, 1),
        "regime": "RISK_ON",
        "regime_confidence": 77,
        "regime_drivers": json.dumps(["volatility easing", "btc above 200ma"]),
        "sp500_vol_30d": 0.12,
        "crypto_vol_30d": 0.35,
        "btc_sp500_corr_30d": 0.42,
        "sp500_vs_ma200": 0.08,
        "btc_vs_ma200": 0.11,
    }
    regime_cursor = FakeCursor(fetchone=regime_row)
    monkeypatch.setattr(market_tools, "_get_db_conn", lambda: FakeConn(regime_cursor))

    regime = market_tools.get_market_regime()
    cached = market_tools.get_market_regime()

    assert regime["regime"] == "RISK_ON"
    assert regime["confidence"] == "77%"
    assert "volatility easing" in regime["drivers"]
    assert cached == regime

    movers_cursor = FakeCursor(
        fetchall=[
            {"symbol": "BTC", "date": datetime(2026, 6, 1), "return_30d": 0.1234},
            {"symbol": "ETH", "date": datetime(2026, 6, 1), "return_30d": 0.1010},
        ]
    )
    monkeypatch.setattr(market_tools, "_get_db_conn", lambda: FakeConn(movers_cursor))
    movers = market_tools.get_top_movers(metric="return_30d", direction="top", limit=2)

    assert movers["metric"] == "return_30d"
    assert movers["results"][0]["return_30d"] == "+12.34%"
    assert movers["as_of"].startswith("2026-06-01T00:00:00")
    assert market_tools.get_top_movers(metric="bad_metric")["status"] == "ERROR"


def test_index_summary_uses_yfinance_and_cache(monkeypatch):
    monkeypatch.setattr(market_tools, "_REDIS_AVAILABLE", False)
    monkeypatch.setattr(market_tools, "_REDIS", None)
    market_tools._CACHE.clear()
    dates = pd.date_range("2025-01-01", periods=40, freq="D")
    columns = pd.MultiIndex.from_product([["^NDX", "^GSPC"], ["Close"]])
    data = pd.DataFrame(
        [[100.0 + i, 200.0 + (i * 0.5)] for i in range(40)],
        index=dates,
        columns=columns,
    )

    calls = []
    monkeypatch.setattr(market_tools.yf, "download", lambda *args, **kwargs: (calls.append((args, kwargs)) or data))
    payload = market_tools.get_index_historical_summary(years=3, indices=["NDX", "SP500"])
    cached = market_tools.get_index_historical_summary(years=3, indices=["NDX", "SP500"])

    assert payload["status"] == "SUCCESS"
    assert "NASDAQ_100" in payload["indices"]
    assert "SP500" in payload["indices"]
    assert cached == payload
    assert len(calls) == 1


def test_working_memory_alert_math_and_risk_helpers(tmp_path, monkeypatch):
    db_path = tmp_path / "persistence.db"
    _init_persistence_db(db_path)
    monkeypatch.setattr(market_tools, "PERSISTENCE_DB", str(db_path))

    empty_memory = market_tools.get_working_memory("alpha")
    assert empty_memory["emotion"] == "NEUTRAL"

    updated = market_tools.update_working_memory("Watch BTC reclaim", "FOCUSED", session_id="alpha")
    loaded = market_tools.get_working_memory("alpha")
    alert = market_tools.set_smart_alert("price > 100000", "btc", "Breakout")

    assert updated["status"] == "SUCCESS"
    assert loaded["frontal_lobe"] == "Watch BTC reclaim"
    assert loaded["emotion"] == "FOCUSED"
    assert alert["status"] == "SUCCESS"

    ok_math = market_tools.calculate_math_expression("2 + 3 * 4")
    bad_math = market_tools.calculate_math_expression("x +")
    assert ok_math["result"] == 14.0
    assert bad_math["status"] == "ERROR"

    monkeypatch.setattr(market_tools, "calculate_crypto_risk", lambda **_kwargs: {
        "direction": "LONG",
        "position_size_units": 0.25,
        "position_value_usdt": 2500.0,
    })
    monkeypatch.setattr(market_tools, "get_risk_advice_thai", lambda res: f"Advice for {res['direction']}")
    monkeypatch.setattr(market_tools, "calculate_position_scenarios", lambda *args, **kwargs: [{"risk_pct": 1.0}])
    risk = market_tools.calculate_risk_parameters(10000, 100, 95, risk_pct=1.0)
    assert risk["status"] == "SUCCESS"
    assert "LONG" in risk["recommendation"]

    monkeypatch.setattr(market_tools, "calculate_crypto_risk", lambda **_kwargs: {"error": "bad inputs"})
    risk_error = market_tools.calculate_risk_parameters(10000, 100, 95, risk_pct=1.0)
    assert risk_error["status"] == "ERROR"


def test_macro_backtest_options_and_custom_indicator_helpers(monkeypatch):
    monkeypatch.setattr(market_tools, "_REDIS_AVAILABLE", False)
    monkeypatch.setattr(market_tools, "_REDIS", None)

    macro = market_tools.get_macro_sentiment()
    assert macro["market_regime"] == "Risk-On"
    assert macro["correlations"]["BTC_vs_NASDAQ"] == 0.85

    stock_backtest = market_tools.run_strategy_backtest("AAPL", asset_class="STOCK")
    assert stock_backtest["status"] == "NOT_APPLICABLE"

    monkeypatch.setattr(market_tools, "run_crypto_backtest", lambda symbol, timeframe, limit: {
        "symbol": symbol,
        "timeframe": timeframe,
        "trades": limit,
        "status": "SUCCESS",
    })
    crypto_backtest = market_tools.run_strategy_backtest("BTC", timeframe="1h", limit=120, asset_class="CRYPTO")
    assert crypto_backtest["status"] == "SUCCESS"
    assert crypto_backtest["trades"] == 120

    monkeypatch.setenv("UNUSUAL_WHALES_API_KEY", "")
    monkeypatch.setattr(market_tools.random, "uniform", lambda a, b: 1.23 if a == 0.5 else 321000.0)
    monkeypatch.setattr(market_tools.random, "randint", lambda a, b: 7)
    fallback_options = market_tools.get_options_flow("tsla")
    assert fallback_options["symbol"] == "TSLA"
    assert fallback_options["put_call_ratio"] == 1.23
    assert fallback_options["dark_pool_prints"] == 7

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "data": {
                    "put_call_ratio": 0.76,
                    "net_premium_bullish": 1200000,
                    "net_premium_bearish": 450000,
                    "average_30_day_put_call_ratio": 0.91,
                    "dark_pool_prints": 3,
                }
            }

    import sys
    import types

    fake_requests = types.SimpleNamespace(get=lambda *args, **kwargs: FakeResponse())
    monkeypatch.setitem(sys.modules, "requests", fake_requests)
    monkeypatch.setenv("UNUSUAL_WHALES_API_KEY", "real_key")
    live_options = market_tools.get_options_flow("nvda")
    assert live_options["data_source"] == "Unusual Whales"
    assert live_options["put_call_ratio"] == 0.76

    monkeypatch.setattr(
        market_tools,
        "get_kline_data",
        lambda *args, **kwargs: pd.DataFrame({"Close": [100, 101, 102], "Open": [99, 100, 101]}),
    )
    from intelligence import formula_engine

    monkeypatch.setattr(formula_engine, "evaluate_formula", lambda df, formula: pd.Series([1.0, 2.0, 3.5]))
    monkeypatch.setattr(formula_engine, "get_latest_value", lambda result: float(result.iloc[-1]))
    custom = market_tools.calculate_custom_indicator("BTC", "SMA(CLOSE, 2)")
    assert custom["status"] == "SUCCESS"
    assert custom["result"] == 3.5

    monkeypatch.setattr(market_tools, "get_kline_data", lambda *args, **kwargs: pd.DataFrame())
    no_data = market_tools.calculate_custom_indicator("BTC", "SMA(CLOSE, 2)")
    assert "No data found" in no_data["error"]


def test_paper_trade_open_close_list_reset_and_errors(tmp_path, monkeypatch):
    db_path = tmp_path / "paper.db"
    monkeypatch.setattr(market_tools, "_PAPER_DB", str(db_path))
    monkeypatch.setattr(
        market_tools,
        "get_kline_data",
        lambda *args, **kwargs: pd.DataFrame({"close": [250.0]}),
    )
    monkeypatch.setattr(market_tools.uuid, "uuid4", lambda: "test-trade-123456")

    opened = market_tools.paper_trade("OPEN", symbol="TSLA", side="BUY", volume=2.0, price=None)
    assert opened["status"] == "SUCCESS"
    assert opened["trade_id"] == "test-tra"
    assert opened["entry_price"] == 250.0

    listed_open = market_tools.paper_trade("LIST")
    assert len(listed_open["open_trades"]) == 1
    trade_id = listed_open["open_trades"][0]["id"]

    closed = market_tools.paper_trade("CLOSE", trade_id=trade_id, price=255.5)
    assert closed["status"] == "SUCCESS"
    assert closed["result"] == "WIN"
    assert closed["pnl_usd"] == 11.0

    listed_closed = market_tools.paper_trade("LIST")
    assert listed_closed["total_simulated_pnl"] == 11.0
    assert len(listed_closed["closed_trades"]) == 1

    reset = market_tools.paper_trade("RESET")
    assert reset["status"] == "SUCCESS"
    assert market_tools.paper_trade("CLOSE")["error"]
    assert "Unknown action" in market_tools.paper_trade("WHATEVER")["error"]


def test_market_climate_usd_rate_portfolio_and_funding_helpers(tmp_path, monkeypatch):
    monkeypatch.setattr(market_tools, "_REDIS_AVAILABLE", False)
    monkeypatch.setattr(market_tools, "_REDIS", None)
    market_tools._CACHE.clear()

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, period="1d"):
            mapping = {
                "^VIX": [17.5],
                "DX-Y.NYB": [101.8],
                "^TNX": [4.1],
                "EURUSD=X": [1.09],
                "USDJPY=X": [151.0],
                "GC=F": [3305.0],
            }
            values = mapping.get(self.symbol, [])
            return pd.DataFrame({"Close": values})

    monkeypatch.setattr(market_tools.yf, "Ticker", lambda symbol: FakeTicker(symbol))
    monkeypatch.setattr(
        market_tools,
        "_macro_build_market_climate_response",
        lambda vix, dxy, tnx: {"status": "SUCCESS", "risk_score": 61, "inputs": [vix, dxy, tnx]},
    )

    climate = market_tools.get_market_climate()
    cached_climate = market_tools.get_market_climate()
    assert climate["status"] == "SUCCESS"
    assert climate["inputs"] == [17.5, 101.8, 4.1]
    assert cached_climate == climate

    assert market_tools.get_usd_rate("EURJPY") == 1.09
    assert round(market_tools.get_usd_rate("JPYXXX"), 6) == round(1 / 151.0, 6)
    assert market_tools.get_usd_rate("BTCUSDT") == 1.0
    assert market_tools.get_usd_rate("XAUCAD") == 3305.0

    import sys
    import types

    fake_mt5 = types.SimpleNamespace(
        positions_get=lambda: [
            SimpleNamespace(
                _asdict=lambda: {
                    "symbol": "EURJPY",
                    "type": 0,
                    "volume": 2.0,
                    "price_current": 100.0,
                    "contract_size": 1.0,
                    "profit": 25.4,
                }
            ),
            SimpleNamespace(
                _asdict=lambda: {
                    "symbol": "XAUCAD",
                    "type": 1,
                    "volume": 1.0,
                    "price_current": 10.0,
                    "contract_size": 1.0,
                    "profit": -5.0,
                }
            ),
        ]
    )
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake_mt5)
    monkeypatch.setattr("intelligence.mt5_connector.initialize_mt5", lambda: True)
    monkeypatch.setattr("intelligence.mt5_connector.get_mt5_account_info", lambda: {"equity": 1000.0})

    portfolio = market_tools.get_portfolio_analytics()
    assert portfolio["equity"] == 1000.0
    assert len(portfolio["positions"]) == 2
    assert portfolio["positions"][0]["percent_of_equity"] > 20
    assert portfolio["risk_warnings"]

    monkeypatch.setattr("intelligence.mt5_connector.initialize_mt5", lambda: False)
    assert market_tools.get_portfolio_analytics()["error"] == "Failed to connect to MT5"

    class FakeFundingResponse:
        status_code = 200

        def json(self):
            return [
                {"symbol": "BTCUSDT", "lastFundingRate": "0.0025", "markPrice": "68000"},
                {"symbol": "ETHUSDT", "lastFundingRate": "-0.003", "markPrice": "3500"},
                {"symbol": "SOLUSDT", "lastFundingRate": "0.0001", "markPrice": "150"},
            ]

    fake_requests = types.SimpleNamespace(get=lambda *args, **kwargs: FakeFundingResponse())
    monkeypatch.setitem(sys.modules, "requests", fake_requests)
    market_tools._CACHE.clear()
    funding = market_tools.get_funding_rates(["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    assert funding["status"] == "SUCCESS"
    assert funding["rates"][0]["symbol"] == "ETH" or funding["rates"][0]["symbol"] == "BTC"
    assert len(funding["extremes"]) == 2
    assert market_tools.get_funding_rates(["BTCUSDT", "ETHUSDT", "SOLUSDT"]) == funding

    paper_db = tmp_path / "rebalance.db"
    monkeypatch.setattr(market_tools, "_PAPER_DB", str(paper_db))
    with sqlite3.connect(paper_db) as conn:
        conn.execute("CREATE TABLE paper_trades (symbol TEXT, volume REAL, entry_price REAL, status TEXT)")
        conn.executemany(
            "INSERT INTO paper_trades (symbol, volume, entry_price, status) VALUES (?, ?, ?, ?)",
            [("BTC", 1.0, 70000.0, "OPEN"), ("ETH", 1.0, 3500.0, "OPEN")],
        )
        conn.commit()

    class RebalanceTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, period="1d"):
            mapping = {"BTC-USD": [70000.0], "ETH-USD": [3500.0], "GC=F": [2400.0]}
            return pd.DataFrame({"Close": mapping.get(self.symbol, [100.0])})

    monkeypatch.setattr(market_tools.yf, "Ticker", lambda symbol: RebalanceTicker(symbol))
    rebalance = market_tools.suggest_portfolio_rebalance({"BTC": 50.0, "ETH": 25.0, "GOLD": 25.0})
    assert rebalance["status"] == "SUCCESS"
    assert rebalance["rebalance_actions"]
    assert any(action["action"].startswith("REDUCE BTC") for action in rebalance["rebalance_actions"])


def test_iv_rank_etf_flows_and_custom_screener(monkeypatch):
    monkeypatch.setattr(market_tools, "_REDIS_AVAILABLE", False)
    monkeypatch.setattr(market_tools, "_REDIS", None)
    market_tools._CACHE.clear()

    iv_dates = pd.date_range("2025-01-01", periods=260, freq="D")
    iv_close = pd.Series([100 + ((i % 7) - 3) * 2 + i * 0.4 for i in range(260)], index=iv_dates)

    class IvTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, period="1y"):
            return pd.DataFrame({"Close": iv_close})

    monkeypatch.setattr(market_tools.yf, "Ticker", lambda symbol: IvTicker(symbol))
    iv = market_tools.get_iv_rank("nvda")
    cached_iv = market_tools.get_iv_rank("nvda")
    assert iv["status"] == "SUCCESS"
    assert iv["symbol"] == "NVDA"
    assert "recommendation" in iv
    assert cached_iv == iv

    class ShortIvTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, period="1y"):
            return pd.DataFrame({"Close": [100, 101, 102]})

    monkeypatch.setattr(market_tools.yf, "Ticker", lambda symbol: ShortIvTicker(symbol))
    iv_short = market_tools.get_iv_rank("abc")
    assert iv_short["status"] == "NO_DATA"

    market_tools._CACHE.clear()

    class EtfTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, period="10d"):
            mapping = {
                "SPY": {"Close": [100, 101, 102, 103, 104, 106], "Volume": [100, 100, 100, 100, 100, 200]},
                "QQQ": {"Close": [100, 99, 98, 97, 96, 94], "Volume": [100, 100, 100, 100, 100, 220]},
                "GLD": {"Close": [50, 50, 50, 50, 50, 50.2], "Volume": [100, 100, 100, 100, 100, 90]},
            }
            data = mapping[self.symbol]
            return pd.DataFrame(data)

    monkeypatch.setattr(market_tools.yf, "Ticker", lambda symbol: EtfTicker(symbol))
    flows = market_tools.get_etf_flows(["SPY", "QQQ", "GLD"])
    cached_flows = market_tools.get_etf_flows(["SPY", "QQQ", "GLD"])
    assert flows["status"] == "SUCCESS"
    assert len(flows["top_inflows"]) == 1
    assert flows["top_inflows"][0]["symbol"] == "SPY"
    assert len(flows["top_outflows"]) == 1
    assert flows["top_outflows"][0]["symbol"] == "QQQ"
    assert cached_flows == flows

    market_tools._CACHE.clear()

    class ScreenerTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, period="3mo"):
            dates = pd.date_range("2025-01-01", periods=40, freq="D")
            if self.symbol == "AAA":
                close = [100 + i * 1.2 for i in range(40)]
                volume = [100] * 39 + [300]
            elif self.symbol == "BBB":
                close = [100 - i * 0.8 for i in range(40)]
                volume = [100] * 39 + [90]
            else:
                close = [100 + (i % 3) for i in range(40)]
                volume = [100] * 40
            return pd.DataFrame({"Close": close, "Volume": volume}, index=dates)

    monkeypatch.setattr(market_tools.yf, "Ticker", lambda symbol: ScreenerTicker(symbol))
    screener = market_tools.run_custom_screener(
        universe="CUSTOM",
        custom_tickers="AAA, BBB, CCC",
        rsi_min=50,
        vol_spike=1.5,
        min_return_1w=1,
        limit=5,
    )
    cached_screener = market_tools.run_custom_screener(
        universe="CUSTOM",
        custom_tickers="AAA, BBB, CCC",
        rsi_min=50,
        vol_spike=1.5,
        min_return_1w=1,
        limit=5,
    )
    assert screener["status"] == "SUCCESS"
    assert screener["match_count"] == 1
    assert screener["results"][0]["symbol"] == "AAA"
    assert cached_screener == screener


def test_news_sentiment_feature_and_correlation_helpers(monkeypatch):
    monkeypatch.setattr(
        market_tools,
        "_fetch_rss_news",
        lambda symbol_hint="BTC": [
            {"source": "Reuters", "title": f"{symbol_hint} breaks higher"},
            {"source": "Bloomberg", "title": f"{symbol_hint} sees fresh inflows"},
        ],
    )
    news = market_tools.get_news_impact("eth")
    assert news["status"] == "SUCCESS"
    assert news["symbol"] == "eth"
    assert news["news_count"] == 2
    assert news["top_headlines"][0].startswith("[Reuters]")

    monkeypatch.setattr(market_tools, "_fetch_rss_news", lambda symbol_hint="BTC": [])
    no_news = market_tools.get_news_impact("btc")
    assert no_news["sentiment"] == "NEUTRAL"
    assert no_news["news_count"] == 0

    history_rows = [
        {"date": datetime(2026, 6, 4), "avg_score": 40, "dominant_label": "bullish", "reading_count": 4, "max_score": 55, "min_score": 20},
        {"date": datetime(2026, 6, 3), "avg_score": 30, "dominant_label": "bullish", "reading_count": 5, "max_score": 45, "min_score": 10},
        {"date": datetime(2026, 6, 2), "avg_score": 10, "dominant_label": "neutral", "reading_count": 5, "max_score": 20, "min_score": -5},
        {"date": datetime(2026, 6, 1), "avg_score": 0, "dominant_label": "neutral", "reading_count": 3, "max_score": 5, "min_score": -10},
    ]
    monkeypatch.setattr(market_tools, "_get_db_conn", lambda: FakeConn(FakeCursor(fetchall=history_rows)))
    history = market_tools.get_sentiment_history("btc", days=7)
    assert history["symbol"] == "BTC"
    assert history["trend"] == "IMPROVING"
    assert history["data_points"] == 4
    assert history["daily_scores"][0]["date"].startswith("2026-06-04")

    monkeypatch.setattr(market_tools.risk_manager, "check_correlation_risk", lambda symbol: {"status": "SAFE", "symbol": symbol})
    corr = market_tools.analyze_correlation_risk("SOL")
    assert corr == {"status": "SAFE", "symbol": "SOL"}

    monkeypatch.setattr(market_tools, "_REDIS_AVAILABLE", False)
    monkeypatch.setattr(market_tools, "_REDIS", None)
    market_tools._CACHE.clear()
    feature_row = {"symbol": "NVDA", "price": 120.5, "return_7d": 0.045, "date": datetime(2026, 6, 1, 12, 30, 0)}
    monkeypatch.setattr(market_tools, "_get_db_conn", lambda: FakeConn(FakeCursor(fetchone=feature_row)))
    monkeypatch.setattr(
        market_tools,
        "_response_build_market_features_response",
        lambda symbol, row, computed_date, interpret_features_fn: {
            "status": "SUCCESS",
            "symbol": symbol.upper(),
            "price": row["price"],
            "computed_date": computed_date,
            "summary": interpret_features_fn(row, symbol),
        },
    )
    monkeypatch.setattr(market_tools, "_response_interpret_market_features", lambda row, symbol: f"{symbol.upper()} at {row['price']}")
    features = market_tools.get_market_features("nvda")
    cached_features = market_tools.get_market_features("nvda")
    assert features["status"] == "SUCCESS"
    assert features["summary"] == "NVDA at 120.5"
    assert features["computed_date"].startswith("2026-06-01T12:30:00")
    assert cached_features == features


def test_scan_basket_helper(monkeypatch):
    class BasketResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return [
                {"symbol": "ETHUSDT", "lastPrice": "3500", "priceChangePercent": "3.5", "quoteVolume": "123456"},
                {"symbol": "BTCUSDT", "lastPrice": "68000", "priceChangePercent": "1.2", "quoteVolume": "987654"},
            ]

    requests_module = SimpleNamespace(get=lambda *args, **kwargs: BasketResponse())
    monkeypatch.setitem(sys.modules, "requests", requests_module)
    basket = market_tools._scan_basket(["BTC-USD", "ETH-USD"])
    assert [item["symbol"] for item in basket] == ["ETH", "BTC"]
    assert basket[0]["data_source"] == "Binance 24hr ticker"


def test_fetch_yf_screener_helper(monkeypatch):
    monkeypatch.setattr(market_tools, "_REDIS_AVAILABLE", False)
    monkeypatch.setattr(market_tools, "_REDIS", None)
    market_tools._CACHE.clear()

    class ScreenerResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "finance": {
                    "result": [{
                        "quotes": [
                            {
                                "symbol": "AAA",
                                "shortName": "Alpha",
                                "fullExchangeName": "NMS",
                                "regularMarketChangePercent": 31.4,
                                "regularMarketPrice": 12.34,
                                "regularMarketVolume": 2_500_000,
                                "averageDailyVolume3Month": 1_000_000,
                                "marketState": "POST",
                            },
                            {
                                "symbol": "BBB",
                                "shortName": "Beta",
                                "fullExchangeName": "NYQ",
                                "regularMarketChangePercent": -4.2,
                                "regularMarketPrice": 22.22,
                                "regularMarketVolume": 850,
                                "averageDailyVolume3Month": 500,
                                "marketState": "REGULAR",
                            },
                        ]
                    }]
                }
            }

    monkeypatch.setitem(sys.modules, "requests", SimpleNamespace(get=lambda *args, **kwargs: ScreenerResponse()))
    screener_rows = market_tools._fetch_yf_screener("day_gainers", count=2)
    assert screener_rows[0]["is_anomaly"] is True
    assert screener_rows[0]["name"].startswith("[")
    assert screener_rows[0]["market_state"] == "POST (After-Hours EST)"
    assert market_tools._fetch_yf_screener("day_gainers", count=2) == screener_rows


def test_sector_rotation_and_social_sentiment_helpers(monkeypatch):
    monkeypatch.setattr(market_tools, "_REDIS_AVAILABLE", False)
    monkeypatch.setattr(market_tools, "_REDIS", None)
    market_tools._CACHE.clear()
    sector_dates = pd.date_range("2025-01-01", periods=5, freq="D")
    sector_data = pd.DataFrame(
        {
            "XLK": [100, 101, 102, 103, 105],
            "XLF": [100, 100, 99, 98, 97],
            "XLE": [100, 100, 100, 101, 101],
            "XLV": [100, 100, 101, 101, 102],
            "XLI": [100, 99, 99, 99, 98],
            "XLY": [100, 101, 101, 102, 103],
            "XLP": [100, 100, 100, 100, 100],
            "XLB": [100, 102, 103, 104, 106],
            "XLU": [100, 99, 98, 97, 96],
            "XLRE": [100, 101, 101, 100, 99],
        },
        index=sector_dates,
    )
    monkeypatch.setattr(market_tools.yf, "download", lambda *args, **kwargs: {"Close": sector_data})
    monkeypatch.setattr(
        market_tools,
        "_macro_build_sector_rotation_response",
        lambda perf: {"status": "SUCCESS", "leaders": sorted(perf, key=perf.get, reverse=True)[:2]},
    )
    rotation = market_tools.get_sector_rotation()
    cached_rotation = market_tools.get_sector_rotation()
    assert rotation["status"] == "SUCCESS"
    assert cached_rotation == rotation
    assert rotation["leaders"]

    class SocialApiResponse:
        status_code = 200

        def json(self):
            return {
                "results": [
                    {"title": "BTC breakout rally", "votes": {"positive": 4, "negative": 1}},
                    {"title": "BTC gains as bulls buy dip", "votes": {"positive": 3, "negative": 0}},
                    {"title": "BTC risk down after slump", "votes": {"positive": 0, "negative": 2}},
                ]
            }

    monkeypatch.setenv("CRYPTOPANIC_API_KEY", "live_key")
    monkeypatch.setitem(sys.modules, "requests", SimpleNamespace(get=lambda *args, **kwargs: SocialApiResponse()))
    social = market_tools.get_social_sentiment("btc")
    assert social["data_source"] == "CryptoPanic API"
    assert social["trending_mentions"] == 3
    assert social["votes_up"] == 7


def test_analyze_trade_performance_helper(tmp_path, monkeypatch):
    db_path = tmp_path / "performance.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE trade_reviews (review_text TEXT, win_rate REAL, score REAL, created_at TEXT)"
        )
        conn.commit()
    monkeypatch.setattr(market_tools, "PERSISTENCE_DB", str(db_path))

    fake_tl = SimpleNamespace(
        get_statistics=lambda days=30: {"win_rate": 62.0, "total_trades": 12, "total_pnl": 420.5, "max_consecutive_losses": 2},
        get_weekly_report=lambda: {"week": "good"},
        get_recent_trades=lambda count=5: [{"symbol": "BTC"}],
    )
    monkeypatch.setitem(sys.modules, "intelligence.trade_logger", SimpleNamespace(get_trade_logger=lambda: fake_tl))
    fake_mt5 = SimpleNamespace(
        initialize=lambda: True,
        history_deals_get=lambda start, end: [SimpleNamespace(profit=50.0), SimpleNamespace(profit=-10.0), SimpleNamespace(profit=20.0)],
    )
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake_mt5)
    perf = market_tools.analyze_trade_performance()
    assert perf["status"] == "SUCCESS"
    assert perf["score"] > 0
    assert perf["recent_trades"][0]["symbol"] == "BTC"


def test_fear_greed_portfolio_correlation_and_weekly_report(tmp_path, monkeypatch):
    monkeypatch.setattr(market_tools, "_REDIS_AVAILABLE", False)
    monkeypatch.setattr(market_tools, "_REDIS", None)
    market_tools._CACHE.clear()

    class FearGreedResponse:
        def json(self):
            return {
                "data": [
                    {"value": "18", "value_classification": "Extreme Fear"},
                    {"value": "30", "value_classification": "Fear"},
                ]
            }

    monkeypatch.setitem(sys.modules, "requests", SimpleNamespace(get=lambda *args, **kwargs: FearGreedResponse()))

    class FearTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, period="5d"):
            if self.symbol == "^VIX":
                return pd.DataFrame({"Close": [14.0, 15.0, 16.0]})
            if self.symbol == "^GSPC":
                return pd.DataFrame({"Close": [5000.0] * 49 + [5200.0]})
            return pd.DataFrame()

    monkeypatch.setattr(market_tools.yf, "Ticker", lambda symbol: FearTicker(symbol))
    fg = market_tools.get_fear_greed_index()
    cached_fg = market_tools.get_fear_greed_index()
    assert fg["status"] == "SUCCESS"
    assert fg["crypto"]["score"] == 18
    assert fg["crypto"]["delta_1d"] == -12
    assert fg["composite_signal"] == "CONTRARIAN BUY"
    assert cached_fg == fg

    market_tools._CACHE.clear()
    corr_frame = pd.DataFrame(
        {
            "BTC-USD": [100, 102, 104, 106, 108],
            "ETH-USD": [50, 51, 52, 53, 54],
            "GC=F": [200, 199, 201, 198, 202],
        },
        index=pd.date_range("2026-01-01", periods=5, freq="D"),
    )
    monkeypatch.setattr(market_tools.yf, "download", lambda symbols, period="3mo", auto_adjust=True, progress=False: {"Close": corr_frame})
    corr = market_tools.get_portfolio_correlation(["BTC", "ETH", "GOLD"])
    cached_corr = market_tools.get_portfolio_correlation(["BTC", "ETH", "GOLD"])
    assert corr["status"] == "SUCCESS"
    assert corr["symbols"] == ["BTC", "ETH", "GOLD"]
    assert corr["top_correlations"]
    assert any(pair["risk_flag"] for pair in corr["top_correlations"])
    assert cached_corr == corr

    db_path = tmp_path / "weekly.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE trades (symbol TEXT, side TEXT, entry_price REAL, exit_price REAL, pnl_usd REAL, status TEXT, timestamp TEXT)"
        )
        conn.executemany(
            "INSERT INTO trades VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("BTC", "BUY", 100.0, 110.0, 10.0, "CLOSED", "2026-06-01T10:00:00"),
                ("ETH", "SELL", 200.0, 190.0, 8.0, "WIN", "2026-06-02T10:00:00"),
                ("SOL", "BUY", 50.0, 45.0, -5.0, "LOSS", "2026-06-03T10:00:00"),
                ("GOLD", "BUY", 2400.0, 0.0, 0.0, "OPEN", "2026-06-04T10:00:00"),
            ],
        )
        conn.commit()

    monkeypatch.setenv("TRADE_LOG_DB", str(db_path))
    monkeypatch.setattr(market_tools, "PERSISTENCE_DB", str(db_path))
    monkeypatch.setattr(market_tools, "get_market_regime", lambda: {"regime": "RISK_ON"})
    report = market_tools.generate_weekly_report()
    assert report["status"] == "SUCCESS"
    assert report["summary"]["total_trades"] == 3
    assert report["summary"]["wins"] == 2
    assert report["summary"]["losses"] == 1
    assert report["market_regime_this_week"] == "RISK_ON"
    assert report["best_trade"]["symbol"] == "BTC"


def test_economic_calendar_variants(monkeypatch):
    monkeypatch.setattr(market_tools, "_REDIS_AVAILABLE", False)
    monkeypatch.setattr(market_tools, "_REDIS", None)
    market_tools._CACHE.clear()

    class FrozenDateTime(datetime):
        @classmethod
        def utcnow(cls):
            return cls(2026, 6, 2, 9, 0, 0)

    class FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, timeout=None, headers=None):
        if "finnhub.io" in url:
            return FakeResponse(
                200,
                {
                    "earningsCalendar": [
                        {"date": "2026-06-03", "symbol": "AAPL", "company": "Apple", "epsEstimate": 1.5},
                        {"date": "2026-06-04", "symbol": "SMALL", "company": "Ignore", "epsEstimate": 0.1},
                    ]
                },
            )
        if "thisweek" in url:
            return FakeResponse(
                200,
                [
                    {
                        "date": "2026-06-03",
                        "time": "12:30",
                        "title": "ADP Non-Farm Employment Change",
                        "impact": "Medium",
                        "country": "USD",
                        "actual": "120K",
                        "forecast": "115K",
                        "previous": "100K",
                    },
                    {
                        "date": "2026-06-06",
                        "time": "14:00",
                        "title": "Weekend Noise",
                        "impact": "Low",
                        "country": "USD",
                    },
                ],
            )
        if "nextweek" in url:
            return FakeResponse(
                200,
                [
                    {
                        "date": "2026-06-08",
                        "time": "13:30",
                        "title": "US CPI (Inflation)",
                        "impact": "High",
                        "country": "USD",
                        "actual": None,
                        "forecast": "2.8%",
                        "previous": "2.9%",
                    }
                ],
            )
        raise AssertionError(f"Unexpected URL {url}")

    monkeypatch.setattr(market_tools, "dt_datetime", FrozenDateTime)
    monkeypatch.setenv("FINNHUB_API_KEY", "demo")
    monkeypatch.setitem(sys.modules, "requests", SimpleNamespace(get=fake_get))

    calendar = market_tools.get_economic_calendar(days_ahead=7)
    assert calendar["status"] == "SUCCESS"
    assert calendar["total_events"] >= 3
    assert calendar["high_impact_count"] >= 2
    assert any(event["type"] == "EARNINGS" and event["symbol"] == "AAPL" for event in calendar["events"])
    assert any(event["source"] == "forex_factory" for event in calendar["events"])

    market_tools._CACHE.clear()
    monkeypatch.setattr(
        market_tools,
        "get_economic_calendar",
        lambda days_ahead=7: {
            "events": [
                {
                    "date": "2026-06-13",
                    "time": "13:30",
                    "type": "MACRO",
                    "name": "US CPI (Inflation)",
                    "symbol": "CPI",
                    "impact": "CRITICAL",
                    "source": "live_feed",
                },
                {
                    "date": "2026-06-04",
                    "time": "20:00",
                    "type": "EARNINGS",
                    "name": "Apple",
                    "symbol": "AAPL",
                    "impact": "HIGH",
                    "source": "finnhub_earnings",
                },
            ],
            "macro_watch": [{"name": "watch"}],
        },
    )
    calendar_v2 = market_tools.get_economic_calendar_v2(days_ahead=14)
    assert calendar_v2["status"] == "SUCCESS"
    assert calendar_v2["sources"]["live"] == 2
    assert calendar_v2["estimated_count"] > 0
    assert any(event.get("symbol") == "CPI" and not event.get("is_estimated") for event in calendar_v2["events"])
    assert any(event.get("is_estimated") for event in calendar_v2["events"])
    assert calendar_v2["macro_watch"] == [{"name": "watch"}]


def test_estimated_calendar_liquidation_heatmap_and_mtf_scan(monkeypatch):
    monkeypatch.setattr(market_tools, "_REDIS_AVAILABLE", False)
    monkeypatch.setattr(market_tools, "_REDIS", None)
    market_tools._CACHE.clear()

    class FrozenDateTime(datetime):
        @classmethod
        def utcnow(cls):
            return cls(2026, 1, 10, 9, 0, 0)

    monkeypatch.setattr(market_tools, "dt_datetime", FrozenDateTime)
    estimated = market_tools.get_economic_calendar_estimated(days_ahead=25)
    assert estimated["status"] == "SUCCESS"
    assert estimated["estimated_count"] == estimated["total_events"]
    assert any(event["symbol"] == "GDP" for event in estimated["events"])
    assert estimated["critical_count"] >= 1

    market_tools._CACHE.clear()

    class LiqResponse:
        status_code = 200

        def json(self):
            return {
                "data": {
                    "buyLiquidationMap": [
                        {"price": 98000.0, "value": 3_000_000.0},
                        {"price": 97000.0, "value": 1_500_000.0},
                    ],
                    "sellLiquidationMap": [
                        {"price": 103000.0, "value": 4_000_000.0},
                        {"price": 104000.0, "value": 2_500_000.0},
                    ],
                }
            }

    monkeypatch.setitem(sys.modules, "requests", SimpleNamespace(get=lambda *args, **kwargs: LiqResponse()))
    heatmap = market_tools.get_liquidation_heatmap("BTCUSDT")
    assert heatmap["status"] == "SUCCESS"
    assert heatmap["symbol"] == "BTC"
    assert heatmap["top_long_liquidation_zones"][0]["price"] == 98000.0
    assert heatmap["top_short_liquidation_zones"][0]["usd_value_M"] == 4.0

    market_tools._CACHE.clear()

    class LiqFallbackResponse:
        status_code = 503

        def json(self):
            return {}

    monkeypatch.setitem(sys.modules, "requests", SimpleNamespace(get=lambda *args, **kwargs: LiqFallbackResponse()))
    monkeypatch.setattr(
        market_tools,
        "get_kline_data",
        lambda *args, **kwargs: pd.DataFrame(
            {
                "close": [100.0 + i for i in range(48)],
                "low": [90.0 + i * 0.1 for i in range(48)],
                "high": [110.0 + i * 0.1 for i in range(48)],
            }
        ),
    )
    fallback_heatmap = market_tools.get_liquidation_heatmap("ETH")
    assert fallback_heatmap["status"] == "ESTIMATED"
    assert fallback_heatmap["symbol"] == "ETH"
    assert fallback_heatmap["estimated_long_liq_zone"] < fallback_heatmap["current_price"]
    assert fallback_heatmap["estimated_short_liq_zone"] > fallback_heatmap["estimated_long_liq_zone"]

    market_tools._CACHE.clear()

    def fake_analysis(symbol, timeframe, asset_class):
        mapping = {
            "5m": {"summary": "buy breakout", "indicators": {"rsi": 61, "trend": "UP"}},
            "15m": {"signal": "short fade", "indicators": {"rsi": 41, "ma_trend": "DOWN"}},
            "1h": {"indicators": {"recommendation": "hold", "rsi": 50, "trend": "SIDEWAYS"}},
            "4h": "bullish continuation",
        }
        if timeframe == "1d":
            raise RuntimeError("feed unavailable")
        return mapping[timeframe]

    monkeypatch.setattr(market_tools, "get_market_analysis", fake_analysis)
    mtf = market_tools.scan_multi_timeframe("btc", asset_class="CRYPTO")
    assert mtf["status"] == "SUCCESS"
    assert mtf["dominant_bias"] == "BULLISH"
    assert mtf["bull_tfs"] == 2
    assert mtf["bear_tfs"] == 1
    assert mtf["neutral_tfs"] == 1
    assert mtf["per_timeframe"]["1d"]["bias"] == "ERROR"
