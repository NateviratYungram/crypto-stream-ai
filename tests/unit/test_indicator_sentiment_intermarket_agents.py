import json
from types import SimpleNamespace

from intelligence.agents import intermarket_agent, sentiment_agent
from intelligence.agents.indicator_agent import create_indicator_agent
from intelligence.agents.intermarket_agent import _compute_macro_bias, create_intermarket_agent
from intelligence.agents.sentiment_agent import create_sentiment_agent


class FakeModels:
    def __init__(self, payload=None, raises=None):
        self.payload = payload or {}
        self.raises = raises
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.raises:
            raise self.raises
        return SimpleNamespace(text=json.dumps(self.payload))


def _indicator_summary():
    return {
        "price": 101,
        "rsi": {"value": 58, "signal": "bullish"},
        "macd": {"value": 1.2, "signal": "bullish"},
        "macd_histogram": {"value": 0.4, "signal": "rising"},
        "stochastic": {"k": 70, "d": 60, "signal": "bullish"},
        "williams_r": {"value": -30, "signal": "bullish"},
        "adx": {"value": 25, "signal": "trend"},
        "atr": {"value": 2},
        "bollinger_bands": {"position": "upper", "upper": 110, "lower": 90},
        "ema": {"signal": "bullish", "ema_20": 100, "ema_50": 98, "ema_200": 90},
        "vwap": {"value": 100, "position": "above"},
        "volume": {"spike": True, "cmf": 0.2},
        "hurst": {"h100": 0.6, "regime": "TRENDING"},
        "patterns": {"detected": ["Bullish Engulfing"]},
        "higher_timeframe": {
            "bias": "BULLISH",
            "timeframe": "4h",
            "adx": 30,
            "rsi": 60,
            "regime": "TRENDING",
            "structure": {"structure": "BULLISH"},
        },
        "smart_money": {
            "structure": {"structure": "BULLISH", "last_bos": "BULLISH_BOS", "choch": True, "swing_high": 110, "swing_low": 95},
            "nearest_ob": {"type": "BULLISH_OB", "top": 102, "bottom": 99, "strength": "HIGH"},
            "nearest_fvg": {"type": "BULLISH_FVG", "top": 103, "bottom": 100, "gap_size": 3},
            "liquidity": {"buy_side": [108, 110], "sell_side": [96], "nearest_sweep_target": 108},
            "session": "NEW_YORK",
            "regime": "TREND",
        },
        "trend_analysis": {"market_phase": "TREND", "primary_trend": "UP", "levels": {"support": 95, "resistance": 110}},
    }


def test_indicator_agent_handles_missing_crypto_stock_and_errors():
    missing = create_indicator_agent(SimpleNamespace(models=FakeModels()))({})

    crypto_models = FakeModels(
        {
            "bias": "BULLISH",
            "confidence": 78,
            "key_signals": [{"indicator": "RSI", "signal": "bullish", "weight": "HIGH"}],
            "momentum_direction": "UPWARD",
            "volatility_level": "MEDIUM",
            "summary": "Liquidity and structure align.",
        }
    )
    crypto = create_indicator_agent(SimpleNamespace(models=crypto_models))(
        {"symbol": "BTC", "asset_class": "CRYPTO", "indicator_summary": _indicator_summary()}
    )

    stock_models = FakeModels(
        {
            "bias": "BEARISH",
            "confidence": 66,
            "key_signals": [{"indicator": "EMA", "signal": "bear stack", "weight": "MEDIUM"}],
            "momentum_direction": "DOWNWARD",
            "volatility_level": "HIGH",
            "summary": "Trend and momentum are weakening.",
        }
    )
    stock = create_indicator_agent(SimpleNamespace(models=stock_models))(
        {"symbol": "AAPL", "asset_class": "STOCK", "indicator_summary": _indicator_summary()}
    )

    failure = create_indicator_agent(SimpleNamespace(models=FakeModels(raises=RuntimeError("llm"))))(
        {"indicator_summary": _indicator_summary()}
    )

    assert missing["indicator_bias"] == "NEUTRAL"
    assert crypto["indicator_bias"] == "BULLISH"
    assert "ICT" in crypto_models.calls[0]["contents"]
    assert stock["indicator_bias"] == "BEARISH"
    assert "equity technical analyst" in stock_models.calls[0]["contents"]
    assert failure["indicator_confidence"] == 0


def test_sentiment_agent_handles_empty_success_and_error(monkeypatch):
    monkeypatch.setattr(sentiment_agent, "_fetch_rss_news", lambda **_kwargs: [])
    neutral = create_sentiment_agent(SimpleNamespace(models=FakeModels()))({"symbol": "BTC"})
    assert neutral["sentiment_label"] == "NEUTRAL"

    monkeypatch.setattr(
        sentiment_agent,
        "_fetch_rss_news",
        lambda **_kwargs: [
            {"title": "BTC ETF inflow grows", "summary": "Demand strong", "source": "coindesk", "published": "today"},
            {"title": "Macro turns supportive", "summary": "Risk assets bid", "source": "reuters", "published": "today"},
        ],
    )
    monkeypatch.setattr(sentiment_agent, "_fetch_fear_greed", lambda: {"value": 72, "label": "Greed"})
    monkeypatch.setattr(sentiment_agent, "_fetch_macro_context", lambda is_crypto: ({"verdict": "bullish", "signals": ["DXY down"]}, {"direction": "inflow"}))
    monkeypatch.setattr(sentiment_agent, "get_current_persona", lambda: "Persona")
    monkeypatch.setattr("intelligence.security.detect_suspicious_patterns", lambda _headline: [])
    monkeypatch.setattr("intelligence.security.sanitize_external_content", lambda text, source=None: text)
    persisted = {}
    monkeypatch.setattr(sentiment_agent, "_persist_sentiment", lambda **kwargs: persisted.update(kwargs))

    models = FakeModels(
        {
            "sentiment": "BULLISH",
            "score": 88,
            "key_factors": ["ETF inflow", "Macro support", "Risk appetite"],
            "risk_events": ["CPI"],
            "symbol_impact": "HIGH",
            "summary": "Strong positive catalyst stack.",
        }
    )
    success = create_sentiment_agent(SimpleNamespace(models=models))({"symbol": "BTC", "asset_class": "CRYPTO"})
    failure = create_sentiment_agent(SimpleNamespace(models=FakeModels(raises=RuntimeError("llm"))))(
        {"symbol": "BTC", "asset_class": "CRYPTO"}
    )

    assert success["sentiment_label"] == "BULLISH"
    assert success["sentiment_score"] == 88
    assert persisted["label"] == "BULLISH"
    assert "Fear & Greed Index" in models.calls[0]["contents"]
    assert failure["sentiment_label"] == "NEUTRAL"


def test_intermarket_macro_bias_and_agent_paths(monkeypatch):
    assert _compute_macro_bias({"trend": "DOWN"}, {"level": "LOW"}, {"value": 70}, "CRYPTO") == "RISK_ON"
    assert _compute_macro_bias({"trend": "UP"}, {"level": "HIGH"}, {"value": 20}, "CRYPTO") == "RISK_OFF"
    assert _compute_macro_bias({"trend": "UNKNOWN"}, {"level": "UNKNOWN"}, {"value": 50}, "MACRO") == "NEUTRAL"

    stock = create_intermarket_agent()({"asset_class": "STOCK"})
    assert stock["intermarket"]["skipped"] is True

    monkeypatch.setattr(intermarket_agent, "_CACHE", {})
    monkeypatch.setattr(intermarket_agent, "_CACHE_TS", {})
    monkeypatch.setattr(intermarket_agent, "_fetch_dxy", lambda: {"value": 100.0, "trend": "DOWN"})
    monkeypatch.setattr(intermarket_agent, "_fetch_vix", lambda: {"value": 14.0, "level": "LOW"})
    monkeypatch.setattr(intermarket_agent, "_fetch_fear_greed", lambda: {"value": 68, "label": "Greed"})
    monkeypatch.setattr(intermarket_agent, "_fetch_btc_dominance", lambda: {"value": 54.0})
    monkeypatch.setattr(intermarket_agent, "_fetch_funding_rate", lambda symbol: {"rate_pct": 0.01, "bias": "NEUTRAL"})
    monkeypatch.setattr(intermarket_agent, "_fetch_liquidation_bias", lambda symbol: {"liq_bias": "BULLISH", "buy_liq": 10, "sell_liq": 2})
    monkeypatch.setattr(intermarket_agent, "_fetch_oi_trend", lambda symbol: {"oi_trend": "RISING", "oi_change_pct": 3.2})

    node = create_intermarket_agent()
    crypto = node({"asset_class": "CRYPTO", "symbol": "BTC"})
    cached = node({"asset_class": "CRYPTO", "symbol": "ETH"})
    macro = node({"asset_class": "MACRO", "symbol": "GOLD"})

    assert crypto["intermarket"]["macro_bias"] == "RISK_ON"
    assert crypto["intermarket"]["liquidation"]["liq_bias"] == "BULLISH"
    assert cached["intermarket"] == crypto["intermarket"]
    assert "tailwind" in macro["intermarket"]["metals_context"].lower()


def test_sentiment_fetch_rss_news_caches_symbol_and_broad_feeds(monkeypatch):
    sentiment_agent._symbol_news_cache.clear()
    sentiment_agent._rss_cache.update({"timestamp": 0, "articles": [], "feed_type": "crypto"})

    class FakeFeed:
        def __init__(self, entries):
            self.entries = entries

    calls = []

    def _parse(url):
        calls.append(url)
        if "finance.yahoo.com" in url:
            return FakeFeed(
                [
                    {
                        "title": "BTC jumps",
                        "summary": "Strong move",
                        "published": "today",
                        "link": "https://example.com/btc",
                    }
                ]
            )
        return FakeFeed(
            [
                {
                    "title": "Broad market",
                    "summary": "Macro backdrop",
                    "published": "today",
                    "link": "https://example.com/broad",
                }
            ]
        )

    monkeypatch.setitem(sentiment_agent.__dict__, "time", SimpleNamespace(time=lambda: 1000.0))
    monkeypatch.setitem(__import__("sys").modules, "feedparser", SimpleNamespace(parse=_parse))

    btc_articles = sentiment_agent._fetch_rss_news("BTC")
    btc_cached = sentiment_agent._fetch_rss_news("BTC")
    macro_articles = sentiment_agent._fetch_rss_news("XAUUSD")
    macro_cached = sentiment_agent._fetch_rss_news("XAUUSD")

    assert len(btc_articles) == 1
    assert btc_cached == btc_articles
    assert btc_articles[0]["source"] == "Yahoo Finance (Ticker)"
    assert len(macro_articles) >= 1
    assert macro_cached == macro_articles
    assert any("feeds.finance.yahoo.com" in url for url in calls)
    assert any("reuters" in url or "investing.com" in url or "marketwatch.com" in url for url in calls)


def test_sentiment_macro_and_fear_greed_helpers_cache_and_fail(monkeypatch):
    sentiment_agent._macro_cache.clear()
    sentiment_agent._symbol_news_cache.clear()
    monkeypatch.setitem(sentiment_agent.__dict__, "time", SimpleNamespace(time=lambda: 5000.0))

    monkeypatch.setattr("intelligence.macro_signals.get_macro_regime", lambda: {"verdict": "bullish", "signals": ["DXY down"]})
    monkeypatch.setattr("intelligence.macro_signals.get_btc_etf_flows", lambda: {"direction": "inflow"})
    regime, etf = sentiment_agent._fetch_macro_context(True)
    regime_cached, etf_cached = sentiment_agent._fetch_macro_context(True)
    assert regime == {"verdict": "bullish", "signals": ["DXY down"]}
    assert etf == {"direction": "inflow"}
    assert regime_cached == regime
    assert etf_cached == etf

    class FakeUrlOpen:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"data":[{"value":"77","value_classification":"Greed"}]}'

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: FakeUrlOpen())
    fg = sentiment_agent._fetch_fear_greed()
    fg_cached = sentiment_agent._fetch_fear_greed()
    assert fg == {"value": 77, "label": "Greed"}
    assert fg_cached == fg

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("down")))
    sentiment_agent._symbol_news_cache.pop("__fg_index__", None)
    assert sentiment_agent._fetch_fear_greed() == {}


def test_sentiment_persist_sentiment_success_and_failure(monkeypatch):
    executed = []
    commits = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params):
            executed.append((sql, params))

    class FakeConn:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            commits.append("commit")

        def close(self):
            commits.append("close")

    monkeypatch.setattr(sentiment_agent.psycopg2, "connect", lambda **kwargs: FakeConn())
    sentiment_agent._persist_sentiment(
        symbol="btc",
        asset_type="CRYPTO",
        score=55,
        label="BULLISH",
        articles=[
            {"title": "A", "source": "one", "published": "now"},
            {"title": "B", "source": "two", "published": "now"},
        ],
        report="hello",
    )
    assert executed
    assert commits == ["commit", "close"]
    assert executed[0][1][0] == "BTC"
    assert executed[0][1][2] == 55

    monkeypatch.setattr(sentiment_agent.psycopg2, "connect", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("db down")))
    sentiment_agent._persist_sentiment("btc", "CRYPTO", 0, "NEUTRAL", [], "noop")


def test_intermarket_fetch_helpers_cover_success_and_fallbacks(monkeypatch):
    class FakeSeries:
        def __init__(self, values):
            self._values = list(values)
            self.iloc = self

        def __getitem__(self, index):
            return self._values[index]

        def ewm(self, span=20):
            return SimpleNamespace(mean=lambda: FakeSeries([value - 1 for value in self._values]))

    class FakeFrame:
        def __init__(self, closes):
            self._close = FakeSeries(closes)

        def __len__(self):
            return len(self._close._values)

        def __getitem__(self, key):
            if key == "Close":
                return SimpleNamespace(squeeze=lambda: self._close)
            raise KeyError(key)

    monkeypatch.setitem(
        __import__("sys").modules,
        "yfinance",
        SimpleNamespace(download=lambda *args, **kwargs: FakeFrame([100.0] * 11 + [105.0])),
    )
    dxy = intermarket_agent._fetch_dxy()
    vix = intermarket_agent._fetch_vix()
    assert dxy["trend"] == "UP"
    assert vix["level"] == "HIGH"

    def _requests_get(url, timeout=0, headers=None):
        if "alternative.me" in url:
            return SimpleNamespace(json=lambda: {"data": [{"value": "22", "value_classification": "Fear"}]})
        if "coingecko" in url:
            return SimpleNamespace(json=lambda: {"data": {"market_cap_percentage": {"btc": 57.3}}})
        if "fundingRate" in url:
            return SimpleNamespace(json=lambda: [{"fundingRate": "0.0006"}])
        if "allForceOrders" in url:
            return SimpleNamespace(json=lambda: [{"side": "BUY", "origQty": "8"}, {"side": "SELL", "origQty": "2"}])
        if "openInterestHist" in url:
            return SimpleNamespace(json=lambda: [{"sumOpenInterest": "100"}, {"sumOpenInterest": "104"}])
        raise AssertionError(url)

    monkeypatch.setitem(__import__("sys").modules, "requests", SimpleNamespace(get=_requests_get))
    assert intermarket_agent._fetch_fear_greed() == {"value": 22, "label": "Fear"}
    assert intermarket_agent._fetch_btc_dominance() == {"value": 57.3}
    assert intermarket_agent._fetch_funding_rate("BTCUSD") == {"rate_pct": 0.06, "bias": "BEARISH"}
    liq = intermarket_agent._fetch_liquidation_bias("BTCUSD")
    assert liq["liq_bias"] == "BULLISH"
    assert liq["buy_liq"] == 8.0
    oi = intermarket_agent._fetch_oi_trend("BTCUSD")
    assert oi["oi_trend"] == "RISING"
    assert oi["oi_change_pct"] == 4.0

    monkeypatch.setitem(__import__("sys").modules, "requests", SimpleNamespace(get=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("down"))))
    assert intermarket_agent._fetch_btc_dominance() == {"value": None}
    assert intermarket_agent._fetch_funding_rate("BTCUSD") == {"rate_pct": None, "bias": "NEUTRAL"}
