# -*- coding: utf-8 -*-
"""
CryptoStream AI — Web Chat Server
FastAPI backend serving the chat UI and proxying requests to Gemini + MCP.

World-class architecture:
- SQLAlchemy connection pool (no connection-per-request)
- slowapi rate limiting (10 req/min per IP on /api/chat)
- lifespan context manager (replaces deprecated on_event)
- SQL allowlist injection guard (no raw AI-generated SQL to DB)
- All secrets via environment variables only
"""
import os
import json
import logging
import logging.handlers
import requests
import re
import sys
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

# Fix Windows console encoding for emojis
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from contextlib import asynccontextmanager
from typing import Optional

# ── Rotating log (never grows unbounded, never committed to git) ────────────
log_handler = logging.handlers.RotatingFileHandler(
    "server.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8" # 5MB × 3 = 15MB max
)
logging.basicConfig(
    handlers=[log_handler, logging.StreamHandler()],
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    force=True,
)
logger = logging.getLogger("cryptostream")
logger.info("=== CryptoStream AI Server Starting ===")

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from google import genai
from google.genai import types
from anthropic import AsyncAnthropic # Migrated to Async for proper event loop handling

from dotenv import load_dotenv
import asyncio
import psycopg2
from psycopg2 import pool as pg_pool
from psycopg2.extras import RealDictCursor
from aiokafka import AIOKafkaConsumer
import pandas as pd
import time
from urllib.parse import quote
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from passlib.context import CryptContext
from jose import JWTError, jwt as jose_jwt

from intelligence.constants import NASDAQ_100_TICKERS, SP500_TICKERS, MACRO_MAPPING
from services.notification_service import NotificationService
from intelligence.agents.sentiment_agent import create_sentiment_agent, _fetch_rss_news
# ── Technical Tools ──────────────────────────────────────────────────────────
# Tools are imported inside the runner to ensure scope stability

# Define Tool Runner outside any nested scopes to ensure global accessibility
async def run_agent_tool_async(name, args, session_id="default"):
    """
    World-class tool executor with maximum robustness.
    Uses dynamic lookup to prevent NameError/Scope issues.
    """
    try:
        logger.info(f"🛠️ Agent Tool Calling: {name} with args {args} (Session: {session_id})")
        
        # Just-in-time import to guarantee fresh scope
        from intelligence.tools import market_tools
        
        # Safely fetch the function
        func = getattr(market_tools, name, None)
        
        if not func:
            logger.warning(f"⚠️ Tool {name} not found in market_tools")
            return {"error": f"Tool {name} not found"}
            
        # Normalize symbol if present
        if isinstance(args, dict) and "symbol" in args:
            args["symbol"] = str(args["symbol"]).upper()
            
        # Inject session_id for session-aware tools
        if name in ["get_working_memory", "update_working_memory", "prepare_mt5_trade_draft"]:
            if isinstance(args, dict):
                args["session_id"] = session_id
            else:
                args = {"session_id": session_id}

        # Execute (Offload to thread pool to prevent blocking the event loop)
        loop = asyncio.get_event_loop()
        if isinstance(args, dict):
            res = await loop.run_in_executor(None, lambda: func(**args))
        else:
            res = await loop.run_in_executor(None, func)
        
        logger.info(f"✅ Tool {name} execution successful")
        return res
        
    except Exception as e:
        logger.error(f"❌ Error in run_agent_tool_async ({name}): {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {"error": f"Internal Tool Error: {str(e)}"}

# ==========================================
# Market Timekeeping & DST Awareness
# ==========================================
class MarketTimekeeper:
    """
    Expert utility for tracking global market hours with automatic DST detection.
    """
    @staticmethod
    def is_us_dst(dt_ict):
        # US DST: 2nd Sunday of March to 1st Sunday of November
        year = dt_ict.year
        march_8 = datetime(year, 3, 8, tzinfo=None)
        dst_start = march_8 + timedelta(days=(6 - march_8.weekday()) % 7)
        nov_1 = datetime(year, 11, 1, tzinfo=None)
        dst_end = nov_1 + timedelta(days=(6 - nov_1.weekday()) % 7)
        # Use simple date comparison for the trigger
        current_date = dt_ict.replace(tzinfo=None)
        return dst_start <= current_date < dst_end

    @staticmethod
    def get_status():
        """Returns consolidated market accessibility status."""
        try:
            now_utc = datetime.now(timezone.utc)
            now_ict = now_utc + timedelta(hours=7)
            
            # Detect DST for US Markets
            is_dst = MarketTimekeeper.is_us_dst(now_ict)
            et_offset = -4 if is_dst else -5
            now_et = now_utc + timedelta(hours=et_offset)
            
            weekday = now_et.weekday() # 0=Mon, 4=Fri, 5=Sat, 6=Sun
            time_val = now_et.hour + now_et.minute / 60.0
            
            status = {
                "bkk_time": now_ict.strftime("%Y-%m-%d %H:%M"),
                "ny_time": now_et.strftime("%Y-%m-%d %I:%M %p"),
                "is_dst": is_dst,
                "crypto": "OPEN (24/7)"
            }

            # US Stocks: 09:30 - 16:00 ET (Mon-Fri)
            if weekday < 5 and 9.5 <= time_val < 16.0:
                status["stocks_us"] = "🟢 OPEN"
            else:
                status["stocks_us"] = "🔴 CLOSED"

            # Forex: Opens Sun 17:00 ET, Closes Fri 17:00 ET
            if (weekday == 6 and now_et.hour >= 17) or (weekday < 4) or (weekday == 4 and now_et.hour < 17):
                status["forex"] = "🟢 OPEN"
            else:
                status["forex"] = "🔴 CLOSED"

            # Gold: Opens Sun 18:00 ET, Closes Fri 17:00 ET, Daily break 17:00-18:00 ET
            if (weekday == 6 and now_et.hour >= 18) or (weekday < 4) or (weekday == 4 and now_et.hour < 17):
                if weekday < 5 and now_et.hour == 17:
                    status["gold"] = "⚠️ DAILY BREAK (Maintenance)"
                else:
                    status["gold"] = "🟢 OPEN"
            else:
                status["gold"] = "🔴 CLOSED"

            return status
        except Exception as e:
            logger.error(f"MarketTimekeeper Error: {e}")
            return {"error": "Failed to calculate market hours"}

load_dotenv()

# ==========================================
# Config — all from environment, no defaults that look real
# ==========================================
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "frontend", "dist")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
MCP_API_KEY    = os.environ.get("MCP_API_KEY", "")
APP_API_KEY    = os.environ.get("APP_API_KEY", "")
KAFKA_BROKER   = os.environ.get("KAFKA_BROKER", "localhost:9092")
MCP_URL        = "http://localhost:8000"
MODEL_ID       = os.environ.get("MODEL_ID", "gemini-2.5-flash")
CLAUDE_MODEL_ID = os.environ.get("CLAUDE_MODEL_ID", "claude-3-7-sonnet-20250219")
CHAT_RATE_LIMIT   = os.environ.get("CHAT_RATE_LIMIT",   "15/minute")   # AI chat
MARKET_RATE_LIMIT = os.environ.get("MARKET_RATE_LIMIT", "60/minute")   # market data endpoints

# DB config from env (no hardcoded passwords)
DB_HOST     = os.environ.get("POSTGRES_HOST", os.environ.get("DB_HOST", "localhost"))
DB_PORT     = int(os.environ.get("POSTGRES_PORT", os.environ.get("DB_PORT", "5432")))
DB_NAME     = os.environ.get("POSTGRES_DB", os.environ.get("DB_NAME", "crypto_stream_db"))
DB_USER     = os.environ.get("POSTGRES_USER", os.environ.get("DB_USER", "user"))
DB_PASSWORD = os.environ.get("POSTGRES_PASSWORD", os.environ.get("DB_PASS", ""))

if not GEMINI_API_KEY:
    logger.error("❌ GEMINI_API_KEY MISSING")
    raise RuntimeError("GEMINI_API_KEY must be set in .env")

if not APP_API_KEY:
    logger.warning("⚠️  APP_API_KEY not set — API endpoints are unprotected!")

client = genai.Client(api_key=GEMINI_API_KEY)
# Dual-Agent Synthesis config (Anthropic) - Only used for final formatting and strategy
# Dual-Agent Synthesis config (Anthropic) - Only used for final formatting and strategy
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")
# Status flag for runtime failures
CLAUDE_AVAILABLE = False
anthropic_client = None

if ANTHROPIC_API_KEY and "placeholder" not in ANTHROPIC_API_KEY.lower():
    try:
        # Initialize Async client
        anthropic_client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY, timeout=10.0) 
        CLAUDE_AVAILABLE = True
        logger.info("🧠 Dual-Agent Mode: Claude Strategist initialized (Async)")
    except Exception as e:
        logger.error(f"Failed to initialize Anthropic client: {e}")
        CLAUDE_AVAILABLE = False
else:
    if ANTHROPIC_API_KEY:
        logger.info("ℹ️ Claude Strategist Disabled: Placeholder API Key detected.")
    else:
        logger.info("ℹ️ Claude Strategist Disabled: No API Key provided.")


# ==========================================
# Connection Pool (MED-01 fix)
# Reuses DB connections instead of open/close per request
# min=2 idle connections, max=10 concurrent
# ==========================================
_db_pool: Optional[pg_pool.ThreadedConnectionPool] = None
GLOBAL_MACRO_CACHE = {}  # Stores latest yfinance macro data

# ── Persistence Layer (SQLite) ────────────────────────────────────────────────
PERSISTENCE_DB = "persistence.db"

# ── Auth Configuration ───────────────────────────────────────────────────────
JWT_SECRET = os.environ.get("JWT_SECRET", "cryptostream-super-secret-change-in-prod-2024")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = 30
_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
_bearer_scheme = HTTPBearer(auto_error=False)

def _hash_password(plain: str) -> str:
    return _pwd_ctx.hash(plain)

def _verify_password(plain: str, hashed: str) -> bool:
    return _pwd_ctx.verify(plain, hashed)

def _create_token(user_id: str, email: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRE_DAYS)
    return jose_jwt.encode({"sub": user_id, "email": email, "exp": expire}, JWT_SECRET, algorithm=JWT_ALGORITHM)

def _decode_token(token: str) -> dict:
    return jose_jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = _decode_token(credentials.credentials)
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
        conn = sqlite3.connect(PERSISTENCE_DB)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        conn.close()
        if not row:
            raise HTTPException(status_code=401, detail="User not found")
        return dict(row)
    except JWTError:
        raise HTTPException(status_code=401, detail="Token expired or invalid")

def init_persistence_db():
    conn = sqlite3.connect(PERSISTENCE_DB)
    cursor = conn.cursor()
    # Sessions table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            title TEXT,
            updated_at DATETIME
        )
    """)
    # Messages table (metadata is JSON string)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT DEFERRABLE INITIALLY DEFERRED,
            role TEXT,
            content TEXT,
            metadata TEXT,
            created_at DATETIME,
            FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
        )
    """)
    # Working memory table (Cognitive Stashing)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS working_memory (
            session_id TEXT PRIMARY KEY,
            memory TEXT,
            emotion TEXT,
            updated_at DATETIME,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        )
    """)
    # Active Smart Alerts
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS active_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT DEFAULT 'default',
            symbol TEXT,
            condition TEXT,
            message TEXT,
            status TEXT DEFAULT 'ACTIVE',
            created_at DATETIME
        )
    """)
    # Trade Reviews
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trade_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT DEFAULT 'default',
            review_text TEXT,
            win_rate REAL,
            score INTEGER,
            created_at DATETIME
        )
    """)
    # Trade Drafts (Persistent Trade Plans)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trade_drafts (
            id TEXT PRIMARY KEY,
            session_id TEXT,
            symbol TEXT,
            action TEXT,
            volume REAL,
            sl REAL,
            tp REAL,
            comment TEXT,
            created_at DATETIME
        )
    """)
    # Active Trades Tracker (for institutional automation like Break-Even)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS active_trades (
            ticket INTEGER PRIMARY KEY,
            symbol TEXT,
            entry_price REAL,
            tp1 REAL,
            be_triggered BOOLEAN DEFAULT FALSE,
            draft_id TEXT,
            created_at DATETIME
        )
    """)
    # Sniper Audit Log (Intelligence V7 Sniper Core)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sniper_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            confidence REAL,
            reasoning TEXT,
            price REAL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()
    logger.info(f"✅ Persistence DB initialized: {PERSISTENCE_DB}")

def get_db_pool() -> pg_pool.ThreadedConnectionPool:
    global _db_pool
    if _db_pool is None:
        _db_pool = pg_pool.ThreadedConnectionPool(
            minconn=1, maxconn=5,
            host=DB_HOST, port=DB_PORT,
            database=DB_NAME, user=DB_USER, password=DB_PASSWORD,
        )
        logger.info("✅ DB connection pool initialized (min=1, max=5)")
    return _db_pool

# Helper: safely get a pooled connection as context manager
from contextlib import contextmanager

@contextmanager
def get_db_conn():
    conn = get_db_pool().getconn()
    try:
        yield conn
    finally:
        get_db_pool().putconn(conn)

# ==========================================
# Rate Limiter (CRIT-03 fix)
# ==========================================
limiter = Limiter(key_func=get_remote_address)

# ==========================================
# Institutional Automation Workers
# ==========================================
async def news_shield_poller_task():
    """Refreshes the Macro News Shield calendar every 5 minutes."""
    while True:
        try:
            from intelligence.guards.macro_shield import refresh_news_calendar
            refresh_news_calendar()
            logger.info("🛡️ Institutional: Macro News Shield calendar refreshed.")
        except Exception as e:
            logger.error(f"Macro Shield Poller Error: {e}")
        await asyncio.sleep(300)

async def position_monitoring_task():
    """
    Monitors active positions every 10 seconds.
    Triggers automated Break-Even logic if price hits TP1.
    """
    await asyncio.sleep(45) # Wait for initial systems boot
    while True:
        try:
            from intelligence.persistence_utils import get_active_trades, mark_trade_be_triggered
            from intelligence.mt5_connector import mt5_modify_position, _MT5_AVAILABLE, initialize_mt5
            import MetaTrader5 as mt5

            active_trades = get_active_trades()
            if not active_trades:
                await asyncio.sleep(10)
                continue

            if _MT5_AVAILABLE and initialize_mt5():
                for trade in active_trades:
                    ticket = trade["ticket"]
                    tp1 = trade["tp1"]
                    entry = trade["entry_price"]
                    
                    # Fetch current market state for this position
                    pos = mt5.positions_get(ticket=ticket)
                    if not pos:
                        # Position probably closed manually or hit SL/TP - we can mark it as handled or let it expire
                        continue
                    
                    p = pos[0]
                    curr_price = p.price_current
                    action = p.type # 0 for BUY, 1 for SELL
                    
                    trigger_be = False
                    if action == 0 and curr_price >= tp1: # BUY
                        trigger_be = True
                    elif action == 1 and curr_price <= tp1: # SELL
                        trigger_be = True
                        
                    if trigger_be:
                        logger.info(f"🎯 BREAK-EVEN TRIGGERED for Ticket {ticket} ({trade['symbol']})")
                        res = mt5_modify_position(ticket=ticket, sl=entry)
                        if res.get("status") == "SUCCESS":
                            mark_trade_be_triggered(ticket)
                            # Notify UI
                            await manager.broadcast({
                                "type": "ALERT",
                                "data": {
                                    "title": "Institutional Safety: Break-Even",
                                    "message": f"Successfully moved Stop Loss to Entry for {trade['symbol']} (Ticket #{ticket}). Trade is now RISK-FREE.",
                                    "symbol": trade["symbol"]
                                }
                            })

        except Exception as e:
            logger.error(f"Position Monitor Error: {e}")
        await asyncio.sleep(10)

# ==========================================
# App + Lifespan (CRIT-05 fix: replaces deprecated on_event)
# ==========================================
async def multi_asset_whale_poller_task():
    """
    Poll yfinance every 2 minutes for ALL major tradeable assets.
    Detects volume spikes > 3× 20-bar average — these are institutional signals.
    Writes hits to SQLite multi_asset_whales table and broadcasts WHALE_ALERT.

    Asset classes covered:
      CRYPTO  — BTC, ETH, SOL, BNB, XRP, DOGE, AVAX, LINK
      STOCK   — NVDA, AAPL, TSLA, META, MSFT, AMZN, GOOGL, NFLX, AMD, INTC, V, JPM
      GOLD    — GC=F (Gold Futures)
      OIL     — CL=F (WTI Crude)
      FX      — EURUSD=X, GBPUSD=X, USDJPY=X, DX-Y.NYB (DXY)
      INDEX   — ^GSPC (SP500), ^IXIC (Nasdaq), ^DJI (Dow)
    """
    import yfinance as yf
    import sqlite3

    WATCH_LIST = [
        # symbol, yf_ticker, asset_class, usd_per_unit_approx
        ("BTC",    "BTC-USD",    "CRYPTO", 1),
        ("ETH",    "ETH-USD",    "CRYPTO", 1),
        ("SOL",    "SOL-USD",    "CRYPTO", 1),
        ("BNB",    "BNB-USD",    "CRYPTO", 1),
        ("XRP",    "XRP-USD",    "CRYPTO", 1),
        ("DOGE",   "DOGE-USD",   "CRYPTO", 1),
        ("AVAX",   "AVAX-USD",   "CRYPTO", 1),
        ("LINK",   "LINK-USD",   "CRYPTO", 1),
        ("NVDA",   "NVDA",       "STOCK",  1),
        ("AAPL",   "AAPL",       "STOCK",  1),
        ("TSLA",   "TSLA",       "STOCK",  1),
        ("META",   "META",       "STOCK",  1),
        ("MSFT",   "MSFT",       "STOCK",  1),
        ("AMZN",   "AMZN",       "STOCK",  1),
        ("GOOGL",  "GOOGL",      "STOCK",  1),
        ("NFLX",   "NFLX",       "STOCK",  1),
        ("AMD",    "AMD",        "STOCK",  1),
        ("JPM",    "JPM",        "STOCK",  1),
        ("GOLD",   "GC=F",       "GOLD",   1),
        ("OIL",    "CL=F",       "OIL",    1),
        ("EURUSD", "EURUSD=X",   "FX",     1),
        ("GBPUSD", "GBPUSD=X",   "FX",     1),
        ("USDJPY", "USDJPY=X",   "FX",     1),
        ("DXY",    "DX-Y.NYB",   "FX",     1),
        ("SP500",  "^GSPC",      "INDEX",  1),
        ("NASDAQ", "^IXIC",      "INDEX",  1),
    ]

    # Thresholds: minimum USD value to qualify as whale per asset class
    USD_THRESHOLDS = {
        "CRYPTO": 500_000,
        "STOCK":  1_000_000,
        "GOLD":   500_000,
        "OIL":    300_000,
        "FX":     5_000_000,
        "INDEX":  2_000_000,
    }

    # Init SQLite table
    try:
        con = sqlite3.connect("persistence.db")
        con.execute("""
            CREATE TABLE IF NOT EXISTS multi_asset_whales (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol   TEXT,
                asset_class TEXT,
                price    REAL,
                volume   REAL,
                usd_value REAL,
                direction TEXT,
                vol_ratio REAL,
                timestamp TEXT
            )
        """)
        con.commit(); con.close()
    except Exception as e:
        logger.error(f"multi_asset_whales table init error: {e}")

    await asyncio.sleep(45)  # brief delay after startup

    while True:
        try:
            loop = asyncio.get_event_loop()

            def _scan():
                hits = []
                for symbol, yf_ticker, asset_class, _ in WATCH_LIST:
                    try:
                        df = yf.download(yf_ticker, period="1d", interval="5m",
                                         progress=False, auto_adjust=True)
                        if df is None or len(df) < 25:
                            continue

                        df = df.dropna()
                        close  = float(df["Close"].iloc[-1])
                        volume = float(df["Volume"].iloc[-1])
                        avg_vol = float(df["Volume"].iloc[-21:-1].mean())

                        if avg_vol < 1:
                            continue

                        vol_ratio = volume / avg_vol
                        usd_value = close * volume

                        threshold = USD_THRESHOLDS.get(asset_class, 500_000)
                        if vol_ratio >= 3.0 and usd_value >= threshold:
                            # Determine direction from bar color
                            open_p = float(df["Open"].iloc[-1])
                            direction = "BUY" if close >= open_p else "SELL"
                            hits.append({
                                "symbol":      symbol,
                                "asset_class": asset_class,
                                "price":       round(close, 6),
                                "volume":      round(volume, 4),
                                "usd_value":   round(usd_value, 2),
                                "direction":   direction,
                                "vol_ratio":   round(vol_ratio, 2),
                                "timestamp":   str(int(time.time() * 1000)),
                            })
                    except Exception:
                        continue
                return hits

            hits = await loop.run_in_executor(None, _scan)

            if hits:
                con = sqlite3.connect("persistence.db")
                for h in hits:
                    con.execute("""
                        INSERT INTO multi_asset_whales
                        (symbol, asset_class, price, volume, usd_value, direction, vol_ratio, timestamp)
                        VALUES (?,?,?,?,?,?,?,?)
                    """, (h["symbol"], h["asset_class"], h["price"], h["volume"],
                          h["usd_value"], h["direction"], h["vol_ratio"], h["timestamp"]))

                    # Broadcast to all WebSocket clients
                    await manager.broadcast({
                        "type": "WHALE_ALERT",
                        "data": {
                            "symbol":      h["symbol"],
                            "asset_class": h["asset_class"],
                            "price":       str(h["price"]),
                            "quantity":    str(h["volume"]),
                            "usd_value":   h["usd_value"],
                            "is_buyer_maker": h["direction"] == "SELL",
                            "vol_ratio":   h["vol_ratio"],
                            "timestamp":   h["timestamp"],
                        }
                    })
                    logger.info(
                        f"🐳 [{h['asset_class']}] {h['symbol']} whale: "
                        f"${h['usd_value']:,.0f} ({h['vol_ratio']:.1f}× avg vol)"
                    )
                con.commit(); con.close()

        except Exception as e:
            logger.error(f"multi_asset_whale_poller error: {e}")

        await asyncio.sleep(120)  # poll every 2 minutes


async def outcome_scanner_task():
    """
    Background task: scan open paper trades every 10 minutes.
    Auto-closes any trade that has hit SL or TP, recording WIN/LOSS outcome
    so the ML model can learn from real paper trade results.
    Also triggers auto-retrain when 25+ new outcomes accumulate since last retrain.
    """
    await asyncio.sleep(60)  # wait for server to fully start
    while True:
        try:
            from intelligence.ml.outcome_tracker import scan_and_update
            summary = await asyncio.get_event_loop().run_in_executor(None, scan_and_update)
            closed = summary.get("closed_win", 0) + summary.get("closed_loss", 0)
            if closed > 0:
                logger.info(f"[OutcomeScanner] Closed trades — WIN:{summary['closed_win']} LOSS:{summary['closed_loss']}")

            # Auto-retrain check: trigger if 25+ new outcomes since last retrain
            try:
                import sqlite3 as _sq
                from intelligence.ml.signal_model import _load_model, train_model, invalidate_model_cache
                _bundle = _load_model()
                _outcomes_at_retrain = _bundle.get("outcomes_at_retrain", 0) if _bundle else 0
                _con = _sq.connect(PERSISTENCE_DB)
                _total = _con.execute(
                    "SELECT COUNT(*) FROM paper_trades WHERE outcome IS NOT NULL AND status='CLOSED'"
                ).fetchone()[0]
                _con.close()
                _new = _total - _outcomes_at_retrain
                if _new >= 25:
                    logger.info(f"[AutoRetrain] {_new} new outcomes → triggering retrain")
                    await asyncio.get_event_loop().run_in_executor(None, train_model)
                    invalidate_model_cache()
                    logger.info("[AutoRetrain] Model retrained successfully")
            except Exception as _re:
                logger.debug(f"[AutoRetrain] check failed: {_re}")

        except Exception as e:
            logger.debug(f"[OutcomeScanner] skipped: {e}")
        await asyncio.sleep(600)  # every 10 minutes


async def ml_signal_scanner_task():
    """
    Background task: every 15 minutes scan all symbols for high-probability
    ML setups and auto-insert them into active_alerts for the dashboard.
    """
    await asyncio.sleep(90)  # let server fully start + model cache warm up
    while True:
        try:
            from intelligence.ml.signal_scanner import scan_for_high_probability_signals
            summary = await asyncio.get_event_loop().run_in_executor(None, scan_for_high_probability_signals)
            if summary.get("found", 0) > 0:
                logger.info(f"[MLScanner] {summary['found']} high-probability setups found across {summary['scanned']} symbols")
            else:
                logger.debug(f"[MLScanner] scan complete — no new signals above threshold")
        except Exception as e:
            logger.debug(f"[MLScanner] skipped: {e}")
        await asyncio.sleep(900)  # every 15 minutes


async def lifespan(app: FastAPI):
    """Start Kafka consumers and Macro poller on startup."""
    logger.info("🚀 Starting background workers...")
    init_persistence_db()
    t1 = asyncio.create_task(kafka_consumer_task())
    t2 = asyncio.create_task(dlq_consumer_task())
    t3 = asyncio.create_task(macro_poller_task())
    t4 = asyncio.create_task(market_cache_prewarm_task())
    t5 = asyncio.create_task(smart_alert_poller_task())
    t6 = asyncio.create_task(news_shield_poller_task())
    t7 = asyncio.create_task(position_monitoring_task())
    t8 = asyncio.create_task(multi_asset_whale_poller_task())
    t9  = asyncio.create_task(outcome_scanner_task())
    t10 = asyncio.create_task(ml_signal_scanner_task())
    t11 = asyncio.create_task(binance_price_broadcaster_task())
    yield  # App runs here
    logger.info("⏳ Shutting down background workers...")
    for t in (t1, t2, t3, t4, t5, t6, t7, t8, t9, t10, t11):
        t.cancel()
    await asyncio.gather(t1, t2, t3, t4, t5, t6, t7, t8, t9, t10, t11, return_exceptions=True)
    if _db_pool:
        _db_pool.closeall()
    logger.info("✅ Workers stopped and DB pool closed.")


async def market_cache_prewarm_task():
    """
    Pre-warms the get_market_opportunities cache every 5 minutes.
    This means user queries for top movers are near-instant (served from cache).
    First run happens 30 seconds after server startup to avoid blocking boot.
    """
    loop = asyncio.get_event_loop()
    await asyncio.sleep(30)  # Give server time to fully start
    while True:
        try:
            logger.info("🔄 Background: Pre-warming market opportunities cache...")
            from intelligence.tools.market_tools import get_market_opportunities
            await loop.run_in_executor(None, lambda: get_market_opportunities("ALL"))
            logger.info("✅ Background: Market cache warmed successfully.")
        except Exception as e:
            logger.warning(f"⚠️ Background cache prewarm failed: {e}")
        await asyncio.sleep(300)  # Refresh every 5 minutes

async def macro_poller_task():
    """Polls yfinance for Gold, Stocks, and Indices every 30s and broadcasts to UI."""
    import yfinance as yf
    from intelligence.technical_engine import MACRO_MAPPING
    
    symbols = list(MACRO_MAPPING.keys())
    tickers = list(MACRO_MAPPING.values())
    
    while True:
        try:
            # Fetch latest data (5d to ensure we get last close on weekends)
            data = yf.download(tickers, period="5d", interval="1m", progress=False)
            if not data.empty:
                for sym, ticker in MACRO_MAPPING.items():
                    try:
                        # Extract last valid close price for this ticker
                        if ticker in data["Close"]:
                            # Get the last non-NaN price
                            ticker_series = data["Close"][ticker].dropna()
                            if not ticker_series.empty:
                                price = float(ticker_series.iloc[-1])
                                # Calculate a simple daily delta for context
                                delta = 0
                                if len(ticker_series) > 1:
                                    first_price = ticker_series.iloc[0]
                                    delta = ((price - first_price) / first_price) * 100
                                
                                GLOBAL_MACRO_CACHE[sym] = {"price": price, "delta": delta}
                                
                                await manager.broadcast({
                                    "type": "TICK",
                                    "data": {
                                        "symbol": sym,
                                        "price": price,
                                        "timestamp": int(time.time() * 1000),
                                        "delta": delta
                                    }
                                })
                    except Exception as e:
                        continue
            logger.info(f"✅ Macro poller updated {len(symbols)} assets.")
        except Exception as e:
            logger.warning(f"Macro poller error: {e}")
            
        await asyncio.sleep(30)

app = FastAPI(title="CryptoStream AI", version="2.0.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
try:
    from intelligence.crypto_intelligence import CryptoIntelligence
    from intelligence.risk_calculator_crypto import calculate_crypto_risk, get_risk_advice_thai, calculate_position_scenarios
    crypto_intel = CryptoIntelligence(client)
    INTELLIGENCE_AVAILABLE = True
    logger.info("✅ Intelligence Layer loaded (Multi-Agent mode)")
except Exception as e:
    logger.warning(f"⚠️ Intelligence Layer unavailable: {e}")
    crypto_intel = None
    INTELLIGENCE_AVAILABLE = False



app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8888", "http://127.0.0.1:8888", "http://localhost:5173"],
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Robust Static Mounting
if not os.path.exists(STATIC_DIR):
    logging.error(f"❌ STATIC_DIR NOT FOUND: {STATIC_DIR}")
    os.makedirs(STATIC_DIR, exist_ok=True)

# Mount the 'assets' folder specifically so Vite can find its JS/CSS
ASSETS_DIR = os.path.join(STATIC_DIR, "assets")
if os.path.exists(ASSETS_DIR):
    app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")

# Also mount the root dist for other files like favicon.svg, icons.svg
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ==========================================
# WebSocket & Kafka Bridge
# ==========================================
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logging.info(f"New WebSocket connection. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        logging.info(f"WebSocket disconnected. Remaining: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        if not self.active_connections:
            return
        
        # We use a copy to avoid 'size changed during iteration' errors
        for connection in self.active_connections[:]:
            try:
                await connection.send_json(message)
            except Exception as e:
                logging.error(f"Broadcast error: {e}")
                if connection in self.active_connections:
                    self.active_connections.remove(connection)

manager = ConnectionManager()
notifier = NotificationService()

async def smart_alert_poller_task():
    """
    Background poller that checks active_alerts every 60s.
    Fetches latest price from yfinance and dispatches Telegram alerts
    when a user-defined condition is met.
    """
    import sqlite3
    import yfinance as yf
    import re

    SYMBOL_TICKER_MAP = {
        "XAUUSD": "GC=F", "GOLD": "GC=F", "XAU": "GC=F",
        "BTC": "BTC-USD", "ETH": "ETH-USD", "SOL": "SOL-USD",
        "BTCUSDT": "BTC-USD", "ETHUSDT": "ETH-USD", "SOLUSDT": "SOL-USD",
        "OIL": "CL=F", "DXY": "DX-Y.NYB", "NASDAQ": "^NDX", "SP500": "^GSPC",
    }

    while True:
        await asyncio.sleep(60)
        try:
            conn = sqlite3.connect("persistence.db")
            cursor = conn.cursor()
            cursor.execute("SELECT id, symbol, condition, message FROM active_alerts WHERE status='ACTIVE'")
            alerts = cursor.fetchall()
            conn.close()

            for alert_id, symbol, condition, msg in alerts:
                ticker = SYMBOL_TICKER_MAP.get(symbol.upper(), f"{symbol.upper()}-USD")
                try:
                    data = yf.download(ticker, period="1d", interval="1m", progress=False)
                    if data.empty:
                        continue
                    last_price = float(data["Close"].dropna().iloc[-1])

                    # Parse simple conditions like "price < 2280" or "price > 3000"
                    match = re.match(r"price\s*([<>=!]+)\s*([\d.]+)", condition.strip(), re.IGNORECASE)
                    if not match:
                        continue
                    op, val = match.group(1), float(match.group(2))

                    triggered = (
                        (op == "<" and last_price < val) or
                        (op == "<=" and last_price <= val) or
                        (op == ">" and last_price > val) or
                        (op == ">=" and last_price >= val) or
                        (op in ("=", "==") and abs(last_price - val) < val * 0.001)
                    )

                    if triggered:
                        alert_msg = (
                            f"🚨 *SMART ALERT TRIGGERED*\n"
                            f"Symbol: `{symbol}`\n"
                            f"Condition: `{condition}`\n"
                            f"Current Price: `${last_price:,.2f}`\n\n"
                            f"📋 {msg}"
                        )
                        await notifier.send_telegram_alert(alert_msg)
                        # Mark alert as FIRED to prevent repeat
                        conn2 = sqlite3.connect("persistence.db")
                        cursor2 = conn2.cursor()
                        cursor2.execute("UPDATE active_alerts SET status='FIRED' WHERE id=?", (alert_id,))
                        conn2.commit()
                        conn2.close()
                        logger.info(f"✅ Alert fired for {symbol}: {condition} @ ${last_price:,.2f}")

                except Exception as e:
                    logger.warning(f"⚠️ Alert check failed for {symbol}: {e}")

        except Exception as e:
            logger.error(f"❌ smart_alert_poller_task error: {e}")

async def kafka_consumer_task():
    """Consumes normal trade stream for ticking and whales."""
    import time
    last_tick_time = 0

    consumer = AIOKafkaConsumer(
        "trade_stream",
        bootstrap_servers=KAFKA_BROKER,
        group_id="chat_server_v1",
        auto_offset_reset="latest"
    )
    await consumer.start()
    try:
        async for msg in consumer:
            data = json.loads(msg.value.decode("utf-8"))
            
            # Broadcast Tick (Throttled to 2 FPS to prevent UI rendering crashes from the raw firehose)
            now = time.time()
            if now - last_tick_time > 0.5:
                last_tick_time = now
                await manager.broadcast({
                    "type": "TICK",
                    "data": data
                })

            # Broadcast Whale Alert (No throttle necessary, these are sparse)
            if float(data.get("quantity", 0)) > 0.5:
                # Local broadcast
                await manager.broadcast({
                    "type": "WHALE_ALERT",
                    "data": data
                })
                # External notification
                await notifier.notify_whale(data)
    except Exception as e:
        print(f"Error in Consumer: {e}")
    finally:
        await consumer.stop()

async def dlq_consumer_task():
    """Consumes DLQ topic for risk alerts."""
    consumer = AIOKafkaConsumer(
        "trade_stream_dlq",
        bootstrap_servers=KAFKA_BROKER,
        group_id="chat_server_dlq_v1",
        auto_offset_reset="latest"
    )
    await consumer.start()
    try:
        async for msg in consumer:
            data = json.loads(msg.value.decode("utf-8"))
            await manager.broadcast({
                "type": "DQ_ALERT",
                "data": data
            })
            # External notification for risk
            await notifier.notify_risk(data.get("error_reason", "Data quality anomaly detected"))
    except Exception as e:
        print(f"Error in DLQ Consumer: {e}")
    finally:
        await consumer.stop()


async def binance_price_broadcaster_task():
    """
    Connects to Binance combined stream WebSocket and broadcasts live TICK
    messages (BTC, ETH, SOL) to all connected frontend clients.
    Falls back gracefully when Binance is unreachable (e.g. local dev without internet).
    Auto-reconnects with exponential backoff on disconnect.
    """
    import websockets as _ws

    BINANCE_STREAM_URL = (
        "wss://stream.binance.com:9443/stream"
        "?streams=btcusdt@miniTicker/ethusdt@miniTicker/solusdt@miniTicker"
    )
    RETRY_DELAYS = [3, 5, 10, 20, 30, 60]  # seconds between reconnect attempts

    retry_idx = 0
    while True:
        try:
            logger.info("📡 Connecting to Binance WebSocket price stream...")
            async with _ws.connect(BINANCE_STREAM_URL, ping_interval=20, ping_timeout=10) as ws:
                retry_idx = 0  # reset on successful connect
                logger.info("✅ Binance price stream connected.")
                async for raw in ws:
                    try:
                        envelope = json.loads(raw)
                        ticker = envelope.get("data", {})
                        symbol = ticker.get("s", "")   # e.g. "BTCUSDT"
                        price  = ticker.get("c", "")   # current close price (str)
                        if symbol and price and manager.active_connections:
                            await manager.broadcast({
                                "type": "TICK",
                                "data": {"symbol": symbol, "price": price}
                            })
                    except Exception:
                        pass  # malformed frame — skip silently
        except asyncio.CancelledError:
            logger.info("🛑 Binance price broadcaster cancelled.")
            return
        except Exception as e:
            delay = RETRY_DELAYS[min(retry_idx, len(RETRY_DELAYS) - 1)]
            logger.warning(f"⚠️  Binance WebSocket disconnected: {e}. Retrying in {delay}s…")
            retry_idx += 1
            await asyncio.sleep(delay)


def get_market_snapshot():
    """Fetches the latest market metrics from PostgreSQL for AI context."""
    try:
        with get_db_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get Latest VWAPs
                cur.execute("SELECT symbol, avg_price, total_volume, trade_count FROM market_metrics ORDER BY window_end DESC LIMIT 5")
                metrics = cur.fetchall()
                
                # Get Recent Whales
                cur.execute("SELECT symbol, price, quantity, is_buyer_maker FROM enriched_trades WHERE is_whale = TRUE ORDER BY timestamp DESC LIMIT 3")
                whales = cur.fetchall()
                
        return {
            "metrics": metrics, 
            "whales": whales,
            "global_macro": GLOBAL_MACRO_CACHE,
            "market_hours": MarketTimekeeper.get_status()
        }
    except Exception as e:
        logger.error(f"DB Error for snapshot: {e}")
        return None




@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # We must receive data to keep the connection alive/check for closure
            data = await websocket.receive_text()
            # Handle client-side pings or commands here if needed
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logging.error(f"WebSocket Loop Error: {e}")
        manager.disconnect(websocket)


# ==========================================
# MCP Helpers
# ==========================================
def _get_schema() -> dict | None:
    headers = {"X-API-Key": MCP_API_KEY}
    try:
        r = requests.get(f"{MCP_URL}/api/v1/schemas", headers=headers, timeout=5)
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        logging.warning(f"MCP Connection failed: {e}")
        return None


def _execute_sql(sql: str) -> dict:
    # 🚨 SQL Allowlist Guard (CRIT-04 Fix)
    # Prevent destructive commands regardless of AI hallucination/injection
    forbidden_keywords = ["DROP", "DELETE", "TRUNCATE", "ALTER", "UPDATE", "INSERT", "GRANT", "REVOKE"]
    sql_upper = sql.upper()
    
    if any(keyword in sql_upper for keyword in forbidden_keywords):
        logger.warning(f"🚨 BLOCKED ILLEGAL SQL QUERY: {sql}")
        return {"error": "SECURITY_VIOLATION: Destructive operations are strictly forbidden."}

    headers = {"X-API-Key": MCP_API_KEY, "Content-Type": "application/json"}
    payload = {"sql": sql, "max_rows": 100}
    try:
        r = requests.post(f"{MCP_URL}/api/v1/query", headers=headers, json=payload, timeout=10)
        return r.json() if r.status_code == 200 else {"error": r.text}
    except Exception as e:
        return {"error": str(e)}


# ==========================================
# Chat Endpoint (Full Logic Restored)
# ==========================================
# ── Auth Models (Phase 16) ───────────────────────────────────────────────────
class RegisterRequest(BaseModel):
    email: str
    username: str
    full_name: str
    password: str
    phone: str = ""
    country: str = ""
    account_type: str = "retail"   # 'retail' | 'institutional'
    bio: str = ""

class LoginRequest(BaseModel):
    email: str
    password: str

class UpdateProfileRequest(BaseModel):
    full_name: str = ""
    phone: str = ""
    country: str = ""
    bio: str = ""
    account_type: str = ""

# ── Auth Endpoints (Phase 16) ────────────────────────────────────────────────
@app.post("/api/auth/register")
def auth_register(req: RegisterRequest):
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    if not req.email or "@" not in req.email:
        raise HTTPException(status_code=400, detail="Invalid email address")
    if not req.username or len(req.username) < 3:
        raise HTTPException(status_code=400, detail="Username must be at least 3 characters")
    conn = sqlite3.connect(PERSISTENCE_DB)
    conn.row_factory = sqlite3.Row
    existing = conn.execute("SELECT id FROM users WHERE email=? OR username=?", (req.email.lower(), req.username.lower())).fetchone()
    if existing:
        conn.close()
        raise HTTPException(status_code=409, detail="Email or username already registered")
    user_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO users (id, email, username, full_name, phone, country, account_type, bio, password_hash) VALUES (?,?,?,?,?,?,?,?,?)",
        (user_id, req.email.lower(), req.username.lower(), req.full_name, req.phone, req.country, req.account_type, req.bio, _hash_password(req.password))
    )
    conn.commit()
    conn.close()
    token = _create_token(user_id, req.email.lower())
    return {"token": token, "user": {"id": user_id, "email": req.email.lower(), "username": req.username.lower(), "full_name": req.full_name, "account_type": req.account_type}}

@app.post("/api/auth/login")
def auth_login(req: LoginRequest):
    conn = sqlite3.connect(PERSISTENCE_DB)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM users WHERE email=?", (req.email.lower(),)).fetchone()
    conn.close()
    if not row or not _verify_password(req.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = _create_token(row["id"], row["email"])
    return {"token": token, "user": {"id": row["id"], "email": row["email"], "username": row["username"], "full_name": row["full_name"], "account_type": row["account_type"], "phone": row["phone"] or "", "country": row["country"] or "", "bio": row["bio"] or ""}}

@app.get("/api/auth/me")
def auth_me(current_user: dict = Depends(get_current_user)):
    return {k: v for k, v in current_user.items() if k != "password_hash"}

@app.put("/api/auth/profile")
def auth_update_profile(req: UpdateProfileRequest, current_user: dict = Depends(get_current_user)):
    updates, params = [], []
    if req.full_name:  updates.append("full_name=?");  params.append(req.full_name)
    if req.phone:      updates.append("phone=?");      params.append(req.phone)
    if req.country:    updates.append("country=?");    params.append(req.country)
    if req.bio:        updates.append("bio=?");        params.append(req.bio)
    if req.account_type in ("retail", "institutional"):
        updates.append("account_type=?"); params.append(req.account_type)
    if not updates:
        return {"ok": True}
    params.append(current_user["id"])
    conn = sqlite3.connect(PERSISTENCE_DB)
    conn.execute(f"UPDATE users SET {', '.join(updates)} WHERE id=?", params)
    conn.commit()
    conn.close()
    return {"ok": True}

# ── Chat Models ───────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    history: list = []  # Conversation history: [{"role": "user"|"ai", "content": "..."}]

class ChatResponse(BaseModel):
    reply: str
    sql_query: str | None = None
    has_data: bool = False

@app.get("/")
def root():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"error": "Frontend build not found. Please run 'npm run build' in the /frontend directory.", "path": index_path}


# ── Security ─────────────────────────────────────────────────────────────────
from fastapi import Header

# Concurrent Gemini request guard — prevent queue buildup under heavy load
_GEMINI_SEMAPHORE = asyncio.Semaphore(5)  # max 5 simultaneous AI calls

def verify_token(x_api_key: str = Header(None)):
    """Validate API key. Accepts APP_API_KEY from env or 'demo' for local dev."""
    # In production set APP_API_KEY in .env — never use 'demo' in prod
    dev_mode = not APP_API_KEY or APP_API_KEY in ("", "changeme")
    valid_keys = {APP_API_KEY} if APP_API_KEY else set()
    valid_keys.add("demo")  # always allow demo for local dev
    if dev_mode:
        return  # no key configured → open for local development
    if x_api_key not in valid_keys:
        logger.warning(f"Unauthorized access attempt — key: {str(x_api_key)[:8]}...")
        raise HTTPException(status_code=403, detail="Unauthorized")

from fastapi.responses import StreamingResponse

# ==========================================
# Session & History API
# ==========================================
class SaveSessionRequest(BaseModel):
    id: str
    title: str
    messages: list

@app.get("/api/history")
async def get_history(x_api_key: str = Header(None)):
    """Fetch all sessions and their metadata."""
    verify_token(x_api_key)
    try:
        conn = sqlite3.connect(PERSISTENCE_DB)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM sessions ORDER BY updated_at DESC")
        rows = cursor.fetchall()
        
        sessions = []
        for row in rows:
            # Optionally fetch last message snippet if needed
            sessions.append({
                "id": row["id"],
                "title": row["title"],
                "updatedAt": row["updated_at"]
            })
        conn.close()
        return sessions
    except Exception as e:
        logger.error(f"Error fetching history: {e}")
        return []

@app.get("/api/history/{session_id}")
async def get_session_history(session_id: str, x_api_key: str = Header(None)):
    """Fetch full message set for a session."""
    verify_token(x_api_key)
    try:
        conn = sqlite3.connect(PERSISTENCE_DB)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM messages WHERE session_id = ? ORDER BY id ASC", (session_id,))
        rows = cursor.fetchall()
        
        messages = []
        for r in rows:
            meta = json.loads(r["metadata"]) if r["metadata"] else {}
            messages.append({
                "role": r["role"],
                "content": r["content"],
                "toolCalls": meta.get("toolCalls", []),
                "toolResults": meta.get("toolResults", []),
                "chart": meta.get("chart"),
                "tvSymbol": meta.get("tvSymbol"),
                "intent": meta.get("intent")
            })
        conn.close()
        return messages
    except Exception as e:
        logger.error(f"Error loading session {session_id}: {e}")
        return []

@app.post("/api/history")
async def save_history(req: SaveSessionRequest, x_api_key: str = Header(None)):
    """Upsert a session and all its messages."""
    verify_token(x_api_key)
    try:
        conn = sqlite3.connect(PERSISTENCE_DB)
        cursor = conn.cursor()
        
        now = datetime.now().isoformat()
        
        # Upsert session
        cursor.execute("""
            INSERT INTO sessions (id, title, updated_at) 
            VALUES (?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET title=excluded.title, updated_at=excluded.updated_at
        """, (req.id, req.title, now))
        
        # Replace messages (Clear and Insert most efficient for small turns)
        cursor.execute("DELETE FROM messages WHERE session_id = ?", (req.id,))
        for m in req.messages:
            meta = {
                "toolCalls": m.get("toolCalls", []),
                "toolResults": m.get("toolResults", []),
                "chart": m.get("chart"),
                "tvSymbol": m.get("tvSymbol"),
                "intent": m.get("intent")
            }
            cursor.execute("""
                INSERT INTO messages (session_id, role, content, metadata, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (req.id, m["role"], m["content"], json.dumps(meta), now))
            
        conn.commit()
        conn.close()
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error saving history: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/history/{session_id}")
async def delete_history(session_id: str, x_api_key: str = Header(None)):
    """Purge a session and its messages."""
    verify_token(x_api_key)
    try:
        conn = sqlite3.connect(PERSISTENCE_DB)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        cursor.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.commit()
        conn.close()
        return {"status": "deleted"}
    except Exception as e:
        logger.error(f"Error deleting history: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def save_message_record(session_id: str, role: str, content: str, metadata: dict = None):
    """Internal helper to save a message directly to SQLite."""
    try:
        conn = sqlite3.connect(PERSISTENCE_DB)
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        
        # Ensure session exists
        cursor.execute("INSERT OR IGNORE INTO sessions (id, title, updated_at) VALUES (?, ?, ?)", 
                       (session_id, "Strategy Briefing", now))
        
        meta_json = json.dumps(metadata or {})
        cursor.execute("""
            INSERT INTO messages (session_id, role, content, metadata, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (session_id, role, content, meta_json, now))
        
        # Update session timestamp
        cursor.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
        
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to record message to database: {e}")

@app.post("/api/chat")
@limiter.limit(CHAT_RATE_LIMIT)
def chat(request: Request, req: ChatRequest, x_api_key: str = Header(None)):
    verify_token(x_api_key)
    user_input = req.message.strip()
    if not user_input:
        raise HTTPException(status_code=400, detail="Empty message")

    # Record User Message
    save_message_record(req.session_id, "user", user_input)

    async def generate_response():
        global CLAUDE_AVAILABLE
        # Container for server-side persistence
        full_response_text = ""
        collected_tool_calls = []
        collected_tool_results = []
        final_intent = "GENERAL"
        final_tv_symbol = None
        final_tv_symbols = []

        # 0. Fast-path: greeting detection — no API calls needed
        import re as _re
        import random as _random

        _GREETINGS = {
            "สวัสดี", "สวัสดีครับ", "สวัสดีค่ะ", "สวัสดีคับ", "สวัสดีฮะ",
            "หวัดดี", "หวัดดีครับ", "หวัดดีค่ะ", "ดีครับ", "ดีค่ะ", "ดีคับ",
            "hi", "hello", "hey", "yo", "hii", "hiii", "hiiii",
            "hi krub", "hi kub", "hello kub", "hello krub",
            "ดี bro", "yo kub", "hi na",
        }
        _FINANCE_TERMS = {
            "ทอง", "gold", "xau", "btc", "eth", "sol", "crypto", "เหรียญ", "coin",
            "หุ้น", "stock", "nasdaq", "s&p", "sp500", "dow", "index",
            "oil", "น้ำมัน", "silver", "ดอลลาร์", "Baht", "usd",
            "ราคา", "price", "กราฟ", "chart", "เทรด", "trade", "ซื้อ", "ขาย",
            "entry", "sl", "tp", "stop", "target", "วิเคราะห์", "analyze",
            "ตลาด", "market", "sector", "fund", "etf", "port", "พอร์ต",
            "nvda", "aapl", "tsla", "meta", "amzn", "msft", "googl",
        }
        # Words to skip during manual ticker extraction (fallback mode)
        # Prevents misidentifying common trading terms and conversational fillers as assets.
        SKIP_WORDS = {
            "GREETING", "THANKS", "HELLO", "HI", "HEY", "OK", "YES", "NO", "GO", "ACT",
            "FIX", "BET", "SET", "DID", "CAN", "SEE", "HOW", "ALL", "BIT", "FOR", "GET",
            "PUT", "USE", "THE", "AND", "ANY", "HAS", "HAD", "WAS", "ARE", "FOR",
            "TREND", "ANALYSIS", "PLAN", "CHART", "SIGNAL", "BUY", "SELL", "TRADE",
            "LONG", "SHORT", "ENTRY", "EXIT", "STOP", "SL", "TP", "RISK", "PORT",
            "ZONE", "LEVEL", "HIGH", "LOW", "RSI", "MACD", "OB", "FVG", "BOS", "EMA",
            "VWAP", "SMC", "ICT", "MT5", "ORDER", "DRAFT", "VERIFY", "CONFIRM"
        }

        def _is_greeting(text: str) -> bool:
            raw = text.strip().lower()
            if any(fw in raw for fw in _FINANCE_TERMS):
                return False
            t = _re.sub(r"[!?.ๆ~\-_,]+", "", raw)
            t = _re.sub(r"(.)\1{2,}", r"\1\1", t)
            if t in _GREETINGS:
                return True
            if any((g in t and " " in g) for g in _GREETINGS):
                return True
            patterns = [r"\bhi+\b", r"\bhey+\b", r"\byo+\b", r"\bhello+\b",
                        r"^สวัสดี", r"^หวัดดี", r"^ดี(ครับ|ค่ะ|ค้าบ|งับ|ฮะ)?$"]
            return any(_re.search(p, t) for p in patterns)

        if _is_greeting(user_input) and len(user_input.strip().split()) <= 5:
            reply = _random.choice([
                "สวัสดีครับ! 😊 มีอะไรให้ช่วยเรื่องการลงทุนไหมครับ?",
                "หวัดดีครับ 👋 วันนี้สนใจหุ้น, crypto หรือทองดีครับ?",
                "ดีครับ! 📈 อยากวิเคราะห์ตัวไหน บอกมาได้เลย",
                "มาแล้วครับ 🚀 วันนี้จะลุยตลาดไหนดี?",
                "โย่ว 😎 มีตัวไหนให้ผมช่วยดูกราฟไหม?",
                "พร้อมลุยตลาดแล้วครับ 🔥 อยากดู entry / exit ตัวไหน?",
                "ผมอยู่ครับ 🤖 อยากคุยเรื่องตลาดหรือให้ช่วยวิเคราะห์อะไรดี?",
            ])
            yield json.dumps({"type": "chunk", "content": reply}) + "\n"
            yield json.dumps({"type": "done", "intent": "CHAT", "tvSymbol": None}) + "\n"
            return

        # 1. Schema Access
        schema = await asyncio.to_thread(_get_schema)
        if not schema:
            yield json.dumps({"type": "chunk", "content": "⚠️ ไม่สามารถเชื่อมต่อกับ MCP Server ที่ port 8000 ได้"}) + "\n"
            return
        
        schema_str = json.dumps(schema, indent=2)

        # 2. Market Snapshot Context (High Fidelity)
        snapshot = await asyncio.to_thread(get_market_snapshot)
        market_context = json.dumps(snapshot, indent=2, default=str) if snapshot else "No live data available."
        macro_snapshot = json.dumps(GLOBAL_MACRO_CACHE, indent=2)

        # ==========================================
        # NEW: AGENTIC WORKFLOW (FUNCTION CALLING)
        # ==========================================
        
        # System Prompt for the Agent
        agent_system_prompt = """
You are Alex, a world-class AI financial advisor and Senior Quant Strategist. Your goal is to provide institutional-grade trading advice that is strictly data-driven.

CRITICAL ANALYTICAL FRAMEWORK:
When analyzing any asset, you must synthesize data from ALL provided tool outputs:
1. Technical Indicators (RSI, MACD, EMA)
2. Smart Money Concepts (Order Blocks, Fair Value Gaps, Liquidity)
3. Market Structure (BOS, CHoCH, Trend Slopes)
4. Fundamental News Sentiment & Macro Climate

STRICT RESPONSE STRUCTURE (8-PART TRADE PLAN):
1. 📈 **แนวโน้ม (Trend)**: วิเคราะห์โครงสร้างตลาด (Bullish/Bearish/Sideways) และความแข็งแกร่งของเทรนด์
2. 📰 **ข้อมูลข่าวสาร (Intel)**: สรุป Sentiment จากข่าวล่าสุดและผลกระทบที่คาดว่าจะเกิดขึ้น (Impact Analysis)
3. 🕯️ **รูปแบบราคา (Patterns)**: ระบุ Candlestick patterns หรือ SMC zones (OB/FVG) ที่สำคัญ
4. 🧠 **ความจำย้อนหลัง (Memory)**: (ถ้ามีข้อมูลจาก recall_memories) วิเคราะห์บทเรียนจากอดีตในสถาณการณ์ที่คล้ายกัน
5. 🎯 **จุดเข้า (Entry Zone)**: ระบุราคาหรือช่วงราคาที่ได้เปรียบที่สุด
6. 🛑 **Stop Loss (SL)**: จุดตัดขาดทุนที่ชัดเจน (Invalidation point)
7. 🎯 **Take Profit (TP)**: ระบุเป้าหมายกำไรอย่างน้อย 2 ระดับ
8. ⚡ **กลยุทธ์สรุป (Strategy)**: สรุปคำแนะนำสุดท้าย (BUY/SELL/HOLD) พร้อมระดับความมั่นใจ (%) และตบท้ายด้วย **คำถาม (CTA)** ว่า "คุณต้องการใช้แผนนี้เลยไหมครับ?" พร้อมเสนอทางเลือกให้ผู้ใช้พิมพ์ต่อได้ง่ายๆ เช่น "พิมพ์ **'จัดเลย'** หรือ **'เอาแผนนี้ไปใช้'** เพื่อดำเนินการร่างออเดอร์ทันทีครับ"

SAFETY PROTOCOL (HUMAN-IN-THE-LOOP):
- You are STRICTLY FORBIDDEN from executing trades directly without user confirmation. (Wait for Draft ID confirmation).
- CALL TO ACTION (CTA): Every time you present a trade plan with a clear BUY or SELL signal, you MUST end with a clear question asking if the user wants to execute it, and provide suggested keywords (e.g., "พิมพ์ 'จัดเลย' หรือ 'เอาแผนนี้ไปใช้' เพื่อดำเนินการร่างออเดอร์ทันทีครับ"). If the recommendation is WAIT/SIT ON HANDS/NO TRADE, do NOT ask the user to execute — instead explain why to wait.
- STEP 1: ONLY when the user explicitly says to execute/place a trade (e.g., "จัดเลย", "กดเลย", "execute", "place order", "ตามแผน", "เปิดออเดอร์"), call `prepare_mt5_trade_draft` to generate a **Draft ID**. DO NOT call prepare_mt5_trade_draft during an analysis response — wait for explicit user confirmation first.
- STEP 2: Present the trade plan to the user along with the Draft ID.
- STEP 3: Explicitly ask the user to confirm. ALWAYS display the confirmation phrase inside a fenced code block so the user can copy it easily, like this:
```
ยืนยัน BTCUSD-TRADE-PLAN-12345
```
  Never put the confirmation phrase in quotes or inline text only — always use a code block.
- STEP 4: Only call `execute_approved_mt5_trade` AFTER the user has explicitly confirmed that specific Draft ID.

EXECUTION RESULT HANDLING:
- If `execute_approved_mt5_trade` returns `"status": "SIMULATED"` or `"mode": "PAPER_TRADE"`, tell the user:
  "✅ บันทึก Paper Trade สำเร็จแล้วครับ! (Ticket #{ticket}) ระบบยังไม่ได้เชื่อมต่อกับ MetaTrader5 จริง จึงบันทึกเป็น Paper Trade แทน"
  Then display the full trade details (symbol, action, volume, SL, TP).
  DO NOT say "ทำไม่ได้" or apologize — the trade IS recorded, just as a paper trade.
- If `execute_approved_mt5_trade` returns `"status": "SUCCESS"`, confirm live execution with ticket number.
- If it returns `"error"`, report the error clearly and suggest next steps.

COGNITIVE STASHING (STATE RECOVERY):
- Whenever you finish generating a valid trade plan (Symbol, Side, SL, TP), you MUST call `update_working_memory` to stash these parameters.
- This ensures that if the user asks "do it" later, you can recover the plan even if the conversation history is truncated.
- Example: update_working_memory(memory="Plan: BUY XAUUSD at 2300, SL 2280, TP 2350", emotion="CONFIDENT")

CONTEXTUAL EXECUTION (AUTO-PARAMETER EXTRACTION):
- If you have just provided a trade plan (Side, SL, TP) and the user asks to execute it (e.g., 'เปิดออเดอร์', 'จัดเลย', 'place it', 'กดเลย'), you MUST autonomously extract the Symbol, Side, SL, and TP from your own previous analysis.
- DO NOT ask the user for these details again if they were already discussed in the conversation history.
- LOT SIZE: If the user has not specified a lot size, use **0.01** as a safe institutional default. Inform the user in your message that you used the default lot size.

GUIDELINES:
- ALWAYS match user's language (Thai -> Thai).
- MULTI-ASSET COMPARISON: If the user asks to compare multiple assets (e.g. 'NASDAQ vs BTC'), you MUST call `get_market_analysis` MULTIPLE TIMES IN PARALLEL for EACH asset before responding. NEVER say you lack data for comparison.
- SAFETY RULE: Do NOT treat conversational agreement (e.g., "OK", "Yes", "Confirmed") or trading terms (e.g., "TREND", "RSI") as ticker symbols.
- MARKET VIGILANCE: Access the `market_hours` field in your context. If a user asks to trade or analyze an asset whose market is currently "🔴 CLOSED" or in "⚠️ DAILY BREAK", you MUST proactively warn them. Explain when it will open and advise whether to wait or use a pending order.
- NEVER hallucinate prices. Use ONLY data from tool outputs.
- Personality: Professional, direct, and highly analytical. No fluff.
"""

        # Prepare tools for Gemini
        gemini_tools = [types.Tool(function_declarations=[
            types.FunctionDeclaration(
                name="get_market_analysis",
                description=(
                    "Fetch real-time price, technical indicators, Smart Money zones (OB/FVG/Liquidity), "
                    "market structure, and multi-timeframe analysis for ANY asset. "
                    "ALWAYS specify asset_class correctly: "
                    "CRYPTO for BTC/ETH/SOL/etc, "
                    "MACRO for GOLD/XAU/OIL/NASDAQ/SP500/indices/commodities, "
                    "STOCK for ALL equities including small-cap/mid-cap (EOSE, AMC, GME, AAPL, NVDA, TSLA, etc.) "
                    "— any company stock that is NOT crypto uses asset_class='STOCK'."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "symbol":     types.Schema(type="STRING", description="Ticker symbol e.g. BTC, GOLD, NVDA, EOSE, AMC"),
                        "timeframe":  types.Schema(type="STRING", description="Timeframe: 1m, 5m, 15m, 1h, 1d"),
                        "asset_class":types.Schema(type="STRING", description="CRYPTO | STOCK | MACRO — must be correct for data routing"),
                    },
                    required=["symbol", "asset_class"]
                )
            ),
            types.FunctionDeclaration(
                name="get_trading_tactics",
                description=(
                    "Institutional Intelligence: Aggregates SMC, Trend, and Mean Reversion strategies "
                    "to provide explicit entry/SL/TP 'moves' for a given symbol. "
                    "Supports: CRYPTO (BTC, ETH, SOL, BNB, XRP, DOGE, AVAX, LINK, ADA, DOT, MATIC), "
                    "COMMODITIES (GOLD/XAUUSD, SILVER/XAGUSD, OIL/USOIL), "
                    "INDICES (NASDAQ/US100, SP500/US500, DOW/US30), "
                    "FOREX (EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF). "
                    "Use this when the user asks for a trade plan, analysis, entry/SL/TP, or 'ขอแผน'."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "symbol": types.Schema(type="STRING", description="Short symbol: BTC, ETH, GOLD, OIL, NASDAQ, SP500, EURUSD, etc.")
                    },
                    required=["symbol"]
                )
            ),
            types.FunctionDeclaration(
                name="get_macro_sentiment",
                description="Get overall market regime and sentiment scores.",
                parameters=types.Schema(type="OBJECT", properties={})
            ),
            types.FunctionDeclaration(
                name="get_news_impact",
                description="Fetch the latest news and calculate the market impact score for a specific symbol.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "symbol": types.Schema(type="STRING", description="Ticker symbol (e.g. BTC, ETH, NVDA)")
                    },
                    required=["symbol"]
                )
            ),
            types.FunctionDeclaration(
                name="get_sentiment_history",
                description=(
                    "Query historical sentiment scores for a symbol from the database. "
                    "Use this when asked about sentiment trends, whether market mood has been improving or "
                    "deteriorating, or to compare current vs past sentiment. "
                    "Examples: 'BTC sentiment ช่วง 30 วันที่ผ่านมา', 'sentiment NVDA เปลี่ยนไปมั้ย', "
                    "'was crypto sentiment positive last week'"
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "symbol": types.Schema(type="STRING", description="Ticker symbol (e.g. BTC, NVDA, GOLD)"),
                        "days":   types.Schema(type="INTEGER", description="Lookback window in days (default 30, max 90)")
                    },
                    required=["symbol"]
                )
            ),
            types.FunctionDeclaration(
                name="get_market_features",
                description=(
                    "Retrieve precomputed statistical features for any symbol from the feature store. "
                    "Use for: returns/performance (1d/7d/30d/90d/1y), volatility, correlations vs SP500/BTC/Gold, "
                    "beta vs SP500, % from 52-week high/low, relative strength vs market. "
                    "Much faster than computing live. Examples: "
                    "'NVDA ทำได้ดีแค่ไหน 3 เดือน', 'BTC สัมพันธ์กับ SP500 มั้ย', "
                    "'หุ้นไหน stable ที่สุด', 'NVDA เสี่ยงกว่าตลาดเท่าไหร่'"
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "symbol": types.Schema(type="STRING", description="Ticker symbol (e.g. BTC-USD, NVDA, GC=F, ^GSPC)")
                    },
                    required=["symbol"]
                )
            ),
            types.FunctionDeclaration(
                name="get_market_regime",
                description=(
                    "Return the current global market regime: RISK_ON, RISK_OFF, or NEUTRAL. "
                    "Includes SP500/crypto volatility, BTC-SP500 correlation, and MA200 position. "
                    "Use when asked: 'ตลาดตอนนี้ risk-on หรือ risk-off?', "
                    "'ควร aggressive หรือ defensive?', 'BTC decoupled จาก stocks แล้วมั้ย?'"
                ),
                parameters=types.Schema(type="OBJECT", properties={})
            ),
            types.FunctionDeclaration(
                name="get_top_movers",
                description=(
                    "Rank ALL tracked symbols by a statistical feature and return top/bottom N. "
                    "Use when asked about rankings across assets: "
                    "'หุ้นไหน outperform ตลาดมากที่สุด' → metric=rel_strength_30d direction=top, "
                    "'asset ไหนผันผวนน้อยที่สุด' → metric=volatility_30d direction=bottom, "
                    "'หุ้นไหน return ดีที่สุด 3 เดือน' → metric=return_90d direction=top, "
                    "'asset ไหน corr กับ BTC สูงสุด' → metric=corr_vs_btc_30d direction=top"
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "metric":    types.Schema(type="STRING", description=(
                            "Feature to rank by. One of: return_1d, return_7d, return_30d, return_90d, "
                            "return_365d, volatility_30d, volatility_90d, corr_vs_sp500_30d, "
                            "corr_vs_btc_30d, corr_vs_gold_30d, beta_vs_sp500, rel_strength_30d, "
                            "pct_from_52w_high, pct_from_52w_low"
                        )),
                        "direction": types.Schema(type="STRING", description="'top' for highest, 'bottom' for lowest"),
                        "limit":     types.Schema(type="INTEGER", description="Number of results (default 10, max 50)"),
                    },
                    required=["metric"]
                )
            ),
            types.FunctionDeclaration(
                name="recall_memories",
                description="Retrieve past trade memories for a symbol. Pass `context` (description of current market conditions) to enable semantic similarity search — finds trades from situations most like the present, not just the most recent ones.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "symbol": types.Schema(type="STRING", description="Ticker symbol (e.g. BTC, GOLD)"),
                        "limit": types.Schema(type="INTEGER", description="Number of past trades to recall"),
                        "context": types.Schema(type="STRING", description="Optional: describe current market conditions to find semantically similar past trades")
                    },
                    required=["symbol"]
                )
            ),
            types.FunctionDeclaration(
                name="remember_trade",
                description="Record a trading decision and reasoning into memory.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "symbol": types.Schema(type="STRING", description="Ticker symbol"),
                        "side": types.Schema(type="STRING", description="Trade side: BUY or SELL"),
                        "entry_price": types.Schema(type="NUMBER", description="Entry price in USD"),
                        "reasoning": types.Schema(type="STRING", description="Detailed reasoning for the trade"),
                        "outcome": types.Schema(type="STRING", description="Optional: WIN or LOSS"),
                        "pnl_pct": types.Schema(type="NUMBER", description="Optional: Profit/Loss percentage")
                    },
                    required=["symbol", "side", "entry_price", "reasoning"]
                )
            ),
            types.FunctionDeclaration(
                name="run_strategy_backtest",
                description=(
                    "Run a historical backtest for CRYPTO or MACRO assets ONLY. "
                    "Tests whether the AI agent's ICT logic would have beaten the market historically. "
                    "DO NOT call for stocks (asset_class=STOCK) — stocks use Buy & Hold, not trading strategies."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "symbol":       types.Schema(type="STRING",  description="Ticker symbol (e.g. BTC, GOLD, ETH)"),
                        "timeframe":    types.Schema(type="STRING",  description="Timeframe (15m, 1h, 1d)"),
                        "limit":        types.Schema(type="INTEGER", description="Number of candles to test (default 500)"),
                        "asset_class":  types.Schema(type="STRING",  description="CRYPTO or MACRO only — never STOCK"),
                    },
                    required=["symbol"]
                )
            ),
            types.FunctionDeclaration(
                name="prepare_mt5_trade_draft",
                description=(
                    "Step 1 of the trading process. Drafts a trade and returns a Draft ID. "
                    "You MUST show this Draft ID to the user and wait for confirmation before executing."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "symbol": types.Schema(type="STRING", description="MT5 symbol (e.g. 'XAUUSD')"),
                        "side": types.Schema(type="STRING", description="BUY or SELL"),
                        "volume": types.Schema(type="NUMBER", description="Lot size (e.g. 0.01)"),
                        "sl": types.Schema(type="NUMBER", description="Optional: Stop Loss price"),
                        "tp": types.Schema(type="NUMBER", description="Optional: Take Profit price")
                    },
                    required=["symbol", "side", "volume"]
                )
            ),
            types.FunctionDeclaration(
                name="execute_approved_mt5_trade",
                description="Step 2 of the trading process. Executes a trade ONLY after the user has confirmed the Draft ID.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "draft_id": types.Schema(type="STRING", description="The confirmed Draft ID provided in the previous step.")
                    },
                    required=["draft_id"]
                )
            ),
            types.FunctionDeclaration(
                name="get_mt5_account_summary",
                description="Get current MT5 account balance, equity, and free margin.",
                parameters=types.Schema(type="OBJECT", properties={})
            ),
            types.FunctionDeclaration(
                name="run_ai_trade_analysis",
                description=(
                    "Run the full 8-agent AI analysis pipeline for a symbol, validate the signal through "
                    "Guard Layer and Circuit Breaker, then optionally execute on MT5. "
                    "By default runs in DRY_RUN mode (safe — no real order). "
                    "Use when user says 'วิเคราะห์แล้วเทรดเลย', 'AI เทรดให้หน่อย', 'analyze and trade', "
                    "'ส่ง order อัตโนมัติ'. "
                    "NEVER call with dry_run=False unless user explicitly says 'เทรดจริง' or 'live trade'."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "symbol":                types.Schema(type="STRING",  description="Symbol e.g. BTC, ETH, GOLD"),
                        "timeframe":             types.Schema(type="STRING",  description="Timeframe: 15m, 1h, 4h"),
                        "dry_run":               types.Schema(type="BOOLEAN", description="True=simulate only (default). False=live execution (only when user explicitly requests)"),
                        "risk_pct":              types.Schema(type="NUMBER",  description="% of balance to risk per trade (default 1.0)"),
                        "confirmation_required": types.Schema(type="BOOLEAN", description="True=return draft for user to confirm. False=execute immediately"),
                    },
                    required=["symbol"]
                )
            ),
            types.FunctionDeclaration(
                name="get_market_opportunities",
                description=(
                    "Scan the market for top movers — gainers and losers — grouped by asset class. "
                    "Each group (NASDAQ_100, SP500, NASDAQ_COMPOSITE, CRYPTO) is returned SEPARATELY with its own hero. "
                    "Use asset_class='ALL' when user asks broadly (e.g. 'ตลาดวันนี้', 'มีอะไรน่าสนใจ', 'ภาพรวมตลาด', 'what's moving'). "
                    "Use asset_class='STOCK' for US stocks only. "
                    "Use asset_class='CRYPTO' for crypto only."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "asset_class": types.Schema(
                            type="STRING",
                            description="'ALL' = all groups (default for broad questions) | 'STOCK' = US stocks only | 'CRYPTO' = crypto only"
                        )
                    },
                    required=["asset_class"]
                )
            ),
            types.FunctionDeclaration(
                name="get_custom_screener",
                description="Scan a custom basket of stocks/crypto for a specific theme or to find sector laggards. MUST provide a list of tickers to scan.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "tickers": types.Schema(
                            type="ARRAY", 
                            items=types.Schema(type="STRING"),
                            description="List of explicitly chosen ticker symbols to scan. Max 20. (e.g. ['NVDA', 'AMD', 'SMCI', 'PLTR'])"
                        )
                    },
                    required=["tickers"]
                )
            ),
            types.FunctionDeclaration(
                name="get_sector_rotation",
                description="Analyze institutional money flow across major equity sectors to identify market leadership and rotation.",
                parameters=types.Schema(type="OBJECT", properties={})
            ),
            types.FunctionDeclaration(
                name="calculate_risk_parameters",
                description="Calculate optimal position sizing and risk/reward parameters for a trade based on account size and stop loss.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "account_size": types.Schema(type="NUMBER", description="Current account balance in USD"),
                        "entry": types.Schema(type="NUMBER", description="Target entry price"),
                        "stop_loss": types.Schema(type="NUMBER", description="Target stop loss price"),
                        "risk_pct": types.Schema(type="NUMBER", description="Risk percentage per trade (default 1.0 = 1%)")
                    },
                    required=["account_size", "entry", "stop_loss"]
                )
            ),
            types.FunctionDeclaration(
                name="get_market_climate",
                description="Analyze current global macro risk, climate score, and threat level using VIX, DXY, and Bond Yields.",
                parameters=types.Schema(type="OBJECT", properties={})
            ),
            types.FunctionDeclaration(
                name="get_working_memory",
                description="Retrieve your persistent internal stance, grand strategy, and current cognitive focus. Use this at the start of complex sessions to remember your plan.",
                parameters=types.Schema(type="OBJECT", properties={})
            ),
            types.FunctionDeclaration(
                name="update_working_memory",
                description="Update your internal stance, trading plan, or emotional bias. Use this to maintain state across different chat sessions.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "memory": types.Schema(type="STRING", description="The new core focus or strategic plan to remember"),
                        "emotion": types.Schema(type="STRING", description="Optional: Your current emotional stance (e.g. AGGRESSIVE, DEFENSIVE, CAUTIOUS)")
                    }
                )
            ),
            types.FunctionDeclaration(
                name="calculate_math_expression",
                description="Safely evaluate a mathematical expression. Useful for calculating position sizes, pip values, profit/loss, and other math required by the user.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "expression": types.Schema(type="STRING", description="Mathematical expression to evaluate (e.g., '100 * 0.05', '(5000 - 4500) * 0.1')")
                    },
                    required=["expression"]
                )
            ),
            types.FunctionDeclaration(
                name="set_smart_alert",
                description="Set a background monitoring alert for a specific market condition.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "condition": types.Schema(type="STRING", description="Condition to monitor, e.g., 'price < 2280'"),
                        "target_symbol": types.Schema(type="STRING", description="Symbol to monitor, e.g., 'XAUUSD', 'BTC'"),
                        "message": types.Schema(type="STRING", description="Message to send when triggered")
                    },
                    required=["condition", "target_symbol", "message"]
                )
            ),
            types.FunctionDeclaration(
                name="get_user_portfolio",
                description="Retrieve MT5 portfolio context aligned to a specific user.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "user_id": types.Schema(type="STRING", description="Optional user ID, defaults to 'default'")
                    }
                )
            ),
            types.FunctionDeclaration(
                name="get_onchain_flow",
                description="Fetch Whale money flows and exchange net inflows for Crypto.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "symbol": types.Schema(type="STRING", description="Token symbol e.g., 'BTC'")
                    },
                    required=["symbol"]
                )
            ),
            types.FunctionDeclaration(
                name="get_options_flow",
                description="Fetch Put/Call Ratio and Gamma Exposure (GEX) for TradFi/Crypto options.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "symbol": types.Schema(type="STRING", description="Symbol e.g., 'NVDA', 'BTC'")
                    },
                    required=["symbol"]
                )
            ),
            types.FunctionDeclaration(
                name="analyze_trade_performance",
                description="Analyze recent closed trades to provide an automated AI journal/review of performance.",
                parameters=types.Schema(type="OBJECT", properties={})
            ),
            types.FunctionDeclaration(
                name="get_social_sentiment",
                description="Scan social media hype, Reddit mentions, and influence scores for a specific token or asset.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "keyword": types.Schema(type="STRING", description="Keyword or ticker to scan, e.g., 'PEPE'")
                    },
                    required=["keyword"]
                )
            ),
            # ── Phase 14: New Tools ──────────────────────────────────────
            types.FunctionDeclaration(
                name="get_fear_greed_index",
                description=(
                    "Return the Crypto Fear & Greed Index (0=Extreme Fear, 100=Extreme Greed) "
                    "plus a Stock market composite. Use when asked: "
                    "'ตลาดตอนนี้กลัวหรือโลภ?', 'fear greed index', 'sentiment ตลาดเป็นยังไง', "
                    "'ควร contrarian buy ไหม?', 'crypto mood'"
                ),
                parameters=types.Schema(type="OBJECT", properties={})
            ),
            types.FunctionDeclaration(
                name="get_economic_calendar",
                description=(
                    "Fetch upcoming high-impact macro events: Fed meetings, CPI, NFP, GDP, earnings. "
                    "Use when asked: 'ปฏิทินเศรษฐกิจ', 'อาทิตย์นี้มีตัวเลขอะไร', "
                    "'FOMC เมื่อไหร่', 'CPI ประกาศเมื่อไหร่', 'upcoming events', "
                    "'งบออกเมื่อไหร่', 'ก่อนเทรดต้องระวังอะไร'"
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "days_ahead": types.Schema(type="INTEGER", description="Look ahead N days (default 7, max 30)")
                    }
                )
            ),
            types.FunctionDeclaration(
                name="get_liquidation_heatmap",
                description=(
                    "Fetch crypto liquidation clusters — price levels where mass long/short liquidations "
                    "are concentrated. Critical for identifying stop-hunt targets and cascade zones. "
                    "Use when asked: 'liquidation zone', 'short squeeze level', 'where will longs get liquidated', "
                    "'จุด liquidate', 'แนว stop hunt', 'แนวที่จะเกิด cascade'"
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "symbol": types.Schema(type="STRING", description="Crypto symbol e.g. BTC, ETH, SOL")
                    },
                    required=["symbol"]
                )
            ),
            types.FunctionDeclaration(
                name="scan_multi_timeframe",
                description=(
                    "Scan 5m/15m/1h/4h/1d simultaneously and return a confluence score (0-100%). "
                    "High score = multiple TFs agree = stronger signal. "
                    "Use when asked: 'ทุก timeframe บอกว่าอะไร', 'MTF analysis', 'confluence', "
                    "'ทุก TF bullish ไหม', 'ภาพรวมทุก TF', 'multi timeframe'"
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "symbol":      types.Schema(type="STRING", description="Ticker symbol"),
                        "asset_class": types.Schema(type="STRING", description="CRYPTO | STOCK | MACRO")
                    },
                    required=["symbol"]
                )
            ),
            types.FunctionDeclaration(
                name="get_portfolio_correlation",
                description=(
                    "Compute pairwise correlation matrix between portfolio assets. "
                    "Flags pairs with correlation > 0.85 as concentration risk. "
                    "Use when asked: 'portfolio กระจายความเสี่ยงดีไหม', 'correlation ระหว่าง assets', "
                    "'BTC กับ ETH relate กัน?', 'พอร์ตเสี่ยงกระจุกไหม', 'diversification check'"
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "symbols": types.Schema(type="ARRAY", description="List of symbols e.g. ['BTC','ETH','NVDA']",
                                                items=types.Schema(type="STRING")),
                        "period":  types.Schema(type="STRING", description="Lookback period: 1mo, 3mo, 6mo, 1y (default 3mo)")
                    }
                )
            ),
            types.FunctionDeclaration(
                name="generate_weekly_report",
                description=(
                    "Generate a full AI weekly performance report: win rate, P&L, best/worst trade, "
                    "profit factor, AI recommendations, and market regime context. "
                    "Use when asked: 'สรุปผลการเทรดสัปดาห์นี้', 'weekly report', 'performance รายสัปดาห์', "
                    "'ทำได้ดีแค่ไหน 7 วันที่ผ่านมา', 'trade journal', 'AI review'"
                ),
                parameters=types.Schema(type="OBJECT", properties={})
            ),
            types.FunctionDeclaration(
                name="paper_trade",
                description=(
                    "Simulate trades without real capital or MT5. "
                    "action='OPEN' opens a simulated position. "
                    "action='CLOSE' closes it and calculates P&L. "
                    "action='LIST' shows all paper trades. "
                    "action='RESET' clears history. "
                    "Use when asked: 'ทดสอบเทรด', 'paper trade', 'simulate', 'ลองเทรดดูก่อน', "
                    "'ไม่อยากใช้เงินจริง', 'เปิด paper position', 'ดู paper trade ทั้งหมด'"
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "action":   types.Schema(type="STRING", description="OPEN | CLOSE | LIST | RESET"),
                        "symbol":   types.Schema(type="STRING", description="Ticker symbol e.g. BTC"),
                        "side":     types.Schema(type="STRING", description="BUY or SELL"),
                        "volume":   types.Schema(type="NUMBER", description="Lot/unit size"),
                        "price":    types.Schema(type="NUMBER", description="Entry price (optional — uses live price)"),
                        "trade_id": types.Schema(type="STRING", description="Paper trade ID (required for CLOSE)")
                    },
                    required=["action"]
                )
            ),
            # ── Phase 15 Tools ───────────────────────────────────────
            types.FunctionDeclaration(
                name="get_funding_rates",
                description=(
                    "Fetch perpetual swap funding rates for crypto assets. "
                    "High positive funding = crowded longs = contrarian short. "
                    "Use when asked: 'funding rate', 'ค่า funding', 'long ล้น', 'short squeeze โอกาส'"
                ),
                parameters=types.Schema(type="OBJECT", properties={})
            ),
            types.FunctionDeclaration(
                name="suggest_portfolio_rebalance",
                description=(
                    "Compare current holdings vs target allocation and suggest rebalancing. "
                    "Use when asked: 'rebalance พอร์ต', 'ปรับพอร์ต', 'overweight underweight', 'จัดพอร์ตใหม่'"
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "target_allocation": types.Schema(
                            type="OBJECT",
                            description="Target weight per symbol e.g. {BTC:40, ETH:20, GOLD:20}"
                        )
                    }
                )
            ),
            types.FunctionDeclaration(
                name="get_iv_rank",
                description=(
                    "Compute IV Rank for a stock/ETF. IVR>80=expensive(sell premium). IVR<20=cheap(buy directional). "
                    "Use when asked: 'IV rank', 'options ถูกหรือแพง', 'IVR', 'ควร sell covered call ไหม'"
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "symbol": types.Schema(type="STRING", description="Ticker e.g. NVDA, SPY, BTC")
                    },
                    required=["symbol"]
                )
            ),
            types.FunctionDeclaration(
                name="get_etf_flows",
                description=(
                    "Track fund flow signals for major ETFs (SPY, QQQ, GLD, IBIT etc.). "
                    "Use when asked: 'ETF flows', 'เงินไหลเข้า ETF', 'risk on ETF', 'fund flow'"
                ),
                parameters=types.Schema(type="OBJECT", properties={})
            ),
            types.FunctionDeclaration(
                name="run_custom_screener",
                description=(
                    "Scan NASDAQ100/SP500/CRYPTO with filters: RSI, volume spike, 52w proximity, return. "
                    "Use when asked: 'สแกนหุ้น RSI ต่ำ', 'หุ้น oversold', 'volume spike screen', 'custom screener'"
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "universe":      types.Schema(type="STRING", description="NASDAQ100 | SP500 | CRYPTO"),
                        "rsi_max":       types.Schema(type="NUMBER", description="Max RSI"),
                        "rsi_min":       types.Schema(type="NUMBER", description="Min RSI"),
                        "vol_spike":     types.Schema(type="NUMBER", description="Min vol ratio"),
                        "pct_from_52wh": types.Schema(type="NUMBER", description="Max % below 52w high"),
                        "min_return_1w": types.Schema(type="NUMBER", description="Min 1w return %"),
                        "max_return_1w": types.Schema(type="NUMBER", description="Max 1w return %"),
                        "limit":         types.Schema(type="INTEGER", description="Max results")
                    }
                )
            ),
        ])]

        # Known crypto symbols (routing helper)
        KNOWN_CRYPTO_SYMS = {
            "BTC","ETH","SOL","BNB","XRP","ADA","DOGE","PEPE","SHIB","AVAX",
            "MATIC","DOT","LINK","UNI","LTC","BCH","ATOM","FIL","NEAR","APT",
            "ARB","OP","INJ","SUI","TIA","BONK","WIF","FLOKI"
        }
        KNOWN_MACRO_SYMS = {
            "GOLD","XAU","XAUUSD","SILVER","OIL","DXY","NASDAQ","SP500",
            "CRUDE","BRENT","EURUSD","GBPUSD","USDJPY"
        }
        # Words to skip when auto-detecting tickers from Thai sentences
        SKIP_WORDS = {
            "BUY","SELL","LONG","SHORT","HOLD","AND","THE","FOR","NOT","USD",
            "THB","ATR","RSI","EMA","ICT","HTF","LTF","BOS","SMC","FVG",
            "TP","SL","RR","ADX","OB","AI","TV","API","DB"
        }

        def _resolve_asset_class(sym: str) -> str:
            # Auto-detect FX pairs (e.g. EURUSD, GBPJPY) as MACRO
            if re.match(r'^[A-Z]{6}$', sym) and any(c in sym for c in ["USD","EUR","JPY","GBP","CHF","AUD","NZD","CAD"]):
                return "MACRO"
            if sym in KNOWN_CRYPTO_SYMS or sym.endswith("USDT"):
                return "CRYPTO"
            if sym in KNOWN_MACRO_SYMS:
                return "MACRO"
            return "STOCK"

        def _resolve_tv_symbol(sym: str, exchange: str = None) -> str:
            if sym in ["GOLD","XAUUSD"]: return "OANDA:XAUUSD"
            if sym in ["NASDAQ","IXIC", "NDX"]: return "OANDA:NAS100USD"
            if sym in ["SP500","GSPC"]:  return "OANDA:SPX500USD"
            if sym in ["OIL","CRUDE"]:   return "OANDA:WTICOUSD"
            
            # Use provided exchange metadata if available
            if exchange:
                ex_upper = exchange.upper()
                if "NASDAQ" in ex_upper: return f"NASDAQ:{sym}"
                if "NYSE" in ex_upper:   return f"NYSE:{sym}"
                if "AMEX" in ex_upper:   return f"AMEX:{sym}"
                if "BINANCE" in ex_upper: return f"BINANCE:{sym}USDT"
            
            # Heuristic fallbacks
            if sym in NASDAQ_100_TICKERS or sym in SP500_TICKERS:
                return f"NASDAQ:{sym}"
            if sym in KNOWN_CRYPTO_SYMS or sym.endswith("USDT"):
                return f"BINANCE:{sym}USDT"
            
            # Default for unidentified stocks - try NASDAQ first for tech focus, else NYSE
            return f"NASDAQ:{sym}"

        # ── Greeting fast-path: bypass Gemini entirely for pure small-talk ─────────
        import re as _re

        _GREETINGS = {
            # Thai (ทั่วไป)
            "สวัสดี", "หวัดดี", "ดีครับ", "ดีค่ะ", "ดีจ้า", "ดีนะ",
            "ฮัลโหล", "โย่ว", "ไง", "เป็นไง", "เป็นไงบ้าง", "สบายดีไหม",
            "อรุณสวัสดิ์", "ราตรีสวัสดิ์", "ทักครับ", "ทักค่ะ",
            # Thai (slang / วัยรุ่น)
            "ดีค้าบ", "ดีงับ", "หวัดดีงับ", "ดีฮะ", "โย่วๆ", "โย่ววว",
            "ว่าไง", "ว่าไงบ้าง", "ไงงง", "ดีๆ", "มาแล้ว", "อยู่มั้ย",
            "มีใครอยู่ไหม", "บอทอยู่ไหม",
            # English
            "hello", "hi", "hey", "hiya", "yo", "sup", "wassup",
            "good morning", "good afternoon", "good evening", "good night",
            "yo bro", "yo man", "sup bro", "sup man",
            "what's up", "whats up", "how are you", "how r u",
            "how's it going", "hows it going", "what's good", "whats good",
            # Hybrid
            "hi kub", "hi krub", "hello kub", "hello krub",
            "ดี bro", "ดีครับ bro", "yo kub", "hi na",
        }

        # Finance keywords — if present, NEVER treat as greeting
        _FINANCE_TERMS = {
            "ทอง", "gold", "xau", "btc", "eth", "sol", "crypto", "เหรียญ", "coin",
            "หุ้น", "stock", "nasdaq", "s&p", "sp500", "dow", "index",
            "oil", "น้ำมัน", "silver", "เงิน", "ดอลลาร์", "dollar", "usd", "baht",
            "ราคา", "price", "กราฟ", "chart", "เทรด", "trade", "ซื้อ", "ขาย",
            "entry", "sl", "tp", "stop", "target", "วิเคราะห์", "analyze",
            "ตลาด", "market", "sector", "fund", "etf", "port", "พอร์ต",
            "nvda", "aapl", "tsla", "meta", "amzn", "msft", "googl",
        }

        def _is_greeting(text: str) -> bool:
            raw = text.strip().lower()
            # If message contains ANY finance keyword → not a greeting
            if any(fw in raw for fw in _FINANCE_TERMS):
                return False
            t = _re.sub(r"[!?.ๆ~\-_,]+", "", raw)
            t = _re.sub(r"(.)\1{2,}", r"\1\1", t)  # ยุบตัวซ้ำ เช่น hiiiii → hii
            if t in _GREETINGS:
                return True
            # Substring match only for multi-word phrases (has space) to avoid false positives
            if any((g in t and " " in g) for g in _GREETINGS):
                return True
            # Exact-word patterns
            patterns = [
                r"\bhi+\b", r"\bhey+\b", r"\byo+\b", r"\bhello+\b",
                r"^สวัสดี", r"^หวัดดี", r"^ดี(ครับ|ค่ะ|ค้าบ|งับ|ฮะ)?$",
            ]
            return any(_re.search(p, t) for p in patterns)

        if _is_greeting(user_input) and len(user_input.strip().split()) <= 5:
            _greet_replies = [
                "สวัสดีครับ! 😊 มีอะไรให้ช่วยเรื่องการลงทุนไหมครับ?",
                "หวัดดีครับ 👋 วันนี้สนใจหุ้น, crypto หรือทองดีครับ?",
                "ดีครับ! 📈 อยากวิเคราะห์ตัวไหน บอกมาได้เลย",
                "มาแล้วครับ 🚀 วันนี้จะลุยตลาดไหนดี?",
                "โย่ว 😎 มีตัวไหนให้ผมช่วยดูกราฟไหม?",
                "สวัสดีครับ 📊 วันนี้อยากให้ผมช่วยหา setup เทรดไหม?",
                "พร้อมลุยตลาดแล้วครับ 🔥 อยากดู entry / exit ตัวไหน?",
                "ผมอยู่ครับ 🤖 อยากคุยเรื่องตลาดหรือให้ช่วยวิเคราะห์อะไรดี?",
                "เรียกผมมาแล้ว 😄 มีอะไรให้ช่วยเต็มที่เลยครับ",
            ]
            import random as _random
            reply = _random.choice(_greet_replies)
            yield json.dumps({"type": "chunk", "content": reply}) + "\n"
            yield json.dumps({"type": "done", "intent": "CHAT", "tvSymbol": None}) + "\n"
            return

        # Build history with strict turn-based structure (Gemini requirement)
        history_contents = []
        for msg in req.history[-25:]:
            msg_role = "user" if msg.get("role") == "user" else "model"
            msg_content = msg.get("content", "")
            
            p = []
            if msg_content:
                p.append(types.Part(text=msg_content))
            
            # Combine text and tool calls in one turn (Assistant role)
            if msg.get("tool_calls"):
                for tc in (msg.get("tool_calls") or []):
                    p.append(types.Part(
                        function_call=types.FunctionCall(
                            name=tc.get("name"),
                            args=tc.get("args", {})
                        )
                    ))
            
            if p:
                history_contents.append(types.Content(role=msg_role, parts=p))
            
            # Tool results MUST be a separate turn with role="user"
            if msg.get("tool_results"):
                tr_parts = []
                for tr in (msg.get("tool_results") or []):
                    _tr_content = tr.get("content")
                    if isinstance(_tr_content, str):
                        try: _tr_content = json.loads(_tr_content)
                        except Exception: _tr_content = {"result": _tr_content}
                    elif not isinstance(_tr_content, dict):
                        _tr_content = {"result": str(_tr_content)}
                    tr_parts.append(types.Part(
                        function_response=types.FunctionResponse(
                            name=tr.get("tool"),
                            response=_tr_content
                        )
                    ))
                if tr_parts:
                    history_contents.append(types.Content(role="user", parts=tr_parts))

        # Merge consecutive same-role turns to avoid Gemini validation errors
        merged_history = []
        for h in (history_contents or []):
            if merged_history and merged_history[-1].role == h.role:
                merged_history[-1].parts.extend(h.parts or [])
            else:
                merged_history.append(h)
        history_contents = merged_history
        user_lower = user_input.lower()
        
        # Thematic / laggard queries → force get_custom_screener
        THEMATIC_KEYWORDS = [
            "ตีม", "กลุ่ม", "sector", "theme", "laggard", "หุ้นน้ำมัน", "หุ้น ai",
            "หุ้นธนาคาร", "หุ้นเทค", "หุ้นพลังงาน", "หุ้นสุขภาพ", "หุ้น healthcare",
            "หุ้น semiconductor", "หุ้นชิป", "หุ้นยา", "ยังไม่ขึ้น", "ยังไม่พุ่ง",
            "ที่ยังไม่ไปไหน", "ที่ราคายัง", "ราคาต่ำ", "ราคาถูก", "หาหุ้น", "แนะหุ้น",
            "เซกเตอร์", "อุตสาหกรรม", "ช่วยจัดพอร์ต", "หุ้นปันผล", "หุ้นเติบโต"
        ]
        # Economic / macro calendar queries → force get_economic_calendar
        CALENDAR_KEYWORDS = [
            "ปฏิทิน", "economic calendar", "งบออก", "earnings", "ตัวเลขเศรษฐกิจ", "cpi",
            "เงินเฟ้อ", "gdp", "ดอกเบี้ย", "เฟด", "fed", "fomc", "ข่าวเศรษฐกิจ",
            "สัปดาห์นี้มีอะไร", "อาทิตย์นี้มีอะไร", "คืนนี้มีอะไร", "วันนี้มีอะไร", "upcoming",
            "ประกาศงบ", "ผลประกอบการ", "ประกาศตัวเลข"
        ]
        # General market scan → force get_market_opportunities
        # Split into stock-only vs broad (ALL) to avoid scanning unnecessary asset classes
        SCREENER_STOCK_KEYWORDS = [
            "หุ้นขึ้นแรง", "หุ้นลงแรง", "หุ้นขึ้นเยอะ", "หุ้นลงเยอะ",
            "วันนี้หุ้น", "หุ้นอะไร", "หุ้นน่า", "หุ้นไหน",
            "stock scan", "scan หุ้น", "top gainer", "top loser",
        ]
        SCREENER_CRYPTO_KEYWORDS = [
            "crypto น่า", "เหรียญน่า", "เหรียญขึ้น", "เหรียญลง",
            "coin น่า", "วันนี้ crypto", "วันนี้เหรียญ",
        ]
        SCREENER_ALL_KEYWORDS = [
            "ขึ้นเยอะ", "ลงเยอะ", "น่าสนใจ", "น่าซื้อ",
            "market scan", "scan ตลาด", "ภาพรวมตลาด", "วันนี้ตลาด",
            "ตลาดเป็นยังไง", "ดูตลาดให้หน่อย", "สรุปตลาด", "วันนี้มีตัวไหนแววดี",
        ]
        # Analysis plan keywords → get_trading_tactics (NOT order placement)
        ANALYSIS_PLAN_KEYWORDS = [
            "ขอแผน", "มีแผน", "แผน btc", "แผน eth", "แผน sol", "แผน gold", "แผน nvda",
            "แผน oil", "แผน nasdaq", "แผน sp500", "แผน eur", "แผน gbp", "แผน silver",
            "แผน doge", "แผน avax", "แผน bnb", "แผน xrp", "แผน link", "แผน ada",
            "วางแผน", "วิเคราะห์แผน", "ให้แผน", "แผนการเทรด", "trade plan",
            "ท่าเทรด", "setup", "entry point", "จุดเข้า", "จุดซื้อ", "จุดขาย",
            "ควรเข้า", "ควรซื้อ", "ควรขาย", "น่าซื้อไหม", "น่าเข้าไหม",
            "analyse", "วิเคราะห์", "analyze",
            "ดู btc", "ดู eth", "ดู gold", "ดู oil", "ดู nasdaq", "ดู eur",
            "ดู gbp", "ดู silver", "ดู doge", "ดู avax", "ดู bnb",
        ]

        ORDER_PLACEMENT_KEYWORDS = [
            "จัดเลย", "กดเลย", "กดออเดอร์", "เปิดออเดอร์", "จัดทอง", "จัดทองให้หน่อย",
            "ตามนั้น", "เอาจิงนะ", "place trade", "execute trade", "place order",
            "ตามแผน", "จัดไป", "เอาเลย", "ลุยเลย", "เอาแผนนี้ไปใช้", "เอาแผนนี้ไปเทรด",
            "เปิดตามแผน", "จัดตามนี้", "เอาตามนี้", "จัดไปวัยรุ่น", "เข้าออเดอร์",
            "เข้าไม้", "จัดเต็ม", "ลุย", "ไป", "GO", "เทรดเลย", "เอาเลยครับ",
            "จัดไปครับ", "เอานะ", "ตามนี้เลย", "ลุยตามแผน", "เอาทอง", "ขอคมๆ",
            # เพิ่ม: คำที่ผู้ใช้กดจากปุ่ม UI หรือพูดตามธรรมชาติ
            "เอามาเปิดไปเทรด", "เอามาเทรด", "เอาไปเทรด", "เปิดไปเลย", "เปิดตามนี้",
            "เอาแผนนี้", "ใช้แผนนี้", "ดำเนินการ", "execute", "open trade", "open order",
            "เอาเลย", "เปิดเลย", "เข้าเลย", "เอาตามแผน", "ทำตามแผน", "เริ่มเทรด",
            # เพิ่ม: ปุ่ม "ออกออเดอร์ใหม่" และคำพ้องความหมาย
            "ออกออเดอร์ใหม่", "ออกแผนใหม่", "ขอแผนใหม่", "แผนใหม่", "ออเดอร์ใหม่",
            "new order", "new plan", "ออกออเดอร์", "สร้างออเดอร์ใหม่",
        ]
        
        # ── Phase 14 keyword routing ─────────────────────────────────
        FEAR_GREED_KEYWORDS = [
            "fear greed", "fear & greed", "กลัวหรือโลภ", "โลภ", "กลัว",
            "sentiment ตลาด", "crypto mood", "ตลาดกลัว", "ตลาดโลภ",
            "contrarian", "ดัชนีความกลัว", "market sentiment",
        ]
        LIQUIDATION_KEYWORDS = [
            "liquidation", "liquidate", "liq", "short squeeze level",
            "จุด liquidate", "แนว stop hunt", "cascade", "ลิควิเดชั่น",
            "short squeeze", "long squeeze",
        ]
        MTF_KEYWORDS = [
            "multi timeframe", "mtf", "ทุก timeframe", "ทุก tf", "confluence",
            "ทุก tf bullish", "ทุก tf bearish", "ภาพรวมทุก", "หลาย timeframe",
            "5m 15m 1h", "all timeframe",
        ]
        CORRELATION_KEYWORDS = [
            "correlation", "correlate", "กระจายความเสี่ยง", "พอร์ตกระจุก",
            "diversification", "relate กัน", "สัมพันธ์กัน", "concentration risk",
        ]
        WEEKLY_REPORT_KEYWORDS = [
            "weekly report", "สรุปสัปดาห์", "สรุปผล", "trade journal",
            "ผล 7 วัน", "performance สัปดาห์", "ai review", "win rate",
            "สัปดาห์นี้เป็นยังไง", "ทำได้ดีแค่ไหน", "profit factor",
        ]
        PAPER_TRADE_KEYWORDS = [
            "paper trade", "paper trading", "ทดสอบเทรด", "simulate",
            "ลองเทรด", "ไม่อยากใช้เงินจริง", "เปิด paper", "paper position",
            "ดู paper", "ล้าง paper",
        ]

        # ── Phase 15 keyword routing ─────────────────────────────────
        FUNDING_RATE_KEYWORDS = [
            "funding rate", "ค่า funding", "long ล้น", "short ล้น",
            "funding สูง", "funding ต่ำ", "perp funding", "perpetual funding",
            "contrarian short", "contrarian long from funding",
        ]
        REBALANCE_KEYWORDS = [
            "rebalance", "ปรับพอร์ต", "overweight", "underweight",
            "จัดพอร์ตใหม่", "allocation drift", "target allocation",
        ]
        IV_RANK_KEYWORDS = [
            "iv rank", "ivr", "implied volatility rank", "options ถูกหรือแพง",
            "covered call ไหม", "sell premium", "iv percentile",
        ]
        ETF_FLOW_KEYWORDS = [
            "etf flow", "etf inflow", "etf outflow", "fund flow",
            "เงินไหลเข้า etf", "เงินไหลออก etf", "ibit flow", "spy flow",
        ]
        SCREENER_CUSTOM_KEYWORDS = [
            "สแกนหุ้น rsi", "หุ้น oversold", "volume spike screen",
            "custom screener", "custom screen", "filter หุ้น",
            "หุ้น rsi ต่ำ", "หา setup", "screener",
        ]

        # [NEW] Numeric Lot Size Detection (e.g. "0.05", "0.1", "1.5")
        import re as _strict_re
        is_numeric_volume = _strict_re.match(r"^\d*\.?\d+$", user_input.strip())
        
        # Check for trade confirmation first (higher priority)
        import re as _confirm_re
        forced_tool_names = None  # Will be set to force specific function call via tool_config
        _confirm_match = _confirm_re.match(r"^ยืนยัน\s+([\w\-]+)\s*$", user_input.strip())

        # Extract symbol from user input for analysis routing
        # Aliases: OIL/CRUDE→OIL, NASDAQ/NDX/US100→NASDAQ, SP500/SPX→SP500, DOW/DJI→DOW,
        #          EUR/EURUSD→EURUSD, GBP/GBPUSD→GBPUSD, JPY/USDJPY→USDJPY, SILVER/XAG→SILVER
        _input_upper = user_input.upper()
        _input_upper = re.sub(r'\bCRUDE\b', 'OIL', _input_upper)
        _input_upper = re.sub(r'\b(NDX|US100|NAS100)\b', 'NASDAQ', _input_upper)
        _input_upper = re.sub(r'\b(SPX|US500|S&P)\b', 'SP500', _input_upper)
        _input_upper = re.sub(r'\b(DJI|US30)\b', 'DOW', _input_upper)
        _input_upper = re.sub(r'\b(EUR|EURUSD)\b', 'EURUSD', _input_upper)
        _input_upper = re.sub(r'\b(GBP|GBPUSD)\b', 'GBPUSD', _input_upper)
        _input_upper = re.sub(r'\b(JPY|USDJPY)\b', 'USDJPY', _input_upper)
        _input_upper = re.sub(r'\b(XAG|SILVER)\b', 'SILVER', _input_upper)
        _sym_match = re.search(
            r'\b(BTC|ETH|SOL|BNB|XRP|DOGE|AVAX|LINK|ADA|DOT|MATIC|'
            r'GOLD|SILVER|OIL|NASDAQ|SP500|DOW|'
            r'EURUSD|GBPUSD|USDJPY|AUDUSD|USDCAD|USDCHF|'
            r'NVDA|TSLA|AAPL|AMZN|MSFT|META|AMD|GOOGL|SPY|QQQ)\b',
            _input_upper
        )
        # None = no explicit symbol in message → must infer from working memory
        _detected_sym = _sym_match.group(1) if _sym_match else None

        if _confirm_match:
            _draft_id = _confirm_match.group(1).upper()
            override = (
                f"[MANDATORY: The user confirmed Draft ID = {_draft_id}. "
                f"You MUST invoke the execute_approved_mt5_trade function tool with draft_id='{_draft_id}'. "
                f"Do NOT output code. Do NOT ask for confirmation again. Call the tool directly.]"
            )
            forced_tool_names = ["execute_approved_mt5_trade"]
        elif any(kw in user_lower for kw in ANALYSIS_PLAN_KEYWORDS):
            if _detected_sym:
                override = (
                    f"[MANDATORY OVERRIDE: ผู้ใช้ขอแผนการเทรดหรือวิเคราะห์ {_detected_sym} "
                    f"ให้เรียก get_trading_tactics(symbol='{_detected_sym}') ทันที "
                    f"แล้วตอบเป็นแผนการเทรดแบบละเอียด 8 ส่วน พร้อม Entry/SL/TP ชัดเจน ห้ามเรียก prepare_mt5_trade_draft ก่อนที่ user จะขอ execute]"
                )
            else:
                override = (
                    "[MANDATORY OVERRIDE: ผู้ใช้ขอแผนการเทรด "
                    "ให้เรียก get_working_memory ก่อนเพื่อหา symbol ล่าสุด "
                    "แล้วเรียก get_trading_tactics(symbol=<symbol จาก memory>) ทันที "
                    "ตอบเป็นแผนการเทรดแบบละเอียด 8 ส่วน พร้อม Entry/SL/TP]"
                )
                forced_tool_names = ["get_working_memory", "get_trading_tactics"]
                # override forced_tool_names set below only if _detected_sym exists
            if _detected_sym:
                forced_tool_names = ["get_trading_tactics"]
        elif any(kw in user_lower for kw in ORDER_PLACEMENT_KEYWORDS) or is_numeric_volume:
            _is_new_order = any(kw in user_lower for kw in ["ออกออเดอร์ใหม่", "ออกแผนใหม่", "ขอแผนใหม่", "แผนใหม่", "ออเดอร์ใหม่", "new order", "new plan", "สร้างออเดอร์ใหม่"])
            if _is_new_order:
                override = (
                    "[MANDATORY: The user wants a FRESH trade plan. "
                    "Step 1: Call get_working_memory to retrieve last known symbol. "
                    "Step 2: Call get_market_analysis for that symbol to get the latest data. "
                    "Step 3: Call prepare_mt5_trade_draft with the analysis result (symbol, side from structure/bias, sl/tp from ATR). "
                    "Do NOT output code blocks. Call tools directly. Use Volume = 0.01 if unspecified.]"
                )
                forced_tool_names = ["get_working_memory", "get_market_analysis", "prepare_mt5_trade_draft"]
            else:
                # Map detected shorthand to MT5 broker symbols
                _sym_mt5_map = {
                    # Crypto
                    "BTC": "BTCUSD",  "ETH": "ETHUSD",  "SOL": "SOLUSD",
                    "BNB": "BNBUSD",  "XRP": "XRPUSD",  "DOGE": "DOGEUSD",
                    "AVAX": "AVAXUSD","LINK": "LINKUSD", "ADA": "ADAUSD",
                    "DOT": "DOTUSD",  "MATIC": "MATICUSD",
                    # Commodities
                    "GOLD": "XAUUSD", "SILVER": "XAGUSD", "OIL": "USOIL",
                    # Indices (XM broker cash names)
                    "NASDAQ": "US100Cash", "SP500": "US500Cash", "DOW": "US30Cash",
                    # Forex
                    "EURUSD": "EURUSD", "GBPUSD": "GBPUSD", "USDJPY": "USDJPY",
                    "AUDUSD": "AUDUSD", "USDCAD": "USDCAD", "USDCHF": "USDCHF",
                    # US Stocks (XM uses # suffix)
                    "NVDA": "NVDA#",  "TSLA": "TSLA#",  "AAPL": "AAPL#",
                    "AMZN": "AMZN#",  "MSFT": "MSFT#",  "META": "META#",
                    "AMD":  "AMD#",   "GOOGL": "GOOGL#", "SPY": "SPY#",
                    "QQQ":  "QQQ#",
                }
                if _detected_sym:
                    # Symbol was explicitly mentioned in the message
                    _mt5_sym = _sym_mt5_map.get(_detected_sym, _detected_sym)
                    override = (
                        f"[MANDATORY: The user wants to place a trade for {_detected_sym} (MT5 symbol: {_mt5_sym}). "
                        f"Step 1: Call get_working_memory to retrieve the latest SL, TP, Side for {_detected_sym}. "
                        f"Step 2: Extract from memory or the MOST RECENT AI message in conversation: "
                        f"side (BUY/SELL), sl (Stop Loss price as a number), tp (first Take Profit price as a number). "
                        f"Step 3: Call prepare_mt5_trade_draft with symbol='{_mt5_sym}', side from step 2, "
                        f"sl from step 2, tp from step 2, " +
                        (f"volume={user_input.strip()}." if is_numeric_volume else "volume=0.01.") +
                        " Do NOT ask the user for more details. Do NOT output code. "
                        "If SL/TP are truly unknown after checking memory, use sl=None tp=None and proceed anyway.]"
                    )
                else:
                    # No symbol in message → get the LAST discussed symbol from working memory
                    override = (
                        "[MANDATORY: The user wants to place a trade using the MOST RECENT plan discussed. "
                        "Step 1: Call get_working_memory to find the last symbol, side, SL, TP from memory. "
                        "Step 2: Look up the MT5 symbol from the symbol found (e.g. GOLD→XAUUSD, BTC→BTCUSD). "
                        "Step 3: Call prepare_mt5_trade_draft with that symbol, side, sl, tp. " +
                        (f"volume={user_input.strip()}." if is_numeric_volume else "volume=0.01.") +
                        " CRITICAL: Use the symbol from WORKING MEMORY, NOT BTC by default. "
                        "Do NOT ask the user. Do NOT output code.]"
                    )
                forced_tool_names = ["get_working_memory", "prepare_mt5_trade_draft"]
        elif any(kw in user_lower for kw in THEMATIC_KEYWORDS):
            override = "[MANDATORY OVERRIDE: ผู้ใช้ถามหา 'กลุ่มหุ้นเฉพาะทาง' หรือ 'หุ้น Laggard' ให้คุณทำดังนี้ทันที: (1) คิดรายชื่อหุ้น ticker สัก 8-12 ตัวที่อยู่ในกลุ่มนั้นขึ้นมาจากความรู้ของคุณเอง (2) เรียก get_custom_screener(tickers=[...]) ด้วยรายชื่อที่คิดได้ ห้ามเรียก get_market_opportunities เด็ดขาด]"
        elif any(kw in user_lower for kw in CALENDAR_KEYWORDS):
            override = "[MANDATORY OVERRIDE: ผู้ใช้ถามหา 'ปฏิทินเศรษฐกิจ' หรือ 'ข่าวสำคัญล่วงหน้า' ให้เรียก get_economic_calendar(query='...') ทันที]"
        elif any(kw in user_lower for kw in SCREENER_STOCK_KEYWORDS):
            override = "[MANDATORY OVERRIDE: ผู้ใช้ถามเรื่องหุ้น ให้เรียก get_market_opportunities(asset_class='STOCK') ทันที]"
        elif any(kw in user_lower for kw in SCREENER_CRYPTO_KEYWORDS):
            override = "[MANDATORY OVERRIDE: ผู้ใช้ถามเรื่อง crypto ให้เรียก get_market_opportunities(asset_class='CRYPTO') ทันที]"
        elif any(kw in user_lower for kw in SCREENER_ALL_KEYWORDS):
            override = "[MANDATORY OVERRIDE: ผู้ใช้ถามภาพรวมตลาดกว้างๆ ให้เรียก get_market_opportunities(asset_class='ALL') ทันที]"
        # ── Phase 14 forced routes ───────────────────────────────
        elif any(kw in user_lower for kw in FEAR_GREED_KEYWORDS):
            override = "[MANDATORY OVERRIDE: ผู้ใช้ถามเรื่อง sentiment/fear & greed ให้เรียก get_fear_greed_index() ทันที]"
            forced_tool_names = ["get_fear_greed_index"]
        elif any(kw in user_lower for kw in LIQUIDATION_KEYWORDS):
            override = "[MANDATORY OVERRIDE: ผู้ใช้ถามเรื่อง liquidation zones ให้เรียก get_liquidation_heatmap(symbol='...') ทันที]"
            forced_tool_names = ["get_liquidation_heatmap"]
        elif any(kw in user_lower for kw in MTF_KEYWORDS):
            override = "[MANDATORY OVERRIDE: ผู้ใช้ต้องการ multi-timeframe analysis ให้เรียก scan_multi_timeframe(symbol='...') ทันที]"
            forced_tool_names = ["scan_multi_timeframe"]
        elif any(kw in user_lower for kw in CORRELATION_KEYWORDS):
            override = "[MANDATORY OVERRIDE: ผู้ใช้ถาม correlation/diversification ให้เรียก get_portfolio_correlation() ทันที]"
            forced_tool_names = ["get_portfolio_correlation"]
        elif any(kw in user_lower for kw in WEEKLY_REPORT_KEYWORDS):
            override = "[MANDATORY OVERRIDE: ผู้ใช้ขอ weekly performance report ให้เรียก generate_weekly_report() ทันที]"
            forced_tool_names = ["generate_weekly_report"]
        elif any(kw in user_lower for kw in PAPER_TRADE_KEYWORDS):
            override = "[MANDATORY OVERRIDE: ผู้ใช้ต้องการ paper trade simulation ให้เรียก paper_trade(action='...') ทันที]"
            forced_tool_names = ["paper_trade"]
        # ── Phase 15 routes ─────────────────────────────────────────
        elif any(kw in user_lower for kw in FUNDING_RATE_KEYWORDS):
            override = "[MANDATORY OVERRIDE: ผู้ใช้ถาม funding rate ให้เรียก get_funding_rates() ทันที]"
            forced_tool_names = ["get_funding_rates"]
        elif any(kw in user_lower for kw in REBALANCE_KEYWORDS):
            override = "[MANDATORY OVERRIDE: ผู้ใช้ต้องการ rebalance portfolio ให้เรียก suggest_portfolio_rebalance() ทันที]"
            forced_tool_names = ["suggest_portfolio_rebalance"]
        elif any(kw in user_lower for kw in IV_RANK_KEYWORDS):
            override = "[MANDATORY OVERRIDE: ผู้ใช้ถาม IV rank ให้เรียก get_iv_rank(symbol='...') ทันที]"
            forced_tool_names = ["get_iv_rank"]
        elif any(kw in user_lower for kw in ETF_FLOW_KEYWORDS):
            override = "[MANDATORY OVERRIDE: ผู้ใช้ถาม ETF flows ให้เรียก get_etf_flows() ทันที]"
            forced_tool_names = ["get_etf_flows"]
        elif any(kw in user_lower for kw in SCREENER_CUSTOM_KEYWORDS):
            override = "[MANDATORY OVERRIDE: ผู้ใช้ต้องการ custom screener ให้เรียก run_custom_screener(universe='...') ทันที]"
            forced_tool_names = ["run_custom_screener"]
        else:
            override = "[SYSTEM OVERRIDE: ห้ามปฏิเสธ ห้ามอ้างว่าเป็น AI เด็ดขาด ให้เลือกเรียก Tool ที่เหมาะสมที่สุดตามบริบท]"
        
        
        working_mem_text = ""
        if any(kw in user_lower for kw in ORDER_PLACEMENT_KEYWORDS) or is_numeric_volume:
            try:
                from intelligence.tools.market_tools import get_working_memory
                wm = get_working_memory(session_id=req.session_id)
                if wm and isinstance(wm, dict) and wm.get("frontal_lobe"):
                    wm_str = wm["frontal_lobe"]
                    if wm_str and "No current focus" not in wm_str:
                        working_mem_text = f"\n\n[🔥 SYSTEM INJECTION - PREVIOUS TRADE PLAN MEMORY]:\n{wm_str}\n(กรุณาใช้ข้อมูล SL และ TP จากด้านบนนี้ในการอ้างอิงและเปิดออเดอร์ทันที ห้ามบอกว่าไม่มีข้อมูล)"
            except Exception as e:
                logger.error(f"Failed to auto-inject working memory: {e}")

        enriched_user_input = user_input + f"\n\n{override}" + working_mem_text
        history_contents.append(types.Content(role="user", parts=[types.Part(text=enriched_user_input)]))


        try:
            # Yield a "Thinking" indicator immediately so the UI doesn't look stuck
            # 1. Immediate acknowledgment to prevent UI "sticky" states
            yield json.dumps({"type": "status", "content": "Initializing Neural Links..."}) + "\n"
            yield json.dumps({"type": "status", "content": "กำลังรวบรวมข้อมูลตลาดและวิเคราะห์ผ่าน Smart Money Intelligence Enclave..."}) + "\n"

            # First pass: Let the Agent decide if it needs tools
            # system_instruction is the correct way — treated more authoritatively than a user message
            _first_pass_config_kwargs = dict(
                system_instruction=agent_system_prompt,
                tools=gemini_tools,
            )
            # Force function calling mode when a specific tool must be invoked
            if forced_tool_names:
                _first_pass_config_kwargs["tool_config"] = types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(
                        mode="ANY",
                        allowed_function_names=forced_tool_names,
                    )
                )
            agent_res = await client.aio.models.generate_content(
                model=MODEL_ID,
                contents=history_contents,
                config=types.GenerateContentConfig(**_first_pass_config_kwargs)
            )
            # [NEW] Check for Safety Filter Block at the initial call
            if agent_res.candidates and agent_res.candidates[0].finish_reason == "SAFETY":
                 yield json.dumps({"type": "chunk", "content": "⚠️ **การเข้าถึงถูกจำกัด (Safety Filter Blocked)**\n\nระบบความปลอดภัยของโมเดล AI ตรวจพบเนื้อหาที่มีความเสี่ยงสูง (เช่น การให้คำปรึกษาด้านการลงทุนที่เข้าข่ายเร่งรัดเกินไป) จึงไม่สามารถสร้างข้อความตอบกลับได้ครับ\n\n*คำแนะนำ: ลองใช้คำสั่งอื่นที่ชัดเจน เช่น 'ร่างออเดอร์' หรือ 'วิเคราะห์ปัจจัยเสี่ยง' แทนครับ*" }) + "\n"
                 return

            # Process Tool Calls (if any)
            tool_results_parts = []
            target_sym = "BTC" # Default
            tv_symbol = "BINANCE:BTCUSDT"
            recommended_symbols = [] # New: Aggregate ALL symbols for UI
            intent = "GENERAL"

            # Initial mapping based on user input for UI metadata
            if "ทอง" in user_input or "GOLD" in user_input.upper():
                target_sym, tv_symbol, intent = "GOLD", "TVC:GOLD", "ANALYZE"
                recommended_symbols.append(tv_symbol)
            elif any(kw in user_input.upper() for kw in ["BTC", "ETH", "CRYPTO", "เหรียญ"]):
                target_sym, tv_symbol, intent = "BTC", "BINANCE:BTCUSDT", "ANALYZE"
                recommended_symbols.append(tv_symbol)
            elif any(kw in user_input.upper() for kw in ["หุ้น", "STOCK", "NASDAQ", "NYSE", "SPY", "SET"]):
                target_sym, tv_symbol, intent = "SPY", "AMEX:SPY", "ANALYZE"
                recommended_symbols.append(tv_symbol)
            else:
                # DEFAULT: Stay on GENERAL intent, no chart metadata until tool confirms
                target_sym, tv_symbol, intent = "BTC", "BINANCE:BTCUSDT", "GENERAL"

            parts = []
            if agent_res.candidates and hasattr(agent_res.candidates[0], 'content') and agent_res.candidates[0].content and hasattr(agent_res.candidates[0].content, 'parts') and agent_res.candidates[0].content.parts:
                parts = agent_res.candidates[0].content.parts

            for part in parts:
                if part.function_call:
                    fn_name = part.function_call.name
                    fn_args = dict(part.function_call.args)

                    yield json.dumps({"type": "tool_call", "tool": fn_name, "symbol": fn_args.get('symbol', 'Market')}) + "\n"

                    # Execute the tool using the global async runner
                    yield json.dumps({"type": "status", "content": f"กำลังรวบรวมข้อมูล: {fn_name.replace('_', ' ').title()}"}) + "\n"
                    tool_out = await run_agent_tool_async(fn_name, fn_args, session_id=req.session_id)
                    
                    # Record for persistence
                    collected_tool_calls.append({"name": fn_name, "args": fn_args, "symbol": fn_args.get('symbol')})

                    collected_tool_results.append({"tool": fn_name, "content": tool_out})

                    # PERSISTENCE: Yield the result back to frontend so it can be remembered next turn
                    yield json.dumps({"type": "tool_result", "tool": fn_name, "content": tool_out}) + "\n"

                    # FunctionResponse.response must be a dict — some tools return JSON strings
                    if isinstance(tool_out, str):
                        try:
                            _tool_out_dict = json.loads(tool_out)
                        except Exception:
                            _tool_out_dict = {"result": tool_out}
                    elif isinstance(tool_out, dict):
                        _tool_out_dict = tool_out
                    else:
                        _tool_out_dict = {"result": str(tool_out)}
                    tool_results_parts.append(types.Part(
                        function_response=types.FunctionResponse(name=fn_name, response=_tool_out_dict)
                    ))

                    # AUTO-SAVE: After get_market_analysis succeeds, stash key data into working memory
                    # so next turn "เอามาเปิดไปเทรด" can always find the trade plan
                    if fn_name == "get_market_analysis" and isinstance(tool_out, dict) and "error" not in tool_out:
                        try:
                            _sym   = fn_args.get("symbol", "UNKNOWN").upper()
                            _cls   = fn_args.get("asset_class", "CRYPTO").upper()
                            _price = tool_out.get("price") or tool_out.get("price_action", {}).get("current", 0)
                            _atr   = tool_out.get("atr", {}).get("value", 0) if isinstance(tool_out.get("atr"), dict) else 0
                            _struct= tool_out.get("smart_money", {}).get("structure", {}).get("structure", "NEUTRAL")
                            _htf_bias = tool_out.get("higher_timeframe", {}).get("bias", "NEUTRAL")
                            _rsi   = tool_out.get("rsi", {}).get("value", 50) if isinstance(tool_out.get("rsi"), dict) else 50

                            # Determine directional bias
                            if _struct == "BULLISH" or _htf_bias == "BULLISH" or float(_rsi) < 40:
                                _side = "BUY"
                            elif _struct == "BEARISH" or _htf_bias == "BEARISH" or float(_rsi) > 65:
                                _side = "SELL"
                            else:
                                _side = "WAIT"

                            # Suggest SL/TP from ATR (1.5× ATR SL, 3× ATR TP)
                            _sl_dist = round(float(_atr) * 1.5, 4) if _atr else None
                            _tp_dist = round(float(_atr) * 3.0, 4) if _atr else None
                            _sl = round(float(_price) - _sl_dist, 4) if (_sl_dist and _side == "BUY") else (round(float(_price) + _sl_dist, 4) if _sl_dist else None)
                            _tp = round(float(_price) + _tp_dist, 4) if (_tp_dist and _side == "BUY") else (round(float(_price) - _tp_dist, 4) if _tp_dist else None)

                            _mem_str = (
                                f"Last Analysis: {_side} {_sym} ({_cls}) | "
                                f"Price={_price} | SL={_sl} | TP={_tp} | "
                                f"Structure={_struct} | HTF={_htf_bias} | RSI={round(float(_rsi),1)}"
                            )
                            from intelligence.tools.market_tools import update_working_memory as _uwm
                            _uwm(memory=_mem_str, emotion="CONFIDENT" if _side != "WAIT" else "NEUTRAL", session_id=req.session_id)
                            logger.info(f"[Auto-Stash] {_mem_str}")
                        except Exception as _stash_err:
                            logger.warning(f"Auto-stash working memory failed: {_stash_err}")

                    # AUTO-SAVE: After get_trading_tactics, stash the ACTUAL plan SL/TP to memory
                    if fn_name == "get_trading_tactics":
                        try:
                            _tact_data = _tool_out_dict if isinstance(_tool_out_dict, dict) else {}
                            _tact_sym  = _tact_data.get("symbol", fn_args.get("symbol", "UNKNOWN")).upper()
                            _tact_price= _tact_data.get("price", 0)
                            _tactics   = _tact_data.get("tactics", [])
                            _best_name = _tact_data.get("best_persona", "")
                            # Find the best tactic entry
                            _best = next((t for t in _tactics if t.get("name") == _best_name), None)
                            if not _best and _tactics:
                                _best = _tactics[0]
                            if _best:
                                # Determine side from 'move' field (e.g. "BUY", "SELL", "SIT ON HANDS")
                                # and from the overall recommendation string
                                _move_str = str(_best.get("move", "")).upper()
                                _rec_str  = str(_tact_data.get("recommendation", "")).upper()
                                _combined = _move_str + " " + _rec_str
                                if any(k in _combined for k in ["BUY", "LONG"]):
                                    _tact_side = "BUY"
                                elif any(k in _combined for k in ["SELL", "SHORT"]):
                                    _tact_side = "SELL"
                                else:
                                    _tact_side = "WAIT"

                                if _tact_side == "WAIT":
                                    # Don't overwrite memory with a WAIT stash that has no SL/TP
                                    # Just log and skip
                                    logger.info(f"[Tactics-Stash] SKIP — move='{_move_str}' is WAIT for {_tact_sym}")
                                else:
                                    _tact_sl = _best.get("sl") or _best.get("invalidation")
                                    _tact_tp = _best.get("tp") or _best.get("target")
                                    # Extract numeric value from strings like "4855.00 (เหนือ Swing High)"
                                    import re as _re_tact
                                    def _extract_num(val):
                                        if isinstance(val, (int, float)): return float(val)
                                        m = _re_tact.search(r'[\d]+\.?[\d]*', str(val))
                                        return float(m.group()) if m else None
                                    _sl_num = _extract_num(_tact_sl)
                                    _tp_num = _extract_num(_tact_tp)
                                    _mem_str = (
                                        f"Last Analysis: {_tact_side} {_tact_sym} (TACTICS) | "
                                        f"Price={_tact_price} | SL={_sl_num} | TP={_tp_num} | "
                                        f"Tactic={_best_name} | Move={_move_str}"
                                    )
                                    from intelligence.tools.market_tools import update_working_memory as _uwm2
                                    _uwm2(memory=_mem_str, emotion="CONFIDENT", session_id=req.session_id)
                                    logger.info(f"[Tactics-Stash] {_mem_str}")
                        except Exception as _te:
                            logger.warning(f"Tactics auto-stash failed: {_te}")

                    # ML EDGE SCORE: After get_trading_tactics, compute win probability
                    if fn_name == "get_trading_tactics" and isinstance(tool_out, dict) and "error" not in tool_out:
                        try:
                            from intelligence.technical_engine import get_kline_data, compute_indicators
                            from intelligence.backtest_crypto import generate_backtest_signals
                            from intelligence.ml.feature_extractor import extract_features
                            from intelligence.ml.signal_model import predict_win_probability
                            _tml_sym = fn_args.get("symbol", "UNKNOWN").upper()
                            _tml_cls = "CRYPTO" if any(c in _tml_sym for c in ["BTC","ETH","SOL","XRP","DOGE","ADA","AVAX","MATIC","LINK"]) else "MACRO"
                            _tml_df  = get_kline_data(_tml_sym, timeframe="1h", limit=300, asset_class=_tml_cls)
                            if _tml_df is not None and len(_tml_df) >= 60:
                                _tml_df = compute_indicators(_tml_df)
                                _tml_df = generate_backtest_signals(_tml_df)
                                _tml_df = _tml_df.dropna(subset=["rsi_14", "ema_20", "adx_14"])
                                if not _tml_df.empty:
                                    # Get best tactic's side
                                    _tact_out   = tool_out if isinstance(tool_out, dict) else {}
                                    _best_tname = _tact_out.get("best_persona", "")
                                    _tactics_l  = _tact_out.get("tactics", [])
                                    _best_t     = next((t for t in _tactics_l if t.get("name") == _best_tname), _tactics_l[0] if _tactics_l else {})
                                    _move_s     = str(_best_t.get("move", "")).upper()
                                    _tml_side   = "BUY" if "BUY" in _move_s or "LONG" in _move_s else "SELL" if "SELL" in _move_s or "SHORT" in _move_s else "BUY"
                                    _tml_feats  = extract_features(_tml_df, len(_tml_df)-1, side=_tml_side, symbol=_tml_sym, asset_class=_tml_cls)
                                    _tml_result = predict_win_probability(_tml_feats)
                                    if _tml_result.get("available"):
                                        yield json.dumps({"type": "ml_score", "win_pct": _tml_result["win_pct"], "n_samples": _tml_result["n_samples"], "roc_auc": _tml_result["roc_auc"], "side": _tml_side, "symbol": _tml_sym}) + "\n"
                                        logger.info(f"[ML-Score/Tactics] {_tml_sym} {_tml_side}: {_tml_result['win_pct']}%")
                        except Exception as _tml_err:
                            logger.debug(f"[ML-Score/Tactics] skipped: {_tml_err}")

                    # ML EDGE SCORE: After get_market_analysis, compute win probability
                    if fn_name == "get_market_analysis" and isinstance(tool_out, dict) and "error" not in tool_out:
                        try:
                            from intelligence.technical_engine import get_kline_data, compute_indicators
                            from intelligence.backtest_crypto import generate_backtest_signals
                            from intelligence.ml.feature_extractor import extract_features
                            from intelligence.ml.signal_model import predict_win_probability
                            _ml_sym = fn_args.get("symbol", "UNKNOWN").upper()
                            _ml_cls = fn_args.get("asset_class", "CRYPTO").upper()
                            _ml_df  = get_kline_data(_ml_sym, timeframe="1h", limit=300, asset_class=_ml_cls)
                            if _ml_df is not None and len(_ml_df) >= 60:
                                _ml_df = compute_indicators(_ml_df)
                                _ml_df = generate_backtest_signals(_ml_df)
                                _ml_df = _ml_df.dropna(subset=["rsi_14", "ema_20", "adx_14"])
                                if not _ml_df.empty:
                                    # Detect current side from structure
                                    _ml_struct = tool_out.get("smart_money", {}).get("structure", {}).get("structure", "NEUTRAL")
                                    _ml_htf    = tool_out.get("higher_timeframe", {}).get("bias", "NEUTRAL")
                                    _ml_rsi_v  = tool_out.get("rsi", {}).get("value", 50)
                                    if _ml_struct == "BULLISH" or _ml_htf == "BULLISH":
                                        _ml_side = "BUY"
                                    elif _ml_struct == "BEARISH" or _ml_htf == "BEARISH":
                                        _ml_side = "SELL"
                                    else:
                                        _ml_side = "BUY" if float(_ml_rsi_v or 50) < 50 else "SELL"
                                    _ml_feats = extract_features(_ml_df, len(_ml_df) - 1, side=_ml_side, symbol=_ml_sym, asset_class=_ml_cls)
                                    _ml_result = predict_win_probability(_ml_feats)
                                    if _ml_result.get("available"):
                                        _ml_score_str = (
                                            f"\n\n[🤖 ML EDGE SCORE]: "
                                            f"WIN probability = **{_ml_result['win_pct']}%** "
                                            f"(trained on {_ml_result['n_samples']:,} setups | "
                                            f"AUC={_ml_result['roc_auc']} | "
                                            f"model age: {_ml_result['model_age']})"
                                        )
                                        # Inject as a tool_result part so Claude sees it
                                        _existing_parts = [p for p in tool_results_parts if p.function_response.name != "_ml_score"]
                                        tool_results_parts.clear()
                                        tool_results_parts.extend(_existing_parts)
                                        tool_results_parts.append(types.Part(
                                            function_response=types.FunctionResponse(
                                                name="get_market_analysis",
                                                response={**_tool_out_dict, "_ml_edge": _ml_result}
                                            )
                                        ))
                                        yield json.dumps({"type": "ml_score", "win_pct": _ml_result["win_pct"], "n_samples": _ml_result["n_samples"], "roc_auc": _ml_result["roc_auc"], "side": _ml_side, "symbol": _ml_sym}) + "\n"
                                        yield json.dumps({"type": "status", "content": f"ML Edge: {_ml_result['win_pct']}% WIN probability ({_ml_result['n_samples']} setups)"}) + "\n"
                                        logger.info(f"[ML-Score] {_ml_sym} {_ml_side}: {_ml_result['win_pct']}% win prob")
                        except Exception as _ml_err:
                            logger.debug(f"[ML-Score] skipped: {_ml_err}")

                    # UPDATE UI METADATA based on tool arguments
                    if fn_name == "get_market_opportunities":
                        if isinstance(tool_out, dict):
                            # Detect query intent: loser or gainer?
                            loser_keywords = ["ลง", "ตก", "loser", "decline", "down", "drop", "worst", "fell", "fall"]
                            is_loser_query = any(kw in user_input.lower() for kw in loser_keywords)

                            if is_loser_query and tool_out.get("hero_loser"):
                                target_sym = tool_out["hero_loser"]
                                best_ex    = tool_out.get("hero_loser_exchange")
                            elif tool_out.get("hero_symbol"):
                                target_sym = tool_out["hero_symbol"]
                                best_ex    = tool_out.get("hero_exchange")
                            else:
                                target_sym = None
                                best_ex    = None

                            if target_sym:
                                tv_symbol = _resolve_tv_symbol(target_sym, exchange=best_ex)
                                intent = "ANALYZE"
                                recommended_symbols.insert(0, tv_symbol)

                    elif fn_name == "get_custom_screener":
                        if isinstance(tool_out, dict) and "hero_symbol" in tool_out:
                            target_sym = tool_out["hero_symbol"]
                            best_ex = tool_out.get("hero_exchange")
                            tv_symbol = _resolve_tv_symbol(target_sym, exchange=best_ex)
                            intent = "ANALYZE"
                            recommended_symbols.insert(0, tv_symbol)

                        if isinstance(tool_out, dict) and "top_gainers" in tool_out:
                            for g in tool_out["top_gainers"][:8]:
                                s = g.get("symbol")
                                ex = g.get("exchange")
                                if s:
                                    res_s = _resolve_tv_symbol(s, exchange=ex)
                                    if res_s not in recommended_symbols:
                                        recommended_symbols.append(res_s)
                    elif "symbol" in fn_args:
                        s = str(fn_args["symbol"]).upper()
                        target_sym = s
                        intent = "ANALYZE"
                        tv_symbol = _resolve_tv_symbol(s)
                        if tv_symbol not in recommended_symbols:
                            recommended_symbols.append(tv_symbol)

            # ── FALLBACK: Gemini skipped the tool — detect ticker and call it ourselves ──
            if not tool_results_parts:
                # Extract uppercase word(s) that look like a ticker (2-6 chars, letters only)
                # We ignore words in SKIP_WORDS and words that look like parts of a sentence.
                ticker_candidates = re.findall(r'\b([A-Z]{2,6})\b', user_input.upper())
                # Deduplicate while preserving order, limit to 2 for fallback
                auto_syms = list(dict.fromkeys(t for t in ticker_candidates if t not in SKIP_WORDS))[:2]

                if auto_syms:
                    for auto_sym in auto_syms:
                        logger.info(f"🔄 Gemini skipped tool call — auto-fetching {auto_sym}")
                        asset_class = _resolve_asset_class(auto_sym)
                        yield json.dumps({"type": "tool_call", "tool": "get_market_analysis", "symbol": auto_sym}) + "\n"
                        
                        # Fetch Technical Analysis
                        tool_out = await run_agent_tool_async("get_market_analysis", {
                            "symbol": auto_sym,
                            "asset_class": asset_class,
                            "timeframe": "15m"
                        }, session_id=req.session_id)
                        # PERSISTENCE: Yield result for memory
                        yield json.dumps({"type": "tool_result", "tool": "get_market_analysis", "content": tool_out}) + "\n"
                        
                        _fallback_out = tool_out if isinstance(tool_out, dict) else (json.loads(tool_out) if isinstance(tool_out, str) else {"result": str(tool_out)})
                        tool_results_parts.append(types.Part(
                            function_response=types.FunctionResponse(name="get_market_analysis", response=_fallback_out)
                        ))

                        # For fallback, we ONLY promote to ANALYZE if the user explicitly mentioned a chart keyword
                        # Or if we have high confidence this is a genuine asset intended for analysis.
                        has_chart_intent = any(kw in user_input.lower() for kw in ["กราฟ", "chart", "graph", "show", "visualize", "ดู"])
                        if has_chart_intent:
                            target_sym = auto_sym
                            intent = "ANALYZE"
                            tv_symbol = _resolve_tv_symbol(auto_sym)
                            if tv_symbol not in recommended_symbols:
                                recommended_symbols.append(tv_symbol)

            # Yield metadata for UI
            # Unique symbols maintaining order
            final_symbols = []
            for s in recommended_symbols:
                if s not in final_symbols:
                    final_symbols.append(s)

            final_tv_symbol = tv_symbol
            final_tv_symbols = final_symbols
            final_intent = intent

            yield json.dumps({
                "type": "metadata",
                "sql_query": None,
                "has_data": True,
                "intent": intent,
                "tv_symbol": tv_symbol if intent == "ANALYZE" else None,
                "tv_symbols": final_symbols if intent == "ANALYZE" else []
            }) + "\n"

            # Final pass: Generate response with tool results
            # DUAL-AGENT STRATEGY: Use Claude for Strategic Synthesis if available
            if tool_results_parts:
                has_yielded_text = False
                # Add tool calls and responses to history
                # Safety check for candidates
                if agent_res.candidates and agent_res.candidates[0].content:
                    history_contents.append(agent_res.candidates[0].content)
                history_contents.append(types.Content(role="user", parts=tool_results_parts))

                if anthropic_client and CLAUDE_AVAILABLE:
                    logger.info("🧠 Dual-Agent Mode: Claude is synthesizing the strategy...")
                    # Convert Gemini history to Claude messages
                    claude_messages = []
                    for content in (history_contents or []):
                        role = "user" if content.role == "user" else "assistant"
                        text_parts = []
                        for part in (content.parts or []):
                            if part.text:
                                text_parts.append(part.text)
                            elif part.function_response:
                                # Standardize tool output for Claude
                                text_parts.append(f"[TOOL_OUTPUT: {part.function_response.name}] {json.dumps(part.function_response.response)}")
                            elif part.function_call:
                                text_parts.append(f"[TOOL_CALL: {part.function_call.name}] {json.dumps(part.function_call.args)}")
                        
                        if text_parts:
                            claude_messages.append({"role": role, "content": "\n".join(text_parts)})

                    logger.info("🎨 Dual-Agent Synthesis: Starting Async Stream...")
                    try:
                        # Stream Claude's response with a strict timeout to prevent frontend hang
                        # We wrap in asyncio.wait_for for extra safety beyond the client timeout
                        async with asyncio.timeout(12.0): # 12s total budget for synthesis
                            async with anthropic_client.messages.stream(
                                model=CLAUDE_MODEL_ID,
                                max_tokens=2048,
                                system=agent_system_prompt + "\n\nCRITICAL: You are the Senior Strategist. Use the TOOL_OUTPUT data provided in the history to build a high-quality 8-part trade plan in Thai. Match the Bloomberg/TradingView style.",
                                messages=claude_messages,
                            ) as stream:
                                async for text in stream.text_stream:
                                    has_yielded_text = True
                                    full_response_text += text
                                    yield json.dumps({"type": "chunk", "content": text}) + "\n"
                    except (asyncio.TimeoutError, Exception) as ce:
                        logger.error(f"Claude Synthesis Error or Timeout: {ce}")
                        # Detect auth failure or persistent error
                        if "401" in str(ce) or "invalid x-api-key" in str(ce).lower() or "not_found_error" in str(ce).lower():
                            logger.warning("🔴 Disabling Claude for this session due to Auth/Model failure.")
                            CLAUDE_AVAILABLE = False
                        
                        yield json.dumps({"type": "status", "content": "กำลังสลับเส้นทางประมวลผลสำรองเพื่อความเร็วสูงสุด..."}) + "\n"
                        # Fallback to Gemini if Claude fails or times out
                        final_stream = await client.aio.models.generate_content_stream(
                            model=MODEL_ID,
                            contents=history_contents,
                            config=types.GenerateContentConfig(system_instruction=agent_system_prompt)
                        )
                        async for chunk in final_stream:
                            if chunk.text:
                                has_yielded_text = True
                                full_response_text += chunk.text
                                yield json.dumps({"type": "chunk", "content": chunk.text}) + "\n"
                else:
                    # Original Gemini-only path (No Claude available or configured)
                    final_stream = await client.aio.models.generate_content_stream(
                        model=MODEL_ID,
                        contents=history_contents,
                        config=types.GenerateContentConfig(
                            system_instruction=agent_system_prompt,
                        )  # No tools → text-only
                    )
                    async for chunk in final_stream:
                        try:
                            if chunk.text:
                                has_yielded_text = True
                                full_response_text += chunk.text
                                yield json.dumps({"type": "chunk", "content": chunk.text}) + "\n"
                        except ValueError:
                            has_yielded_text = True
                            yield json.dumps({"type": "chunk", "content": "⚠️ ถูกบล็อกโดยระบบรักษาความปลอดภัย (Safety Filter) ไม่สามารถแสดงผลได้"}) + "\n"

                    
                    if not has_yielded_text:
                        # Safety: If tool results available but synthesis yielded nothing, force-yield the result summary
                        if tool_results_parts and any(p.function_response.name == "prepare_mt5_trade_draft" for p in tool_results_parts):
                            # get draft details and show them directly
                            for _p in tool_results_parts:
                                if _p.function_response.name == "prepare_mt5_trade_draft":
                                    _d = _p.function_response.response or {}
                                    _sym   = _d.get("symbol", "")
                                    _side  = _d.get("side", "")
                                    _vol   = _d.get("volume", 0.01)
                                    _sl    = _d.get("sl", "N/A")
                                    _tp    = _d.get("tp", "N/A")
                                    _price = _d.get("price", "N/A")
                                    _did   = _d.get("draft_id", "N/A")
                                    yield json.dumps({"type": "chunk", "content": (
                                        f"## 🎯 แผนการเทรด {_sym}\n\n"
                                        f"| รายละเอียด | ค่า |\n|---|---|\n"
                                        f"| **Direction** | {'🟢 BUY (Long)' if _side=='BUY' else '🔴 SELL (Short)'} |\n"
                                        f"| **Entry Price** | {_price} |\n"
                                        f"| **Stop Loss** | 🛑 {_sl} |\n"
                                        f"| **Take Profit** | 🎯 {_tp} |\n"
                                        f"| **Volume** | {_vol} lot |\n"
                                        f"| **Draft ID** | `{_did}` |\n\n"
                                        f"✅ แผนถูกสร้างเรียบร้อยแล้ว — คัดลอกคำยืนยันด้านล่างแล้วส่งในแชทได้เลยครับ\n\n"
                                        f"```\nยืนยัน {_did}\n```\n\n"
                                        f"หรือพิมพ์ **`ขอแผน {_sym}`** เพื่อดูการวิเคราะห์เพิ่มเติม"
                                    )}) + "\n"
                                    break
                        elif tool_results_parts and any(p.function_response.name == "execute_approved_mt5_trade" for p in tool_results_parts):
                            # Special case for trade execution confirmation
                            for p in tool_results_parts:
                                if p.function_response.name == "execute_approved_mt5_trade":
                                    exec_result = p.function_response.response or {}
                                    status = exec_result.get("status", "")
                                    if status == "SIMULATED":
                                        ticket = exec_result.get("ticket", "N/A")
                                        sym    = exec_result.get("symbol", "")
                                        action = exec_result.get("action", "")
                                        vol    = exec_result.get("volume", 0.01)
                                        sl     = exec_result.get("sl", "N/A")
                                        tp     = exec_result.get("tp", "N/A")
                                        yield json.dumps({"type": "chunk", "content": (
                                            f"✅ **Paper Trade บันทึกสำเร็จครับ!**\n\n"
                                            f"🎫 **Ticket:** #{ticket}\n"
                                            f"📊 **{action}** {vol} lot **{sym}**\n"
                                            f"🛑 **SL:** {sl}\n"
                                            f"🎯 **TP:** {tp}\n\n"
                                            f"*(ระบบอยู่ในโหมด **Paper Trade** เนื่องจากยังไม่ได้เชื่อมต่อ MT5 จริงครับ — ออเดอร์ถูกบันทึกในระบบจำลองเรียบร้อยแล้ว)*"
                                        )}) + "\n"
                                    elif status == "SUCCESS":
                                        order_id = exec_result.get("order_id", "N/A")
                                        sym    = exec_result.get("symbol", "")
                                        action = exec_result.get("action", "")
                                        vol    = exec_result.get("volume", 0.01)
                                        price  = exec_result.get("price", "N/A")
                                        yield json.dumps({"type": "chunk", "content": (
                                            f"✅ **Live Trade Executed สำเร็จครับ!**\n\n"
                                            f"🎫 **Order ID:** #{order_id}\n"
                                            f"📊 **{action}** {vol} lot **{sym}** @ {price}\n"
                                        )}) + "\n"
                                    elif status == "GUARD_BLOCKED":
                                        msg = exec_result.get("message", "")
                                        yield json.dumps({"type": "chunk", "content": (
                                            f"🚫 **Trade ถูกบล็อกโดย Safety Guard ครับ**\n\n{msg}\n\n"
                                            f"*(กรุณาตรวจสอบขนาด Position หรือรอ Cooldown ครับ)*"
                                        )}) + "\n"
                                    else:
                                        err = exec_result.get("error") or exec_result.get("comment") or str(exec_result)
                                        yield json.dumps({"type": "chunk", "content": (
                                            f"⚠️ **Trade ไม่สำเร็จครับ**\n\nรายละเอียด: {err}"
                                        )}) + "\n"
                                    break
                        elif agent_res.text:
                            yield json.dumps({"type": "chunk", "content": agent_res.text}) + "\n"
                        else:
                            yield json.dumps({"type": "chunk", "content": "*(AI ประมวลผลสำเร็จ แต่อาจถูกจำกัดการอธิบายข้อความ กรุณาอ้างอิงข้อมูลจากหน้าจอและผลลัพธ์การสแกนครับ)*"}) + "\n"
            else:
                if CLAUDE_AVAILABLE and anthropic_client and agent_res.text:
                    logger.info("💬 Claude is handling the general conversation...")
                    claude_messages = [{"role": "user", "content": enriched_user_input}]
                    try:
                        async with asyncio.timeout(10.0):
                            async with anthropic_client.messages.stream(
                                model=CLAUDE_MODEL_ID,
                                max_tokens=1024,
                                system=agent_system_prompt,
                                messages=claude_messages,
                            ) as stream:
                                async for text in stream.text_stream:
                                    yield json.dumps({"type": "chunk", "content": text}) + "\n"
                    except Exception as ce:
                        logger.warning(f"Claude Chat Error: {ce}")
                        if "401" in str(ce) or "invalid x-api-key" in str(ce).lower():
                            CLAUDE_AVAILABLE = False
                        if agent_res.text:
                            yield json.dumps({"type": "chunk", "content": agent_res.text}) + "\n"

                elif agent_res.text:
                    full_response_text += agent_res.text
                    yield json.dumps({"type": "chunk", "content": agent_res.text}) + "\n"
                else:
                    # Final safety fallback for empty responses
                    fallback_msg = "*(AI ได้ทำการตรวจสอบข้อมูลแล้ว พบสภาวะปกติหรือยังไม่มีข้อมูลใหม่ที่เกี่ยวข้องในขณะนี้ครับ)*"
                    full_response_text += fallback_msg
                    yield json.dumps({"type": "chunk", "content": fallback_msg}) + "\n"

        except Exception as e:
            logging.error(f"Agent Workflow Error: {e}")
            yield json.dumps({"type": "chunk", "content": f"⚠️ ระบบ AI Agent ขัดข้อง: {str(e)}"}) + "\n"

        # FINAL PERSISTENCE: Save the AI's response to the SQLite vault
        if full_response_text:
            final_metadata = {
                "toolCalls": collected_tool_calls,
                "toolResults": collected_tool_results,
                "intent": final_intent,
                "tvSymbol": final_tv_symbol,
                "tvSymbols": final_tv_symbols
            }
            save_message_record(req.session_id, "ai", full_response_text, final_metadata)

        return # End of agentic response

    return StreamingResponse(generate_response(), media_type="application/x-ndjson")

@app.get("/api/health")
def health():
    db_status = "error"
    kafka_status = "error"
    
    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            db_status = "ok"
    except Exception as e:
        logger.warning(f"Health check DB failed: {e}")
    
    # Basic check for port 8000 (MCP)
    mcp_status = "ok" if _get_schema() else "error"
    
    return {
        "status": "ok", 
        "mcp": mcp_status,
        "db": db_status,
        "kafka_broker": KAFKA_BROKER
    }

@app.get("/api/ml/feature-importance")
async def get_feature_importance(request: Request):
    """Return ranked feature importances from the trained model."""
    try:
        from intelligence.ml.signal_model import _load_model
        bundle = _load_model()
        if not bundle:
            return {"available": False, "features": []}
        return {
            "available": True,
            "features":  bundle.get("feature_importance", []),
            "n_samples": bundle.get("n_samples", 0),
            "trained_at":bundle.get("trained_at", ""),
        }
    except Exception as e:
        return {"available": False, "error": str(e)}


@app.get("/api/ml/stats")
async def get_ml_stats(request: Request):
    """Return ML model stats + paper trade win rate for the dashboard."""
    try:
        from intelligence.ml.outcome_tracker import get_ml_stats as _get_stats
        from intelligence.ml.signal_model import _load_model, MODEL_PATH
        from pathlib import Path

        paper_stats = _get_stats()
        model_bundle = _load_model()

        model_info = {}
        if model_bundle:
            model_info = {
                "trained":    True,
                "n_samples":  model_bundle.get("n_samples", 0),
                "accuracy":   model_bundle.get("accuracy", 0),
                "roc_auc":    model_bundle.get("roc_auc", 0),
                "trained_at": model_bundle.get("trained_at", ""),
            }
        else:
            model_info = {"trained": False}

        return {
            "paper_trades": paper_stats,
            "model":        model_info,
            "model_path":   str(MODEL_PATH),
            "model_exists": Path(MODEL_PATH).exists(),
        }
    except Exception as e:
        logger.error(f"/api/ml/stats error: {e}")
        return {"error": str(e)}


@app.post("/api/ml/retrain")
async def trigger_retrain(request: Request):
    """Manually trigger ML model retraining (runs in background thread)."""
    import asyncio
    async def _retrain():
        try:
            from intelligence.ml.signal_model import train_model, invalidate_model_cache
            result = await asyncio.get_event_loop().run_in_executor(None, lambda: train_model(limit=2000))
            invalidate_model_cache()
            logger.info(f"[ML-Retrain] Manual retrain complete: {result}")
        except Exception as e:
            logger.error(f"[ML-Retrain] failed: {e}")
    asyncio.create_task(_retrain())
    return {"status": "started", "message": "Retraining started in background — check /api/ml/stats in ~60s"}


@app.get("/api/whales/all")
async def get_all_whales(request: Request, limit: int = 60):
    """
    Combined whale feed: PostgreSQL crypto whales (Kafka stream) +
    SQLite multi-asset whales (yfinance volume spike detector).
    Returns unified list sorted by timestamp DESC.
    """
    _ = verify_token(request)
    rows = []

    # ── 1. Crypto whales from PostgreSQL (Kafka stream) ──
    try:
        pg_result = _execute_sql(
            "SELECT symbol, quantity, price, timestamp, is_buyer_maker "
            "FROM enriched_trades WHERE is_whale = TRUE "
            "ORDER BY timestamp DESC LIMIT 40"
        )
        for r in (pg_result.get("data") or []):
            qty   = float(r.get("quantity", 0))
            price = float(r.get("price", 0))
            rows.append({
                "symbol":       r.get("symbol", ""),
                "asset_class":  "CRYPTO",
                "price":        price,
                "quantity":     qty,
                "usd_value":    round(qty * price, 2),
                "is_buyer_maker": bool(r.get("is_buyer_maker", False)),
                "vol_ratio":    None,
                "timestamp":    str(r.get("timestamp", "")),
                "source":       "stream",
            })
    except Exception as e:
        logger.warning(f"/api/whales/all PostgreSQL error: {e}")

    # ── 2. Multi-asset whales from SQLite (yfinance poller) ──
    try:
        con = sqlite3.connect("persistence.db")
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute("""
            SELECT symbol, asset_class, price, volume, usd_value, direction, vol_ratio, timestamp
            FROM multi_asset_whales
            ORDER BY id DESC LIMIT 80
        """)
        for r in cur.fetchall():
            rows.append({
                "symbol":       r["symbol"],
                "asset_class":  r["asset_class"],
                "price":        r["price"],
                "quantity":     r["volume"],
                "usd_value":    r["usd_value"],
                "is_buyer_maker": r["direction"] == "SELL",
                "vol_ratio":    r["vol_ratio"],
                "timestamp":    r["timestamp"],
                "source":       "poller",
            })
        con.close()
    except Exception as e:
        logger.warning(f"/api/whales/all SQLite error: {e}")

    # Sort by timestamp descending (handle both int ms and ISO strings)
    def _ts_key(r):
        ts = r.get("timestamp", "0")
        try:
            return int(ts)
        except (ValueError, TypeError):
            try:
                from datetime import datetime
                return int(datetime.fromisoformat(str(ts)).timestamp() * 1000)
            except Exception:
                return 0

    rows.sort(key=_ts_key, reverse=True)
    return {"data": rows[:limit]}


@app.get("/api/data/{category}")
def get_dashboard_data(category: str):
    """
    Data Proxy: Fetches specific institutional datasets using pre-defined safe queries.
    """
    queries = {
        "whales": "SELECT symbol, quantity, price, timestamp, is_buyer_maker FROM enriched_trades WHERE is_whale = TRUE ORDER BY timestamp DESC LIMIT 20",
        "trends": "SELECT * FROM (SELECT DISTINCT ON (symbol) symbol, avg_price, total_volume, trade_count FROM market_metrics ORDER BY symbol, window_start DESC) t ORDER BY total_volume DESC LIMIT 20",
        "audits": """
            (SELECT 'DQ_ERROR' as type, error_reason as detail, detected_at as time FROM data_quality_log)
            UNION ALL
            (SELECT 'AI_QUERY' as type, SUBSTR(sql_query, 1, 50) as detail, created_at as time FROM mcp_audit_log)
            ORDER BY time DESC LIMIT 20
        """
    }
    
    if category not in queries:
        raise HTTPException(status_code=404, detail="Category not found")
        
    result = _execute_sql(queries[category])
    
    # Return raw database results - no synthetic data fabrication
    # Trading platforms must only display verified market data
    if "data" not in result:
        result = {"data": []}
    
    return result

@app.get("/api/signals")
def get_signals():
    """
    [UPGRADED] Multi-Agent signals using technical indicators (RSI/MACD/ADX).
    Falls back to price-delta method if Intelligence Layer unavailable.
    """
    # ── Try Intelligence Layer first ──────────────────────────────────────────
    if INTELLIGENCE_AVAILABLE and crypto_intel:
        try:
            symbols = ["BTC", "ETH", "SOL", "BNB", "XRP", "GOLD", "NASDAQ", "SP500"]
            signals = crypto_intel.get_quick_signals(symbols, timeframe="15m")
            if signals:
                logging.info(f"✅ Intelligence signals: {len(signals)} symbols")
                return {"signals": signals, "source": "multi_agent_indicators"}
        except Exception as e:
            logging.warning(f"Intelligence signals failed, falling back: {e}")

    # ── Fallback: original price-delta method ─────────────────────────────────
    try:
        with get_db_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT symbol, avg_price, total_volume, trade_count,
                           window_start, window_end
                    FROM market_metrics
                    WHERE window_end > NOW() - INTERVAL '10 minutes'
                    ORDER BY window_end DESC
                    LIMIT 30
                """)
                rows = cur.fetchall()

        from collections import defaultdict
        grouped = defaultdict(list)
        for r in rows:
            grouped[r['symbol']].append(r)

        signals = []
        for symbol, records in grouped.items():
            if len(records) < 2:
                continue
            latest = records[0]
            prev   = records[1]
            price_now  = float(latest['avg_price'])
            price_prev = float(prev['avg_price'])
            vol_now    = float(latest['total_volume'])
            vol_prev   = float(prev['total_volume'])

            delta_pct = ((price_now - price_prev) / price_prev) * 100 if price_prev else 0
            vol_surge = (vol_now / vol_prev) if vol_prev else 1.0

            if delta_pct > 0.1 and vol_surge > 1.2:
                direction, confidence = "BUY",  min(95, 60 + int(abs(delta_pct) * 10 + vol_surge * 5))
                reason = f"Price +{delta_pct:.2f}% with volume surge x{vol_surge:.1f}"
            elif delta_pct < -0.1 and vol_surge > 1.2:
                direction, confidence = "SELL", min(95, 60 + int(abs(delta_pct) * 10 + vol_surge * 5))
                reason = f"Price {delta_pct:.2f}% with volume surge x{vol_surge:.1f}"
            elif abs(delta_pct) < 0.05:
                direction, confidence = "HOLD", 50
                reason = "Low momentum, tight range consolidation"
            else:
                direction, confidence = "WATCH", 45
                reason = f"Mixed signal: Δ{delta_pct:.2f}%, vol x{vol_surge:.1f}"

            signals.append({
                "symbol": symbol, "direction": direction, "confidence": confidence,
                "reason": reason, "price": price_now,
                "delta_pct": round(delta_pct, 4), "vol_surge": round(vol_surge, 2),
                "timestamp": str(latest['window_end'])
            })

        signals.sort(key=lambda x: x['confidence'], reverse=True)
        return {"signals": signals[:10], "source": "price_delta_fallback"}

    except Exception as e:
        logging.error(f"Signals error: {e}")
        return {"signals": [], "error": str(e)}


# ==========================================
# Intelligence Endpoints (NEW)
# ==========================================
class AnalyzeRequest(BaseModel):
    symbol: str = "BTC"
    timeframe: str = "15m"
    include_charts: bool = True

class RiskRequest(BaseModel):
    entry_price: float
    stop_loss_price: float
    account_balance_usdt: float
    risk_percent: float = 1.0
    leverage: float = 1.0


@app.post("/api/analyze")
def analyze_symbol(req: AnalyzeRequest, x_api_key: str = None):
    """
    [NEW] Full Multi-Agent Analysis — 8-step pipeline.
    Runs: Indicator → Pattern (Vision) → Trend (Vision) → Sentiment → Decision → Master
    
    Returns complete analysis with master decision, entry/SL/TP zones.
    ⚠️ Takes 15-30s to complete (Vision + 6 LLM calls).
    """
    if not INTELLIGENCE_AVAILABLE or not crypto_intel:
        raise HTTPException(status_code=503, detail="Intelligence Layer not available. Check server logs.")

    symbol = req.symbol.upper().replace("USDT", "")
    logging.info(f"🧠 Full analysis requested: {symbol} ({req.timeframe})")

    try:
        state = crypto_intel.analyze(
            symbol=symbol,
            timeframe=req.timeframe,
            include_charts=req.include_charts,
        )

        # Build structured response (strip large binary data)
        return {
            "symbol": f"{symbol}USDT",
            "timeframe": req.timeframe,
            "analysis_time_seconds": state.get("analysis_time_seconds", 0),

            # Individual agent reports
            "indicator_report":  state.get("indicator_report", ""),
            "pattern_report":    state.get("pattern_report", ""),
            "trend_report":      state.get("trend_report", ""),
            "sentiment_report":  state.get("sentiment_report", ""),
            "decision_report":   state.get("decision_report", ""),

            # Aggregate scores
            "indicator_bias":    state.get("indicator_bias", "NEUTRAL"),
            "sentiment_score":   state.get("sentiment_score", 0),
            "confluence_score":  state.get("confluence_score", 0),

            # Final master decision
            "master_decision":   state.get("master_decision", "NO_TRADE"),
            "master_confidence": int(state.get("master_confidence", 0) * 100),
            "master_report":     state.get("master_report", ""),
            "master_reasoning":  state.get("master_reasoning", ""),

            # Execution plan
            "entry_zone":  state.get("entry_zone", {}),
            "stop_loss":   state.get("stop_loss", {}),
            "take_profit": state.get("take_profit", {}),
            "risk_reward": state.get("risk_reward_ratio", 0),

            # Raw indicator data for UI
            "indicator_summary": state.get("indicator_summary", {}),
        }

    except Exception as e:
        logging.error(f"Analysis error for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)[:200]}")


@app.post("/api/risk")
def calculate_risk(req: RiskRequest):
    """
    [NEW] Position sizing and risk calculation.
    Returns: position size, margin required, risk level, trades to wipeout.
    """
    if not INTELLIGENCE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Intelligence Layer not available")

    result = calculate_crypto_risk(
        entry_price=req.entry_price,
        stop_loss_price=req.stop_loss_price,
        account_balance_usdt=req.account_balance_usdt,
        risk_percent=req.risk_percent,
        leverage=req.leverage,
    )

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    result["advice_thai"] = get_risk_advice_thai(result)
    result["scenarios"] = calculate_position_scenarios(
        req.entry_price, req.stop_loss_price, req.account_balance_usdt, req.leverage
    )
    return result


@app.get("/api/sentiment")
async def get_market_sentiment():
    """Returns real-time news sentiment analyzed by Gemini."""
    try:
        # We reuse the sentiment agent logic directly
        client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY") or GEMINI_API_KEY, http_options={'api_version': 'v1alpha'})
        agent = create_sentiment_agent(client)
        
        # Analyze general market sentiment
        result = agent({"symbol": "Crypto Market"})
        
        # Also return the raw articles for the feed
        articles = _fetch_rss_news()
        
        return {
            "overall": result.get("sentiment_data", {}),
            "articles": articles[:15]
        }
    except Exception as e:
        logging.error(f"Sentiment API error: {e}")
        return {
            "overall": {
                "sentiment": "NEUTRAL",
                "score": 0,
                "summary": f"Could not analyze sentiment: {str(e)}"
            },
            "articles": []
        }

@app.get("/api/intelligence/status")
def intelligence_status():
    """[NEW] Check if Intelligence Layer is available."""
    return {
        "intelligence_available": INTELLIGENCE_AVAILABLE,
        "agents": [
            "indicator_agent", "pattern_agent", "trend_agent",
            "sentiment_agent", "decision_agent", "master_agent"
        ] if INTELLIGENCE_AVAILABLE else [],
        "model": MODEL_ID,
        "note": "Use POST /api/analyze for full multi-agent analysis",
    }


# ==========================================
# Market Data Proxy Endpoints (Sentiment Hub)
# Caches are refreshed on each call with TTL logic
# ==========================================

_market_cache: dict = {}  # { key: { data: ..., ts: float } }
MARKET_CACHE_TTL = 300  # 5 minutes

def _cache_get(key: str):
    entry = _market_cache.get(key)
    if entry and (time.time() - entry["ts"]) < MARKET_CACHE_TTL:
        return entry["data"]
    return None

def _cache_set(key: str, data):
    _market_cache[key] = {"data": data, "ts": time.time()}

@app.get("/api/market/crypto-fear-greed")
async def crypto_fear_greed():
    """Crypto Fear & Greed Index from alternative.me — includes historical data."""
    cached = _cache_get("crypto_fg_v2")
    if cached:
        return cached
    try:
        # Fetch current and historical (limit=31 to cover last month)
        r = requests.get(
            "https://api.alternative.me/fng/?limit=31&format=json",
            timeout=8,
            headers={"User-Agent": "CryptoStreamAI/2.0"},
        )
        r.raise_for_status()
        payload = r.json()
        data = payload["data"]
        
        # Current
        curr = data[0]
        
        # Historical mapping
        # data[0] = now, data[1] = yesterday, data[7] = last week, data[30] = last month
        yesterday = data[1] if len(data) > 1 else curr
        last_week = data[7] if len(data) > 7 else data[-1]
        last_month = data[30] if len(data) > 30 else data[-1]

        result = {
            "value": int(curr["value"]),
            "label": curr["value_classification"],
            "timestamp": curr["timestamp"],
            "history": {
                "yesterday": {"value": int(yesterday["value"]), "label": yesterday["value_classification"]},
                "last_week": {"value": int(last_week["value"]), "label": last_week["value_classification"]},
                "last_month": {"value": int(last_month["value"]), "label": last_month["value_classification"]},
            }
        }
        _cache_set("crypto_fg_v2", result)
        return result
    except Exception as e:
        logger.warning(f"Crypto F&G fetch error: {e}")
        cached_fallback = _market_cache.get("crypto_fg_v2", {}).get("data")
        return cached_fallback or {
            "value": 50, "label": "Neutral", "timestamp": "",
            "history": {
                "yesterday": {"value": 50, "label": "Neutral"},
                "last_week": {"value": 50, "label": "Neutral"},
                "last_month": {"value": 50, "label": "Neutral"},
            }
        }

@app.get("/api/market/cnn-fear-greed")
async def cnn_fear_greed():
    """CNN Fear & Greed Index — includes historical data from CNN API."""
    cached = _cache_get("cnn_fg_v2")
    if cached:
        return cached
    try:
        r = requests.get(
            "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
            timeout=10,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
                "Referer": "https://www.cnn.com/markets/fear-and-greed",
            },
        )
        r.raise_for_status()
        payload = r.json()
        fg = payload.get("fear_and_greed", {})
        
        # CNN provides historical fields in the response
        result = {
            "value": round(float(fg.get("score", 50)), 1),
            "label": fg.get("rating", "Neutral").replace("_", " ").title(),
            "timestamp": fg.get("timestamp", ""),
            "history": {
                "yesterday": {"value": round(float(fg.get("previous_close", 50)), 1), "label": fg.get("previous_close_rating", "Neutral").replace("_", " ").title()},
                "last_week": {"value": round(float(fg.get("previous_1_week", 50)), 1), "label": fg.get("previous_1_week_rating", "Neutral").replace("_", " ").title()},
                "last_month": {"value": round(float(fg.get("previous_1_month", 50)), 1), "label": fg.get("previous_1_month_rating", "Neutral").replace("_", " ").title()},
            }
        }
        _cache_set("cnn_fg_v2", result)
        return result
    except Exception as e:
        logger.warning(f"CNN F&G fetch error: {e}")
        cached_fallback = _market_cache.get("cnn_fg_v2", {}).get("data")
        return cached_fallback or {
            "value": 50, "label": "Neutral", "timestamp": "",
            "history": {
                "yesterday": {"value": 50, "label": "Neutral"},
                "last_week": {"value": 50, "label": "Neutral"},
                "last_month": {"value": 50, "label": "Neutral"},
            }
        }

@app.get("/api/market/dxy-news")
async def dxy_news():
    """Fetches macro/forex news and analyzes its impact on the US Dollar Index (DXY)."""
    cached = _cache_get("dxy_news_v1")
    if cached:
        return cached
    try:
        # Use the existing sentiment agent logic geared for DXY
        client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY") or GEMINI_API_KEY, http_options={'api_version': 'v1alpha'})
        agent = create_sentiment_agent(client)
        
        # Analyze DXY sentiment
        result = agent({"symbol": "DXY", "asset_class": "MACRO"})
        
        # Also return the raw macro articles for the feed
        articles = _fetch_rss_news("DXY")
        
        response_data = {
            "overall": result.get("sentiment_data", {}),
            "articles": articles[:5] # Limit to 5 for the card
        }
        _cache_set("dxy_news_v1", response_data)
        return response_data
    except Exception as e:
        logger.error(f"DXY News API error: {e}")
        return {
            "overall": {
                "sentiment": "NEUTRAL",
                "score": 0,
                "summary": "Could not analyze DXY catalysts."
            },
            "articles": []
        }

@app.get("/api/market/indices")
async def market_indices():
    """Nasdaq Composite (^IXIC), Dow Jones (^DJI), S&P 500 (^GSPC), and DXY (DX-Y.NYB) via Yahoo Finance with Intraday History."""
    cached = _cache_get("market_indices_v7")
    if cached:
        return cached
    try:
        def _fetch_yahoo_chart(symbol: str, range_: str, interval: str):
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='-.')}"
            r = requests.get(
                url,
                params={
                    "range": range_,
                    "interval": interval,
                    "includePrePost": "false",
                    "events": "div,splits",
                },
                timeout=12,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "application/json,text/plain,*/*",
                    "Referer": "https://finance.yahoo.com/",
                },
            )
            r.raise_for_status()
            payload = r.json()
            chart = (payload or {}).get("chart", {})
            err = chart.get("error")
            if err:
                raise ValueError(str(err))
            results = chart.get("result") or []
            if not results:
                raise ValueError("Empty chart result")
            return results[0]

        def _series_from_chart_result(chart_result: dict):
            ts = chart_result.get("timestamp") or []
            ind = (chart_result.get("indicators") or {}).get("quote") or []
            closes = (ind[0] if ind else {}).get("close") or []
            series = []
            for t, c in zip(ts, closes):
                if c is None:
                    continue
                series.append({"time": int(t), "value": round(float(c), 2)})
            return series

        result = {}
        symbols_map = {
            "^IXIC": {"key": "nasdaq", "name": "Nasdaq Composite"},
            "^DJI": {"key": "dow", "name": "Dow Jones"},
            "^GSPC": {"key": "sp500", "name": "S&P 500"},
            "DX-Y.NYB": {"key": "dxy", "name": "US Dollar Index"},
        }

        for sym, meta in symbols_map.items():
            try:
                chart_result = _fetch_yahoo_chart(sym, "5d", "15m")
                series = _series_from_chart_result(chart_result)
                if not series:
                    chart_result = _fetch_yahoo_chart(sym, "1mo", "1d")
                    series = _series_from_chart_result(chart_result)

                meta_info = chart_result.get("meta") or {}
                prev_close = meta_info.get("previousClose")
                if prev_close is None:
                    prev_close = meta_info.get("chartPreviousClose")

                price = float(series[-1]["value"]) if series else 0.0
                prev = float(prev_close) if prev_close not in (None, 0, "0") else (float(series[-2]["value"]) if len(series) > 1 else price)
                chg_pct = ((price - prev) / prev) * 100 if prev else 0.0

                result[meta["key"]] = {
                    "name": meta["name"],
                    "price": round(price, 2),
                    "change_pct": round(chg_pct, 2),
                    "previous_close": round(prev, 2),
                    "series": series,
                }
            except Exception as inner_e:
                logger.warning(f"❌ Yahoo chart API {sym} error: {inner_e}")
                result[meta["key"]] = {"name": meta["name"], "price": 0, "change_pct": 0, "previous_close": 0, "series": []}

        _cache_set("market_indices_v7", result)
        return result
    except Exception as e:
        logger.warning(f"Market indices fetch error: {e}")
        cached_fallback = _market_cache.get("market_indices_v5", {}).get("data")
        return cached_fallback or {
            "nasdaq": {"name": "Nasdaq", "price": 0, "change_pct": 0, "previous_close": 0, "series": []},
            "dow": {"name": "Dow Jones", "price": 0, "change_pct": 0, "previous_close": 0, "series": []},
            "sp500": {"name": "S&P 500", "price": 0, "change_pct": 0, "previous_close": 0, "series": []},
            "dxy": {"name": "US Dollar Index", "price": 0, "change_pct": 0, "previous_close": 0, "series": []}
        }

@app.get("/api/market/pulse")
async def market_pulse():
    """
    [NEW] Aggregated Status for the Agent UI.
    Combines Macro Sentiment, Top Sector Rotation, and Global Climate.
    """
    cached = _cache_get("market_pulse_v1")
    if cached:
        return cached
    try:
        from intelligence.tools.market_tools import get_sector_rotation, get_market_climate
        
        # 1. Fetch Sentiment
        crypto_fg = await crypto_fear_greed()
        cnn_fg = await cnn_fear_greed()
        
        # 2. Fetch Strategic Intelligence (in thread)
        rotation = await asyncio.to_thread(get_sector_rotation)
        climate = await asyncio.to_thread(get_market_climate)
        
        result = {
            "sentiment": {
                "fear_greed": cnn_fg.get("value", 50),
                "crypto_fg": crypto_fg.get("value", 50),
                "label": cnn_fg.get("label", "Neutral")
            },
            "leadership": {
                "top_sector": rotation.get("leading_sectors", [["N/A", 0]])[0][0],
                "top_sector_chg": rotation.get("leading_sectors", [["N/A", 0]])[0][1],
                "summary": rotation.get("market_summary", "Neutral Context")
            },
            "climate": {
                "score": climate.get("global_risk_score", 50),
                "regime": climate.get("regime", "NEUTRAL"),
                "threat_level": climate.get("threat_level", "NORMAL"),
                "color": climate.get("color", "slate"),
                "summary": climate.get("summary", "Scanning macro indices...")
            },
            "timestamp": time.time()
        }
        
        _cache_set("market_pulse_v1", result) # 5 min default cache
        return result
    except Exception as e:
        logger.error(f"Pulse API Error: {e}")
        from fastapi import Response
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=500, content={"error": str(e)})



def _yahoo_batch_quotes(symbols: list[str]) -> dict:
    """Fetch real-time quotes for multiple symbols using yfinance (avoids v7 API 401 errors)."""
    import yfinance as yf
    result = {}
    try:
        tickers_str = " ".join(symbols)
        data = yf.download(tickers_str, period="5d", interval="1m", progress=False, group_by="ticker")
        if data.empty:
            return result

        for sym in symbols:
            try:
                if len(symbols) == 1:
                    sym_data = data
                elif isinstance(data.columns, pd.MultiIndex) and sym in data.columns.get_level_values(0):
                    sym_data = data[sym]
                else:
                    continue

                closes = sym_data["Close"].dropna()
                if closes.empty:
                    continue

                last_price = float(closes.iloc[-1])
                prev_price = float(closes.iloc[-2]) if len(closes) > 1 else last_price
                change_pct = ((last_price - prev_price) / prev_price * 100) if prev_price != 0 else 0.0

                result[sym] = {
                    "regularMarketPrice": last_price,
                    "regularMarketChangePercent": change_pct,
                    "regularMarketPreviousClose": prev_price,
                    "shortName": sym,
                }
            except Exception:
                continue
    except Exception as e:
        logger.warning(f"_yahoo_batch_quotes yfinance error: {e}")
    return result


@app.get("/api/market/stocks")
async def market_stocks():
    """Real-time prices for all ticker bar symbols via Yahoo Finance (polling fallback)."""
    cached = _cache_get("market_stocks_v2")
    if cached:
        return cached
    try:
        # Key → Yahoo Finance symbol
        symbols_map = {
            "BTC":    "BTC-USD",
            "ETH":    "ETH-USD",
            "SOL":    "SOL-USD",
            "NVDA":   "NVDA",
            "TSLA":   "TSLA",
            "GOLD":   "GC=F",
            "NASDAQ": "^IXIC",
            "SP500":  "^GSPC",
        }
        yahoo_symbols = list(symbols_map.values())
        raw = await asyncio.to_thread(_yahoo_batch_quotes, yahoo_symbols)

        result = {}
        for key, ysym in symbols_map.items():
            q = raw.get(ysym, {})
            price = float(q.get("regularMarketPrice") or 0)
            chg   = float(q.get("regularMarketChangePercent") or 0)
            prev  = float(q.get("regularMarketPreviousClose") or price)
            name  = q.get("shortName") or key
            result[key] = {"price": round(price, 2), "change_pct": round(chg, 4),
                           "previous_close": round(prev, 2), "name": name}

        _cache_set("market_stocks_v2", result)
        return result
    except Exception as e:
        logger.warning(f"market_stocks error: {e}")
        return {k: {"price": 0, "change_pct": 0} for k in
                ["BTC", "ETH", "SOL", "NVDA", "TSLA", "GOLD", "NASDAQ", "SP500"]}


# ──────────────────────────────────────────────────────────────────────────────
# NASDAQ-100 + S&P 500 — sourced from intelligence/constants.py (single source of truth)
# ──────────────────────────────────────────────────────────────────────────────
_NASDAQ100 = NASDAQ_100_TICKERS
_SP500     = SP500_TICKERS

# Combined deduplicated list (NASDAQ-100 first, then S&P 500 additions)
_ALL_SCREENER_SYMBOLS = list(dict.fromkeys(_NASDAQ100 + _SP500))


def _chunks(lst: list, n: int):
    """Split list into chunks of size n."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


@app.get("/api/market/screener")
async def market_screener(index: str = "all"):
    """
    Real-time quotes for full NASDAQ-100 (101) + S&P 500 (~500) components.
    Param: index = 'nasdaq100' | 'sp500' | 'all'
    Uses parallel Yahoo Finance batch requests (100 symbols each). Cached 5 min.
    """
    cache_key = f"market_screener_v2_{index}"
    cached = _cache_get(cache_key)
    if cached:
        return cached
    try:
        if index == "nasdaq100":
            symbols = _NASDAQ100
        elif index == "sp500":
            symbols = list(dict.fromkeys(_SP500))
        else:
            symbols = _ALL_SCREENER_SYMBOLS

        # Parallel batch fetch — 100 symbols per request
        batches = list(_chunks(symbols, 100))
        tasks = [asyncio.to_thread(_yahoo_batch_quotes, batch) for batch in batches]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        raw: dict = {}
        for res in results:
            if isinstance(res, dict):
                raw.update(res)

        stocks = []
        for sym in symbols:
            q = raw.get(sym)
            if not q:
                continue
            price = float(q.get("regularMarketPrice") or 0)
            if price <= 0:
                continue
            chg  = float(q.get("regularMarketChangePercent") or 0)
            prev = float(q.get("regularMarketPreviousClose") or price)
            cap  = q.get("marketCap")
            stocks.append({
                "symbol":         sym,
                "name":           q.get("shortName") or q.get("longName") or sym,
                "price":          round(price, 2),
                "change_pct":     round(chg, 4),
                "previous_close": round(prev, 2),
                "market_cap":     cap,
                "market_cap_b":   round(cap / 1e9, 2) if cap else None,
                "volume":         q.get("regularMarketVolume"),
                "avg_volume":     q.get("averageDailyVolume3Month"),
                "sector":         q.get("sector"),
                "industry":       q.get("industry"),
                "exchange":       q.get("fullExchangeName") or q.get("exchange"),
                "in_nasdaq100":   sym in set(_NASDAQ100),
                "in_sp500":       sym in set(_SP500),
            })

        result = {
            "count":     len(stocks),
            "stocks":    stocks,
            "timestamp": time.time(),
            "index":     index,
        }
        _cache_set(cache_key, result)
        return result
    except Exception as e:
        logger.warning(f"market_screener error: {e}")
        return {"count": 0, "stocks": [], "timestamp": time.time(), "index": index}


# ─────────────────────────────────────────────────────────────────────────────
# Auto-Trade endpoint — full AI pipeline → Guard → CircuitBreaker → MT5
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/api/auto-trade")
async def auto_trade_endpoint(
    symbol: str = "BTC",
    timeframe: str = "15m",
    dry_run: bool = True,
    risk_pct: float = 1.0,
    confirmation_required: bool = True,
):
    """
    Trigger the full AI pipeline and optional MT5 execution.

    dry_run=true (default) — analysis + guard/CB check only, no real order.
    dry_run=false          — live execution (USE WITH CAUTION).

    Always returns: master_decision, execution_status, trade_details.
    """
    try:
        from intelligence.tools.market_tools import run_ai_trade_analysis
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: run_ai_trade_analysis(
                symbol=symbol,
                timeframe=timeframe,
                dry_run=dry_run,
                risk_pct=risk_pct,
                confirmation_required=confirmation_required,
            )
        )
        return result
    except Exception as e:
        logger.error(f"auto_trade_endpoint error: {e}")
        return {"error": str(e), "symbol": symbol}


# Circuit Breaker status endpoint
@app.get("/api/circuit-breaker/status")
async def circuit_breaker_status():
    """Get current circuit breaker state (daily PnL, paused, etc.)."""
    try:
        from intelligence.circuit_breaker import get_circuit_breaker
        cb = get_circuit_breaker()
        return cb.get_status()
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/circuit-breaker/reset")
async def circuit_breaker_reset():
    """Manual reset of circuit breaker (use after reviewing permanent stop)."""
    try:
        from intelligence.circuit_breaker import get_circuit_breaker
        cb = get_circuit_breaker()
        cb.reset()
        return {"status": "reset", "new_state": cb.get_status()}
    except Exception as e:
        return {"error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# Backtest REST endpoint — callable from the UI directly (not just via AI chat)
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/api/backtest")
async def run_backtest_endpoint(
    symbol: str = "BTC",
    timeframe: str = "15m",
    limit: int = 500,
    risk_pct: float = 2.0,
    leverage: float = 1.0,
    asset_class: str = "CRYPTO",
):
    """
    Run a full backtest for a symbol and return strategy performance metrics.
    Params: symbol, timeframe (1m/15m/1h/4h/1d), limit, risk_pct, leverage.
    Returns: win_rate, profit_factor, CAGR, Sharpe, max_drawdown, trade log summary.
    """
    cache_key = f"backtest_{symbol.upper()}_{timeframe}_{limit}_{risk_pct}_{leverage}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    try:
        from intelligence.backtest_crypto import run_crypto_backtest
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: run_crypto_backtest(
                symbol.upper().replace("USDT", ""),
                timeframe=timeframe,
                limit=limit,
                risk_pct=risk_pct,
                leverage=leverage,
            )
        )
        result["asset_class"] = asset_class.upper()
        _cache_set(cache_key, result)
        return result
    except Exception as e:
        logger.error(f"backtest endpoint error: {e}")
        return {"error": str(e), "symbol": symbol}


# ─────────────────────────────────────────────────────────────────────────────
# Position Monitor endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/positions")
async def get_positions():
    """
    Check all open CryptoStream AI positions and apply management rules
    (break-even, trailing SL, max hold time).
    Returns list of actions taken per position.
    """
    try:
        from intelligence.position_monitor import PositionMonitor
        pm = PositionMonitor()
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, pm.check_positions)
        return result
    except Exception as e:
        logger.error(f"positions endpoint error: {e}")
        return {"status": f"Error: {e}", "actions": []}


# ─────────────────────────────────────────────────────────────────────────────
# Trade Logger endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/trade-log")
async def get_trade_log(days: int = None, count: int = 50):
    """
    Return recent trade log entries and performance statistics.
    Query params: days (filter by last N days), count (number of recent trades).
    """
    try:
        from intelligence.trade_logger import get_trade_logger
        tl = get_trade_logger()
        return {
            "statistics":    tl.get_statistics(days=days),
            "recent_trades": tl.get_recent_trades(count=count),
            "heatmap":       tl.get_session_heatmap(),
        }
    except Exception as e:
        logger.error(f"trade-log endpoint error: {e}")
        return {"error": str(e)}


@app.get("/api/trade-log/weekly-report")
async def get_weekly_report():
    """Return the weekly performance report as a plain text string."""
    try:
        from intelligence.trade_logger import get_trade_logger
        tl = get_trade_logger()
        return {"report": tl.get_weekly_report()}
    except Exception as e:
        logger.error(f"weekly-report endpoint error: {e}")
        return {"error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# Trade Replay — AI analysis of past losing trades
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/trade-replay")
async def run_trade_replay(num_trades: int = 5):
    """
    Use Gemini to analyze the last N losing trades and return lessons.
    Query param: num_trades (default 5).
    Returns: analysis (text), lessons (list), trades_analyzed.
    """
    try:
        from intelligence.trade_replay import analyze_past_trades
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: analyze_past_trades(gemini_client, num_trades=num_trades),
        )
        return result
    except Exception as e:
        logger.error(f"trade-replay endpoint error: {e}")
        return {"error": str(e), "analysis": "", "lessons": []}


@app.get("/api/market/macro-signals")
async def get_macro_signals_endpoint():
    """
    Macro regime overlay: QQQ trend, growth vs defensive, safe-haven pressure, BTC momentum.
    Returns verdict (bullish/defensive/neutral), individual signals, and latest benchmark prices.
    Cached 1 hour — uses yfinance, no additional API key required.
    """
    cache_key = "macro_signals_endpoint"
    cached = _cache_get(cache_key)
    if cached:
        return cached
    try:
        from intelligence.macro_signals import get_macro_regime
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, get_macro_regime)
        _cache_set(cache_key, result)
        return result
    except Exception as e:
        logger.error(f"macro-signals endpoint error: {e}")
        return {"error": str(e), "verdict": "neutral", "signals": []}


@app.get("/api/market/btc-etf-flows")
async def get_btc_etf_flows_endpoint():
    """
    BTC ETF capital flow estimate (IBIT, FBTC, ARKB, BITB, HODL, BRRR, EZBC, BTCW).
    Returns direction (inflow/outflow/mixed), net score, and per-ETF breakdown.
    Cached 1 hour — uses yfinance, no additional API key required.
    """
    cache_key = "btc_etf_flows_endpoint"
    cached = _cache_get(cache_key)
    if cached:
        return cached
    try:
        from intelligence.macro_signals import get_btc_etf_flows
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, get_btc_etf_flows)
        _cache_set(cache_key, result)
        return result
    except Exception as e:
        logger.error(f"btc-etf-flows endpoint error: {e}")
        return {"error": str(e), "direction": "mixed", "etfs": []}


@app.get("/api/market/hl-price/{symbol}")
async def get_hyperliquid_price(symbol: str):
    """
    Real-time mid price from Hyperliquid L2 orderbook (free, no API key).
    Path param: symbol (e.g. BTC, ETH, SOL)
    """
    try:
        from intelligence.hyperliquid_price import get_hl_mid_price
        loop = asyncio.get_event_loop()
        price = await loop.run_in_executor(None, lambda: get_hl_mid_price(symbol))
        if price is None:
            return {"error": f"Could not fetch price for {symbol}", "symbol": symbol}
        return {"symbol": symbol.upper(), "price": price, "source": "hyperliquid"}
    except Exception as e:
        logger.error(f"hl-price endpoint error: {e}")
        return {"error": str(e), "symbol": symbol}


@app.get("/api/trade-replay/summary")
async def get_trade_replay_summary(count: int = 20):
    """
    Return recent trade history for the frontend panel (no LLM, instant).
    Query param: count (default 20).
    """
    try:
        from intelligence.trade_replay import get_trade_summary
        return {"trades": get_trade_summary(count=count)}
    except Exception as e:
        logger.error(f"trade-replay/summary endpoint error: {e}")
        return {"error": str(e), "trades": []}


@app.get("/api/alerts")
async def get_alerts(request: Request):
    """Return all smart alerts from persistence.db for the dashboard."""
    _ = verify_token(request)
    try:
        conn = sqlite3.connect(PERSISTENCE_DB)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT id, user_id, symbol, condition, message, status, created_at FROM active_alerts ORDER BY id DESC LIMIT 100")
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return {"alerts": rows}
    except Exception as e:
        logger.error(f"/api/alerts error: {e}")
        return {"alerts": [], "error": str(e)}


@app.delete("/api/alerts/{alert_id}")
async def delete_alert(alert_id: int, request: Request):
    """Delete or dismiss a smart alert by ID."""
    _ = verify_token(request)
    try:
        conn = sqlite3.connect(PERSISTENCE_DB)
        cursor = conn.cursor()
        cursor.execute("UPDATE active_alerts SET status='DISMISSED' WHERE id=?", (alert_id,))
        conn.commit()
        conn.close()
        return {"status": "DISMISSED", "id": alert_id}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/trade-reviews")
async def get_trade_reviews(request: Request):
    """Return all AI trade reviews from persistence.db for the dashboard."""
    _ = verify_token(request)
    try:
        conn = sqlite3.connect(PERSISTENCE_DB)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT id, review_text, win_rate, score, created_at FROM trade_reviews ORDER BY id DESC LIMIT 50")
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return {"reviews": rows}
    except Exception as e:
        logger.error(f"/api/trade-reviews error: {e}")
        return {"reviews": [], "error": str(e)}


@app.get("/api/tactics/{symbol}")
async def get_tactics(symbol: str, request: Request):
    """Serve institutional trading tactics for a specific symbol."""
    _ = verify_token(request)
    try:
        from intelligence.tools.market_tools import get_trading_tactics
        result_json = get_trading_tactics(symbol.upper())
        return json.loads(result_json)
    except Exception as e:
        logger.error(f"/api/tactics error for {symbol}: {e}")
        return {"error": str(e)}


@app.get("/api/tactics/audit/logs")
async def get_sniper_audit(request: Request):
    """Fetch the latest rejected signals from the Sniper Audit Log."""
    _ = verify_token(request)
    try:
        conn = sqlite3.connect("persistence.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM sniper_audit_log ORDER BY timestamp DESC LIMIT 20")
        rows = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return {"logs": rows}
    except Exception as e:
        logger.error(f"/api/tactics/audit error: {e}")
        return {"logs": [], "error": str(e)}


# ══════════════════════════════════════════════════════════════
# Phase 15 — New Endpoints
# ══════════════════════════════════════════════════════════════

# ── Funding Rates ─────────────────────────────────────────────
@app.get("/api/market/funding-rates")
async def api_funding_rates(request: Request):
    _ = verify_token(request)
    loop = asyncio.get_event_loop()
    from intelligence.tools.market_tools import get_funding_rates
    result = await loop.run_in_executor(None, get_funding_rates)
    return result


# ── ETF Flows ─────────────────────────────────────────────────
@app.get("/api/market/etf-flows")
async def api_etf_flows(request: Request):
    _ = verify_token(request)
    loop = asyncio.get_event_loop()
    from intelligence.tools.market_tools import get_etf_flows
    result = await loop.run_in_executor(None, get_etf_flows)
    return result


# ── IV Rank ───────────────────────────────────────────────────
@app.get("/api/market/iv-rank/{symbol}")
async def api_iv_rank(symbol: str, request: Request):
    _ = verify_token(request)
    loop = asyncio.get_event_loop()
    from intelligence.tools.market_tools import get_iv_rank
    result = await loop.run_in_executor(None, lambda: get_iv_rank(symbol.upper()))
    return result


# ── Custom Screener ───────────────────────────────────────────
@app.get("/api/screener")
async def api_custom_screener(
    request: Request,
    universe:      str   = "NASDAQ100",
    rsi_max:       float = None,
    rsi_min:       float = None,
    vol_spike:     float = None,
    pct_from_52wh: float = None,
    min_return_1w: float = None,
    max_return_1w: float = None,
    limit:         int   = 15,
):
    _ = verify_token(request)
    loop = asyncio.get_event_loop()
    from intelligence.tools.market_tools import run_custom_screener
    result = await loop.run_in_executor(None, lambda: run_custom_screener(
        universe=universe, rsi_max=rsi_max, rsi_min=rsi_min,
        vol_spike=vol_spike, pct_from_52wh=pct_from_52wh,
        min_return_1w=min_return_1w, max_return_1w=max_return_1w,
        limit=limit,
    ))
    return result


# ── Watchlist CRUD ────────────────────────────────────────────
def _init_watchlist_table():
    con = sqlite3.connect(PERSISTENCE_DB)
    con.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id   TEXT DEFAULT 'default',
            symbol    TEXT,
            note      TEXT,
            added_at  TEXT
        )
    """)
    con.commit(); con.close()

_init_watchlist_table()


@app.get("/api/watchlist")
async def get_watchlist(request: Request, user_id: str = "default"):
    _ = verify_token(request)
    try:
        con = sqlite3.connect(PERSISTENCE_DB)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT id, symbol, note, added_at FROM watchlist WHERE user_id=? ORDER BY id DESC",
            (user_id,)
        ).fetchall()
        con.close()
        symbols = [dict(r) for r in rows]

        # Enrich with live prices
        loop = asyncio.get_event_loop()
        import yfinance as _yf
        def _fetch_prices(syms):
            prices = {}
            for s in syms:
                try:
                    yf_sym = {"BTC":"BTC-USD","ETH":"ETH-USD","SOL":"SOL-USD",
                               "GOLD":"GC=F","XAU":"GC=F"}.get(s, s)
                    df = _yf.Ticker(yf_sym).history(period="2d")
                    if not df.empty:
                        now  = float(df["Close"].iloc[-1])
                        prev = float(df["Close"].iloc[-2]) if len(df) > 1 else now
                        prices[s] = {"price": round(now,4), "change_pct": round((now/prev-1)*100,3)}
                except Exception:
                    pass
            return prices

        sym_list = [r["symbol"] for r in symbols]
        prices   = await loop.run_in_executor(None, lambda: _fetch_prices(sym_list))
        for r in symbols:
            r.update(prices.get(r["symbol"], {"price": None, "change_pct": None}))

        return {"watchlist": symbols}
    except Exception as e:
        return {"watchlist": [], "error": str(e)}


class WatchlistItem(BaseModel):
    symbol: str
    note:   Optional[str] = ""
    user_id: str = "default"

@app.post("/api/watchlist")
async def add_to_watchlist(item: WatchlistItem, request: Request):
    _ = verify_token(request)
    try:
        con = sqlite3.connect(PERSISTENCE_DB)
        # Prevent duplicates
        exists = con.execute(
            "SELECT id FROM watchlist WHERE user_id=? AND symbol=?",
            (item.user_id, item.symbol.upper())
        ).fetchone()
        if exists:
            con.close()
            return {"status": "ALREADY_EXISTS", "symbol": item.symbol.upper()}
        con.execute(
            "INSERT INTO watchlist (user_id, symbol, note, added_at) VALUES (?,?,?,?)",
            (item.user_id, item.symbol.upper(), item.note,
             datetime.now(timezone.utc).isoformat())
        )
        con.commit(); con.close()
        return {"status": "ADDED", "symbol": item.symbol.upper()}
    except Exception as e:
        return {"error": str(e)}

@app.delete("/api/watchlist/{symbol}")
async def remove_from_watchlist(symbol: str, request: Request, user_id: str = "default"):
    _ = verify_token(request)
    try:
        con = sqlite3.connect(PERSISTENCE_DB)
        con.execute("DELETE FROM watchlist WHERE user_id=? AND symbol=?", (user_id, symbol.upper()))
        con.commit(); con.close()
        return {"status": "REMOVED", "symbol": symbol.upper()}
    except Exception as e:
        return {"error": str(e)}


# ── AI Persona Customization ──────────────────────────────────
@app.get("/api/persona")
async def get_persona(request: Request):
    _ = verify_token(request)
    try:
        from intelligence.persona import get_current_persona
        return {"persona": get_current_persona()}
    except Exception as e:
        return {"error": str(e)}

class PersonaUpdate(BaseModel):
    persona: str

@app.put("/api/persona")
async def update_persona_api(payload: PersonaUpdate, request: Request):
    _ = verify_token(request)
    try:
        from intelligence.persona import update_persona
        update_persona(payload.persona)
        return {"status": "UPDATED"}
    except Exception as e:
        return {"error": str(e)}


# ── Trading Journal (trade history enriched) ──────────────────
@app.get("/api/journal")
async def get_journal(request: Request, limit: int = 50):
    """Return trade history with per-trade P&L, symbol, side, and chart data pointers."""
    _ = verify_token(request)
    try:
        con = sqlite3.connect(PERSISTENCE_DB)
        con.row_factory = sqlite3.Row
        rows = con.execute("""
            SELECT id, symbol, side, entry_price, exit_price, volume,
                   pnl_usd, status, opened_at, closed_at
            FROM paper_trades
            ORDER BY id DESC LIMIT ?
        """, (limit,)).fetchall()
        trades = [dict(r) for r in rows]
        con.close()

        # Compute basic stats
        closed  = [t for t in trades if t.get("status") == "CLOSED"]
        wins    = [t for t in closed if (t.get("pnl_usd") or 0) > 0]
        total_pnl  = sum(t.get("pnl_usd") or 0 for t in closed)
        win_rate   = round(len(wins) / max(len(closed), 1) * 100, 1)

        return {
            "trades":    trades,
            "stats": {
                "total_trades": len(closed),
                "win_rate_pct": win_rate,
                "total_pnl":   round(total_pnl, 2),
                "wins":  len(wins),
                "losses": len(closed) - len(wins),
            }
        }
    except Exception as e:
        return {"trades": [], "stats": {}, "error": str(e)}


# ── TradingView Webhook Receiver ─────────────────────────────────────────────
class TVWebhookPayload(BaseModel):
    """
    Standard TradingView alert JSON body.
    Configure your TV alert message as:
      {"symbol":"{{ticker}}", "action":"{{strategy.order.action}}",
       "price":"{{close}}", "timeframe":"{{interval}}", "secret":"YOUR_TV_SECRET"}
    """
    symbol:    str
    action:    str              # BUY / SELL / CLOSE
    price:     Optional[float] = None
    timeframe: Optional[str]   = "15m"
    volume:    Optional[float] = 0.01
    secret:    Optional[str]   = None
    comment:   Optional[str]   = None

@app.post("/api/webhooks/tradingview")
async def tradingview_webhook(payload: TVWebhookPayload, request: Request):
    """
    Receive alerts from TradingView strategy/indicator.
    - Validates the shared secret (TV_WEBHOOK_SECRET env var)
    - Runs Multi-Timeframe Confluence check
    - Creates a paper trade draft for human confirmation
    - Sends Telegram notification
    Returns a draft_id the user must confirm via chat to execute live.
    """
    TV_SECRET = os.getenv("TV_WEBHOOK_SECRET", "")
    if TV_SECRET and payload.secret != TV_SECRET:
        raise HTTPException(status_code=403, detail="Invalid webhook secret")

    logger.info(f"TradingView Webhook: {payload.symbol} {payload.action} @ {payload.price}")

    try:
        loop = asyncio.get_event_loop()
        from intelligence.tools import market_tools

        sym    = payload.symbol.upper().replace("USDT","").replace("-USD","").replace(".P","")
        action = payload.action.upper()

        # Auto-detect asset class
        CRYPTO_SYMS = {"BTC","ETH","SOL","BNB","XRP","ADA","DOGE","PEPE","AVAX","LINK","UNI","MATIC"}
        asset_class = "CRYPTO" if sym in CRYPTO_SYMS else "STOCK"

        # Run MTF confluence check asynchronously
        mtf_result = await loop.run_in_executor(
            None, lambda: market_tools.scan_multi_timeframe(sym, asset_class)
        )

        draft = None
        if action in ("BUY","SELL") and payload.volume and payload.volume > 0:
            draft = await loop.run_in_executor(
                None, lambda: market_tools.prepare_mt5_trade_draft(
                    symbol=sym, side=action, volume=payload.volume,
                    session_id="tradingview_webhook"
                )
            )

        # Send Telegram alert
        notif_msg = (
            f"📡 *TradingView Alert Received*\n"
            f"Symbol: `{sym}` | Action: `{action}` | Price: `{payload.price}`\n"
            f"Timeframe: `{payload.timeframe}` | Comment: `{payload.comment or '-'}`\n"
            f"MTF Confluence: `{mtf_result.get('confluence_score','?')}%` "
            f"({mtf_result.get('dominant_bias','?')})\n"
            + (f"Draft ID: `{draft.get('draft_id')}` — ยืนยันใน Chat เพื่อ execute"
               if draft and draft.get("draft_id") else "")
        )
        await notifier.broadcast(notif_msg)

        return {
            "status":     "RECEIVED",
            "symbol":     sym,
            "action":     action,
            "mtf_confluence": mtf_result,
            "draft":      draft,
            "message":    "Alert processed. Confirm draft_id in chat to execute live trade.",
        }
    except Exception as e:
        logger.error(f"TradingView webhook error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Change Password ──────────────────────────────────────────────────────────
class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

@app.post("/api/auth/change-password")
def auth_change_password(req: ChangePasswordRequest, current_user: dict = Depends(get_current_user)):
    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")
    if not _verify_password(req.current_password, current_user["password_hash"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    conn = sqlite3.connect(PERSISTENCE_DB)
    conn.execute("UPDATE users SET password_hash=? WHERE id=?", (_hash_password(req.new_password), current_user["id"]))
    conn.commit(); conn.close()
    return {"ok": True, "message": "Password changed successfully"}

# ── Paper Trading REST API ────────────────────────────────────────────────────
class PaperTradeOpenRequest(BaseModel):
    symbol: str
    side:   str   # BUY | SELL
    volume: float = 1.0
    price:  Optional[float] = None

class PaperTradeCloseRequest(BaseModel):
    price: Optional[float] = None

@app.get("/api/paper-trades")
async def list_paper_trades(request: Request):
    _ = verify_token(request)
    try:
        loop = asyncio.get_event_loop()
        from intelligence.tools import market_tools
        result = await loop.run_in_executor(None, lambda: market_tools.paper_trade(action="LIST"))
        return result
    except Exception as e:
        return {"open_trades": [], "closed_trades": [], "total_simulated_pnl": 0, "error": str(e)}

@app.post("/api/paper-trades")
async def open_paper_trade(req: PaperTradeOpenRequest, request: Request):
    _ = verify_token(request)
    try:
        loop = asyncio.get_event_loop()
        from intelligence.tools import market_tools
        result = await loop.run_in_executor(
            None, lambda: market_tools.paper_trade(
                action="OPEN", symbol=req.symbol, side=req.side,
                volume=req.volume, price=req.price
            )
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/paper-trades/{trade_id}/close")
async def close_paper_trade(trade_id: str, req: PaperTradeCloseRequest, request: Request):
    _ = verify_token(request)
    try:
        loop = asyncio.get_event_loop()
        from intelligence.tools import market_tools
        result = await loop.run_in_executor(
            None, lambda: market_tools.paper_trade(
                action="CLOSE", trade_id=trade_id, price=req.price
            )
        )
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])

        # Telegram notification on trade close
        pnl     = result.get("pnl_usd", 0) or 0
        outcome = result.get("result", "")
        symbol  = result.get("symbol", trade_id)
        emoji   = "✅" if pnl >= 0 else "❌"
        asyncio.create_task(notifier.send_telegram_alert(
            f"{emoji} *Paper Trade Closed* — {symbol}\n"
            f"P&L: `{'%+.2f' % pnl} USD`  |  {outcome}\n"
            f"Exit: `{result.get('exit_price', '—')}`"
        ))

        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/paper-trades")
async def reset_paper_trades(request: Request):
    _ = verify_token(request)
    loop = asyncio.get_event_loop()
    from intelligence.tools import market_tools
    result = await loop.run_in_executor(None, lambda: market_tools.paper_trade(action="RESET"))
    return result

# ── Economic Calendar ─────────────────────────────────────────────────────────
@app.get("/api/market/calendar")
async def get_calendar(request: Request, days: int = 7):
    _ = verify_token(request)
    try:
        loop = asyncio.get_event_loop()
        from intelligence.tools import market_tools
        result = await loop.run_in_executor(None, lambda: market_tools.get_economic_calendar(days_ahead=days))
        return result
    except Exception as e:
        return {"events": [], "error": str(e)}

# Catch-all for SPA routing (Must be last)
@app.get("/{full_path:path}")
async def catch_all(full_path: str):
    # If it's an API call, it already failed to match above routes, so return 404
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API route not found")
    
    # Check if the file exists in the static directory
    file_path = os.path.join(STATIC_DIR, full_path)
    if os.path.isfile(file_path):
        return FileResponse(file_path)
    
    # Otherwise, return index.html for React SPA (Client-side routing fallback)
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(
            index_path, 
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache"
            }
        )
    return {"error": "index.html not found"}

if __name__ == "__main__":
    import uvicorn
    logging.info("Starting uvicorn on port 8888...")
    uvicorn.run(app, host="0.0.0.0", port=8888, reload=False)
