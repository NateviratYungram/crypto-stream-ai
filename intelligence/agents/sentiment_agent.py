"""
CryptoStream AI — Sentiment Agent
Fetches crypto news from free RSS feeds and uses Gemini to score market sentiment.
Ported from QuantAgent sentiment_agent.py, adapted for crypto-specific feeds.

Feeds used (all free, no API key required):
  - CoinDesk RSS
  - CoinTelegraph RSS
  - CryptoSlate RSS

Persistence:
  Every sentiment result is stored in news_sentiment (PostgreSQL) so the AI
  can query historical sentiment trends across time without re-fetching.
"""

import json
import logging
import os
import time

import psycopg2

from intelligence.event_logger import log_security_threat
from intelligence.persona import get_current_persona

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DB persistence helper
# ---------------------------------------------------------------------------
def _persist_sentiment(symbol: str, asset_type: str, score: int, label: str,
                       articles: list, report: str) -> None:
    """
    Persist sentiment result to news_sentiment table.
    Fire-and-forget: failures are logged but never bubble up to the AI flow.
    """
    try:
        top_headlines = [
            {"title": a.get("title", ""), "source": a.get("source", ""),
             "published": a.get("published", "")}
            for a in articles[:3]
        ]
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "5432")),
            dbname=os.getenv("DB_NAME", "crypto_stream_db"),
            user=os.getenv("DB_USER", "user"),
            password=os.getenv("DB_PASS", "password"),
        )
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO news_sentiment
                    (symbol, asset_type, score, label, headline_count, top_headlines, raw_report)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                symbol.upper(),
                asset_type,
                int(score),
                label,
                len(articles),
                json.dumps(top_headlines),
                report[:4000],   # cap to avoid huge TEXT blobs
            ))
        conn.commit()
        conn.close()
        logger.debug(f"Sentiment persisted for {symbol}: {label} ({score:+d})")
    except Exception as e:
        logger.warning(f"Failed to persist sentiment for {symbol}: {e}")
MODEL_ID = os.environ.get("MODEL_ID", "gemini-2.5-flash")

CRYPTO_RSS_FEEDS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss",
    "https://cryptoslate.com/feed/",
    "https://decrypt.co/feed",                        # Decrypt — quality crypto journalism
    "https://bitcoinmagazine.com/.rss/full/",          # Bitcoin Magazine — BTC-specific depth
]

# Macro/Gold/Forex feeds — used when asset is not crypto
MACRO_RSS_FEEDS = [
    "https://feeds.reuters.com/reuters/businessNews",
    "https://www.investing.com/rss/news_301.rss",  # Gold news
    "https://feeds.bbci.co.uk/news/business/rss.xml",
    "https://www.marketwatch.com/rss/topstories",   # MarketWatch top stories
]

MACRO_ASSETS = {"GOLD", "XAU", "XAUUSD", "GC=F", "SILVER", "OIL", "CL=F",
                "NASDAQ", "SP500", "IXIC", "GSPC", "DXY", "EURUSD"}

# Cache TTLs
# Symbol-specific: 5 min — ticker news updates frequently during trading hours
# Broad feeds: 15 min — general market headlines are slower-moving
SYMBOL_CACHE_TTL = 300   # 5 minutes
BROAD_CACHE_TTL  = 900   # 15 minutes

# Cache stores
_rss_cache = {"timestamp": 0, "articles": [], "feed_type": "crypto"}
_symbol_news_cache: dict = {}  # Per-symbol specific tracker (Stocks & Crypto)

def _fetch_rss_news(symbol_hint: str = "") -> list:
    """Fetch news from appropriate RSS feeds based on asset type, with caching."""
    global _rss_cache, _symbol_news_cache

    sym_upper = symbol_hint.upper().replace("USDT", "")
    # Normalize crypto symbols for YF (BTC -> BTC-USD)
    yf_symbol = sym_upper
    if sym_upper in {"BTC", "ETH", "SOL", "ADA", "XRP", "BNB", "DOT", "LINK", "AVAX"}:
        yf_symbol = f"{sym_upper}-USD"

    is_macro = sym_upper in MACRO_ASSETS
    now = time.time()

    # 1. Ticker-Specific Validation (Highest Relevance)
    # Use Yahoo Finance for specific headlines (Works for both Stocks and Crypto)
    if sym_upper and not is_macro:
        if sym_upper in _symbol_news_cache and (now - _symbol_news_cache[sym_upper]["timestamp"] < SYMBOL_CACHE_TTL):
            return _symbol_news_cache[sym_upper]["articles"]

        try:
            import feedparser
            # YF RSS is great for specific ticker news
            yf_feed = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={yf_symbol}&region=US&lang=en-US"
            feed = feedparser.parse(yf_feed)
            articles = []
            for entry in feed.entries[:8]: # Increase to 8 for better variety
                articles.append({
                    "title": entry.get("title", ""),
                    "summary": entry.get("summary", "")[:300],
                    "source": "Yahoo Finance (Ticker)",
                    "published": entry.get("published", ""),
                    "link": entry.get("link", "")
                })

            # If we found specific news, cache and return
            if articles:
                _symbol_news_cache[sym_upper] = {"timestamp": now, "articles": articles}
                return articles
        except Exception as e:
            logger.warning(f"Failed to fetch symbol-specific RSS for {sym_upper}: {e}")

    # 2. General Market / Crypto Broad Feeds (Fallback or Macro)
    feed_type = "macro" if is_macro else "crypto"
    cache_still_valid = (now - _rss_cache["timestamp"] < BROAD_CACHE_TTL
                         and _rss_cache["articles"]
                         and _rss_cache.get("feed_type") == feed_type)

    if cache_still_valid:
        return _rss_cache["articles"]

    try:
        import feedparser
    except ImportError:
        logger.warning("feedparser not installed. Run: pip install feedparser")
        return []

    feeds = MACRO_RSS_FEEDS if is_macro else CRYPTO_RSS_FEEDS
    articles = []
    for feed_url in feeds:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:8]:
                title = entry.get("title", "")
                summary = entry.get("summary", "")[:200]
                published = entry.get("published", "")
                link = entry.get("link", "")
                source = feed_url.split("/")[2].replace("www.", "")
                articles.append({
                    "title": title,
                    "summary": summary,
                    "source": source,
                    "published": published,
                    "link": link,
                })
        except Exception as e:
            logger.warning(f"RSS feed error ({feed_url}): {e}")
            continue

    _rss_cache["timestamp"] = now
    _rss_cache["articles"] = articles
    _rss_cache["feed_type"] = feed_type
    return articles


_macro_cache: dict = {}   # {ts: float, regime: dict, etf: dict}
_MACRO_AGENT_TTL = 3600  # re-fetch macro at most once per hour


def _fetch_macro_context(is_crypto: bool) -> tuple[dict, dict]:
    """
    Fetch macro regime + BTC ETF flows (cached 1h).
    Returns (regime_dict, etf_dict). Both are {} on failure.
    """
    global _macro_cache
    now = time.time()
    if _macro_cache.get("ts", 0) + _MACRO_AGENT_TTL > now:
        return _macro_cache.get("regime", {}), _macro_cache.get("etf", {})
    try:
        from intelligence.macro_signals import get_btc_etf_flows, get_macro_regime
        regime = get_macro_regime()
        etf    = get_btc_etf_flows() if is_crypto else {}
        _macro_cache = {"ts": now, "regime": regime, "etf": etf}
        return regime, etf
    except Exception as e:
        logger.warning(f"SentimentAgent: macro context fetch failed: {e}")
        return {}, {}


def _fetch_fear_greed() -> dict:
    """
    Fetch Crypto Fear & Greed Index from alternative.me (free, no API key).
    Returns {"value": int, "label": str} or {} on failure. Cached 1 hour.
    """
    global _rss_cache
    cache_key = "__fg_index__"
    now = time.time()
    cached = _symbol_news_cache.get(cache_key)
    if cached and (now - cached["timestamp"] < 3600):
        return cached["data"]
    try:
        import json as _json
        import urllib.request
        with urllib.request.urlopen(
            "https://api.alternative.me/fng/?limit=1&format=json", timeout=5
        ) as resp:
            raw = _json.loads(resp.read())
        entry = raw.get("data", [{}])[0]
        result = {
            "value": int(entry.get("value", 50)),
            "label": entry.get("value_classification", "Neutral"),
        }
        _symbol_news_cache[cache_key] = {"timestamp": now, "data": result}
        return result
    except Exception as e:
        logger.warning(f"Fear & Greed fetch failed: {e}")
        return {}


def create_sentiment_agent(client):
    """
    Returns a sentiment_agent_node function.

    Fetches crypto RSS news + Fear & Greed Index → Gemini analysis → score -100 to +100.
    Falls back to NEUTRAL (0) if sources unavailable.
    """

    def sentiment_agent_node(state: dict) -> dict:
        symbol = state.get("symbol", "BTC")
        asset_class = state.get("asset_class", "CRYPTO")

        articles = _fetch_rss_news(symbol_hint=symbol)
        is_crypto = asset_class.upper() in ("CRYPTO", "")

        # Fetch Fear & Greed for crypto assets (adds market-wide mood context)
        fg = {}
        if is_crypto:
            fg = _fetch_fear_greed()

        # Fetch macro regime overlay (QQQ/XLP/GLD/UUP/BTC trends, ETF flows)
        macro_regime, btc_etf = _fetch_macro_context(is_crypto)

        # Fallback: neutral if no news
        if not articles:
            return {
                "sentiment_report": "📰 **SENTIMENT:** NEUTRAL (no news data available)",
                "sentiment_score": 0,
                "sentiment_label": "NEUTRAL",
            }

        # Build news text for Gemini
        raw_news = f"=== Latest News (Relevance: {symbol}) ===\n\n"
        from intelligence.security import detect_suspicious_patterns

        for art in articles[:12]:
            headline = art.get('title', '')
            suspicious = detect_suspicious_patterns(headline)
            if suspicious:
                log_security_threat(source=f"RSS_{art['source']}", pattern=str(suspicious))

            raw_news += f"[{art['source']}] {headline}\n"
            if art.get("summary"):
                raw_news += f"  → {art['summary'][:120]}\n"

        # Apply Security Sanitization (Institutional Logic)
        from intelligence.security import sanitize_external_content
        news_text = sanitize_external_content(raw_news, source="RSS_MULTI_FEED")

        # Fear & Greed context block (crypto only)
        fg_section = ""
        if fg:
            fg_section = (
                f"\n=== Crypto Fear & Greed Index ===\n"
                f"Current Score: {fg['value']}/100 — {fg['label']}\n"
                f"(0=Extreme Fear, 50=Neutral, 100=Extreme Greed)\n"
            )

        # Macro regime + BTC ETF flow context block
        macro_section = ""
        if macro_regime:
            try:
                from intelligence.macro_signals import format_macro_for_prompt
                macro_section = "\n" + format_macro_for_prompt(macro_regime, btc_etf) + "\n"
            except Exception:
                pass

        persona_instructions = get_current_persona()
        prompt = f"""{persona_instructions}

Analyze these headlines for their impact on {symbol} price.

{news_text}{fg_section}{macro_section}
Provide sentiment analysis as JSON:
{{
  "sentiment": "BULLISH" | "BEARISH" | "NEUTRAL",
  "score": <integer from -100 to +100>,
  "key_factors": ["factor1", "factor2", "factor3"],
  "risk_events": ["risk1", "risk2"],
  "symbol_impact": "HIGH" | "MEDIUM" | "LOW",
  "summary": "<2-3 sentences on how this news affects {symbol}>"
}}

Scoring:
  +100 = extremely bullish (major institutional adoption, ETF approval, etc.)
  +50  = moderately bullish
  0    = neutral/mixed
  -50  = moderately bearish
  -100 = extremely bearish (major hack, ban, etc.)

Rules:
- Focus on news DIRECTLY relevant to {symbol}
- General crypto market news = MEDIUM impact
- Unrelated news: ignore
- Mixed/unclear news → score near 0
- If Fear & Greed Index is provided, treat it as a secondary macro-mood signal
  (Extreme Fear: slight bearish bias; Extreme Greed: slight overbought caution)
- If Macro Regime Overlay is provided, use it as a broad market backdrop:
  * "defensive" macro verdict with "outflow" ETF flows → cap bullish score at +30
  * "bullish" macro verdict with "inflow" ETF flows → allow full bullish range
  * Macro context should AMPLIFY news signals, not override them entirely
"""

        try:
            response = client.models.generate_content(
                model=MODEL_ID,
                contents=prompt,
                config={"response_mime_type": "application/json"},
            )
            data = json.loads(response.text)
            sentiment = data.get("sentiment", "NEUTRAL")
            score = float(data.get("score", 0))
            score = max(-100, min(100, score))
            key_factors = data.get("key_factors", [])
            risk_events = data.get("risk_events", [])
            impact = data.get("symbol_impact", "MEDIUM")
            summary = data.get("summary", "")

            sent_emoji = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "⚪"}.get(sentiment, "⚪")

            report = f"""📰 **SENTIMENT ANALYSIS — {symbol}**

**Sentiment:** {sent_emoji} {sentiment} (Score: {int(score):+d}/100)
**Market Impact:** {impact}

**Key Drivers:**
"""
            for f in key_factors[:3]:
                report += f"  • {f}\n"

            if risk_events:
                report += "\n**Risk Events:**\n"
                for r in risk_events[:2]:
                    report += f"  ⚠️ {r}\n"

            report += f"\n**Summary:** {summary}"

            # Persist to DB (non-blocking — failure doesn't affect AI response)
            _persist_sentiment(
                symbol=symbol,
                asset_type=asset_class,
                score=int(score),
                label=sentiment,
                articles=articles,
                report=report,
            )

            return {
                "sentiment_report": report,
                "sentiment_score": score,
                "sentiment_label": sentiment,
                "sentiment_data": data,
                "fear_greed_index": fg,
                "macro_regime": macro_regime.get("verdict") if macro_regime else None,
                "macro_signals": macro_regime.get("signals", []),
                "btc_etf_flows": btc_etf.get("direction") if btc_etf else None,
            }

        except Exception as e:
            logger.error(f"SentimentAgent error: {e}")
            return {
                "sentiment_report": f"📰 **SENTIMENT:** NEUTRAL (analysis error: {str(e)[:60]})",
                "sentiment_score": 0,
                "sentiment_label": "NEUTRAL",
            }

    return sentiment_agent_node
