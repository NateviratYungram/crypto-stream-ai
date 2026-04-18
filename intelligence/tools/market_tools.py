import logging
import json
import os
import pandas as pd
import yfinance as yf
from typing import Dict, Any, Optional, List
from dotenv import load_dotenv
from google import genai as _genai
from intelligence.technical_engine import (
    get_kline_data, compute_indicators, get_indicator_summary,
    get_smart_money_analysis
)
from intelligence.constants import MACRO_MAPPING, NASDAQ_100_TICKERS, SP500_TICKERS, SMALL_CAP_TICKERS
from intelligence.backtest_crypto import run_crypto_backtest
from intelligence.mt5_connector import get_mt5_account_info, mt5_execute_trade, mt5_close_position
import time
import psycopg2
from intelligence.agents.sentiment_agent import _fetch_rss_news
import psycopg2.extras
import random
import sqlite3
import uuid
from datetime import datetime as dt_datetime
from intelligence.brain import update_brain_state, get_brain_state
from intelligence.symbol_index import search_market_symbols
from intelligence.visual_analysis import analyze_chart_visually
try:
    from intelligence.ml.signal_model import predict_win_probability, predict_with_neural_consensus
except Exception:
    def predict_win_probability(*a, **kw): return {"win_probability": 0.5, "direction": "HOLD", "confidence": 0}
    def predict_with_neural_consensus(*a, **kw): return {"win_probability": 0.5, "direction": "HOLD", "confidence": 0}
from intelligence.risk_manager import risk_manager

load_dotenv()

logger = logging.getLogger(__name__)

# ── Cache Layer (Redis → in-process fallback) ────────────────────────────────
# Tries Redis first for shared, persistent cache across restarts.
# Falls back to a local dict if Redis is unavailable (dev / offline mode).
try:
    import redis as _redis_lib
    _REDIS_AVAILABLE = True
except ImportError:
    _redis_lib = None
    _REDIS_AVAILABLE = False

_REDIS = None
_CACHE: Dict[str, Dict] = {}   # in-process fallback

def _get_redis():
    """Return a Redis client, or None if Redis is unreachable or not installed."""
    global _REDIS
    if not _REDIS_AVAILABLE:
        return None
    if _REDIS is not None:
        return _REDIS
    try:
        r = _redis_lib.Redis(
            host=os.getenv("REDIS_HOST", "redis"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            db=0,
            socket_connect_timeout=1,
            decode_responses=True,
        )
        r.ping()
        _REDIS = r
        logger.info("[Cache] Connected to Redis")
    except Exception:
        logger.warning("[Cache] Redis unavailable — using in-process fallback")
        _REDIS = None
    return _REDIS

def _cache_get(key: str):
    """Return cached value if still fresh, else None."""
    r = _get_redis()
    if r:
        try:
            raw = r.get(key)
            if raw:
                logger.debug(f"[Cache HIT Redis] {key}")
                return json.loads(raw)
        except Exception:
            pass
    # fallback
    entry = _CACHE.get(key)
    if entry and (time.time() - entry["ts"]) < entry["ttl"]:
        logger.debug(f"[Cache HIT local] {key}")
        return entry["val"]
    return None

def _cache_set(key: str, val, ttl: int):
    """Store value with TTL in seconds in Redis (or local fallback)."""
    r = _get_redis()
    if r:
        try:
            r.setex(key, ttl, json.dumps(val, default=str))
            return
        except Exception:
            pass
    _CACHE[key] = {"val": val, "ts": time.time(), "ttl": ttl}

# Cache for dynamic index data to avoid repeated disk reads
_INDEX_CACHE = {"data": None, "timestamp": 0}

def _load_index_data():
    """Load the full set of S&P500, NASDAQ, and NYSE tickers from local JSON."""
    global _INDEX_CACHE
    now = time.time()
    # Cache for 1 hour
    if _INDEX_CACHE["data"] and (now - _INDEX_CACHE["timestamp"]) < 3600:
        return _INDEX_CACHE["data"]
    
    path = os.path.join("intelligence", "market_data", "index_tickers.json")
    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                data = json.load(f)
                _INDEX_CACHE = {"data": data, "timestamp": now}
                return data
        except Exception as e:
            logger.error(f"Failed to load dynamic tickers: {e}")
    
    # Fallback to hardcoded list if JSON missing
    return {
        "indices": {"SP500": SP500_TICKERS, "NASDAQ_100": NASDAQ_100_TICKERS},
        "exchanges": {"NASDAQ": [], "NYSE_AMEX": []}
    }

def _get_db_conn():
    """Helper to get a fresh DB connection for memory tools."""
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        port=os.getenv('DB_PORT', '5432'),
        database=os.getenv('DB_NAME', 'crypto_stream_db'),
        user=os.getenv('DB_USER', 'user'),
        password=os.getenv('DB_PASS', 'password')
    )

def _get_embedding(text: str) -> Optional[List[float]]:
    """
    Generate a 768-dim embedding using Gemini text-embedding-004.
    Returns None on failure so callers can gracefully degrade.
    """
    try:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return None
        client = _genai.Client(api_key=api_key)
        result = client.models.embed_content(
            model="models/text-embedding-004",
            contents=[text],
        )
        return result.embeddings[0].values
    except Exception as e:
        logger.warning(f"Embedding generation failed (non-critical): {e}")
        return None

def remember_trade(symbol: str, side: str, entry_price: float, reasoning: str, outcome: Optional[str] = None, pnl_pct: Optional[float] = None, market_conditions: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Record a trading decision or outcome into the Trade Memory.
    Generates a semantic embedding so future recall_memories calls can find
    situations that are contextually similar, not just same-symbol matches.
    """
    try:
        # Build embedding text: combine reasoning + key market conditions
        embed_text = f"{symbol} {side} at {entry_price}. {reasoning}"
        if market_conditions:
            embed_text += " Conditions: " + json.dumps(market_conditions)
        embedding = _get_embedding(embed_text)

        conn = _get_db_conn()
        cur = conn.cursor()

        query = """
            INSERT INTO trade_memory
                (symbol, side, entry_price, reasoning, outcome, pnl_pct, market_conditions, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id;
        """
        cur.execute(query, (
            symbol.upper(), side.upper(), entry_price, reasoning,
            outcome, pnl_pct,
            json.dumps(market_conditions) if market_conditions else None,
            embedding,
        ))
        trade_id = cur.fetchone()[0]

        conn.commit()
        cur.close()
        conn.close()

        return {"status": "SUCCESS", "message": f"Trade memory recorded with ID: {trade_id}", "trade_id": trade_id}
    except Exception as e:
        logger.error(f"Error in remember_trade: {e}")
        return {"status": "ERROR", "error": str(e)}

def recall_memories(symbol: str, limit: int = 3, context: Optional[str] = None) -> Dict[str, Any]:
    """
    Retrieve past trade memories for a specific symbol.
    If `context` is provided (e.g. current market description), performs semantic
    similarity search to surface memories from situations most like the present,
    not just the most recent ones. Falls back to recency sort if no embedding available.
    """
    try:
        conn = _get_db_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Try semantic search if context is given
        embedding = _get_embedding(context) if context else None

        if embedding:
            query = """
                SELECT side, entry_price, outcome, pnl_pct, reasoning, timestamp,
                       1 - (embedding <=> %s::vector) AS similarity
                FROM trade_memory
                WHERE symbol = %s AND embedding IS NOT NULL
                ORDER BY embedding <=> %s::vector
                LIMIT %s;
            """
            cur.execute(query, (embedding, symbol.upper(), embedding, limit))
            search_type = "semantic"
        else:
            query = """
                SELECT side, entry_price, outcome, pnl_pct, reasoning, timestamp,
                       NULL AS similarity
                FROM trade_memory
                WHERE symbol = %s
                ORDER BY timestamp DESC
                LIMIT %s;
            """
            cur.execute(query, (symbol.upper(), limit))
            search_type = "recency"

        memories = cur.fetchall()
        cur.close()
        conn.close()

        for m in memories:
            if m['timestamp']:
                m['timestamp'] = m['timestamp'].isoformat()

        return {
            "symbol": symbol.upper(),
            "search_type": search_type,
            "memory_count": len(memories),
            "past_trades": memories,
            "instruction": "Analyze if current market conditions match any successful past trades or mirror previous failures."
        }
    except Exception as e:
        logger.error(f"Error in recall_memories: {e}")
        return {"status": "ERROR", "error": str(e)}

def get_news_impact(symbol: str = "BTC") -> Dict[str, Any]:
    """
    Fetch the latest news and calculate the market impact score for a specific symbol.
    Returns sentiment data, key news headlines, and an 'Impact Score' (-100 to 100).
    """
    try:
        logger.info(f"Tool: Getting news impact for {symbol}")
        articles = _fetch_rss_news(symbol_hint=symbol)
        
        if not articles:
            return {
                "symbol": symbol,
                "impact_score": 0,
                "sentiment": "NEUTRAL",
                "news_count": 0,
                "top_headlines": [],
                "summary": "No recent news found for this asset."
            }

        # Format headlines for the agent to see
        headlines = [f"[{a['source']}] {a['title']}" for a in articles[:5]]
        
        # We'll let the Master Agent do the deep semantic scoring, 
        # but we provide the raw material and a heuristic 'Impact Score' 
        # based on keyword density if we wanted to be fancy, 
        # but for now, we return the articles for the LLM to process.
        
        return {
            "symbol": symbol,
            "news_count": len(articles),
            "top_headlines": headlines,
            "raw_news": articles[:10], # Give the agent enough context
            "status": "SUCCESS"
        }
    except Exception as e:
        logger.error(f"Error in get_news_impact tool: {e}")
        return {"error": str(e)}

def get_sentiment_history(symbol: str, days: int = 30) -> Dict[str, Any]:
    """
    Query historical sentiment scores for a symbol from the news_sentiment table.
    Returns trend, average score, and recent data points so the AI can identify
    whether market mood has been improving or deteriorating over time.

    Use this when asked: "how has sentiment changed?", "was market bullish last week?",
    "show me BTC sentiment over the past month", etc.
    """
    try:
        conn = _get_db_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute("""
            SELECT
                DATE(analysed_at AT TIME ZONE 'UTC')  AS date,
                ROUND(AVG(score))                     AS avg_score,
                MODE() WITHIN GROUP (ORDER BY label)  AS dominant_label,
                COUNT(*)                              AS reading_count,
                MAX(score)                            AS max_score,
                MIN(score)                            AS min_score
            FROM news_sentiment
            WHERE symbol    = %s
              AND analysed_at >= NOW() - INTERVAL '%s days'
            GROUP BY DATE(analysed_at AT TIME ZONE 'UTC')
            ORDER BY date DESC
            LIMIT 60
        """, (symbol.upper(), days))

        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        conn.close()

        if not rows:
            return {
                "symbol": symbol.upper(),
                "status": "NO_DATA",
                "message": f"No sentiment history found for {symbol} in the last {days} days. "
                           "Data accumulates each time the AI analyses this symbol.",
            }

        # Compute trend: compare first-half vs second-half average
        mid = len(rows) // 2
        recent_avg = sum(r["avg_score"] for r in rows[:mid]) / max(mid, 1)
        older_avg  = sum(r["avg_score"] for r in rows[mid:]) / max(len(rows) - mid, 1)
        trend = "IMPROVING" if recent_avg > older_avg + 5 else \
                "DETERIORATING" if recent_avg < older_avg - 5 else "STABLE"

        overall_avg = sum(r["avg_score"] for r in rows) / len(rows)

        # Serialize dates
        for r in rows:
            if hasattr(r["date"], "isoformat"):
                r["date"] = r["date"].isoformat()
            r["avg_score"] = int(r["avg_score"])

        return {
            "symbol":       symbol.upper(),
            "period_days":  days,
            "data_points":  len(rows),
            "overall_avg_score": round(overall_avg, 1),
            "trend":        trend,
            "recent_avg":   round(recent_avg, 1),
            "older_avg":    round(older_avg, 1),
            "daily_scores": rows[:14],   # last 14 days detail
            "interpretation": (
                f"Over the past {days} days, {symbol} sentiment has been "
                f"{'positive' if overall_avg > 10 else 'negative' if overall_avg < -10 else 'neutral'} "
                f"(avg {overall_avg:+.0f}/100) and is {trend.lower()}."
            ),
        }

    except Exception as e:
        logger.error(f"Error in get_sentiment_history for {symbol}: {e}")
        return {"status": "ERROR", "error": str(e)}


def analyze_correlation_risk(symbol: str) -> Dict[str, Any]:
    """
    Intelligence V6: Analyzes the overlap risk of a new symbol against active positions.
    Returns correlation conflicts and a safety status.
    """
    try:
        logger.info(f"Tool: Analyzing correlation risk for {symbol}")
        res = risk_manager.check_correlation_risk(symbol)
        return res
    except Exception as e:
        logger.error(f"Error in analyze_correlation_risk tool: {e}")
        return {"status": "ERROR", "error": str(e)}

def get_market_features(symbol: str) -> Dict[str, Any]:
    """
    Retrieve precomputed statistical features for a symbol from the feature store.
    Returns returns, volatility, correlations, beta, and price position.

    Use this when asked about:
    - Returns / performance: "NVDA ทำได้ดีแค่ไหน 3 เดือนที่แล้ว?"
    - Volatility / risk: "BTC ผันผวนแค่ไหน?", "asset ไหน stable ที่สุด?"
    - Correlation: "BTC สัมพันธ์กับ SP500 มั้ยช่วงนี้?", "ETH ยัง sync กับ BTC อยู่มั้ย?"
    - Beta / market sensitivity: "NVDA เสี่ยงกว่าตลาดเท่าไหร่?"
    - Price position: "BTC ห่างจาก 52w high เท่าไหร่?"
    - Relative strength: "หุ้นไหน outperform ตลาด?"
    """
    cache_key = f"market_features:{symbol.upper()}"
    cached = _cache_get(cache_key)
    if cached:
        return cached
    try:
        conn = _get_db_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute("""
            SELECT *
            FROM   market_features
            WHERE  symbol = %s
            ORDER  BY date DESC
            LIMIT  1
        """, (symbol.upper(),))
        row = cur.fetchone()
        cur.close()
        conn.close()

        if not row:
            return {
                "symbol": symbol.upper(),
                "status": "NO_DATA",
                "message": (
                    f"No feature data for {symbol}. "
                    "The feature store runs nightly — data available after the first run. "
                    "Use get_market_analysis() for live technical analysis instead."
                ),
            }

        row = dict(row)
        computed_date = row.get("date")
        if hasattr(computed_date, "isoformat"):
            computed_date = computed_date.isoformat()

        def fmt_pct(v):
            return f"{float(v)*100:+.2f}%" if v is not None else "N/A"
        def fmt_corr(v):
            return f"{float(v):.2f}" if v is not None else "N/A"

        result = {
            "symbol":       symbol.upper(),
            "as_of":        computed_date,
            "returns": {
                "1d":  fmt_pct(row.get("return_1d")),
                "7d":  fmt_pct(row.get("return_7d")),
                "30d": fmt_pct(row.get("return_30d")),
                "90d": fmt_pct(row.get("return_90d")),
                "1y":  fmt_pct(row.get("return_365d")),
            },
            "volatility_annualized": {
                "7d":  fmt_pct(row.get("volatility_7d")),
                "30d": fmt_pct(row.get("volatility_30d")),
                "90d": fmt_pct(row.get("volatility_90d")),
            },
            "correlation": {
                "vs_sp500_30d": fmt_corr(row.get("corr_vs_sp500_30d")),
                "vs_sp500_90d": fmt_corr(row.get("corr_vs_sp500_90d")),
                "vs_btc_30d":   fmt_corr(row.get("corr_vs_btc_30d")),
                "vs_btc_90d":   fmt_corr(row.get("corr_vs_btc_90d")),
                "vs_gold_30d":  fmt_corr(row.get("corr_vs_gold_30d")),
            },
            "beta_vs_sp500":     fmt_corr(row.get("beta_vs_sp500")),
            "price_position": {
                "pct_from_52w_high": f"{float(row['pct_from_52w_high']):+.1f}%" if row.get("pct_from_52w_high") is not None else "N/A",
                "pct_from_52w_low":  f"{float(row['pct_from_52w_low']):+.1f}%"  if row.get("pct_from_52w_low")  is not None else "N/A",
            },
            "relative_strength_vs_sp500_30d": fmt_pct(row.get("rel_strength_30d")),
            "interpretation": _interpret_features(row, symbol),
        }
        _cache_set(cache_key, result, ttl=3600)
        return result
    except Exception as e:
        logger.error(f"get_market_features error for {symbol}: {e}")
        return {"status": "ERROR", "error": str(e)}


def _interpret_features(row: dict, symbol: str) -> str:
    """Generate a plain-language summary of the features for the AI."""
    parts = []
    r30 = row.get("return_30d")
    if r30 is not None:
        parts.append(f"{symbol} returned {float(r30)*100:+.1f}% over the past 30 days")
    vol30 = row.get("volatility_30d")
    if vol30 is not None:
        level = "highly volatile" if float(vol30) > 0.5 else "moderately volatile" if float(vol30) > 0.2 else "relatively stable"
        parts.append(f"is {level} ({float(vol30)*100:.0f}% annualized vol)")
    corr_sp500 = row.get("corr_vs_sp500_30d")
    if corr_sp500 is not None:
        c = float(corr_sp500)
        coupling = "strongly correlated" if c > 0.7 else "moderately correlated" if c > 0.4 else "weakly correlated" if c > 0.1 else "decoupled"
        parts.append(f"{coupling} with SP500 (r={c:.2f} over 30d)")
    beta = row.get("beta_vs_sp500")
    if beta is not None:
        b = float(beta)
        parts.append(f"beta vs SP500 = {b:.2f} ({'more' if b > 1 else 'less'} risky than market)")
    rel = row.get("rel_strength_30d")
    if rel is not None:
        r = float(rel) * 100
        parts.append(f"{'outperformed' if r > 0 else 'underperformed'} SP500 by {abs(r):.1f}pp over 30d")
    return ". ".join(parts) + "." if parts else "Insufficient data for interpretation."


def get_market_regime() -> Dict[str, Any]:
    """
    Return the current global market regime (RISK_ON / RISK_OFF / NEUTRAL)
    with supporting evidence: volatility levels, BTC/SP500 correlation, MA200 position.

    Use this when asked:
    - "ตลาดตอนนี้อยู่ใน risk-on หรือ risk-off?"
    - "ตอนนี้ควร aggressive หรือ defensive?"
    - "BTC decoupled จาก US stocks แล้วมั้ย?"
    - "ตลาดหุ้น bullish หรือ bearish ระยะกลาง?"
    """
    cached = _cache_get("market_regime")
    if cached:
        return cached
    try:
        conn = _get_db_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute("""
            SELECT * FROM market_regime
            ORDER BY date DESC LIMIT 1
        """)
        row = cur.fetchone()
        cur.close()
        conn.close()

        if not row:
            return {
                "status": "NO_DATA",
                "message": "Market regime not computed yet. Runs nightly after feature_store DAG.",
            }

        row = dict(row)
        regime_date = row.get("date")
        if hasattr(regime_date, "isoformat"):
            regime_date = regime_date.isoformat()

        drivers = row.get("regime_drivers", [])
        if isinstance(drivers, str):
            import json as _json
            try:
                drivers = _json.loads(drivers)
            except Exception:
                drivers = []

        regime = row.get("regime", "NEUTRAL")
        confidence = float(row.get("regime_confidence", 50))

        emoji = {"RISK_ON": "🟢", "RISK_OFF": "🔴", "NEUTRAL": "⚪"}.get(regime, "⚪")

        sp500_vol = row.get("sp500_vol_30d")
        crypto_vol = row.get("crypto_vol_30d")
        btc_corr = row.get("btc_sp500_corr_30d")
        sp500_ma = row.get("sp500_vs_ma200")
        btc_ma = row.get("btc_vs_ma200")

        def fmt(v, pct=True):
            if v is None:
                return "N/A"
            return f"{float(v)*100:.1f}%" if pct else f"{float(v):.2f}"

        result = {
            "as_of":              regime_date,
            "regime":             regime,
            "regime_emoji":       emoji,
            "confidence":         f"{confidence:.0f}%",
            "drivers":            drivers,
            "market_stress": {
                "sp500_vol_30d_annualized":  fmt(sp500_vol),
                "crypto_vol_30d_annualized": fmt(crypto_vol),
                "btc_sp500_correlation_30d": fmt(btc_corr, pct=False),
            },
            "trend_context": {
                "sp500_vs_200ma": fmt(sp500_ma) if sp500_ma is not None else "N/A",
                "btc_vs_200ma":   fmt(btc_ma)   if btc_ma   is not None else "N/A",
            },
            "interpretation": (
                f"Current market regime is {emoji} {regime} ({confidence:.0f}% confidence). "
                + (f"SP500 is {'above' if sp500_ma and float(sp500_ma) > 0 else 'below'} its 200MA. " if sp500_ma is not None else "")
                + (f"BTC/SP500 correlation is {float(btc_corr):.2f} (30d). " if btc_corr is not None else "")
                + (f"Key drivers: {', '.join(drivers)}." if drivers else "")
            ),
        }
        _cache_set("market_regime", result, ttl=3600)
        return result
    except Exception as e:
        logger.error(f"get_market_regime error: {e}")
        return {"status": "ERROR", "error": str(e)}


def get_top_movers(metric: str = "return_30d", direction: str = "top", limit: int = 10) -> Dict[str, Any]:
    """
    Rank all tracked symbols by a feature metric and return the top/bottom performers.

    Use this when asked:
    - "หุ้นไหน outperform ตลาดมากที่สุดช่วงนี้?"  → metric=rel_strength_30d, direction=top
    - "asset ไหนผันผวนน้อยที่สุด?"               → metric=volatility_30d, direction=bottom
    - "หุ้นไหน return ดีที่สุด 3 เดือน?"          → metric=return_90d, direction=top
    - "asset ไหน corr กับ BTC สูงที่สุด?"         → metric=corr_vs_btc_30d, direction=top

    Valid metrics: return_1d, return_7d, return_30d, return_90d, return_365d,
                   volatility_30d, volatility_90d,
                   corr_vs_sp500_30d, corr_vs_btc_30d, corr_vs_gold_30d,
                   beta_vs_sp500, rel_strength_30d,
                   pct_from_52w_high, pct_from_52w_low
    """
    VALID_METRICS = {
        "return_1d", "return_7d", "return_30d", "return_90d", "return_365d",
        "volatility_7d", "volatility_30d", "volatility_90d",
        "corr_vs_sp500_30d", "corr_vs_sp500_90d",
        "corr_vs_btc_30d", "corr_vs_btc_90d", "corr_vs_gold_30d",
        "beta_vs_sp500", "rel_strength_30d",
        "pct_from_52w_high", "pct_from_52w_low",
    }
    if metric not in VALID_METRICS:
        return {"status": "ERROR", "error": f"Invalid metric '{metric}'. Valid: {sorted(VALID_METRICS)}"}

    order = "DESC" if direction == "top" else "ASC"
    limit = max(1, min(limit, 50))

    try:
        conn = _get_db_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(f"""
            SELECT symbol, date, {metric}
            FROM   market_features
            WHERE  date = (SELECT MAX(date) FROM market_features)
              AND  {metric} IS NOT NULL
            ORDER  BY {metric} {order}
            LIMIT  %s
        """, (limit,))
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        conn.close()

        for r in rows:
            if hasattr(r.get("date"), "isoformat"):
                r["date"] = r["date"].isoformat()
            if r.get(metric) is not None:
                v = float(r[metric])
                if "return" in metric or "vol" in metric or "strength" in metric:
                    r[metric] = f"{v*100:+.2f}%"
                elif "corr" in metric or "beta" in metric:
                    r[metric] = f"{v:.3f}"
                else:
                    r[metric] = f"{v:+.2f}%"

        return {
            "metric":    metric,
            "direction": direction,
            "as_of":     rows[0]["date"] if rows else None,
            "results":   rows,
        }
    except Exception as e:
        logger.error(f"get_top_movers error: {e}")
        return {"status": "ERROR", "error": str(e)}


def _get_stock_fundamentals(ticker: str) -> Dict[str, Any]:
    """
    Fetch fundamental data for value investing analysis.
    Returns P/E, P/B, growth rates, 52w range, analyst targets, etc.
    """
    try:
        import yfinance as yf
        stock = yf.Ticker(ticker)
        info = stock.info

        pe   = info.get("trailingPE")
        fpe  = info.get("forwardPE")
        pb   = info.get("priceToBook")
        ps   = info.get("priceToSalesTrailing12Months")
        eps  = info.get("trailingEps")
        eg   = info.get("earningsGrowth")       # YoY EPS growth
        rg   = info.get("revenueGrowth")        # YoY revenue growth
        pm   = info.get("profitMargins")
        roe  = info.get("returnOnEquity")
        de   = info.get("debtToEquity")
        w52h = info.get("fiftyTwoWeekHigh")
        w52l = info.get("fiftyTwoWeekLow")
        mktcap = info.get("marketCap")
        target = info.get("targetMeanPrice")
        analyst_cnt = info.get("numberOfAnalystOpinions", 0)
        price  = info.get("currentPrice") or info.get("regularMarketPrice")

        # ── Valuation signals ──────────────────────────────────────────────────
        pe_signal = (
            "CHEAP"     if pe and pe < 15 else
            "FAIR"      if pe and pe < 25 else
            "EXPENSIVE" if pe else "N/A"
        )

        # Position in 52-week range (0% = at 52w low, 100% = at 52w high)
        range_pct = None
        range_signal = "UNKNOWN"
        if w52l and w52h and w52h > w52l and price:
            range_pct = round(((price - w52l) / (w52h - w52l)) * 100, 1)
            range_signal = (
                "NEAR_LOW_BUY_ZONE"  if range_pct < 25 else
                "LOWER_MID_RANGE"    if range_pct < 45 else
                "MID_RANGE"          if range_pct < 65 else
                "NEAR_HIGH_CAUTION"
            )

        # Upside to analyst target
        upside_pct = None
        if target and price and price > 0:
            upside_pct = round(((target - price) / price) * 100, 1)

        return {
            "company":          info.get("longName", ticker),
            "sector":           info.get("sector", "N/A"),
            "industry":         info.get("industry", "N/A"),
            "market_cap_b":     round(mktcap / 1e9, 2) if mktcap else None,
            "current_price":    price,
            # Valuation multiples
            "pe_trailing":      round(pe, 2)  if pe  else None,
            "pe_forward":       round(fpe, 2) if fpe else None,
            "pb_ratio":         round(pb, 2)  if pb  else None,
            "ps_ratio":         round(ps, 2)  if ps  else None,
            "pe_signal":        pe_signal,
            # Growth
            "eps":              round(eps, 4) if eps else None,
            "eps_growth_yoy":   f"{eg*100:.1f}%" if eg else "N/A",
            "revenue_growth_yoy": f"{rg*100:.1f}%" if rg else "N/A",
            "profit_margin":    f"{pm*100:.1f}%" if pm else "N/A",
            "roe":              f"{roe*100:.1f}%" if roe else "N/A",
            "debt_to_equity":   round(de, 2) if de else None,
            # 52-week range
            "52w_low":          w52l,
            "52w_high":         w52h,
            "range_pct":        range_pct,
            "range_signal":     range_signal,
            # Analyst
            "analyst_target":   target,
            "analyst_upside_pct": upside_pct,
            "analyst_count":    analyst_cnt,
        }
    except Exception as e:
        logger.warning(f"Fundamentals fetch failed for {ticker}: {e}")
        return {}


def get_market_analysis(symbol: str, timeframe: str = "15m", asset_class: str = "CRYPTO") -> Dict[str, Any]:
    """
    Fetch real-time market data and compute technical indicators for a given symbol.
    - STOCK      → includes fundamental/valuation data (P/E, 52w range, analyst target)
    - CRYPTO/MACRO → includes ICT Smart Money analysis (OB, FVG, liquidity, regime)
    Always includes a higher-timeframe (1h) trend bias for multi-timeframe confirmation.
    """
    try:
        logger.info(f"Tool: Analyzing {symbol} ({timeframe}) - Class: {asset_class}")
        df = get_kline_data(symbol, timeframe=timeframe, limit=100, asset_class=asset_class)

        if df is None or df.empty:
            return {"error": f"No data found for {symbol}. Try a different ticker or check if the market is open."}

        df_with_indicators = compute_indicators(df)
        summary = get_indicator_summary(df_with_indicators, symbol=symbol)
        summary["asset_class"] = asset_class.upper()

        # Price action context
        last_price = df["Close"].iloc[-1]
        prev_price = df["Close"].iloc[-2] if len(df) > 1 else last_price
        change_pct = ((last_price - prev_price) / prev_price) * 100 if prev_price != 0 else 0

        summary["price_action"] = {
            "current":      round(float(last_price), 4),
            "change_pct":   round(float(change_pct), 2),
            "high_session": round(float(df["High"].max()), 4),
            "low_session":  round(float(df["Low"].min()), 4),
        }

        # ── STOCK: add fundamental / valuation data ───────────────────────────
        if asset_class.upper() == "STOCK":
            fundamentals = _get_stock_fundamentals(symbol)
            if fundamentals:
                summary["fundamentals"] = fundamentals
                summary["analysis_mode"] = "VALUE_INVESTING"
            # Still compute SMC for price-action context, but label clearly
            smc = get_smart_money_analysis(df_with_indicators)
            if smc:
                summary["price_structure"] = smc   # renamed key for stocks

        else:
            # ── CRYPTO / MACRO: full ICT Smart Money analysis ─────────────────
            smc = get_smart_money_analysis(df_with_indicators)
            if smc:
                summary["smart_money"] = smc
            summary["analysis_mode"] = "ICT_TRADING"

        # ── Multi-timeframe: fetch 1h trend bias (both modes) ────────────────
        htf = "1h" if timeframe in ("1m", "5m", "15m", "30m") else "1d"
        if htf != timeframe:
            try:
                df_htf = get_kline_data(symbol, timeframe=htf, limit=60, asset_class=asset_class)
                if df_htf is not None and not df_htf.empty:
                    df_htf_ind = compute_indicators(df_htf)
                    summary_htf = get_indicator_summary(df_htf_ind, symbol=symbol)
                    last_htf   = df_htf_ind.iloc[-1]

                    def _s(v):
                        try: return round(float(v), 4)
                        except: return 0.0

                    htf_close = _s(last_htf.get("Close"))
                    htf_ema20 = _s(last_htf.get("ema_20"))
                    htf_ema50 = _s(last_htf.get("ema_50"))
                    htf_adx   = _s(last_htf.get("adx_14"))
                    htf_rsi   = _s(last_htf.get("rsi_14"))

                    htf_bias = (
                        "BULLISH" if htf_close > htf_ema20 > htf_ema50 else
                        "BEARISH" if htf_close < htf_ema20 < htf_ema50 else
                        "NEUTRAL"
                    )

                    htf_smc = get_smart_money_analysis(df_htf_ind)

                    summary["higher_timeframe"] = {
                        "timeframe":  htf,
                        "bias":       htf_bias,
                        "adx":        htf_adx,
                        "rsi":        htf_rsi,
                        "regime":     htf_smc.get("regime", "UNKNOWN"),
                        "structure":  htf_smc.get("structure", {}),
                        "nearest_ob": htf_smc.get("nearest_ob"),
                        "liquidity":  htf_smc.get("liquidity", {}),
                        "hurst":      summary_htf.get("hurst", {}),
                        "note": (
                            f"{htf} regime={htf_smc.get('regime','?')} | "
                            f"hurst={summary_htf.get('hurst',{}).get('h100','?')} | "
                            f"bias={htf_bias}"
                        )
                    }
            except Exception as htf_err:
                logger.warning(f"HTF fetch failed for {symbol}/{htf}: {htf_err}")

        return summary
    except Exception as e:
        logger.error(f"Error in get_market_analysis tool: {e}")
        return {"error": str(e)}

def get_macro_sentiment() -> Dict[str, Any]:
    """
    Fetch the latest sentiment scores and macro correlations (Gold, Oil, Nasdaq).
    Use this to understand the broader market environment before trading.
    """
    # This would ideally call sentiment_agent.py or similar
    # For now, we provide a structured placeholder that can be expanded
    return {
        "market_regime": "Risk-On", 
        "correlations": {
            "BTC_vs_NASDAQ": 0.85,
            "BTC_vs_GOLD": -0.2
        },
        "news_sentiment": "Positive"
    }

def run_strategy_backtest(symbol: str, timeframe: str = "15m", limit: int = 500, asset_class: str = "CRYPTO") -> Dict[str, Any]:
    """
    Run a historical backtest for tradeable assets (CRYPTO / MACRO only).
    Tests whether the AI agent's ICT logic would have beaten the market historically.
    NOT applicable for stocks (use value investing analysis instead).
    """
    # Stocks are buy-and-hold → backtest is not meaningful
    if asset_class.upper() == "STOCK":
        return {
            "symbol":  symbol,
            "status":  "NOT_APPLICABLE",
            "message": (
                f"Backtest ไม่เกี่ยวข้องกับหุ้น {symbol} เพราะกลยุทธ์คือ Buy & Hold ระยะยาว "
                "ให้ใช้ get_market_analysis แทน เพื่อดูว่าราคาตอนนี้ถูกหรือแพง (P/E, 52w range, analyst target)"
            )
        }
    try:
        logger.info(f"Tool: Running backtest for {symbol} ({timeframe})")
        results = run_crypto_backtest(symbol, timeframe=timeframe, limit=limit)
        return results
    except Exception as e:
        logger.error(f"Error in run_strategy_backtest tool: {e}")
        return {"error": str(e)}


def run_ai_trade_analysis(
    symbol: str,
    timeframe: str = "15m",
    dry_run: bool = True,
    risk_pct: float = 1.0,
    confirmation_required: bool = True,
) -> Dict[str, Any]:
    """
    Run the full 8-agent AI pipeline for a symbol then pass the signal through
    Guard Layer + Circuit Breaker.

    dry_run=True   → analyse + validate only, NO order sent (safe for any call)
    dry_run=False  → live execution after guard/CB pass (requires user intent)
    confirmation_required=True  → returns a DRAFT that user must confirm
    confirmation_required=False → executes immediately if guard/CB pass

    Returns analysis summary + execution status + trade_details if applicable.
    """
    try:
        from google import genai as _genai
        _client = _genai.Client(api_key=os.getenv("GEMINI_API_KEY", ""))

        from intelligence.crypto_intelligence import CryptoIntelligence
        intel = CryptoIntelligence(_client)

        result = intel.analyze_and_trade(
            symbol=symbol.upper().replace("USDT", ""),
            timeframe=timeframe,
            dry_run=dry_run,
            risk_pct=risk_pct,
            confirmation_required=confirmation_required,
        )

        analysis  = result["analysis"]
        execution = result["execution"]

        return {
            "symbol":            analysis.get("symbol"),
            "timeframe":         timeframe,
            "master_decision":   analysis.get("master_decision"),
            "master_confidence": round(float(analysis.get("master_confidence", 0)) * 100, 1),
            "master_report":     analysis.get("master_report", ""),
            "execution_status":  execution.get("status"),
            "execution_reason":  execution.get("reason"),
            "trade_details":     execution.get("trade_details"),
            "draft_id":          execution.get("draft_id"),
            "cb_status":         execution.get("cb_status"),
            "dry_run":           dry_run,
        }
    except Exception as e:
        logger.error(f"run_ai_trade_analysis error: {e}")
        return {"error": str(e), "symbol": symbol}


import uuid

from intelligence.mt5_connector import get_mt5_account_info, _MT5_AVAILABLE, initialize_mt5, normalize_broker_symbol
from intelligence.persistence_utils import save_trade_draft, get_trade_draft, delete_trade_draft
import MetaTrader5 as _mt5

# Persistent Persistence DB path
PERSISTENCE_DB = "persistence.db"

def prepare_mt5_trade_draft(symbol: str, side: str, volume: float, sl: Optional[float] = None, tp: Optional[float] = None, session_id: str = "default") -> Dict[str, Any]:
    """
    REQUIRED FIRST STEP BEFORE ANY TRADE. 
    Drafts a trade on MetaTrader 5 and generates a draft_id.
    You MUST present the trade details and draft_id to the user and ask for explicit confirmation (e.g., "พิมพ์ ยืนยัน [draft_id]" to execute).
    symbol: The trading symbol (e.g., 'XAUUSD', 'EURUSD', 'BTCUSD')
    side: 'BUY' or 'SELL'
    volume: Lot size (e.g., 0.01, 0.1)
    sl: Stop Loss price (optional)
    tp: Take Profit price (optional)
    """
    try:
        # Symbol Normalization — resolve to what the broker actually uses
        symbol_upper = symbol.strip().upper()

        # Step 1: Integrated Broker-Aware Symbol Normalization
        candidates = normalize_broker_symbol(symbol_upper)

        # Step 2: Try to find a valid symbol from the broker's actual symbol list
        normalized_symbol = symbol_upper  # fallback
        try:
            if _MT5_AVAILABLE and initialize_mt5():
                for candidate in candidates:
                    info = _mt5.symbol_info(candidate)
                    if info is not None:
                        normalized_symbol = candidate
                        logger.info(f"Symbol resolved: {symbol_upper} → {normalized_symbol}")
                        break
                else:
                    # Last resort: search broker symbol list
                    all_syms = _mt5.symbols_get()
                    if all_syms:
                        for candidate in candidates:
                            match = next((s.name for s in all_syms if s.name.upper() == candidate.upper()), None)
                            if match:
                                normalized_symbol = match
                                break
        except Exception as _sym_err:
            logger.warning(f"Symbol resolution failed, using {symbol_upper}: {_sym_err}")

        # Generate a descriptive Draft ID: SYMBOL-TRADE-PLAN-XXXXX
        short_id = str(random.randint(10000, 99999)) # 5 digits like the screenshot
        draft_id = f"{normalized_symbol.upper()}-TRADE-PLAN-{short_id}"
        
        _sl_val = float(sl) if sl else None
        _tp_val = float(tp) if tp else None
        _side_upper = side.strip().upper()

        # ── SL/TP Direction Validation ────────────────────────────
        # For BUY:  SL must be below entry (current price), TP must be above
        # For SELL: SL must be above entry, TP must be below
        # If the values are flipped, swap them automatically.
        if _sl_val and _tp_val:
            if _side_upper == "BUY" and _sl_val > _tp_val:
                logger.warning(f"SL/TP flipped for BUY {normalized_symbol} — auto-swapping (SL={_sl_val}, TP={_tp_val})")
                _sl_val, _tp_val = _tp_val, _sl_val
            elif _side_upper == "SELL" and _sl_val < _tp_val:
                logger.warning(f"SL/TP flipped for SELL {normalized_symbol} — auto-swapping (SL={_sl_val}, TP={_tp_val})")
                _sl_val, _tp_val = _tp_val, _sl_val

        # Details for storage
        trade_details = {
            "symbol": normalized_symbol,
            "action": _side_upper,
            "volume": float(volume),
            "sl": _sl_val,
            "tp": _tp_val,
            "comment": f"Manual plan via AI Agent (Session: {session_id})"
        }

        # ── Persistent Storage (SQLite) ──────────────────────────────────────
        # Step 4: Save to SQLite
        success = save_trade_draft(
            draft_id=draft_id,
            session_id=session_id,
            symbol=normalized_symbol,
            action=_side_upper,
            volume=volume,
            sl=_sl_val,
            tp=_tp_val,
            comment=f"Manual Plan via {session_id}"
        )

        if not success:
            return {"error": "Failed to persist trade plan to database."}

        return {
            "status": "PLAN_READY",
            "message": f"แผนการเทรด {draft_id} สำหรับ {normalized_symbol} พร้อมแล้ว",
            "draft_id": draft_id,
            "details": {
                "symbol": normalized_symbol,
                "action": _side_upper,
                "volume": volume,
                "sl": _sl_val,
                "tp": _tp_val,
            }
        }
    except Exception as e:
        logger.error(f"Error preparing trade draft: {e}")
        return {"error": f"Failed to prepare draft: {e}"}

def execute_approved_mt5_trade(draft_id: str) -> Dict[str, Any]:
    """
    Executes a LIVE trade on MetaTrader 5 using an approved draft_id.
    Falls back to SIMULATED paper trade if MT5 is not installed.
    Call this ONLY after the user explicitly types their confirmation of the draft_id.
    """
    try:
        # Robust Draft Resolution
        draft_id = str(draft_id).strip().upper()
        
        trade = None
        try:
            conn = sqlite3.connect(PERSISTENCE_DB)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Fetch the draft
            cursor.execute("SELECT * FROM trade_drafts WHERE UPPER(id) = ?", (draft_id,))
            row = cursor.fetchone()
            
            if row:
                trade = dict(row)
                # Cleanup: Atomic delete after retrieval to prevent replay attacks
                cursor.execute("DELETE FROM trade_drafts WHERE id = ?", (trade["id"],))
                conn.commit()
                logger.info(f"✅ Draft {draft_id} retrieved and consumed from SQLite.")
            conn.close()
        except Exception as db_err:
            logger.error(f"DB Error fetching draft: {db_err}")
            return {"error": f"Database error during trade retrieval: {str(db_err)}"}

        if not trade:
            return {
                "error": f"Draft ID '{draft_id}' not found, missing, or already executed.",
                "hint": "Please generate a new draft using 'เตรียมเทรด' or 'ร่างแผน' command."
            }

        logger.info(f"Tool: Executing approved trade {draft_id}: {trade}")

        # Check if MT5 is available
        from intelligence.mt5_connector import _MT5_AVAILABLE
        if not _MT5_AVAILABLE:
            # ── Paper Trade fallback ─────────────────────────────────────────
            import time as _time
            from datetime import datetime as _dt
            sim_ticket = int(_time.time()) % 1_000_000

            # Log via TradeLogger (non-blocking)
            try:
                from intelligence.trade_logger import get_trade_logger
                get_trade_logger().log_trade({
                    "symbol":    trade["symbol"],
                    "action":    trade["action"],
                    "volume":    trade["volume"],
                    "sl":        trade["sl"],
                    "tp":        trade["tp"],
                    "price":     None,
                    "mode":      "PAPER",
                    "draft_id":  draft_id,
                    "opened_at": _dt.utcnow().isoformat(),
                })
            except Exception as _log_err:
                logger.warning(f"Paper trade log failed: {_log_err}")

            # ── Persist to paper_trades table with SL/TP for outcome tracking ──
            _paper_trade_id = None
            try:
                from intelligence.ml.outcome_tracker import migrate_schema, attach_sl_tp_features
                migrate_schema()
                _paper_con = sqlite3.connect(_PAPER_DB)
                _paper_cur = _paper_con.cursor()
                _paper_cur.execute("""
                    CREATE TABLE IF NOT EXISTS paper_trades (
                        id TEXT PRIMARY KEY,
                        symbol TEXT, side TEXT, volume REAL,
                        entry_price REAL, current_price REAL,
                        pnl_usd REAL, status TEXT,
                        opened_at TEXT, closed_at TEXT
                    )
                """)
                # Fetch live entry price so P&L is calculated correctly
                _entry_px = 0.0
                try:
                    _ep_sym = trade["symbol"].replace("USD","").replace("Cash","").replace("#","")
                    _ep_ac  = "CRYPTO" if any(c in _ep_sym for c in ["BTC","ETH","SOL","XRP","DOGE","ADA","AVAX","MATIC","LINK"]) else "MACRO"
                    _ep_df  = get_kline_data(_ep_sym, timeframe="1m", limit=2, asset_class=_ep_ac)
                    if _ep_df is not None and not _ep_df.empty:
                        _entry_px = float(_ep_df["Close"].iloc[-1])
                except Exception:
                    pass
                _paper_tid = str(sim_ticket)
                _paper_cur.execute("""
                    INSERT OR IGNORE INTO paper_trades
                    (id, symbol, side, volume, entry_price, current_price, pnl_usd, status, opened_at)
                    VALUES (?,?,?,?,?,?,?,?,?)
                """, (
                    _paper_tid,
                    trade["symbol"], trade["action"], trade["volume"],
                    _entry_px, _entry_px, 0.0, "OPEN",
                    _dt.utcnow().isoformat(),
                ))
                _paper_con.commit()
                _paper_con.close()
                # Capture ML features at the exact moment of execution
                _ml_feats = {}
                try:
                    from intelligence.technical_engine import get_kline_data, compute_indicators
                    from intelligence.backtest_crypto import generate_backtest_signals
                    from intelligence.ml.feature_extractor import extract_features
                    _sym_clean = trade["symbol"].replace("USD","").replace("Cash","").replace("#","")
                    _ac = "CRYPTO" if any(c in _sym_clean for c in ["BTC","ETH","SOL","XRP","DOGE","ADA","AVAX","MATIC","LINK"]) else "MACRO"
                    _feat_df = get_kline_data(_sym_clean, timeframe="1h", limit=250, asset_class=_ac)
                    if _feat_df is not None and len(_feat_df) >= 60:
                        _feat_df = compute_indicators(_feat_df)
                        _feat_df = generate_backtest_signals(_feat_df)
                        _feat_df = _feat_df.dropna(subset=["rsi_14", "ema_20", "adx_14"])
                        if not _feat_df.empty:
                            _ml_feats = extract_features(_feat_df, len(_feat_df)-1, side=trade["action"], symbol=_sym_clean, asset_class=_ac)
                except Exception as _fe:
                    logger.debug(f"[ML-Features] snapshot failed: {_fe}")
                # Compute ML win probability at trade entry time
                _ml_score_pct = None
                if _ml_feats:
                    try:
                        from intelligence.ml.signal_model import predict_win_probability
                        _ml_res = predict_win_probability(_ml_feats)
                        if _ml_res.get("available"):
                            _ml_score_pct = _ml_res["win_pct"]
                    except Exception:
                        pass
                # Attach SL/TP + features so outcome_tracker can auto-close and learn
                attach_sl_tp_features(
                    trade_id=_paper_tid,
                    sl=trade["sl"] or 0,
                    tp=trade["tp"] or 0,
                    features=_ml_feats,
                    ml_score=_ml_score_pct,
                )
                _paper_trade_id = _paper_tid
                logger.info(f"[PaperTrade] Registered {_paper_tid} with SL={trade['sl']} TP={trade['tp']}")
            except Exception as _pt_err:
                logger.warning(f"[PaperTrade] Registration failed: {_pt_err}")

            return {
                "status":        "SIMULATED",
                "mode":          "PAPER_TRADE",
                "ticket":        sim_ticket,
                "paper_trade_id":_paper_trade_id,
                "symbol":        trade["symbol"],
                "action":        trade["action"],
                "volume":        trade["volume"],
                "sl":            trade["sl"],
                "tp":            trade["tp"],
                "message":       (
                    f"✅ Paper trade recorded (MT5 not connected). "
                    f"Ticket #{sim_ticket} | {trade['action']} {trade['volume']} lot {trade['symbol']} "
                    f"| SL={trade['sl']} TP={trade['tp']}. "
                    "Install MetaTrader5 to enable live execution."
                ),
            }

        # ── Live MT5 execution ───────────────────────────────────────────────
        result = mt5_execute_trade(
            symbol=trade["symbol"],
            action=trade["action"],
            volume=trade["volume"],
            sl=trade["sl"],
            tp=trade["tp"],
        )
        
        # New: Register for Break-Even monitoring if successful
        if result.get("status") == "SUCCESS":
            try:
                from intelligence.persistence_utils import register_active_trade
                register_active_trade(
                    ticket=result["deal"],
                    symbol=trade["symbol"],
                    entry=result.get("price", 0.0), # Assuming result has confirmed price
                    tp1=trade["tp"], # Using the initial TP as our TP1 baseline
                    draft_id=draft_id
                )
                logger.info(f"✅ Trade {result['deal']} registered for Institutional Monitoring.")
            except Exception as reg_err:
                logger.warning(f"Failed to register trade for monitoring: {reg_err}")

        return result
    except Exception as e:
        logger.error(f"Error in execute_approved_mt5_trade tool: {e}")
        return {"error": str(e)}

def get_mt5_account_summary() -> Dict[str, Any]:
    """Fetch current MT5 account balance, equity, and margin information."""
    try:
        info = get_mt5_account_info()
        return info
    except Exception as e:
        logger.error(f"Error in get_mt5_account_summary tool: {e}")
        return {"error": str(e)}

def _scan_basket(tickers: list) -> list:
    """
    Download 1-day % change for a basket of tickers using PARALLEL threads.
    Each ticker is fetched concurrently (max 8 threads) with a 6s timeout.
    Returns a list of dicts sorted by change_percent descending.
    """
    import yfinance as yf
    from concurrent.futures import ThreadPoolExecutor, as_completed

    basket = [t for t in tickers if t]
    if not basket:
        return []

    def _fetch_one(ticker: str):
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period="2d", interval="1d", auto_adjust=True, timeout=6)
            if hist.empty or len(hist) < 2:
                return None
            last_price = float(hist["Close"].iloc[-1])
            prev_price = float(hist["Close"].iloc[-2])
            if prev_price == 0:
                return None
            change_pct = ((last_price - prev_price) / prev_price) * 100
            return {
                "symbol": ticker.replace("-USD", ""),
                "exchange": "CRYPTO",
                "current_price": round(last_price, 4),
                "change_percent": round(change_pct, 2),
            }
        except Exception:
            return None

    results = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(_fetch_one, ticker): ticker for ticker in basket}
        for future in as_completed(futures, timeout=15):
            result = future.result()
            if result:
                results.append(result)

    return sorted(results, key=lambda x: x.get("change_percent", 0), reverse=True)


def _fetch_yf_screener(screen_id: str = "day_gainers", count: int = 10, exchange_filter: str = None) -> list:
    """
    Fetch top gainers or losers directly from Yahoo Finance Screener API.
    screen_id: 'day_gainers' | 'day_losers' | 'most_actives'
    exchange_filter: 'NMS' for NASDAQ, 'NYQ' for NYSE/S&P500, None = all
    Returns list of dicts with symbol, name, change_percent, current_price, exchange,
    volume, avg_volume_3m, market_state, and fetched_at timestamp.
    Cached for 5 minutes — screener data changes slowly during market hours.
    """
    cache_key = f"screener:{screen_id}:{count}:{exchange_filter}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    import requests
    from datetime import datetime, timezone
    headers = {"User-Agent": "Mozilla/5.0"}
    url = f"https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds={screen_id}&count={count}&region=US&lang=en-US"
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    try:
        resp = requests.get(url, headers=headers, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        quotes = data["finance"]["result"][0]["quotes"]
        results = []
        for q in quotes:
            ex = q.get("fullExchangeName", "")
            symbol = q.get("symbol", "")
            change_pct = round(q.get("regularMarketChangePercent", 0), 2)
            price = round(q.get("regularMarketPrice", 0), 2)
            name = q.get("shortName", symbol)
            if exchange_filter and exchange_filter not in ex:
                continue
            volume_raw = q.get("regularMarketVolume", 0) or 0
            if volume_raw >= 1_000_000:
                volume_str = f"{volume_raw / 1_000_000:.1f}M"
            elif volume_raw >= 1_000:
                volume_str = f"{volume_raw / 1_000:.1f}K"
            elif volume_raw > 0:
                volume_str = str(volume_raw)
            else:
                volume_str = "N/A"
                
            avg_volume = q.get("averageDailyVolume3Month", 0) or 0
            
            # marketState: REGULAR | PRE | POST | PREPRE | POSTPOST | CLOSED
            market_state = q.get("marketState", "UNKNOWN")
            if market_state == "POST":
                market_state = "POST (After-Hours EST)"
            elif market_state == "PRE":
                market_state = "PRE (Pre-Market EST)"
            elif market_state == "REGULAR":
                market_state = "REGULAR (Market Open)"
                
            # Anomaly / Sanity Check Layer
            is_anomaly = False
            if abs(change_pct) > 30.0:
                is_anomaly = True
                name = f"[⚠️ ANOMALY] {name}"

            results.append({
                "symbol": symbol,
                "name": name,
                "exchange": ex,
                "current_price": price,
                "change_percent": change_pct,
                "volume": volume_str,
                "avg_volume_3m": avg_volume,
                "market_state": market_state,
                "is_anomaly": is_anomaly,
                "data_source": "Yahoo Finance Screener",
                "fetched_at": fetched_at,
            })
        _cache_set(cache_key, results, ttl=300)  # 5 min cache
        return results
    except Exception as e:
        logger.warning(f"YF Screener API failed ({e})")
        return []


def get_market_opportunities(asset_class: str = "ALL") -> Dict[str, Any]:
    """
    Scan the market for the best movers, grouped by asset class.
    asset_class: "ALL" | "STOCK" | "CRYPTO"
    - "ALL"    → returns NASDAQ 100, S&P 500, NASDAQ Composite, and Crypto as SEPARATE groups
    - "STOCK"  → returns only the three US stock index groups
    - "CRYPTO" → returns only the crypto basket
    Each group has its own top_gainer, top_loser, and hero symbol.
    Groups are NEVER mixed together. Each is independent.
    """
    from datetime import datetime, timezone
    from intelligence.agents.sentiment_agent import _fetch_rss_news

    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    MIN_VOLUME = 500_000

    def _liquid(stocks):
        def _parse_vol(v):
            if isinstance(v, (int, float)): return v
            if isinstance(v, str):
                v_clean = v.replace("N/A", "0")
                if "M" in v_clean: return float(v_clean.replace("M", "")) * 1_000_000
                if "K" in v_clean: return float(v_clean.replace("K", "")) * 1_000
                try: return float(v_clean)
                except: return 0
            return 0
        return [s for s in stocks if _parse_vol(s.get("volume", 0)) >= MIN_VOLUME]

    def _abs_change(x):
        try:
            return abs(float(str(x.get("change_percent") or x.get("percent_change") or 0).replace("%", "")))
        except:
            return 0.0

    def _enrich(stock, group_name, fetch_news: bool = False):
        """Add group label (and optionally news headlines) to a stock dict."""
        if not stock:
            return None
        stock = dict(stock)
        stock["group"] = group_name
        if fetch_news:
            try:
                stock["news_headlines"] = [n["title"] for n in _fetch_rss_news(stock["symbol"])[:3]] or ["No news found."]
            except Exception:
                stock["news_headlines"] = ["News unavailable."]
        return stock

    def _build_group(name, gainers, losers, fetch_news: bool = False):
        """Build a self-contained group result with its own hero."""
        g = gainers[0] if gainers else None
        l = losers[0]  if losers  else None
        g = _enrich(g, name, fetch_news=fetch_news)
        l = _enrich(l, name, fetch_news=fetch_news)
        return {
            "group_name": name,
            "top_gainer": g,
            "top_loser":  l,
            # Hero for chart = top gainer of this group
            "hero_symbol":   g["symbol"]   if g else (l["symbol"]   if l else None),
            "hero_exchange": g["exchange"]  if g else (l["exchange"] if l else None),
        }

    try:
        logger.info(f"Tool: Scanning live market opportunities — asset_class={asset_class}")
        mode = asset_class.upper()

        groups = {}

        # ── CRYPTO GROUP ─────────────────────────────────────────────────────────
        if mode in ("ALL", "CRYPTO"):
            # Slim basket for speed — top 12 coins by market cap only
            crypto_basket = [
                "BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD", "ADA-USD",
                "DOGE-USD", "AVAX-USD", "LINK-USD", "DOT-USD", "NEAR-USD", "TON-USD",
            ]
            basket = _scan_basket(crypto_basket)
            
            # STRICT Rules: Gainers MUST be > 0. Losers MUST be < 0.
            crypto_gainer = [s for s in basket if s.get("change_percent", 0) > 0.0]
            # _scan_basket sorts by descending change_percent. 
            # Reverse sort for losers (most negative first)
            crypto_loser = sorted([s for s in basket if s.get("change_percent", 0) < 0.0], 
                                  key=lambda x: x.get("change_percent", 0))
            
            # Add back to arrays of size 1 (if exist)
            crypto_gainer = [crypto_gainer[0]] if crypto_gainer else []
            crypto_loser  = [crypto_loser[0]] if crypto_loser else []
            
            # fetch_news only for CRYPTO-only queries — skip when part of ALL (too slow)
            groups["CRYPTO"] = _build_group("CRYPTO", crypto_gainer, crypto_loser,
                                            fetch_news=(mode == "CRYPTO"))

        # ── US STOCK GROUPS ───────────────────────────────────────────────────────
        if mode in ("ALL", "STOCK"):
            index_data       = _load_index_data()
            sp500_list       = index_data["indices"].get("SP500", SP500_TICKERS)
            nq100_list       = index_data["indices"].get("NASDAQ_100", NASDAQ_100_TICKERS)
            nasdaq_composite = index_data["exchanges"].get("NASDAQ", [])

            # Fetch gainers and losers IN PARALLEL to halve wait time
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=2) as _ex:
                _g_future = _ex.submit(_fetch_yf_screener, "day_gainers", 50)
                _l_future = _ex.submit(_fetch_yf_screener, "day_losers", 50)
                all_gainers = [s for s in _g_future.result() if s.get("change_percent", 0) > 0]
                all_losers  = [s for s in _l_future.result() if s.get("change_percent", 0) < 0]

            # NASDAQ 100 — top 100 large-cap non-financial NASDAQ stocks
            # fetch_news=True only here (the most important group) — 2 calls max
            nq100_g = _liquid([s for s in all_gainers if s["symbol"] in nq100_list])
            nq100_l = _liquid([s for s in all_losers  if s["symbol"] in nq100_list])
            groups["NASDAQ_100"] = _build_group("NASDAQ 100", nq100_g, nq100_l, fetch_news=True)

            # S&P 500 — news skipped to keep response time fast
            sp500_g = _liquid([s for s in all_gainers if s["symbol"] in sp500_list])
            sp500_l = _liquid([s for s in all_losers  if s["symbol"] in sp500_list])
            groups["SP500"] = _build_group("S&P 500", sp500_g, sp500_l, fetch_news=False)

            # NASDAQ Composite — all 3,000+ NASDAQ-listed stocks EXCLUDING NASDAQ 100 & S&P 500
            premium_set   = set(nq100_list) | set(sp500_list)
            composite_g = _liquid([s for s in all_gainers
                                   if s["symbol"] in nasdaq_composite
                                   and s["symbol"] not in premium_set])
            composite_l = _liquid([s for s in all_losers
                                   if s["symbol"] in nasdaq_composite
                                   and s["symbol"] not in premium_set])
            groups["NASDAQ_COMPOSITE"] = _build_group("NASDAQ Composite", composite_g, composite_l, fetch_news=False)

        # ── Chart hero: prefer NASDAQ 100 gainer, then S&P 500, then others ──────
        hero_priority = ["NASDAQ_100", "SP500", "NASDAQ_COMPOSITE", "CRYPTO"]
        hero_symbol   = None
        hero_exchange = None
        hero_loser    = None
        hero_loser_ex = None
        for key in hero_priority:
            if key in groups:
                g = groups[key]
                if not hero_symbol and g.get("top_gainer"):
                    hero_symbol   = g["top_gainer"]["symbol"]
                    hero_exchange = g["top_gainer"].get("exchange")
                if not hero_loser and g.get("top_loser"):
                    hero_loser    = g["top_loser"]["symbol"]
                    hero_loser_ex = g["top_loser"].get("exchange")
            if hero_symbol and hero_loser:
                break

        return {
            "data_source":  "Yahoo Finance Screener (realtime)",
            "fetched_at":   fetched_at,
            "confidence":   "HIGH — live data, volume-filtered (>500K shares), index membership verified",
            "groups":       groups,
            # Top-level heroes for chart routing
            "hero_symbol":          hero_symbol,
            "hero_exchange":        hero_exchange,
            "hero_loser":           hero_loser,
            "hero_loser_exchange":  hero_loser_ex,
            "instruction": (
                "CRITICAL PRESENTATION RULES:\n"
                "1. Each group in 'groups' is INDEPENDENT — present them in SEPARATE sections.\n"
                "   Do NOT mix stocks from different groups.\n"
                "2. Group keys: NASDAQ_100, SP500, NASDAQ_COMPOSITE, CRYPTO\n"
                "   • NASDAQ_100: top 100 large-cap non-financial NASDAQ stocks\n"
                "   • SP500: 500 largest US companies across all exchanges\n"
                "   • NASDAQ_COMPOSITE: all other NASDAQ-listed stocks (smaller, higher risk)\n"
                "   • CRYPTO: top cryptocurrencies by market cap\n"
                "3. For each group show: top_gainer and top_loser with symbol, name, change_percent,\n"
                "   current_price, volume, market_state, and news_headlines.\n"
                "4. market_state: REGULAR = market hours | PRE = pre-market | POST = after-hours\n"
                "5. Always show fetched_at timestamp and data_source for transparency.\n"
                "6. Volume confirms liquidity — always mention it. Format: 14.3M, 850K, etc."
            ),
        }
    except Exception as e:
        logger.error(f"Error in get_market_opportunities: {e}")
        return {"error": str(e)}

def get_sector_rotation() -> Dict[str, Any]:
    """
    Analyzes Institutional Money Flow by comparing major sector ETF performances.
    Categorizes sectors into Leading, Improving, Lagging, and Weakening.
    Cached for 15 minutes — sector flows don't shift minute-by-minute.
    """
    cached = _cache_get("sector_rotation")
    if cached is not None:
        return cached
    try:
        import yfinance as yf
        sectors = {
            "Technology (XLK)": "XLK",
            "Financials (XLF)": "XLF",
            "Energy (XLE)": "XLE",
            "Health Care (XLV)": "XLV",
            "Industrials (XLI)": "XLI",
            "Consumer Disc (XLY)": "XLY",
            "Consumer Staples (XLP)": "XLP",
            "Basic Materials (XLB)": "XLB",
            "Utilities (XLU)": "XLU",
            "Real Estate (XLRE)": "XLRE"
        }
        
        logger.info(f"Tool: Fetching Sector Rotation data for {len(sectors)} sectors...")
        
        # Pull performance data (5-day)
        data = yf.download(list(sectors.values()), period="5d", interval="1d", progress=False)["Close"]
        
        if data.empty:
            return {"error": "Failed to fetch sector data. Market may be closed or API restricted."}
            
        perf = {}
        for name, ticker in sectors.items():
            if ticker in data.columns:
                s_data = data[ticker].dropna()
                if len(s_data) >= 2:
                    change = ((s_data.iloc[-1] - s_data.iloc[0]) / s_data.iloc[0]) * 100
                    perf[name] = round(change, 2)
        
        # Sort sectors
        sorted_perf = sorted(perf.items(), key=lambda x: x[1], reverse=True)
        
        sector_result = {
            "instruction": "Identify which sectors are attracting institutional capital (Leading) and which are being sold (Lagging).",
            "leading_sectors": sorted_perf[:3],
            "lagging_sectors": sorted_perf[-3:],
            "full_rotation": sorted_perf,
            "market_summary": "Institutional flow favors " + sorted_perf[0][0] if sorted_perf else "Neutral"
        }
        _cache_set("sector_rotation", sector_result, ttl=900)  # 15 min cache
        return sector_result
    except Exception as e:
        logger.error(f"Error in get_sector_rotation: {e}")
        return {"error": str(e)}

def calculate_risk_parameters(account_size: float, entry: float, stop_loss: float, risk_pct: float = 1.0) -> Dict[str, Any]:
    """
    Calculates institutional position sizing and risk parameters for a trade.
    risk_pct defaults to 1.0% of the account.
    """
    try:
        if entry == stop_loss:
            return {"error": "Entry and Stop Loss cannot be the same price."}
            
        risk_amount = account_size * (risk_pct / 100)
        distance = abs(entry - stop_loss)
        position_size = risk_amount / distance
        
        # Calculate R:R assuming a standard 1:2 target if TP not provided
        suggested_tp = entry + (distance * 2) if entry > stop_loss else entry - (distance * 2)
        
        return {
            "account_size": account_size,
            "risk_percentage": f"{risk_pct}%",
            "risk_amount_dollars": round(risk_amount, 2),
            "position_size": round(position_size, 4),
            "distance_to_sl": round(distance, 4),
            "trade_instructions": f"To risk {risk_pct}% (${round(risk_amount, 2)}), enter at {entry} with a {round(position_size, 4)} lot/share size. SL at {stop_loss}.",
            "suggested_tp_1_2": round(suggested_tp, 4)
        }
    except Exception as e:
        logger.error(f"Error in calculate_risk_parameters: {e}")
        return {"error": str(e)}

# Contract size per lot for common instruments
_CONTRACT_SIZES: Dict[str, float] = {
    "GOLD":   100.0,   # 100 oz/lot
    "XAUUSD": 100.0,
    "XAUEUR": 100.0,
    "SILVER": 5000.0,  # 5000 oz/lot
    "XAGUSD": 5000.0,
    "OIL":    1000.0,  # 1000 barrels/lot
    "USOIL":  1000.0,
    "UKOIL":  1000.0,
    # Forex — 1 standard lot = 100,000 units of base currency
    "DEFAULT_FX": 100_000.0,
    # Indices (approximate point value)
    "NAS100": 10.0,
    "US30":   10.0,
    "SP500":  50.0,
    "SPX500": 50.0,
}

def calculate_trade_pnl(
    symbol: str,
    action: str,
    volume: float,
    entry_price: float,
    target_price: float,
    account_balance: Optional[float] = None
) -> Dict[str, Any]:
    """
    Calculate profit or loss (in USD) for an open or hypothetical trade.
    - action: 'BUY' or 'SELL'
    - target_price: price at SL, TP, or current market price
    - Returns: pnl_usd, pips/points moved, risk_pct of account (if balance given)
    """
    try:
        sym_upper = symbol.strip().upper()
        contract_size = _CONTRACT_SIZES.get(sym_upper, _CONTRACT_SIZES["DEFAULT_FX"])
        # Override: if symbol looks like forex pair (6-char alphabetic), use forex contract size
        if len(sym_upper) == 6 and sym_upper.isalpha() and sym_upper not in _CONTRACT_SIZES:
            contract_size = _CONTRACT_SIZES["DEFAULT_FX"]

        action_upper = action.strip().upper()
        if action_upper == "BUY":
            pnl_per_lot = (target_price - entry_price) * contract_size
        elif action_upper == "SELL":
            pnl_per_lot = (entry_price - target_price) * contract_size
        else:
            return {"error": f"Invalid action: {action}. Must be BUY or SELL."}

        pnl_usd = round(pnl_per_lot * volume, 2)
        points_moved = round(abs(target_price - entry_price), 4)
        direction_label = "profit" if pnl_usd > 0 else "loss"

        result: Dict[str, Any] = {
            "symbol": sym_upper,
            "action": action_upper,
            "volume_lots": volume,
            "entry_price": entry_price,
            "target_price": target_price,
            "points_moved": points_moved,
            "contract_size_per_lot": contract_size,
            "pnl_usd": pnl_usd,
            "direction": direction_label,
            "summary": (
                f"{action_upper} {volume} lot {sym_upper}: "
                f"if price moves from {entry_price} to {target_price} "
                f"({points_moved} pts), P&L = {'+'if pnl_usd>=0 else ''}{pnl_usd} USD ({direction_label})"
            )
        }

        if account_balance and account_balance > 0:
            result["pct_of_balance"] = round(abs(pnl_usd) / account_balance * 100, 2)
            result["balance_after"] = round(account_balance + pnl_usd, 2)

        return result

    except Exception as e:
        logger.error(f"Error in calculate_trade_pnl: {e}")
        return {"error": str(e)}

def get_market_climate() -> Dict[str, Any]:
    """
    Analyzes global macro climate using VIX, Dollar Index (DXY), and 10Y Yields.
    Returns a Global Risk Score (0-100) and regime classification.
    Cached for 10 minutes — macro indicators change slowly.
    """
    cached = _cache_get("market_climate")
    if cached is not None:
        return cached
    try:
        vix = yf.Ticker('^VIX').history(period='1d')['Close'].iloc[-1]
        dxy = yf.Ticker('DX-Y.NYB').history(period='1d')['Close'].iloc[-1]
        tnx = yf.Ticker('^TNX').history(period='1d')['Close'].iloc[-1]
        
        # Normalized Risk Components (0-100)
        # VIX: 10 is low, 20 is median, 30+ is high
        vix_score = min(100, max(0, (vix - 10) / 25 * 100))
        # DXY: 95 is low, 100 is neutral, 105+ is high
        dxy_score = min(100, max(0, (dxy - 95) / 10 * 100))
        # TNX: 3% is low, 4.5% is high (for current market regime)
        tnx_score = min(100, max(0, (tnx - 3.0) / 2.0 * 100))
        
        # Strategic Weighted Risk Score
        global_risk_score = (vix_score * 0.4) + (dxy_score * 0.3) + (tnx_score * 0.3)
        
        regime = "NEUTRAL"
        threat_level = "LOW"
        color = "emerald"
        
        if global_risk_score > 70:
            regime, threat_level, color = "EXTREME TURBULENCE", "DANGER", "rose"
        elif global_risk_score > 50:
            regime, threat_level, color = "RISK OFF", "ALERT", "amber"
        elif global_risk_score < 30:
            regime, threat_level, color = "RISK ON", "OPTIMAL", "emerald"
            
        summary = f"Vol: {vix:.2f} | DXY: {dxy:.2f} | 10Y: {tnx:.2f}%"
        
        climate_result = {
            "global_risk_score": round(global_risk_score, 2),
            "regime": regime,
            "threat_level": threat_level,
            "color": color,
            "indicators": {
                "vix": round(vix, 2),
                "dxy": round(dxy, 2),
                "tnx_yield": round(tnx, 2)
            },
            "summary": summary
        }
        _cache_set("market_climate", climate_result, ttl=600)  # 10 min cache
        return climate_result
    except Exception as e:
        logger.error(f"Error in get_market_climate: {e}")
        return {"error": str(e)}

def calculate_custom_indicator(symbol: str, formula: str, timeframe: str = "15m", asset_class: str = "CRYPTO") -> Dict[str, Any]:
    """
    Evaluates a technical formula against market data.
    Supported functions: SMA, EMA, RSI, ATR.
    Example formula: "(SMA(CLOSE, 20) - SMA(CLOSE, 50)) / CLOSE * 100"
    """
    try:
        from intelligence.formula_engine import evaluate_formula, get_latest_value
        
        df = get_kline_data(symbol, timeframe=timeframe, limit=100, asset_class=asset_class)
        if df is None or df.empty:
            return {"error": f"No data found for {symbol}."}
            
        result = evaluate_formula(df, formula)
        latest = get_latest_value(result)
        
        return {
            "symbol": symbol,
            "formula": formula,
            "result": latest,
            "status": "SUCCESS",
            "full_series_length": len(result) if hasattr(result, "__len__") else 1
        }
    except Exception as e:
        logger.error(f"Error in calculate_custom_indicator: {e}")
        return {"error": str(e), "hint": "Check formula syntax. Use columns like CLOSE, OPEN, HIGH, LOW."}

def get_usd_rate(symbol: str) -> float:
    """Helper to get conversion rate to USD for non-USD assets."""
    if any(x in symbol.upper() for x in ["USD", "USDT"]):
        return 1.0
    try:
        import yfinance as yf
        # Mapping common MT5 symbols to YF
        mapping = {
            "XAU": "XAUUSD=X", "XAG": "XAGUSD=X", "EUR": "EURUSD=X", 
            "GBP": "GBPUSD=X", "JPY": "USDJPY=X", "BTC": "BTC-USD",
            "ETH": "ETH-USD"
        }
        # Institutional fallbacks if API fails
        fallbacks = {
            "XAU": 2300.0, "XAG": 28.0, "EUR": 1.08, "GBP": 1.25, "JPY": 0.0066
        }
        
        base = symbol[:3].upper()
        yf_sym = mapping.get(base, f"{base}USD=X" if base not in ["USD","USDT"] else None)
        
        if not yf_sym:
            return 1.0
            
        data = yf.Ticker(yf_sym).history(period="1d")
        if not data.empty:
            rate = data["Close"].iloc[-1]
            # Use JPY inverse if needed
            if base == "JPY": return 1.0 / rate
            return float(rate)
        
        return fallbacks.get(base, 1.0)
    except Exception:
        return 1.0

def get_portfolio_analytics() -> Dict[str, Any]:
    """
    Analyzes current MT5 holdings with institutional risk metrics.
    Calculates % of Equity and % of Portfolio for each asset.
    """
    try:
        from intelligence.mt5_connector import get_mt5_account_info, initialize_mt5
        import MetaTrader5 as mt5
        
        if not initialize_mt5():
            return {"error": "Failed to connect to MT5"}
            
        account = get_mt5_account_info()
        equity = account.get("equity", 0)
        positions = mt5.positions_get()
        
        if not positions:
            return {"message": "No open positions found.", "equity": equity}
            
        results = []
        total_market_value = 0
        
        for p in positions:
            p_dict = p._asdict()
            sym = p_dict["symbol"]
            rate = get_usd_rate(sym)
            mv = p_dict.get("contract_size", 1.0) * p_dict.get("volume", 0) * p_dict.get("price_current", 0) * rate
            total_market_value += mv
            results.append({
                "symbol": sym,
                "side": "BUY" if p_dict["type"] == 0 else "SELL",
                "volume": p_dict["volume"],
                "market_value_usd": round(mv, 2),
                "unrealized_pnl": round(p_dict["profit"], 2)
            })
            
        # Calculate percentages
        warnings = []
        for res in results:
            mv = res["market_value_usd"]
            res["percent_of_equity"] = round((mv / equity * 100), 2) if equity > 0 else 0
            res["percent_of_portfolio"] = round((mv / total_market_value * 100), 2) if total_market_value > 0 else 0
            
            if res["percent_of_equity"] > 20:
                warnings.append(f"CONCENTRATION RISK: {res['symbol']} is {res['percent_of_equity']}% of equity.")
        
        return {
            "equity": equity,
            "total_portfolio_value": round(total_market_value, 2),
            "positions": results,
            "risk_warnings": warnings
        }
    except Exception as e:
        logger.error(f"Error in get_portfolio_analytics: {e}")
        return {"error": str(e)}

def get_working_memory(session_id: str = "default") -> Dict[str, Any]:
    """Retrieve the AI's persistent cognitive state and grand strategy for the active session."""
    import sqlite3
    try:
        # Assuming persistence.db is in the root directory (one level up from this file, but since this runs from project root, it's just 'persistence.db')
        conn = sqlite3.connect("persistence.db")
        cursor = conn.cursor()
        cursor.execute("SELECT memory, emotion, updated_at FROM working_memory WHERE session_id = ?", (session_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return {"frontal_lobe": row[0], "emotion": row[1], "last_updated": row[2]}
        else:
            return {
                "frontal_lobe": "No current focus. Analysing market regime.",
                "emotion": "NEUTRAL",
                "last_updated": None
            }
    except Exception as e:
        logger.error(f"Failed to read working memory for session {session_id}: {e}")
        return {"error": str(e)}

def update_working_memory(memory: str = None, emotion: str = None, session_id: str = "default") -> Dict[str, Any]:
    """Update the AI's internal stance, plan, or emotional bias for the active session."""
    import sqlite3
    from datetime import datetime
    try:
        conn = sqlite3.connect("persistence.db")
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        
        cursor.execute("SELECT memory, emotion FROM working_memory WHERE session_id = ?", (session_id,))
        row = cursor.fetchone()
        
        new_mem = memory if memory is not None else (row[0] if row else "")
        new_emo = emotion if emotion is not None else (row[1] if row else "NEUTRAL")
        
        cursor.execute("""
            INSERT INTO working_memory (session_id, memory, emotion, updated_at) 
            VALUES (?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET 
                memory=excluded.memory, 
                emotion=excluded.emotion, 
                updated_at=excluded.updated_at
        """, (session_id, new_mem, new_emo, now))
        
        # Ensure session exists to avoid foreign key constraints (SQLite usually doesn't enforce without PRAGMA but good practice)
        cursor.execute("INSERT OR IGNORE INTO sessions (id, title, updated_at) VALUES (?, ?, ?)", 
                       (session_id, "Strategy Briefing", now))
                       
        conn.commit()
        conn.close()
        logger.info(f"💾 Cognitive Stashing Successful for session {session_id}")
        return {"status": "SUCCESS"}
    except Exception as e:
        logger.error(f"Failed to update working memory for session {session_id}: {e}")
        return {"error": str(e)}

def calculate_math_expression(expression: str) -> Dict[str, Any]:
    """
    Safely evaluate a mathematical expression.
    Useful for calculating position sizes, pip values, profit/loss, and other math required by the user.
    """
    try:
        import pandas as pd
        result = pd.eval(expression)
        return {
            "status": "SUCCESS",
            "expression": expression,
            "result": float(result)
        }
    except Exception as e:
        logger.error(f"Calculation error for expression '{expression}': {e}")
        return {"status": "ERROR", "error": f"Invalid expression: {expression}. Only use standard math operators."}

def set_smart_alert(condition: str, target_symbol: str, message: str) -> Dict[str, Any]:
    """Sets a background monitoring alert."""
    import sqlite3
    from datetime import datetime
    try:
        conn = sqlite3.connect("persistence.db")
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO active_alerts (symbol, condition, message, created_at) VALUES (?, ?, ?, ?)",
            (target_symbol.upper(), condition, message, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
        return {"status": "SUCCESS", "message": f"Alert set for {target_symbol}: {condition}"}
    except Exception as e:
        logger.error(f"Failed to set alert: {e}")
        return {"status": "ERROR", "error": str(e)}

def get_user_portfolio(user_id: str = "default") -> Dict[str, Any]:
    """Retrieve MT5 portfolio context aligned to a specific user or multi-login setup."""
    # Placeholder for multi-login logic. Falls back to global get_portfolio_analytics.
    return get_portfolio_analytics()

def get_onchain_flow(symbol: str) -> Dict[str, Any]:
    """
    Fetch real on-chain data from CoinGecko free API.
    Returns market dominance, volume, price change as Whale Flow proxies.
    """
    import requests
    COINGECKO_ID_MAP = {
        "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
        "BNB": "binancecoin", "XRP": "ripple", "ADA": "cardano",
        "DOGE": "dogecoin", "PEPE": "pepe", "AVAX": "avalanche-2",
        "LINK": "chainlink", "MATIC": "matic-network", "DOT": "polkadot",
        "ARB": "arbitrum", "OP": "optimism", "SUI": "sui",
    }
    cg_id = COINGECKO_ID_MAP.get(symbol.upper(), symbol.lower())
    try:
        url = f"https://api.coingecko.com/api/v3/coins/{cg_id}?localization=false&tickers=false&community_data=false&developer_data=false"
        resp = requests.get(url, timeout=8)
        if resp.status_code != 200:
            raise Exception(f"CoinGecko returned {resp.status_code}")
        d = resp.json()
        md = d.get("market_data", {})
        volume_24h = md.get("total_volume", {}).get("usd", 0)
        price_change_24h = md.get("price_change_percentage_24h", 0)
        market_cap = md.get("market_cap", {}).get("usd", 0)
        # Infer whale activity from volume spike vs market cap ratio
        vol_ratio = round(volume_24h / market_cap * 100, 2) if market_cap else 0
        inflow_spike = vol_ratio > 15  # >15% vol/cap = unusual whale activity
        sentiment = d.get("sentiment_votes_up_percentage", 50)
        nupl_proxy = (
            "Greed" if price_change_24h > 5 else
            "Optimism" if price_change_24h > 0 else
            "Hope" if price_change_24h > -5 else "Capitulation"
        )
        return {
            "symbol": symbol.upper(),
            "whale_net_flow_24h_proxy_volume_usd": round(volume_24h, 2),
            "volume_to_marketcap_ratio_pct": vol_ratio,
            "exchange_inflow_spike": inflow_spike,
            "price_change_24h_pct": round(price_change_24h, 2),
            "community_bullish_votes_pct": round(sentiment, 1),
            "NUPL_proxy": nupl_proxy,
            "data_source": "CoinGecko"
        }
    except Exception as e:
        logger.warning(f"CoinGecko onchain fetch failed for {symbol}: {e}. Using fallback.")
        import random
        return {
            "symbol": symbol.upper(),
            "whale_net_flow_24h": round(random.uniform(-500, 500), 2),
            "exchange_inflow_spike": random.choice([True, False]),
            "NUPL_status": random.choice(["Hope", "Optimism", "Greed", "Capitulation"]),
            "note": "Fallback data (CoinGecko unavailable)"
        }

def get_options_flow(symbol: str) -> Dict[str, Any]:
    """
    Fetch Put/Call Ratio and Gamma Exposure via Unusual Whales API.
    Falls back to simulated data if API key is not configured.
    Get your key at: https://unusualwhales.com/api
    """
    import os
    import requests
    api_key = os.environ.get("UNUSUAL_WHALES_API_KEY", "")

    if api_key and not api_key.startswith("YOUR_"):
        try:
            headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
            # Flow summary endpoint
            url = f"https://api.unusualwhales.com/api/stock/{symbol.upper()}/flow-summary"
            resp = requests.get(url, headers=headers, timeout=8)
            if resp.status_code == 200:
                d = resp.json()
                data = d.get("data", {})
                return {
                    "symbol": symbol.upper(),
                    "put_call_ratio": round(float(data.get("put_call_ratio", 1.0)), 2),
                    "net_premium_bullish": data.get("net_premium_bullish"),
                    "net_premium_bearish": data.get("net_premium_bearish"),
                    "avg_30d_put_call": data.get("average_30_day_put_call_ratio"),
                    "dark_pool_prints": data.get("dark_pool_prints", 0),
                    "data_source": "Unusual Whales"
                }
        except Exception as e:
            logger.warning(f"Unusual Whales API error for {symbol}: {e}")

    # --- Fallback: simulated data ---
    import random
    return {
        "symbol": symbol.upper(),
        "put_call_ratio": round(random.uniform(0.5, 1.5), 2),
        "gamma_exposure": round(random.uniform(-2000000, 5000000), 2),
        "dark_pool_prints": random.randint(0, 10),
        "note": "Simulated data — set UNUSUAL_WHALES_API_KEY in .env for real data"
    }

def analyze_trade_performance() -> Dict[str, Any]:
    """
    Analyze real trade history from TradeLogger JSON + MT5 to generate an AI journal review.
    Saves the result to the trade_reviews table.
    """
    import sqlite3
    from datetime import datetime
    try:
        from intelligence.trade_logger import get_trade_logger
        tl = get_trade_logger()
        stats = tl.get_statistics(days=30)
        weekly = tl.get_weekly_report()
        recent = tl.get_recent_trades(count=5)

        # Also try to pull live MT5 closed deals
        mt5_summary = ""
        try:
            import MetaTrader5 as mt5
            if mt5.initialize():
                from datetime import timedelta
                deals = mt5.history_deals_get(
                    datetime.now() - timedelta(days=30), datetime.now()
                )
                if deals:
                    closed = [d for d in deals if d.profit != 0]
                    mt5_wins = sum(1 for d in closed if d.profit > 0)
                    mt5_total = len(closed)
                    mt5_pnl = round(sum(d.profit for d in closed), 2)
                    mt5_wr = round(mt5_wins / mt5_total * 100, 1) if mt5_total else 0
                    mt5_summary = (
                        f"MT5 Live (30d): {mt5_total} trades | "
                        f"Win Rate: {mt5_wr}% | Net P/L: ${mt5_pnl:+.2f}"
                    )
        except Exception:
            pass

        win_rate = stats.get("win_rate", 0.0)
        total_trades = stats.get("total_trades", 0)
        total_pnl = stats.get("total_pnl", 0.0)
        max_consec_loss = stats.get("max_consecutive_losses", 0)

        # Build AI critique
        critique_parts = []
        if win_rate >= 60:
            critique_parts.append("Win rate is strong. Focus on sizing up in high-conviction setups.")
        elif win_rate >= 45:
            critique_parts.append("Win rate is acceptable but needs improvement. Review your entry triggers.")
        else:
            critique_parts.append("Win rate is below target. Consider trading less and focusing only on A+ setups.")

        if max_consec_loss >= 4:
            critique_parts.append(f"Warning: {max_consec_loss} consecutive losses detected. A circuit-breaker rule is recommended.")

        if total_pnl < 0:
            critique_parts.append("Net P/L is negative. Re-evaluate your risk/reward ratio and Stop Loss discipline.")
        else:
            critique_parts.append(f"Net P/L is positive at ${total_pnl:+.2f}. Maintain consistency.")

        review_msg = " ".join(critique_parts)
        if mt5_summary:
            review_msg += f"\n\n[Live MT5] {mt5_summary}"

        # Compute score 0-100
        score = min(100, max(0, int(win_rate) + (20 if total_pnl > 0 else -10) - (max_consec_loss * 3)))

        conn = sqlite3.connect("persistence.db")
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO trade_reviews (review_text, win_rate, score, created_at) VALUES (?, ?, ?, ?)",
            (review_msg, win_rate, score, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()

        return {
            "status": "SUCCESS",
            "review": review_msg,
            "weekly_report": weekly,
            "statistics": stats,
            "recent_trades": recent,
            "win_rate": win_rate,
            "score": score
        }
    except Exception as e:
        logger.error(f"Failed to analyze trade performance: {e}")
        return {"status": "ERROR", "error": str(e)}

def get_social_sentiment(keyword: str) -> Dict[str, Any]:
    """
    Fetch real crypto news sentiment from CryptoPanic.
    Uses authenticated API if CRYPTOPANIC_API_KEY is set in .env,
    otherwise falls back to public RSS.
    Get your free key: https://cryptopanic.com/developers/api/
    """
    import os
    import requests
    import xml.etree.ElementTree as ET

    api_key = os.environ.get("CRYPTOPANIC_API_KEY", "")

    # --- Authenticated API path ---
    if api_key and not api_key.startswith("YOUR_"):
        try:
            url = (
                f"https://cryptopanic.com/api/v1/posts/"
                f"?auth_token={api_key}&currencies={keyword.upper()}&public=true"
            )
            resp = requests.get(url, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", [])
                titles = [r.get("title", "") for r in results[:20]]

                bull_words = {"surge", "rally", "breakout", "bullish", "pump", "moon", "ath", "buy", "gain", "rise", "up"}
                bear_words = {"crash", "dump", "bearish", "fall", "drop", "sell", "decline", "fear", "risk", "down", "slump"}
                bull_count = sum(1 for t in titles for w in bull_words if w in t.lower())
                bear_count = sum(1 for t in titles for w in bear_words if w in t.lower())
                total_signals = bull_count + bear_count
                score = round((bull_count / total_signals * 100) if total_signals > 0 else 50)

                # CryptoPanic provides vote counts
                votes_up = sum(r.get("votes", {}).get("positive", 0) for r in results)
                votes_down = sum(r.get("votes", {}).get("negative", 0) for r in results)

                return {
                    "keyword": keyword.upper(),
                    "hype_score": score,
                    "trending_mentions": len(results),
                    "bullish_signals": bull_count,
                    "bearish_signals": bear_count,
                    "votes_up": votes_up,
                    "votes_down": votes_down,
                    "sentiment": "BULLISH" if score > 60 else ("BEARISH" if score < 40 else "NEUTRAL"),
                    "headlines": titles[:5],
                    "data_source": "CryptoPanic API"
                }
        except Exception as e:
            logger.warning(f"CryptoPanic API error for '{keyword}': {e}")

    # --- Public RSS fallback ---
    try:
        rss_url = f"https://cryptopanic.com/news/rss/?search={keyword}"
        resp = requests.get(rss_url, timeout=7, headers={"User-Agent": "CryptoStreamAI/1.0"})
        if resp.status_code != 200:
            raise Exception(f"RSS returned {resp.status_code}")
        root = ET.fromstring(resp.text)
        items = root.findall(".//item")
        titles = [item.findtext("title", "") for item in items[:20]]
        if not titles:
            raise Exception("No items in RSS")
        bull_words = {"surge", "rally", "breakout", "bullish", "pump", "moon", "ath", "buy", "gain", "rise", "up"}
        bear_words = {"crash", "dump", "bearish", "fall", "drop", "sell", "decline", "fear", "risk", "down", "slump"}
        bull_count = sum(1 for t in titles for w in bull_words if w in t.lower())
        bear_count = sum(1 for t in titles for w in bear_words if w in t.lower())
        total_signals = bull_count + bear_count
        score = round((bull_count / total_signals * 100) if total_signals > 0 else 50)
        return {
            "keyword": keyword,
            "hype_score": score,
            "trending_mentions": len(items),
            "bullish_signals": bull_count,
            "bearish_signals": bear_count,
            "sentiment": "BULLISH" if score > 60 else ("BEARISH" if score < 40 else "NEUTRAL"),
            "headlines": titles[:5],
            "data_source": "CryptoPanic RSS"
        }
    except Exception as e:
        logger.warning(f"CryptoPanic RSS fallback failed for '{keyword}': {e}")
        import random
        score = random.randint(30, 80)
        return {
            "keyword": keyword,
            "hype_score": score,
            "trending_mentions": random.randint(0, 1000),
            "sentiment": "BULLISH" if score > 60 else ("BEARISH" if score < 40 else "NEUTRAL"),
            "note": "Simulated data — set CRYPTOPANIC_API_KEY in .env for real data"
        }

def get_trading_tactics(symbol: str) -> str:
    """
    AGGREGATED INSTITUTIONAL TRADING TACTICS (V2)
    Implements 6 core personas with Trigger, Invalidation, and TP parameters.
    """
    logger.info(f"🛡️ Generating institutional tactics for {symbol}...")
    try:
        # 1. Fetch data & Indicators
        df = get_kline_data(symbol, timeframe="1h", limit=100)
        if df.empty: return json.dumps({"error": "No market data found"})
        
        df = compute_indicators(df)
        indicators = get_indicator_summary(df)
        smc = get_smart_money_analysis(df)
        
        last = df.iloc[-1]
        price = float(last['Close'])
        
        # Helper data
        ema_data = indicators.get('ema', {})
        ema_50 = ema_data.get('ema_50', 0)
        ema_200 = ema_data.get('ema_200', 0)
        rsi_val = indicators.get('rsi', {}).get('value', 50)
        regime = smc.get('regime', 'UNKNOWN')
        structure = smc.get('structure', {})
        liquidity = smc.get('liquidity', {})
        vol_spike = indicators.get('volume', {}).get('spike', False)
        
        tactics = []
        
        # --- 1. TREND CONTINUATION ---
        trend_score = 50
        trend_move = "SIT ON HANDS"
        if ema_data.get('long_term') == 'BULLISH' and price > ema_50:
            trend_score = 85
            trend_move = "BUY"
        elif ema_data.get('long_term') == 'BEARISH' and price < ema_50:
            trend_score = 85
            trend_move = "SELL"
            
        tactics.append({
            "name": "Trend Continuation",
            "style": "HTF Momentum",
            "score": trend_score,
            "move": trend_move,
            "trigger": "Price pullback to EMA 20/50 + Bullish/Bearish Engulfing",
            "invalidation": "Close below/above last Swing High/Low",
            "tp": "RR 1:2 or next structural resistance",
            "logic": f"Price vs EMA200: {ema_data.get('long_term')} | EMA Order: {ema_data.get('signal')}"
        })
        
        # --- 2. LIQUIDITY SWEEP REVERSAL ---
        liq_score = 50
        has_eq = len(liquidity.get('buy_side', [])) > 0 or len(liquidity.get('sell_side', [])) > 0
        if has_eq and structure.get('choch'):
            liq_score = 90
            
        tactics.append({
            "name": "Liquidity Sweep",
            "style": "Smart Money",
            "score": liq_score,
            "move": "REVERSAL PLAY",
            "trigger": "Liquidity sweep of Equal H/L + CHOCH reversal",
            "invalidation": "New High/Low formed after sweep",
            "tp": "Opposite side liquidity pool",
            "logic": f"Equal Levels: {'Yes' if has_eq else 'No'} | CHOCH: {structure.get('choch')}"
        })
        
        # --- 3. BREAKOUT + RETEST ---
        break_score = 50
        if regime == 'RANGE' and vol_spike:
            break_score = 80
            
        tactics.append({
            "name": "Breakout + Retest",
            "style": "Momentum",
            "score": break_score,
            "move": "WAIT FOR RETEST",
            "trigger": "H1 Candle close outside range with Volume Spike",
            "invalidation": "Price returns inside the previous range",
            "tp": "Measured move from range height",
            "logic": f"Regime: {regime} | Volume Spike: {vol_spike}"
        })
        
        # --- 4. MEAN REVERSION ---
        rev_score = 50
        if regime == 'RANGE' and (rsi_val > 70 or rsi_val < 30):
            rev_score = 85
            
        tactics.append({
            "name": "Mean Reversion",
            "style": "Range Oscillations",
            "score": rev_score,
            "move": "FADE THE EDGE",
            "trigger": "Touch of Overbought/Oversold + Rejection Candle",
            "invalidation": "Breakout with high volume",
            "tp": "Mid-range (EMA 50 or BB Mid)",
            "logic": f"RSI: {rsi_val} | BB Position: {indicators.get('bollinger_bands', {}).get('position')}"
        })
        
        # --- 5. STOCK ACCUMULATION ---
        acc_score = 50
        is_stock = any(x in symbol.upper() for x in ["NAS", "SPX", "NVDA", "TSLA", "AAPL"])
        if is_stock and price < ema_200:
            acc_score = 75
            
        tactics.append({
            "name": "Stock Accumulation",
            "style": "Value / Long-term",
            "score": acc_score,
            "move": "ACCUMULATE",
            "trigger": "Price stabilize < EMA 200 + No lower low",
            "invalidation": "Fundamentals break / Multi-year low",
            "tp": "Long-term trend recovery",
            "logic": f"Is Stock: {is_stock} | Below 200 EMA: {price < ema_200}"
        })
        
        # --- 6. NO TRADE ---
        no_trade_score = 10
        if regime == 'CHAOS':
            no_trade_score = 100
            
        tactics.append({
            "name": "No Trade",
            "style": "Safety / Capital Preservation",
            "score": no_trade_score,
            "move": "STAND ASIDE",
            "trigger": "High volatility (CHAOS) or Signal Conflict",
            "invalidation": "Market stabilize into TREND/RANGE",
            "tp": "None (Capital Saved)",
            "logic": f"Regime: {regime} | Market Condition: High Risk"
        })
        
        # --- 7. AI CONFIDENCE (Intelligence V4 Hybrid Brain) ---
        # Combines Ensemble V3 with Temporal Neural V4
        ai_side = "BUY" if trend_score > 50 or (smc and smc.get('choch')) else "SELL"
        try:
            # Sync with news sentiment
            score_data = get_brain_state().get("sentiment", {}).get(symbol, {})
            sentiment_score = score_data.get("score", 0.0)
            
            ml_result = predict_with_neural_consensus(
                df, 
                len(df) - 1, 
                side=ai_side, 
                symbol=symbol, 
                sentiment_score=sentiment_score
            )
        except Exception as e:
            logger.error(f"[V4] Neural Consensus failed: {e}")
            ml_result = {"available": False}
        
        if ml_result.get("available"):
            ml_score = ml_result.get("win_pct", 50)
            ml_reasons = ml_result.get("rationale", [])
            ml_acc = ml_result.get("accuracy", 0)
            ml_samples = ml_result.get("n_samples", 0)
            neural_match = ml_result.get("neural_alignment", False)
            
            tactics.append({
                "name": "Deep Brain Confidence" if neural_match else "AI Confidence (V4 Hybrid)",
                "style": "Neural Consensus" if neural_match else "Hybrid Stacking",
                "score": ml_score,
                "move": "VERIFIED" if ml_score > 60 else "CAUTION",
                "trigger": f"{'✅ Neural Sync | ' if neural_match else ''}Ensemble ({ml_acc*100:.1f}% Acc | {ml_samples} Samples)",
                "invalidation": "Temporal Shift / Deep Neural Conflict",
                "tp": "Dynamic (Institutional Risk Shield)",
                "logic": f"Win Prob: {ml_score:.0f}% | Neural Match: {neural_match} | Samples: {ml_samples}",
            })
        
        # --- STRATEGIC SELECTION LOGIC ---
        recommendation = "HOLD / NO CLEAR EDGE"
        best_tactic = "None"
        
        if regime == 'CHAOS':
            recommendation = "STAY AWAY: Market is currently in CHAOS mode."
            best_tactic = "No Trade"
        elif regime == 'TREND':
            recommendation = f"FOCUS ON TREND: Use Trend Continuation for {symbol}."
            best_tactic = "Trend Continuation"
        elif has_eq and structure.get('choch'):
            recommendation = "SMC SETUP: Liquidity Sweep + CHOCH detected."
            best_tactic = "Liquidity Sweep"
        elif regime == 'RANGE':
            if vol_spike:
                recommendation = "BREAKOUT ALERT: Range identified with early volume spike."
                best_tactic = "Breakout + Retest"
            else:
                recommendation = "RANGE PLAY: Mean Reversion active."
                best_tactic = "Mean Reversion"
        elif is_stock:
            recommendation = "INVESTMENT VIEW: Accumulation zones active."
            best_tactic = "Stock Accumulation"
            
        # --- 8. INTELLIGENCE V7 SNIPER CORE ---
        v7_sniper_active = False
        sniper_lock_reason = None
        
        ml_score = ml_result.get("win_pct", 0) if ml_result.get("available") else 0
        
        # Sniper Lock: Confidence >= 80% + Institutional Liquidity Confirmation
        has_sweep = False
        sweeps = smc.get("liquidity_sweeps", {})
        if sweeps.get("bullish_sweep") or sweeps.get("bearish_sweep"):
            has_sweep = True

        if ml_score >= 80:
            v7_sniper_active = True
            sniper_lock_reason = "HIGH_CONFIDENCE_NEURAL_CONSENSUS"
            if has_sweep:
                sniper_lock_reason = "INSTITUTIONAL_LIQUIDITY_ALIGNED"

        return json.dumps({
            "symbol": symbol.upper(),
            "price": price,
            "recommendation": recommendation,
            "best_persona": best_tactic,
            "tactics": tactics,
            "timestamp": time.time(),
            "ai_edge": ml_result if ml_result.get("available") else None,
            "v7_status": {
                "active": True,
                "sniper_mode": True,
                "sniper_locked": v7_sniper_active,
                "lock_reason": sniper_lock_reason,
                "institutional_flow": smc.get("liquidity_sweeps", {})
            }
        })
        
    except Exception as e:
        logger.error(f"Tactics Engine Failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return json.dumps({"error": str(e)})

# ============================================================
# NEW FEATURES (Phase 14)
# ============================================================

# ── 1. Fear & Greed Index ────────────────────────────────────
def get_fear_greed_index() -> Dict[str, Any]:
    """
    Return the Crypto Fear & Greed Index (alternative.me, free API)
    combined with a Stock Fear & Greed composite built from VIX,
    put/call ratio, and market breadth.
    """
    cached = _cache_get("fear_greed")
    if cached:
        return cached
    try:
        import requests as _req
        # ── Crypto F&G (alternative.me) ──
        r = _req.get("https://api.alternative.me/fng/?limit=2", timeout=6)
        crypto_data = r.json()["data"]
        crypto_now  = crypto_data[0]
        crypto_prev = crypto_data[1] if len(crypto_data) > 1 else crypto_now

        crypto_score = int(crypto_now["value"])
        crypto_label = crypto_now["value_classification"]
        prev_score   = int(crypto_prev["value"])
        delta        = crypto_score - prev_score

        # ── Stock F&G composite from VIX, breadth, momentum ──
        try:
            vix_val = float(yf.Ticker("^VIX").history(period="2d")["Close"].iloc[-1])
            spx_ser = yf.Ticker("^GSPC").history(period="50d")["Close"]
            spx_now = float(spx_ser.iloc[-1])
            spx_ma50 = float(spx_ser.mean())
            # Simple 0-100 stock score (inverted VIX + momentum)
            vix_cmp = max(0, min(100, 100 - (vix_val - 10) / 30 * 100))
            mmt_cmp = max(0, min(100, (spx_now / spx_ma50 - 0.9) / 0.3 * 100))
            stock_score = round(vix_cmp * 0.6 + mmt_cmp * 0.4, 1)
            if stock_score >= 75: stock_label = "Extreme Greed"
            elif stock_score >= 55: stock_label = "Greed"
            elif stock_score >= 45: stock_label = "Neutral"
            elif stock_score >= 25: stock_label = "Fear"
            else: stock_label = "Extreme Fear"
        except Exception:
            stock_score, stock_label = None, "N/A"

        result = {
            "crypto": {
                "score":      crypto_score,
                "label":      crypto_label,
                "prev_score": prev_score,
                "delta_1d":   delta,
                "interpretation": (
                    "ตลาด Crypto กลัวมาก — มักเป็นจุด Accumulate" if crypto_score < 25
                    else "ตลาด Crypto โลภมาก — ระวัง reversal" if crypto_score > 75
                    else f"Crypto sentiment อยู่ในโซน {crypto_label}"
                )
            },
            "stocks": {
                "score": stock_score,
                "label": stock_label,
            },
            "composite_signal": (
                "CONTRARIAN BUY" if crypto_score < 20
                else "TAKE PROFIT / REDUCE EXPOSURE" if crypto_score > 80
                else "MONITOR"
            ),
            "status": "SUCCESS",
            "source": "alternative.me + yfinance"
        }
        _cache_set("fear_greed", result, ttl=900)  # 15 min
        return result
    except Exception as e:
        logger.error(f"Fear & Greed Error: {e}")
        return {"error": str(e)}


# ── 2. Economic Calendar ─────────────────────────────────────
def get_economic_calendar(days_ahead: int = 7) -> Dict[str, Any]:
    """
    Fetch upcoming high-impact macro events (Fed, CPI, NFP, GDP, earnings).
    Combines Finnhub earnings calendar + a static macro schedule derived from
    known release patterns. No paid API key required for basic use.
    """
    from datetime import timedelta
    today   = dt_datetime.utcnow().date()
    end_dt  = today + timedelta(days=days_ahead)
    # Include today's date in cache key so cache refreshes daily
    cached = _cache_get(f"econ_cal_{days_ahead}_{today}")
    if cached:
        return cached
    try:
        import requests as _req
        events: list = []

        # ── Earnings calendar via Finnhub (free tier, no auth needed for basic) ──
        FINNHUB_KEY = os.getenv("FINNHUB_API_KEY", "")
        if FINNHUB_KEY:
            url = (f"https://finnhub.io/api/v1/calendar/earnings"
                   f"?from={today}&to={end_dt}&token={FINNHUB_KEY}")
            r = _req.get(url, timeout=8)
            if r.status_code == 200:
                for e in (r.json().get("earningsCalendar") or [])[:30]:
                    sym = e.get("symbol","")
                    if sym in NASDAQ_100_TICKERS or sym in SP500_TICKERS:
                        events.append({
                            "date":   e.get("date"),
                            "type":   "EARNINGS",
                            "symbol": sym,
                            "name":   e.get("company",""),
                            "impact": "HIGH",
                            "estimate_eps": e.get("epsEstimate"),
                        })

        # ── Static high-impact macro event anchors (rolling monthly) ──
        MACRO_ANCHORS = [
            {"name": "US CPI (Inflation)", "abbrev": "CPI",  "impact": "CRITICAL",
             "desc": "ตัวเลขเงินเฟ้อสหรัฐ — ผลต่อ Fed rate path และ risk assets ทุกตัว"},
            {"name": "FOMC Meeting / Fed Decision", "abbrev": "FOMC", "impact": "CRITICAL",
             "desc": "ประชุม Fed — ผลต่อ DXY, bonds, crypto และ equities โดยตรง"},
            {"name": "US Non-Farm Payrolls", "abbrev": "NFP",  "impact": "HIGH",
             "desc": "ตัวเลขจ้างงานสหรัฐ — บ่งบอก labor market health"},
            {"name": "US GDP Growth Rate",  "abbrev": "GDP",  "impact": "HIGH",
             "desc": "อัตราเติบโตเศรษฐกิจ — ส่งผลต่อ macro regime"},
            {"name": "US PCE Price Index",  "abbrev": "PCE",  "impact": "HIGH",
             "desc": "ดัชนีราคา PCE — ตัวชี้วัด inflation หลักของ Fed"},
            {"name": "US Retail Sales",     "abbrev": "RETAIL","impact": "MEDIUM",
             "desc": "ยอดขายปลีก — บ่งบอก consumer spending และ GDP"},
        ]

        # ── Fetch Forex Factory calendar ──────────────────────────────────────
        # On weekends, "thisweek" = the week that just ended, so always pull
        # nextweek too. For 14d+, also pull the month file.
        FF_URLS = [
            "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
            "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
        ]
        if days_ahead >= 14:
            FF_URLS.append("https://nfs.faireconomy.media/ff_calendar_thismonth.json")
        # Weekend guard: also fetch nextweek explicitly (already in list, just ensure)
        is_weekend = today.weekday() >= 5  # 5=Sat, 6=Sun

        macro_events: list = []
        seen_keys: set = set()
        for ff_url in FF_URLS:
            try:
                r2 = _req.get(ff_url, timeout=6, headers={"User-Agent": "CryptoStreamAI/1.0"})
                if r2.status_code != 200:
                    continue
                for ev in r2.json():
                    impact = ev.get("impact", "").upper()
                    ev_date = ev.get("date", "")
                    # Filter by date range
                    try:
                        from datetime import date as _date
                        ev_d = _date.fromisoformat(ev_date[:10]) if ev_date else None
                        if ev_d and (ev_d < today or ev_d > end_dt):
                            continue
                    except Exception:
                        pass
                    # Dedup by date+name
                    key = f"{ev_date}_{ev.get('title','')}"
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    # Include ALL impacts (HIGH, MEDIUM, LOW)
                    macro_events.append({
                        "date":     ev_date,
                        "time":     ev.get("time", ""),
                        "type":     "MACRO",
                        "name":     ev.get("title", ""),
                        "impact":   impact if impact in ("HIGH", "MEDIUM", "LOW") else "LOW",
                        "currency": ev.get("country", ""),
                        "actual":   ev.get("actual"),
                        "forecast": ev.get("forecast"),
                        "previous": ev.get("previous"),
                    })
            except Exception:
                continue

        all_events = macro_events + events
        all_events.sort(key=lambda x: x.get("date", ""))

        critical_count = sum(1 for e in all_events if e.get("impact") == "CRITICAL")
        high_count     = sum(1 for e in all_events if e.get("impact") in ("HIGH", "CRITICAL"))

        result = {
            "period":           f"{today} → {end_dt}",
            "total_events":     len(all_events),
            "critical_count":   critical_count,
            "high_impact_count": high_count,
            "events":           all_events,   # no artificial limit
            "macro_watch":      MACRO_ANCHORS[:3],
            "trading_note": (
                "มีตัวเลข CRITICAL ในช่วงนี้ — ระวัง volatility spike, พิจารณาลด size ก่อนประกาศ"
                if critical_count > 0
                else "ไม่มีตัวเลข CRITICAL — ตลาดน่าจะเคลื่อนไหวตาม technicals"
            ),
            "status": "SUCCESS",
        }
        _cache_set(f"econ_cal_{days_ahead}_{today}", result, ttl=1800)  # refresh every 30 min
        return result
    except Exception as e:
        logger.error(f"Economic Calendar Error: {e}")
        return {"error": str(e)}


# ── 3. Liquidation Heatmap ───────────────────────────────────
def get_liquidation_heatmap(symbol: str = "BTC") -> Dict[str, Any]:
    """
    Fetch crypto liquidation clusters from Coinglass public API.
    Returns price levels where long/short liquidations are concentrated
    — critical for identifying magnetic price zones and stop-hunt targets.
    """
    cached = _cache_get(f"liq_heatmap_{symbol.upper()}")
    if cached:
        return cached
    try:
        import requests as _req

        sym = symbol.upper().replace("USDT","").replace("-USD","")

        # Coinglass open endpoint (no auth for summary data)
        url = f"https://open-api.coinglass.com/public/v2/liquidation_ex_chart?ex=Binance&pair={sym}USDT&interval=0"
        headers = {"accept": "application/json"}
        cg_key = os.getenv("COINGLASS_API_KEY", "")
        if cg_key:
            headers["coinglassSecret"] = cg_key

        r = _req.get(url, headers=headers, timeout=8)

        if r.status_code == 200:
            data = r.json().get("data", {})
            buy_liq  = data.get("buyLiquidationMap", [])   # Short liquidations (price falls)
            sell_liq = data.get("sellLiquidationMap", [])  # Long liquidations (price rises)

            def top_clusters(liq_list, n=5):
                if not liq_list:
                    return []
                srt = sorted(liq_list, key=lambda x: x.get("value", 0), reverse=True)
                return [{"price": round(x["price"],2), "usd_value_M": round(x.get("value",0)/1e6,2)} for x in srt[:n]]

            long_clusters  = top_clusters(buy_liq)   # Long liq = price drops to these levels
            short_clusters = top_clusters(sell_liq)  # Short liq = price rises to these levels

            result = {
                "symbol": sym,
                "top_long_liquidation_zones":  long_clusters,   # Bears attack these from above
                "top_short_liquidation_zones": short_clusters,  # Bulls squeeze shorts to these
                "trading_insight": (
                    f"Long liquidation clusters ที่ {[c['price'] for c in long_clusters[:2]]} "
                    f"— ถ้าราคาหล่นลงมาแถวนี้ อาจเกิด cascade drop | "
                    f"Short liquidation clusters ที่ {[c['price'] for c in short_clusters[:2]]} "
                    f"— ถ้าราคาขึ้นไปแถวนี้ อาจเกิด short squeeze"
                ) if long_clusters else "No cluster data available",
                "status": "SUCCESS",
                "source": "Coinglass"
            }
        else:
            # Fallback: estimate liquidation zones from order book / price action
            price_data = get_kline_data(sym, timeframe="1h", limit=48, asset_class="CRYPTO")
            if price_data is not None and not price_data.empty:
                current_price = float(price_data["close"].iloc[-1])
                low_24h  = float(price_data["low"].tail(24).min())
                high_24h = float(price_data["high"].tail(24).max())
                # Common liquidation hotspots: wick lows/highs, round numbers
                result = {
                    "symbol": sym,
                    "current_price": current_price,
                    "estimated_long_liq_zone":  round(low_24h * 0.985, 2),   # ~1.5% below 24h low
                    "estimated_short_liq_zone": round(high_24h * 1.015, 2),  # ~1.5% above 24h high
                    "note": "Coinglass unavailable — estimated from price action (24h H/L extremes)",
                    "status": "ESTIMATED"
                }
            else:
                result = {"symbol": sym, "error": "Unable to fetch liquidation data", "status": "FAILED"}

        _cache_set(f"liq_heatmap_{symbol.upper()}", result, ttl=600)
        return result
    except Exception as e:
        logger.error(f"Liquidation Heatmap Error: {e}")
        return {"error": str(e)}


# ── 4. Multi-Timeframe Confluence Scanner ───────────────────
def scan_multi_timeframe(symbol: str, asset_class: str = "CRYPTO") -> Dict[str, Any]:
    """
    Run get_market_analysis across all key timeframes (5m, 15m, 1h, 4h, 1d)
    and compute a confluence score — how many TFs agree on direction.
    Returns alignment score, dominant bias, and per-TF breakdown.
    """
    cached = _cache_get(f"mtf_{symbol.upper()}_{asset_class}")
    if cached:
        return cached
    try:
        timeframes = ["5m", "15m", "1h", "4h", "1d"]
        results: Dict[str, Any] = {}
        bull_count = bear_count = neutral_count = 0

        for tf in timeframes:
            try:
                ana = get_market_analysis(symbol=symbol, timeframe=tf, asset_class=asset_class)
                # Extract direction from summary
                summary = ""
                if isinstance(ana, dict):
                    summary = (
                        ana.get("summary","") or
                        ana.get("signal","") or
                        str(ana.get("indicators",{}).get("recommendation",""))
                    ).upper()
                elif isinstance(ana, str):
                    summary = ana.upper()

                if any(k in summary for k in ["BUY","BULL","LONG","BULLISH","UPTREND","UP"]):
                    bias = "BULLISH"; bull_count += 1
                elif any(k in summary for k in ["SELL","BEAR","SHORT","BEARISH","DOWNTREND","DOWN"]):
                    bias = "BEARISH"; bear_count += 1
                else:
                    bias = "NEUTRAL"; neutral_count += 1

                # Grab key numbers if present
                tf_entry = {"bias": bias}
                if isinstance(ana, dict):
                    inds = ana.get("indicators", {})
                    tf_entry["rsi"]   = inds.get("rsi")
                    tf_entry["trend"] = inds.get("trend") or inds.get("ma_trend")
                results[tf] = tf_entry
            except Exception as e:
                results[tf] = {"bias": "ERROR", "error": str(e)}

        total = bull_count + bear_count + neutral_count
        confluence_score = round(max(bull_count, bear_count) / total * 100) if total else 0

        if bull_count > bear_count:
            dominant_bias = "BULLISH"
        elif bear_count > bull_count:
            dominant_bias = "BEARISH"
        else:
            dominant_bias = "MIXED / NEUTRAL"

        strength = (
            "STRONG" if confluence_score >= 80
            else "MODERATE" if confluence_score >= 60
            else "WEAK / CONFLICTED"
        )

        result = {
            "symbol":           symbol.upper(),
            "asset_class":      asset_class,
            "dominant_bias":    dominant_bias,
            "confluence_score": confluence_score,
            "strength":         strength,
            "bull_tfs":         bull_count,
            "bear_tfs":         bear_count,
            "neutral_tfs":      neutral_count,
            "per_timeframe":    results,
            "trading_note": (
                f"{symbol.upper()} มี confluence {confluence_score}% ไปทาง {dominant_bias} "
                f"({bull_count}/{total} TF agree) — "
                + ("เหมาะเข้าเทรดตาม bias" if confluence_score >= 60
                   else "ยังขัดแย้งกันระหว่าง TF — รอสัญญาณที่ชัดขึ้น")
            ),
            "status": "SUCCESS"
        }
        _cache_set(f"mtf_{symbol.upper()}_{asset_class}", result, ttl=300)
        return result
    except Exception as e:
        logger.error(f"MTF Confluence Error: {e}")
        return {"error": str(e)}


# ── 5. Portfolio Correlation Matrix ─────────────────────────
def get_portfolio_correlation(symbols: Optional[List[str]] = None, period: str = "3mo") -> Dict[str, Any]:
    """
    Compute pairwise Pearson correlation between portfolio assets (or a given list).
    Flags dangerously high correlations (>0.85) that indicate concentration risk.
    Uses 3-month daily returns by default.
    """
    cached = _cache_get(f"port_corr_{'_'.join(sorted(symbols or []))}")
    if cached:
        return cached
    try:
        # Default to the main ticker bar assets if no list provided
        if not symbols or len(symbols) < 2:
            symbols = ["BTC-USD","ETH-USD","SOL-USD","GC=F","^GSPC","^IXIC","NVDA","TSLA"]

        # Normalize symbols
        yf_syms = []
        sym_map: Dict[str,str] = {}
        for s in symbols:
            s = s.strip().upper()
            mapping = {
                "BTC":"BTC-USD","ETH":"ETH-USD","SOL":"SOL-USD",
                "GOLD":"GC=F","XAU":"GC=F","NASDAQ":"^IXIC","SP500":"^GSPC",
            }
            yf_s = mapping.get(s, s)
            yf_syms.append(yf_s)
            sym_map[yf_s] = s

        df = yf.download(yf_syms, period=period, auto_adjust=True, progress=False)["Close"]
        if isinstance(df, pd.Series):
            df = df.to_frame()
        df.dropna(how="all", inplace=True)
        returns = df.pct_change().dropna()
        corr   = returns.corr().round(3)

        # Build pairs list and flag high correlations
        pairs: list = []
        cols = list(corr.columns)
        for i in range(len(cols)):
            for j in range(i+1, len(cols)):
                c_val = corr.iloc[i, j]
                a, b  = sym_map.get(cols[i], cols[i]), sym_map.get(cols[j], cols[j])
                flag  = abs(c_val) > 0.85
                pairs.append({
                    "asset_a":   a,
                    "asset_b":   b,
                    "correlation": c_val,
                    "risk_flag":   flag,
                    "note": f"⚠️ High correlation — {a} & {b} ขยับเหมือนกันมาก ไม่ช่วย diversify" if flag else ""
                })

        # Sort by absolute correlation descending
        pairs.sort(key=lambda x: abs(x["correlation"]), reverse=True)
        high_risk_pairs = [p for p in pairs if p["risk_flag"]]

        result = {
            "period": period,
            "symbols": [sym_map.get(s,s) for s in yf_syms],
            "top_correlations": pairs[:10],
            "high_risk_pairs":  high_risk_pairs,
            "concentration_warning": (
                f"มี {len(high_risk_pairs)} คู่ที่ correlation > 0.85 — "
                "พอร์ตกระจุกตัว ควรเพิ่ม uncorrelated assets"
                if high_risk_pairs else
                "Diversification ดี — ไม่มีคู่ที่ correlation สูงเกิน 0.85"
            ),
            "status": "SUCCESS"
        }
        _cache_set(f"port_corr_{'_'.join(sorted(symbols))}", result, ttl=3600)
        return result
    except Exception as e:
        logger.error(f"Portfolio Correlation Error: {e}")
        return {"error": str(e)}


# ── 6. AI Weekly Report Generator ───────────────────────────
def generate_weekly_report() -> Dict[str, Any]:
    """
    Compile a full weekly performance report: trade history, win rate,
    best/worst trades, market regime summary, and AI recommendations.
    Returns a structured Markdown-ready dict for the agent to present.
    """
    try:
        from datetime import timedelta
        week_ago = (dt_datetime.utcnow() - timedelta(days=7)).isoformat()

        # ── Pull closed trades from SQLite ──
        trade_rows: list = []
        try:
            con = sqlite3.connect(os.getenv("TRADE_LOG_DB", "persistence.db"))
            cur = con.cursor()
            cur.execute(
                "SELECT symbol, side, entry_price, exit_price, pnl_usd, status, timestamp "
                "FROM trades WHERE timestamp >= ? ORDER BY timestamp DESC",
                (week_ago,)
            )
            trade_rows = [dict(zip([c[0] for c in cur.description], r)) for r in cur.fetchall()]
            con.close()
        except Exception:
            pass

        # ── Aggregate stats ──
        closed  = [t for t in trade_rows if t.get("status") in ("CLOSED","WIN","LOSS")]
        wins    = [t for t in closed if (t.get("pnl_usd") or 0) > 0]
        losses  = [t for t in closed if (t.get("pnl_usd") or 0) <= 0]
        total_pnl   = sum(t.get("pnl_usd") or 0 for t in closed)
        win_rate    = round(len(wins) / len(closed) * 100, 1) if closed else 0
        avg_win     = round(sum(t.get("pnl_usd",0) for t in wins) / len(wins), 2)   if wins   else 0
        avg_loss    = round(sum(t.get("pnl_usd",0) for t in losses) / len(losses), 2) if losses else 0
        profit_factor = round(abs(sum(t.get("pnl_usd",0) for t in wins)) /
                              max(abs(sum(t.get("pnl_usd",0) for t in losses)), 0.01), 2)

        best_trade  = max(closed, key=lambda t: t.get("pnl_usd",0), default=None)
        worst_trade = min(closed, key=lambda t: t.get("pnl_usd",0), default=None)

        # ── Market context ──
        try:
            regime_data = get_market_regime() if callable(get_market_regime) else {}
            regime = regime_data.get("regime", "N/A") if isinstance(regime_data, dict) else "N/A"
        except Exception:
            regime = "N/A"

        # ── Build report ──
        grade = (
            "A+" if win_rate >= 70 and profit_factor >= 2
            else "A"  if win_rate >= 60 and profit_factor >= 1.5
            else "B"  if win_rate >= 50
            else "C"  if win_rate >= 40
            else "D"
        )

        recommendations: list = []
        if win_rate < 45:
            recommendations.append("Win rate ต่ำกว่า 45% — ทบทวน entry criteria หรือลดจำนวนเทรดก่อน")
        if profit_factor < 1.0:
            recommendations.append("Profit Factor < 1.0 — average loss ใหญ่กว่า average win, ปรับ SL/TP ratio")
        if len(losses) > len(wins) * 2:
            recommendations.append("Loss เยอะกว่า Win 2 เท่า — พิจารณาหยุด trade และ review strategy")
        if not recommendations:
            recommendations.append("ผลงานดี — ทำต่อไปตาม process และ risk management เดิม")

        result = {
            "report_period": f"{week_ago[:10]} → {dt_datetime.utcnow().date()}",
            "performance_grade": grade,
            "summary": {
                "total_trades":   len(closed),
                "wins":           len(wins),
                "losses":         len(losses),
                "win_rate_pct":   win_rate,
                "total_pnl_usd":  round(total_pnl, 2),
                "avg_win_usd":    avg_win,
                "avg_loss_usd":   avg_loss,
                "profit_factor":  profit_factor,
            },
            "best_trade":  best_trade,
            "worst_trade": worst_trade,
            "market_regime_this_week": regime,
            "ai_recommendations": recommendations,
            "open_trades_this_week": len([t for t in trade_rows if t.get("status") == "OPEN"]),
            "status": "SUCCESS"
        }
        return result
    except Exception as e:
        logger.error(f"Weekly Report Error: {e}")
        return {"error": str(e)}


# ── 7. Paper Trading Mode ────────────────────────────────────
_PAPER_DB = os.getenv("PAPER_TRADE_DB", "persistence.db")

def paper_trade(action: str, symbol: str = "", side: str = "BUY",
                volume: float = 1.0, price: Optional[float] = None,
                trade_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Simulate trades without touching MT5 or real capital.
    action: 'OPEN' | 'CLOSE' | 'LIST' | 'RESET'
    Creates a separate paper_trades table in SQLite.
    """
    try:
        con = sqlite3.connect(_PAPER_DB)
        cur = con.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS paper_trades (
                id TEXT PRIMARY KEY,
                symbol TEXT, side TEXT, volume REAL,
                entry_price REAL, current_price REAL,
                pnl_usd REAL, status TEXT,
                opened_at TEXT, closed_at TEXT
            )
        """)
        con.commit()

        if action.upper() == "OPEN":
            # Get current price if not supplied
            if not price:
                try:
                    asset_class = "CRYPTO" if symbol.upper() in {"BTC","ETH","SOL","BNB","XRP","DOGE"} else "STOCK"
                    kline = get_kline_data(symbol, timeframe="1m", limit=1, asset_class=asset_class)
                    price = float(kline["close"].iloc[-1]) if kline is not None and not kline.empty else 0.0
                except Exception:
                    price = 0.0

            tid = str(uuid.uuid4())[:8]
            cur.execute("""
                INSERT INTO paper_trades (id,symbol,side,volume,entry_price,current_price,pnl_usd,status,opened_at)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (tid, symbol.upper(), side.upper(), volume, price, price, 0.0, "OPEN",
                  dt_datetime.utcnow().isoformat()))
            con.commit(); con.close()
            return {
                "action": "OPENED",
                "trade_id": tid,
                "symbol": symbol.upper(),
                "side":   side.upper(),
                "volume": volume,
                "entry_price": price,
                "note": f"Paper trade เปิดแล้ว (ID: {tid}) — ไม่กระทบพอร์ตจริง",
                "status": "SUCCESS"
            }

        elif action.upper() == "CLOSE":
            if not trade_id:
                return {"error": "ต้องระบุ trade_id สำหรับ CLOSE"}
            cur.execute("SELECT * FROM paper_trades WHERE id=? AND status='OPEN'", (trade_id,))
            row = cur.fetchone()
            if not row:
                con.close(); return {"error": f"ไม่พบ paper trade ID {trade_id} หรือ status ไม่ใช่ OPEN"}

            cols = [c[0] for c in cur.description]
            t    = dict(zip(cols, row))

            if not price:
                try:
                    asset_class = "CRYPTO" if t["symbol"] in {"BTC","ETH","SOL","BNB"} else "STOCK"
                    kline = get_kline_data(t["symbol"], timeframe="1m", limit=1, asset_class=asset_class)
                    price = float(kline["close"].iloc[-1]) if kline is not None and not kline.empty else t["entry_price"]
                except Exception:
                    price = t["entry_price"]

            direction = 1 if t["side"] == "BUY" else -1
            pnl = direction * (price - t["entry_price"]) * t["volume"]

            cur.execute("""
                UPDATE paper_trades
                SET status='CLOSED', current_price=?, pnl_usd=?, closed_at=?
                WHERE id=?
            """, (price, round(pnl,2), dt_datetime.utcnow().isoformat(), trade_id))
            con.commit(); con.close()
            return {
                "action":     "CLOSED",
                "trade_id":   trade_id,
                "exit_price": price,
                "pnl_usd":    round(pnl,2),
                "result":     "WIN" if pnl > 0 else "LOSS",
                "status":     "SUCCESS"
            }

        elif action.upper() == "LIST":
            cur.execute("SELECT * FROM paper_trades ORDER BY opened_at DESC LIMIT 20")
            rows = [dict(zip([c[0] for c in cur.description], r)) for r in cur.fetchall()]
            con.close()
            open_trades   = [r for r in rows if r["status"]=="OPEN"]
            closed_trades = [r for r in rows if r["status"]=="CLOSED"]
            total_pnl_sim = sum(r.get("pnl_usd",0) for r in closed_trades)
            return {
                "open_trades":   open_trades,
                "closed_trades": closed_trades[:10],
                "total_simulated_pnl": round(total_pnl_sim,2),
                "status": "SUCCESS"
            }

        elif action.upper() == "RESET":
            cur.execute("DELETE FROM paper_trades")
            con.commit(); con.close()
            return {"action":"RESET", "message":"Paper trading history cleared.", "status":"SUCCESS"}

        con.close()
        return {"error": f"Unknown action: {action}. Use OPEN/CLOSE/LIST/RESET"}
    except Exception as e:
        logger.error(f"Paper Trade Error: {e}")
        return {"error": str(e)}


# ============================================================
# Phase 15 — New Features
# ============================================================

# ── 1. Funding Rate Tracker ──────────────────────────────────
def get_funding_rates(symbols: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Fetch current perpetual swap funding rates for major crypto assets.
    High positive funding = crowded longs → potential reversal short opportunity.
    High negative funding = crowded shorts → potential squeeze.
    Uses Binance public API (no auth required).
    """
    cached = _cache_get("funding_rates")
    if cached:
        return cached
    try:
        import requests as _req
        if not symbols:
            symbols = ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT",
                       "DOGEUSDT","AVAXUSDT","LINKUSDT","ARBUSDT","OPUSDT"]

        url = "https://fapi.binance.com/fapi/v1/premiumIndex"
        r = _req.get(url, timeout=8)
        all_rates = {d["symbol"]: d for d in r.json()} if r.status_code == 200 else {}

        rows = []
        for sym in symbols:
            d = all_rates.get(sym, {})
            if not d:
                continue
            rate      = float(d.get("lastFundingRate", 0))
            mark      = float(d.get("markPrice", 0))
            annual    = rate * 3 * 365 * 100  # 3 payments/day × 365
            sentiment = (
                "EXTREME LONG CROWDING ⚠️" if rate >  0.002
                else "BULLISH BIAS"          if rate >  0.0005
                else "EXTREME SHORT CROWDING ⚠️" if rate < -0.002
                else "BEARISH BIAS"          if rate < -0.0005
                else "NEUTRAL"
            )
            signal = (
                "CONTRARIAN SHORT" if rate >  0.002
                else "CONTRARIAN LONG" if rate < -0.002
                else "HOLD"
            )
            rows.append({
                "symbol":    sym.replace("USDT",""),
                "rate_pct":  round(rate * 100, 4),
                "annual_pct":round(annual, 2),
                "mark_price":round(mark, 4),
                "sentiment": sentiment,
                "signal":    signal,
            })

        rows.sort(key=lambda x: abs(x["rate_pct"]), reverse=True)
        extremes = [r for r in rows if abs(r["rate_pct"]) > 0.2]

        result = {
            "rates":   rows,
            "extremes": extremes,
            "market_summary": (
                f"มี {len(extremes)} coins ที่ funding rate สุดขีด — "
                "อาจเป็นโอกาส contrarian trade"
                if extremes else "Funding rates อยู่ในช่วงปกติ"
            ),
            "status": "SUCCESS",
            "source": "Binance Futures"
        }
        _cache_set("funding_rates", result, ttl=300)
        return result
    except Exception as e:
        logger.error(f"Funding Rates Error: {e}")
        return {"error": str(e)}


# ── 2. Portfolio Rebalancing Suggester ───────────────────────
def suggest_portfolio_rebalance(
    target_allocation: Optional[Dict[str, float]] = None
) -> Dict[str, Any]:
    """
    Compare current MT5/paper holdings vs target allocation.
    Calculates drift per asset and suggests BUY/SELL/HOLD actions.
    target_allocation: dict of {symbol: weight_pct}, e.g. {"BTC":40,"ETH":20,"NVDA":20,"GOLD":20}
    If not provided, defaults to 60/20/20 crypto/stock/macro.
    """
    try:
        if not target_allocation:
            target_allocation = {
                "BTC": 30.0, "ETH": 20.0, "SOL": 10.0,
                "NVDA": 15.0, "TSLA": 5.0,
                "GOLD": 15.0, "SP500": 5.0
            }

        # Normalise target to 100%
        total_target = sum(target_allocation.values())
        target = {k: round(v / total_target * 100, 2) for k, v in target_allocation.items()}

        # Get current prices via yfinance
        YF_MAP = {
            "BTC":"BTC-USD","ETH":"ETH-USD","SOL":"SOL-USD","BNB":"BNB-USD",
            "GOLD":"GC=F","SILVER":"SI=F","SP500":"^GSPC","NASDAQ":"^IXIC",
        }
        import requests as _req
        current_prices: Dict[str, float] = {}
        for sym in target:
            yf_sym = YF_MAP.get(sym, sym)
            try:
                df = yf.Ticker(yf_sym).history(period="1d")
                if not df.empty:
                    current_prices[sym] = float(df["Close"].iloc[-1])
            except Exception:
                pass

        # Try to get portfolio from paper_trades or MT5
        holdings: Dict[str, float] = {}
        try:
            con = sqlite3.connect(_PAPER_DB)
            cur = con.cursor()
            cur.execute("SELECT symbol, volume, entry_price FROM paper_trades WHERE status='OPEN'")
            for row in cur.fetchall():
                sym, vol, ep = row
                sym = sym.upper()
                price = current_prices.get(sym, ep or 0)
                holdings[sym] = holdings.get(sym, 0) + vol * price
            con.close()
        except Exception:
            pass

        total_value = sum(holdings.values()) or 100_000  # default $100k if no portfolio
        current_alloc = {sym: round(v / total_value * 100, 2) for sym, v in holdings.items()}

        actions = []
        for sym, tgt_pct in target.items():
            cur_pct = current_alloc.get(sym, 0.0)
            drift   = round(cur_pct - tgt_pct, 2)
            usd_diff = round((drift / 100) * total_value, 2)
            if abs(drift) < 2.0:
                action = "HOLD"
            elif drift > 0:
                action = f"REDUCE {sym} by ${abs(usd_diff):,.0f} ({abs(drift):.1f}% overweight)"
            else:
                action = f"ADD {sym} by ${abs(usd_diff):,.0f} ({abs(drift):.1f}% underweight)"

            actions.append({
                "symbol":    sym,
                "target_pct":  tgt_pct,
                "current_pct": cur_pct,
                "drift_pct":   drift,
                "usd_delta":   usd_diff,
                "action":      action,
                "priority":    "HIGH" if abs(drift) > 10 else "MEDIUM" if abs(drift) > 5 else "LOW"
            })

        actions.sort(key=lambda x: abs(x["drift_pct"]), reverse=True)
        return {
            "portfolio_value_usd": round(total_value, 2),
            "target_allocation":   target,
            "current_allocation":  current_alloc,
            "rebalance_actions":   actions,
            "urgent_actions":      [a for a in actions if a["priority"] == "HIGH"],
            "status": "SUCCESS"
        }
    except Exception as e:
        logger.error(f"Rebalance Error: {e}")
        return {"error": str(e)}


# ── 3. IV Rank / Volatility Alert ───────────────────────────
def get_iv_rank(symbol: str) -> Dict[str, Any]:
    """
    Compute Implied Volatility Rank (IVR) and IV Percentile for a stock/ETF.
    IVR = (IV_now - IV_52w_low) / (IV_52w_high - IV_52w_low) × 100
    IVR > 80 → options expensive → sell premium (credit spreads, covered calls)
    IVR < 20 → options cheap → buy directional options (calls/puts)
    Uses HV as proxy when IV not directly available.
    """
    cached = _cache_get(f"iv_rank_{symbol.upper()}")
    if cached:
        return cached
    try:
        sym = symbol.upper()
        YF_MAP = {"GOLD":"GC=F","XAU":"GC=F","SP500":"^GSPC","NASDAQ":"^IXIC","OIL":"CL=F"}
        yf_sym = YF_MAP.get(sym, sym if sym.endswith("-USD") else sym)

        df = yf.Ticker(yf_sym).history(period="1y")
        if df.empty or len(df) < 60:
            return {"symbol": sym, "error": "Insufficient price history", "status": "NO_DATA"}

        # Historical Volatility (HV) as IV proxy
        log_ret  = (df["Close"] / df["Close"].shift(1)).apply(lambda x: x if x > 0 else float('nan')).dropna()
        import math
        log_ret  = log_ret.apply(math.log)
        hv_20    = log_ret.rolling(20).std() * math.sqrt(252) * 100
        hv_now   = float(hv_20.iloc[-1])
        hv_52w_lo = float(hv_20.dropna().min())
        hv_52w_hi = float(hv_20.dropna().max())

        ivr = round(((hv_now - hv_52w_lo) / max(hv_52w_hi - hv_52w_lo, 0.01)) * 100, 1)
        # IV Percentile: % of days in past year where HV was BELOW current
        pct_below = sum(1 for v in hv_20.dropna() if v < hv_now)
        iv_pct    = round(pct_below / len(hv_20.dropna()) * 100, 1)

        regime = (
            "EXPENSIVE — Sell Premium" if ivr > 80
            else "ELEVATED" if ivr > 60
            else "NORMAL" if ivr > 40
            else "CHEAP — Buy Directional" if ivr < 20
            else "BELOW AVERAGE"
        )
        recommendation = (
            "ขาย premium: Covered Call, Cash-Secured Put, Credit Spread"
            if ivr > 75 else
            "ซื้อ directional options: Long Call/Put"
            if ivr < 25 else
            "Straddle/Strangle หรือ wait for clearer IV regime"
        )

        result = {
            "symbol":   sym,
            "hv_now":   round(hv_now, 2),
            "hv_52w_high": round(hv_52w_hi, 2),
            "hv_52w_low":  round(hv_52w_lo, 2),
            "iv_rank":      ivr,
            "iv_percentile": iv_pct,
            "regime":       regime,
            "recommendation": recommendation,
            "status": "SUCCESS",
            "note": "Using Historical Volatility as IV proxy (no options chain feed)"
        }
        _cache_set(f"iv_rank_{symbol.upper()}", result, ttl=1800)
        return result
    except Exception as e:
        logger.error(f"IV Rank Error: {e}")
        return {"error": str(e)}


# ── 4. ETF Flow Tracker ──────────────────────────────────────
def get_etf_flows(symbols: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Track estimated fund flows for major ETFs (SPY, QQQ, GLD, SLV, BTC ETFs etc.).
    Computes 5-day net flow estimate from AUM × price change + volume signal.
    Also fetches BTC ETF specific data where available.
    """
    cached = _cache_get("etf_flows")
    if cached:
        return cached
    try:
        if not symbols:
            symbols = [
                # Equity
                "SPY","QQQ","IWM","XLK","SOXX","SMH",
                # Commodity
                "GLD","SLV","USO",
                # Crypto ETFs
                "IBIT","FBTC","GBTC","ETHA",
                # Leveraged
                "TQQQ","SOXL",
            ]

        rows = []
        for sym in symbols:
            try:
                t   = yf.Ticker(sym)
                df  = t.history(period="10d")
                if df is None or len(df) < 5:
                    continue

                price_now  = float(df["Close"].iloc[-1])
                price_5d   = float(df["Close"].iloc[-5])
                vol_avg    = float(df["Volume"].iloc[-5:].mean())
                vol_1d     = float(df["Volume"].iloc[-1])
                ret_5d_pct = round((price_now / price_5d - 1) * 100, 2)

                # Flow signal: volume above avg = inflow if price up, outflow if price down
                vol_ratio = vol_1d / max(vol_avg, 1)
                if ret_5d_pct > 0 and vol_ratio > 1.2:
                    flow_signal, flow_dir = "INFLOW", "+"
                elif ret_5d_pct < 0 and vol_ratio > 1.2:
                    flow_signal, flow_dir = "OUTFLOW", "-"
                else:
                    flow_signal, flow_dir = "NEUTRAL", "="

                rows.append({
                    "symbol":       sym,
                    "price":        round(price_now, 2),
                    "return_5d_pct":ret_5d_pct,
                    "vol_ratio":    round(vol_ratio, 2),
                    "flow_signal":  flow_signal,
                    "flow_dir":     flow_dir,
                })
            except Exception:
                continue

        # Sector grouping
        inflows  = [r for r in rows if r["flow_signal"] == "INFLOW"]
        outflows = [r for r in rows if r["flow_signal"] == "OUTFLOW"]
        inflows.sort(key=lambda x: x["return_5d_pct"], reverse=True)
        outflows.sort(key=lambda x: x["return_5d_pct"])

        result = {
            "flows":      rows,
            "top_inflows":  inflows[:5],
            "top_outflows": outflows[:5],
            "market_theme": (
                "RISK ON — เงินไหลเข้า equity/crypto ETFs"
                if len(inflows) > len(outflows) else
                "RISK OFF — เงินไหลออกจาก risk assets"
                if len(outflows) > len(inflows) else
                "MIXED — rotation ระหว่าง sector"
            ),
            "status": "SUCCESS"
        }
        _cache_set("etf_flows", result, ttl=3600)
        return result
    except Exception as e:
        logger.error(f"ETF Flows Error: {e}")
        return {"error": str(e)}


# ── 5. Custom Screener ───────────────────────────────────────
def run_custom_screener(
    universe:   str = "NASDAQ100",
    rsi_max:    Optional[float] = None,
    rsi_min:    Optional[float] = None,
    vol_spike:  Optional[float] = None,
    pct_from_52wh: Optional[float] = None,
    min_return_1w: Optional[float] = None,
    max_return_1w: Optional[float] = None,
    custom_tickers: Optional[str] = None,
    limit: int = 15
) -> Dict[str, Any]:
    """
    Run a custom filter screener over NASDAQ 100, S&P 500, Crypto Top 30, Small-Cap, or custom tickers.
    Filters: RSI range, volume spike, proximity to 52w high, 1-week return range.
    Returns matching tickers sorted by volume ratio descending.
    """
    cached_key = f"screener_{universe}_{rsi_max}_{rsi_min}_{vol_spike}_{pct_from_52wh}_{custom_tickers}"
    cached = _cache_get(cached_key)
    if cached:
        return cached
    try:
        UNIVERSES: Dict[str, list] = {
            "NASDAQ100": list(NASDAQ_100_TICKERS)[:50],
            "SP500":     list(SP500_TICKERS)[:100],
            "CRYPTO":    ["BTC-USD","ETH-USD","SOL-USD","BNB-USD","XRP-USD",
                          "ADA-USD","DOGE-USD","AVAX-USD","LINK-USD","DOT-USD",
                          "MATIC-USD","UNI-USD","ATOM-USD","FIL-USD","NEAR-USD"],
            "SMALL_CAP": list(SMALL_CAP_TICKERS),
        }
        if universe.upper() == "CUSTOM" and custom_tickers:
            tickers = [t.strip().upper() for t in custom_tickers.split(",") if t.strip()]
        else:
            tickers = UNIVERSES.get(universe.upper(), UNIVERSES["NASDAQ100"])

        def _check(sym: str) -> Optional[Dict]:
            try:
                df = yf.Ticker(sym).history(period="3mo")
                if df is None or len(df) < 30:
                    return None
                close  = df["Close"]
                vol_s  = df["Volume"]
                price  = float(close.iloc[-1])
                high52 = float(close.tail(252).max() if len(close) >= 252 else close.max())
                pct_h  = round((price / high52 - 1) * 100, 2)

                vol_now  = float(vol_s.iloc[-1])
                vol_avg  = float(vol_s.tail(20).mean())
                v_ratio  = round(vol_now / max(vol_avg, 1), 2)

                # RSI
                delta = close.diff()
                gain  = delta.clip(lower=0).rolling(14).mean()
                loss  = (-delta.clip(upper=0)).rolling(14).mean()
                rs    = gain / loss.replace(0, float('nan'))
                rsi   = float(100 - (100 / (1 + rs)).iloc[-1])

                ret_1w = round((price / float(close.iloc[-5]) - 1) * 100, 2) if len(close) >= 5 else 0

                # Apply filters
                if rsi_max is not None and rsi > rsi_max:    return None
                if rsi_min is not None and rsi < rsi_min:    return None
                if vol_spike is not None and v_ratio < vol_spike: return None
                if pct_from_52wh is not None and pct_h < -abs(pct_from_52wh): return None
                if min_return_1w is not None and ret_1w < min_return_1w: return None
                if max_return_1w is not None and ret_1w > max_return_1w: return None

                return {
                    "symbol":   sym.replace("-USD",""),
                    "price":    round(price, 2),
                    "rsi":      round(rsi, 1),
                    "vol_ratio":v_ratio,
                    "pct_from_52wh": pct_h,
                    "return_1w_pct": ret_1w,
                }
            except Exception:
                return None

        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=8) as ex:
            results = list(ex.map(_check, tickers))

        matches = [r for r in results if r is not None]
        matches.sort(key=lambda x: x["vol_ratio"], reverse=True)
        matches = matches[:limit]

        result = {
            "universe":   universe,
            "filters_applied": {
                "rsi_min": rsi_min, "rsi_max": rsi_max,
                "vol_spike_min": vol_spike,
                "pct_from_52wh_max": pct_from_52wh,
                "return_1w_range": [min_return_1w, max_return_1w]
            },
            "match_count": len(matches),
            "results":     matches,
            "status": "SUCCESS"
        }
        _cache_set(cached_key, result, ttl=600)
        return result
    except Exception as e:
        logger.error(f"Custom Screener Error: {e}")
        return {"error": str(e)}


# Export tools list for Gemini
MARKET_TOOLS = [
    get_market_analysis, 
    get_macro_sentiment, 
    get_news_impact, 
    remember_trade, 
    recall_memories, 
    run_strategy_backtest, 
    prepare_mt5_trade_draft,
    execute_approved_mt5_trade, 
    get_mt5_account_summary, 
    get_market_opportunities,
    get_sector_rotation,
    calculate_risk_parameters,
    get_market_climate,
    calculate_custom_indicator,
    get_portfolio_analytics,
    get_working_memory,
    update_working_memory,
    calculate_math_expression,
    set_smart_alert,
    get_user_portfolio,
    get_onchain_flow,
    get_options_flow,
    analyze_trade_performance,
    get_social_sentiment,
    get_trading_tactics,
    # Phase 14 additions
    get_fear_greed_index,
    get_economic_calendar,
    get_liquidation_heatmap,
    scan_multi_timeframe,
    get_portfolio_correlation,
    generate_weekly_report,
    paper_trade,
    # Phase 15 additions
    get_funding_rates,
    suggest_portfolio_rebalance,
    get_iv_rank,
    get_etf_flows,
    run_custom_screener,
]
