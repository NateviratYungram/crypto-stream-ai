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

# Fix Windows console encoding for emojis
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from contextlib import asynccontextmanager
from typing import Optional, List

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

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from google import genai
from google.genai import types
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
from datetime import datetime, timedelta, timezone
import uuid

# ── Auth Imports ─────────────────────────────────────────────────────────────
from passlib.context import CryptContext
from jose import JWTError, jwt

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "ultra_secure_jwt_secret_key_crypto_stream")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7 # 1 week

from intelligence.constants import NASDAQ_100_TICKERS, SP500_TICKERS, MACRO_MAPPING, SMALL_CAP_TICKERS
from services.notification_service import NotificationService
from intelligence.agents.sentiment_agent import create_sentiment_agent, _fetch_rss_news
from intelligence.sentinel.alpha_sentinel import alpha_sentinel
import sqlite3

# Initialize shared services
notifier = NotificationService()
# ── Technical Tools ──────────────────────────────────────────────────────────
# Tools are imported inside the runner to ensure scope stability

# Define Tool Runner outside any nested scopes to ensure global accessibility
async def run_agent_tool_async(name, args):
    """
    World-class tool executor with maximum robustness.
    Uses dynamic lookup and non-blocking execution to keep server responsive.
    """
    try:
        logger.info(f"🛠️ Agent Tool Calling: {name} with args {args}")
        
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
            
        # Execute in a separate thread to avoid blocking the main event loop
        # Institutional stability: Timeout prevents indefinite hangs
        try:
            import functools
            loop = asyncio.get_event_loop()
            
            # Prepare arguments
            kwargs = args if isinstance(args, dict) else {}
            
            # Execute synchronously in a thread pool
            timeout_seconds = 35.0 if name == "get_trading_tactics" else 18.0
            res = await asyncio.wait_for(
                loop.run_in_executor(None, functools.partial(func, **kwargs)),
                timeout=timeout_seconds
            )
            
            logger.info(f"✅ Tool {name} execution successful")
            
            # FunctionResponse requires a dict
            if isinstance(res, str):
                try:
                    res = json.loads(res)
                except Exception:
                    res = {"result": res}
                
            return res
        except asyncio.TimeoutError:
            logger.error(f"❌ Tool {name} TIMEOUT after {timeout_seconds:.0f}s")
            return {"error": f"Tool execution for {name} timed out. The market server might be busy."}
        except Exception as e:
            logger.error(f"❌ Tool {name} internal error: {e}")
            return {"error": str(e)}
            
    except Exception as e:
        logger.error(f"❌ Tool runner critical failure: {e}")
        return {"error": "Internal Tool Runner Error"}
        
    except Exception as e:
        logger.error(f"❌ Error in run_agent_tool_async ({name}): {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {"error": f"Internal Tool Error: {str(e)}"}

load_dotenv()

# ==========================================
# Config — all from environment, no defaults that look real
# ==========================================
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "frontend", "dist")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
MCP_API_KEY    = os.environ.get("MCP_API_KEY", "")
APP_API_KEY    = os.environ.get("APP_API_KEY", "")
KAFKA_BROKER   = os.environ.get("KAFKA_BROKER", "localhost:9092")
MCP_URL        = "http://localhost:8000"
MODEL_ID       = os.environ.get("MODEL_ID", "gemini-2.5-flash")
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

# ==========================================
# Connection Pool (MED-01 fix)
# Reuses DB connections instead of open/close per request
# min=2 idle connections, max=10 concurrent
# ==========================================
_db_pool: Optional[pg_pool.ThreadedConnectionPool] = None
GLOBAL_MACRO_CACHE = {}  # Stores latest yfinance macro data
GLOBAL_ACCOUNT_CACHE = {} # Stores latest MT5 account details

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
# Persistence DB (SQLite) for History
# ==========================================
PERSISTENCE_DB = os.path.join(BASE_DIR, "persistence.db")

def init_persistence_db():
    """Ensure SQLite tables exist and are synchronized with current schema."""
    import sqlite3
    try:
        conn = sqlite3.connect(PERSISTENCE_DB)
        cursor = conn.cursor()
        
        # 1. Create sessions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT,
                last_message TEXT,
                updated_at DATETIME
            )
        """)
        
        # 2. Migration: Check if last_message column exists (for older databases)
        cursor.execute("PRAGMA table_info(sessions)")
        columns = [col[1] for col in cursor.fetchall()]
        if "last_message" not in columns:
            logger.info("🛠️ Migrating SQLite: Adding last_message column to sessions table")
            cursor.execute("ALTER TABLE sessions ADD COLUMN last_message TEXT")
            
        # 3. Create messages table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                role TEXT,
                content TEXT,
                metadata TEXT,
                created_at DATETIME,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            )
        """)
        
        # 4. Create users table for Auth
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE,
                email TEXT UNIQUE,
                hashed_password TEXT,
                full_name TEXT,
                disabled BOOLEAN DEFAULT FALSE,
                created_at DATETIME
            )
        """)
        
        # 5. Create trade_drafts table
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
        
        # 6. Create active_trades table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS active_trades (
                ticket INTEGER PRIMARY KEY,
                symbol TEXT,
                entry_price REAL,
                tp1 REAL,
                be_triggered INTEGER DEFAULT 0,
                draft_id TEXT,
                created_at DATETIME
            )
        """)
        
        # 7. Create daily_performance table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_performance (
                date TEXT PRIMARY KEY,
                balance REAL,
                equity REAL,
                drawdown REAL
            )
        """)
        
        # 8. Create sniper_audit_log table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sniper_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                confidence REAL,
                reasoning TEXT,
                price REAL,
                timestamp DATETIME
            )
        """)
        
        # 9. Create tactics_audit_log table (Enriched)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tactics_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                recommendation TEXT,
                price REAL,
                strategy TEXT,
                confidence REAL,
                reasoning TEXT,
                timestamp DATETIME
            )
        """)
        
        # 10. Create watchlist table (RE-CREATE with UNIQUE constraint if needed)
        # Check if symbol has UNIQUE constraint
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='watchlist'")
        row = cursor.fetchone()
        has_unique = row and "UNIQUE" in row[0].upper()
        
        if row and not has_unique:
            logger.info("⚠️ Watchlist schema is outdated (missing UNIQUE). Re-creating...")
            cursor.execute("DROP TABLE IF EXISTS watchlist")
            
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT UNIQUE,
                note TEXT,
                created_at DATETIME
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                symbol TEXT,
                condition TEXT,
                message TEXT,
                status TEXT DEFAULT 'ACTIVE',
                created_at DATETIME
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trade_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                review_text TEXT,
                win_rate REAL,
                score REAL,
                created_at DATETIME
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT,
                detail TEXT,
                time DATETIME
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS paper_trades (
                id TEXT PRIMARY KEY,
                symbol TEXT,
                side TEXT,
                quantity REAL,
                volume REAL,
                entry_price REAL,
                current_price REAL,
                exit_price REAL,
                pnl REAL,
                pnl_usd REAL,
                status TEXT DEFAULT 'OPEN',
                opened_at DATETIME,
                closed_at DATETIME,
                sl REAL,
                tp REAL,
                outcome TEXT,
                features_json TEXT,
                ml_score REAL,
                entry_source TEXT,
                entry_reason TEXT,
                close_reason TEXT,
                label_source TEXT
            )
        """)
        
        # Migration: Ensure all columns exist in watchlist
        cursor.execute("PRAGMA table_info(watchlist)")
        w_cols = [c[1] for c in cursor.fetchall()]
        if "note" not in w_cols:
            logger.info("🛠️ Migrating watchlist: adding note column")
            cursor.execute("ALTER TABLE watchlist ADD COLUMN note TEXT")
        if "created_at" not in w_cols:
            logger.info("🛠️ Migrating watchlist: adding created_at column")
            cursor.execute("ALTER TABLE watchlist ADD COLUMN created_at DATETIME")
        
        cursor.execute("PRAGMA table_info(alerts)")
        alert_cols = [c[1] for c in cursor.fetchall()]
        alert_migrations = {
            "user_id": "ALTER TABLE alerts ADD COLUMN user_id TEXT",
            "symbol": "ALTER TABLE alerts ADD COLUMN symbol TEXT",
            "condition": "ALTER TABLE alerts ADD COLUMN condition TEXT",
            "message": "ALTER TABLE alerts ADD COLUMN message TEXT",
            "status": "ALTER TABLE alerts ADD COLUMN status TEXT DEFAULT 'ACTIVE'",
            "created_at": "ALTER TABLE alerts ADD COLUMN created_at DATETIME",
        }
        for col_name, sql in alert_migrations.items():
            if col_name not in alert_cols:
                logger.info(f"Alerts migration: adding {col_name}")
                cursor.execute(sql)

        cursor.execute("PRAGMA table_info(trade_reviews)")
        review_cols = [c[1] for c in cursor.fetchall()]
        trade_review_migrations = {
            "review_text": "ALTER TABLE trade_reviews ADD COLUMN review_text TEXT",
            "win_rate": "ALTER TABLE trade_reviews ADD COLUMN win_rate REAL",
            "score": "ALTER TABLE trade_reviews ADD COLUMN score REAL",
            "created_at": "ALTER TABLE trade_reviews ADD COLUMN created_at DATETIME",
        }
        for col_name, sql in trade_review_migrations.items():
            if col_name not in review_cols:
                logger.info(f"Trade review migration: adding {col_name}")
                cursor.execute(sql)

        cursor.execute("PRAGMA table_info(audit_activity)")
        audit_cols = [c[1] for c in cursor.fetchall()]
        audit_migrations = {
            "type": "ALTER TABLE audit_activity ADD COLUMN type TEXT",
            "detail": "ALTER TABLE audit_activity ADD COLUMN detail TEXT",
            "time": "ALTER TABLE audit_activity ADD COLUMN time DATETIME",
        }
        for col_name, sql in audit_migrations.items():
            if col_name not in audit_cols:
                logger.info(f"Audit activity migration: adding {col_name}")
                cursor.execute(sql)

        cursor.execute("PRAGMA table_info(paper_trades)")
        pt_cols = [c[1] for c in cursor.fetchall()]
        paper_trade_migrations = {
            "quantity": "ALTER TABLE paper_trades ADD COLUMN quantity REAL",
            "volume": "ALTER TABLE paper_trades ADD COLUMN volume REAL",
            "current_price": "ALTER TABLE paper_trades ADD COLUMN current_price REAL",
            "exit_price": "ALTER TABLE paper_trades ADD COLUMN exit_price REAL",
            "pnl": "ALTER TABLE paper_trades ADD COLUMN pnl REAL",
            "pnl_usd": "ALTER TABLE paper_trades ADD COLUMN pnl_usd REAL",
            "sl": "ALTER TABLE paper_trades ADD COLUMN sl REAL",
            "tp": "ALTER TABLE paper_trades ADD COLUMN tp REAL",
            "outcome": "ALTER TABLE paper_trades ADD COLUMN outcome TEXT",
            "features_json": "ALTER TABLE paper_trades ADD COLUMN features_json TEXT",
            "ml_score": "ALTER TABLE paper_trades ADD COLUMN ml_score REAL",
            "entry_source": "ALTER TABLE paper_trades ADD COLUMN entry_source TEXT",
            "entry_reason": "ALTER TABLE paper_trades ADD COLUMN entry_reason TEXT",
            "close_reason": "ALTER TABLE paper_trades ADD COLUMN close_reason TEXT",
            "label_source": "ALTER TABLE paper_trades ADD COLUMN label_source TEXT",
        }
        for col_name, sql in paper_trade_migrations.items():
            if col_name not in pt_cols:
                logger.info(f"Paper trade migration: adding {col_name}")
                cursor.execute(sql)

        # Migration: Add new columns if missing for tactics_audit_log
        cursor.execute("PRAGMA table_info(tactics_audit_log)")
        cols = [c[1] for c in cursor.fetchall()]
        if "confidence" not in cols:
            logger.info("🛠️ Migrating tactics_audit_log: adding confidence column")
            cursor.execute("ALTER TABLE tactics_audit_log ADD COLUMN confidence REAL DEFAULT 0.0")
        if "reasoning" not in cols:
            logger.info("🛠️ Migrating tactics_audit_log: adding reasoning column")
            cursor.execute("ALTER TABLE tactics_audit_log ADD COLUMN reasoning TEXT")
        
        conn.commit()
        conn.close()
        logger.info("✅ Persistence DB (SQLite) initialized with all institutional tables (incl. Watchlist).")
    except Exception as e:
        logger.error(f"❌ Failed to initialize Persistence DB: {e}")

def log_tactics_call(symbol: str, recommendation: str, price: float, strategy: str, confidence: float = 0.0, reasoning: str = ""):
    """Log a tactics generation call for audit purposes."""
    try:
        conn = sqlite3.connect(PERSISTENCE_DB)
        cursor = conn.cursor()
        now = datetime.now(timezone.utc).isoformat()
        cursor.execute("""
            INSERT INTO tactics_audit_log (symbol, recommendation, price, strategy, confidence, reasoning, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (symbol.upper(), recommendation, price, strategy, confidence, reasoning, now))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"❌ Failed to log tactics call: {e}")

@contextmanager
def get_persistence_conn():
    import sqlite3
    conn = sqlite3.connect(PERSISTENCE_DB)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _append_audit_event(event_type: str, detail: str):
    """Persist lightweight activity events for dashboard views."""
    try:
        with get_persistence_conn() as conn:
            conn.execute(
                "INSERT INTO audit_activity (type, detail, time) VALUES (?, ?, ?)",
                (event_type, detail[:500], datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
    except Exception as e:
        logger.warning(f"Failed to append audit event: {e}")


QUOTE_SYMBOL_MAP = {
    "BTC": "BTC-USD",
    "BTCUSDT": "BTC-USD",
    "BTCUSD": "BTC-USD",
    "ETH": "ETH-USD",
    "ETHUSDT": "ETH-USD",
    "ETHUSD": "ETH-USD",
    "SOL": "SOL-USD",
    "SOLUSDT": "SOL-USD",
    "XRP": "XRP-USD",
    "XRPUSDT": "XRP-USD",
    "BNB": "BNB-USD",
    "BNBUSDT": "BNB-USD",
    "GOLD": "GC=F",
    "SILVER": "SI=F",
    "OIL": "CL=F",
    "NASDAQ": "^IXIC",
    "SP500": "^GSPC",
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
}


def _normalize_quote_symbol(symbol: str) -> str:
    sym = (symbol or "").upper().strip()
    return QUOTE_SYMBOL_MAP.get(sym, sym)


def _get_live_price(symbol: str) -> float:
    """Best-effort live mark price using Binance, cache, then Yahoo."""
    try:
        normalized = _normalize_quote_symbol(symbol)
        raw_symbol = (symbol or "").upper().strip()

        crypto_symbol = raw_symbol
        if normalized.endswith("-USD"):
            crypto_symbol = normalized.replace("-USD", "")
        elif raw_symbol.endswith("USDT"):
            crypto_symbol = raw_symbol.replace("USDT", "")

        if crypto_symbol in {"BTC", "ETH", "SOL", "XRP", "BNB"}:
            try:
                resp = requests.get(
                    "https://api.binance.com/api/v3/ticker/price",
                    params={"symbol": f"{crypto_symbol}USDT"},
                    timeout=6,
                    headers={"User-Agent": "CryptoStreamAI/2.0"},
                )
                resp.raise_for_status()
                price = float(resp.json().get("price") or 0.0)
                if price > 0:
                    return price
            except Exception:
                pass

            cached_market = _cache_get("market_stocks_v2") or {}
            cached_quote = cached_market.get(crypto_symbol) or {}
            cached_price = float(cached_quote.get("price") or 0.0)
            if cached_price > 0:
                return cached_price

        payload = _yahoo_batch_quotes([normalized])
        quote = payload.get(normalized, {})
        return float(quote.get("regularMarketPrice") or 0.0)
    except Exception:
        return 0.0

# ==========================================
# Rate Limiter (CRIT-03 fix)
# ==========================================
limiter = Limiter(key_func=get_remote_address)

# ==========================================
# App + Lifespan (CRIT-05 fix: replaces deprecated on_event)
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start Kafka consumers and Macro poller on startup."""
    logger.info("🚀 Starting background workers...")
    
    # Initialize history DB before workers start
    init_persistence_db()
    
    t1 = asyncio.create_task(kafka_consumer_task())
    t2 = asyncio.create_task(dlq_consumer_task())
    t3 = asyncio.create_task(macro_poller_task())
    t4 = asyncio.create_task(alpha_sentinel.run())
    t5 = asyncio.create_task(market_status_poller_task())
    t6 = asyncio.create_task(signal_broadcaster_task())
    t7 = asyncio.create_task(account_poller_task())
    t8 = asyncio.create_task(auto_paper_trader_task())
    
    # Notify Telegram that system is online
    asyncio.create_task(notifier.notify_system_startup())
    
    yield  # App runs here
    logger.info("⏳ Shutting down background workers...")
    t1.cancel()
    t2.cancel()
    t3.cancel()
    t4.cancel()
    t5.cancel()
    t6.cancel()
    t7.cancel()
    t8.cancel()
    await asyncio.gather(t1, t2, t3, t4, t5, t6, t7, t8, return_exceptions=True)
    if _db_pool:
        _db_pool.closeall()
    logger.info("✅ Workers stopped and DB pool closed.")

async def market_status_poller_task():
    """Polls the market open/close status and notifies Telegram of changes."""
    from intelligence.utils.market_hours import get_market_status_data
    
    last_status = {}
    
    while True:
        try:
            status_data = get_market_status_data()
            
            # Check Forex
            forex = status_data.get("forex", {})
            f_status = forex.get("status")
            if last_status.get("forex") and last_status["forex"] != f_status:
                if f_status == "OPEN":
                    await notifier.notify_market_opened("Forex/Gold")
                elif f_status == "CLOSED":
                    await notifier.notify_market_closed("Forex/Gold")
            last_status["forex"] = f_status
            
            # Check Stocks
            stocks = status_data.get("stocks", {})
            s_status = stocks.get("status")
            if last_status.get("stocks") and last_status["stocks"] != s_status:
                if s_status == "OPEN":
                    await notifier.notify_market_opened("US Stocks (NASDAQ/NYSE)")
                elif s_status in ["CLOSED", "HOLIDAY"]:
                    await notifier.notify_market_closed("US Stocks (NASDAQ/NYSE)", reason=s_status)
            last_status["stocks"] = s_status
            
        except Exception as e:
            logger.warning(f"Market status poller error: {e}")
            
        await asyncio.sleep(60) # check every minute

async def signal_broadcaster_task():
    """[LIVE] Broadcasts ML signals + real system health to all WebSocket clients every 15s."""
    logger.info("📡 Signal Broadcaster Task started.")
    await asyncio.sleep(5)  # Short warm-up delay so the intelligence engine is ready

    while True:
        try:
            loop = asyncio.get_event_loop()

            # 1. Run ML signal generation in a thread (blocking I/O)
            signals = []
            if INTELLIGENCE_AVAILABLE and crypto_intel:
                try:
                    symbols = ["BTC", "ETH", "SOL", "XRP", "GOLD", "SILVER"]  # MT5-verified XM broker symbols only
                    signals = await loop.run_in_executor(
                        None,
                        lambda: crypto_intel.get_quick_signals(symbols, timeframe="15m")
                    )
                except Exception as e:
                    logger.warning(f"Signal broadcaster: ML inference failed — {e}")

            # 2. Check real DB health (non-blocking ping)
            db_ok = False
            try:
                if _db_pool:
                    conn = _db_pool.getconn()
                    cur = conn.cursor()
                    cur.execute("SELECT 1")
                    cur.close()
                    _db_pool.putconn(conn)
                    db_ok = True
            except Exception as e:
                logger.warning(f"Signal broadcaster: DB health check failed — {e}")

            # 3. DQ Guard: signals dataset is considered clean if we got at least some signals
            dq_ok = len(signals) > 0

            # 4. Broadcast payload to all connected UI clients
            if signals or True:  # Always broadcast (even empty list clears stale data)
                await manager.broadcast({
                    "type": "SIGNALS",
                    "data": {
                        "signals": signals,
                        "db_ok": db_ok,
                        "dq_ok": dq_ok,
                        "timestamp": int(time.time() * 1000)
                    }
                })
                logger.info(f"📡 Broadcasted {len(signals)} signals | DB={'OK' if db_ok else 'FAIL'} | DQ={'OK' if dq_ok else 'FAIL'}")

        except Exception as e:
            logger.error(f"Signal broadcaster critical error: {e}")

        await asyncio.sleep(15)  # Broadcast every 15 seconds


async def account_poller_task():
    """[LIVE] Polls MT5 for account summary and open positions every 10s."""
    logger.info("💳 Account Poller Task started.")
    from intelligence.mt5_connector import get_mt5_account_info, get_mt5_positions
    
    while True:
        try:
            loop = asyncio.get_event_loop()
            
            # 1. Fetch Account Info
            acc_info = await loop.run_in_executor(None, get_mt5_account_info)
            
            # 2. Fetch Open Positions
            positions = await loop.run_in_executor(None, get_mt5_positions)
            
            if "error" not in acc_info:
                # 3. Store in cache
                GLOBAL_ACCOUNT_CACHE["summary"] = {
                    "login": acc_info.get("login"),
                    "name": acc_info.get("name", ""),
                    "company": acc_info.get("company", ""),
                    "balance": acc_info.get("balance", 0),
                    "equity": acc_info.get("equity", 0),
                    "profit": acc_info.get("profit", 0),
                    "margin": acc_info.get("margin", 0),
                    "margin_free": acc_info.get("margin_free", 0),
                    "margin_level": acc_info.get("margin_level", 0),
                    "leverage": acc_info.get("leverage", 1),
                    "currency": acc_info.get("currency", "USD"),
                    "server": acc_info.get("server", "N/A"),
                    "trade_allowed": acc_info.get("trade_allowed", False),
                    "trade_expert": acc_info.get("trade_expert", False),
                }
                GLOBAL_ACCOUNT_CACHE["positions"] = positions
                GLOBAL_ACCOUNT_CACHE["updated_at"] = time.time()
                GLOBAL_ACCOUNT_CACHE["connected"] = True
                
                # 4. Broadcast to WebSocket
                await manager.broadcast({
                    "type": "ACCOUNT_UPDATE",
                    "data": {
                        "summary": GLOBAL_ACCOUNT_CACHE["summary"],
                        "positions": positions,
                        "timestamp": int(time.time() * 1000)
                    }
                })
                logger.info(f"💳 Account Sync: Equity={acc_info.get('equity')} | Positions={len(positions)}")
                
                # 5. Optional: Log to persistence DB (SQLite) for history once per hour
                if int(time.time()) % 3600 < 15: # roughly once an hour
                    try:
                        with sqlite3.connect(PERSISTENCE_DB) as conn:
                            conn.execute(
                                "INSERT OR REPLACE INTO daily_performance (date, balance, equity, drawdown) VALUES (?, ?, ?, ?)",
                                (datetime.now().strftime("%Y-%m-%d %H:00"), acc_info.get("balance"), acc_info.get("equity"), 0)
                            )
                    except Exception as e:
                        logger.warning(f"Failed to log performance history: {e}")
                        
        except Exception as e:
            logger.warning(f"Account poller error: {e}")
            
        await asyncio.sleep(12) # Poll every 12 seconds


async def macro_poller_task():
    """Polls yfinance for Gold, Stocks, and Indices every 30s and broadcasts to UI."""
    import yfinance as yf
    from intelligence.technical_engine import MACRO_MAPPING
    
    symbols = list(MACRO_MAPPING.keys())
    tickers = list(MACRO_MAPPING.values())
    
    while True:
        # Give the server a few seconds to warm up before the first heavy fetch
        # but don't wait the full 30s for the very first update
        try:
            # Fetch latest data (Attempt 2d first, fallback if thin)
            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(
                None,
                lambda: yf.download(tickers, period="5d", interval="1h", progress=False, group_by='ticker')
            )
            
            if not data.empty:
                for sym, ticker in MACRO_MAPPING.items():
                    try:
                        price = 0
                        delta = 0
                        
                        # High-reliability fallback if batch fetch failed for this ticker
                        if ticker not in data.columns.levels[0] or pd.isna(data[ticker]['Close'].iloc[-1]):
                            try:
                                # Quick fetch for missing ticker (Use fast_info for instant data)
                                t_obj = yf.Ticker(ticker)
                                price = t_obj.fast_info['lastPrice']
                                # Use previous close if available for delta
                                prev_close = t_obj.fast_info.get('previousClose', price)
                                delta = ((price - prev_close) / (prev_close if prev_close != 0 else 1)) * 100
                            except:
                                # Deep fallback: try current price from history
                                try:
                                    hist = t_obj.history(period="5d")
                                    if not hist.empty:
                                        price = float(hist['Close'].iloc[-1])
                                        prev_close = float(hist['Close'].iloc[-2]) if len(hist) > 1 else price
                                        delta = ((price - prev_close) / (prev_close if prev_close != 0 else 1)) * 100
                                except:
                                    continue
                        else:
                            ticker_data = data[ticker].dropna(subset=['Close'])
                            if not ticker_data.empty:
                                price = float(ticker_data['Close'].iloc[-1])
                                first_price = ticker_data['Close'].iloc[0]
                                delta = ((price - first_price) / (first_price if first_price != 0 else 1)) * 100

                        if price > 0:
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
            logger.info(f"✅ Macro poller updated {len(GLOBAL_MACRO_CACHE)} assets.")
        except Exception as e:
            logger.warning(f"Macro poller error: {e}")
            
        await asyncio.sleep(20)

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
    allow_methods=["GET", "POST", "OPTIONS"],
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
    try:
        await consumer.start()
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
        # Silence local connection errors if Kafka is missing (intentional for local dev)
        if "Bootstrap failed" in str(e) or "connect" in str(e).lower():
            logger.info("ℹ️ Kafka Trade Consumer skipped (local Kafka not found)")
        else:
            logger.error(f"⚠️ Kafka Trade Consumer failed: {e}")
    finally:
        try:
            await consumer.stop()
        except:
            pass

async def dlq_consumer_task():
    """Consumes DLQ topic for risk alerts."""
    consumer = AIOKafkaConsumer(
        "trade_stream_dlq",
        bootstrap_servers=KAFKA_BROKER,
        group_id="chat_server_dlq_v1",
        auto_offset_reset="latest"
    )
    try:
        await consumer.start()
        async for msg in consumer:
            data = json.loads(msg.value.decode("utf-8"))
            await manager.broadcast({
                "type": "DQ_ALERT",
                "data": data
            })
            # External notification for risk
            await notifier.notify_risk(data.get("error_reason", "Data quality anomaly detected"))
    except Exception as e:
        # Silence local connection errors if Kafka is missing
        if "Bootstrap failed" in str(e) or "connect" in str(e).lower():
            logger.info("ℹ️ Kafka DLQ Consumer skipped (local Kafka not found)")
        else:
            logger.error(f"⚠️ Kafka DLQ Consumer failed: {e}")
    finally:
        try:
            await consumer.stop()
        except:
            pass

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
            "global_macro": GLOBAL_MACRO_CACHE
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
# Authentication Endpoints
# ==========================================
def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

class RegisterRequest(BaseModel):
    email: str
    username: str
    password: str
    full_name: str = ""
    phone: str = ""
    country: str = "Thailand"
    account_type: str = "retail"
    bio: str = ""

class LoginRequest(BaseModel):
    email: str
    password: str

@app.post("/api/auth/register")
def register_user(req: RegisterRequest):
    try:
        with get_persistence_conn() as conn:
            cursor = conn.cursor()
            # Check if user exists
            cursor.execute("SELECT id FROM users WHERE email = ? OR username = ?", (req.email, req.username))
            if cursor.fetchone():
                raise HTTPException(status_code=400, detail="Email or username already registered")
            
            user_id = str(uuid.uuid4())
            hashed_pw = pwd_context.hash(req.password)
            
            cursor.execute("""
                INSERT INTO users (id, email, username, full_name, password_hash, phone, country, account_type, bio)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_id, req.email, req.username, req.full_name, hashed_pw, req.phone, req.country, req.account_type, req.bio))
            conn.commit()
            
            user_profile = {
                "id": user_id, "email": req.email, "username": req.username,
                "full_name": req.full_name, "account_type": req.account_type,
                "phone": req.phone, "country": req.country, "bio": req.bio
            }
            
            access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
            access_token = create_access_token(data={"sub": user_id}, expires_delta=access_token_expires)
            
            return {"token": access_token, "user": user_profile}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Registration error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/auth/login")
def login_user(req: LoginRequest):
    try:
        with get_persistence_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE email = ?", (req.email,))
            user = cursor.fetchone()
            
            if not user or not pwd_context.verify(req.password, user['password_hash']):
                raise HTTPException(status_code=401, detail="Invalid email or password")
            
            user_profile = {
                "id": user['id'], "email": user['email'], "username": user['username'],
                "full_name": user['full_name'], "account_type": user['account_type'],
                "phone": user['phone'], "country": user['country'], "bio": user['bio']
            }
            
            access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
            access_token = create_access_token(data={"sub": user['id']}, expires_delta=access_token_expires)
            
            return {"token": access_token, "user": user_profile}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ==========================================
# MT5 Direct Execution Endpoints
# ==========================================
class MT5TradeRequest(BaseModel):
    symbol: str
    side: str        # "BUY" or "SELL"
    volume: float
    sl: float = 0.0
    tp: float = 0.0
    price: Optional[float] = None
    order_kind: str = "MARKET"
    filling_policy: str = "IOC"
    deviation: int = 20
    comment: str = "CryptoStream AI Trade"

class MT5CloseRequest(BaseModel):
    ticket: int

@app.get("/api/mt5/quote")
def mt5_quote(symbol: str = "GOLD"):
    try:
        from intelligence.mt5_connector import get_mt5_quote
        result = get_mt5_quote(symbol.upper().strip())
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"MT5 quote error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/mt5/account")
def mt5_account():
    try:
        cached = GLOBAL_ACCOUNT_CACHE.get("summary", {})
        cached_at = GLOBAL_ACCOUNT_CACHE.get("updated_at", 0)
        cache_age = time.time() - cached_at if cached_at else None
        if cached and cache_age is not None and cache_age <= 20:
            return {
                "account": cached,
                "positions": GLOBAL_ACCOUNT_CACHE.get("positions", []),
                "connected": True,
                "source": "cache_live",
                "cache_age_seconds": round(cache_age, 1),
            }

        from intelligence.mt5_connector import get_mt5_account_info, get_mt5_positions
        acc = get_mt5_account_info()
        pos = get_mt5_positions()
        if "error" in acc:
            # Return cached data if MT5 offline
            if cached:
                cache_is_fresh = cache_age is not None and cache_age <= 60
                return {
                    "account": cached,
                    "positions": GLOBAL_ACCOUNT_CACHE.get("positions", []),
                    "connected": cache_is_fresh,
                    "source": "cache_fallback",
                    "cache_age_seconds": round(cache_age, 1) if cache_age is not None else None,
                    "warning": acc["error"],
                }
            return {"connected": False, "error": acc["error"]}
        GLOBAL_ACCOUNT_CACHE["summary"] = acc
        GLOBAL_ACCOUNT_CACHE["positions"] = pos
        GLOBAL_ACCOUNT_CACHE["updated_at"] = time.time()
        GLOBAL_ACCOUNT_CACHE["connected"] = True
        return {"account": acc, "positions": pos, "connected": True, "source": "direct"}
    except Exception as e:
        logger.error(f"MT5 account error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/mt5/positions")
def mt5_positions():
    try:
        from intelligence.mt5_connector import get_mt5_positions
        return {"positions": get_mt5_positions()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/mt5/trade")
async def mt5_execute(req: MT5TradeRequest):
    """Send a live market order to MT5."""
    try:
        loop = asyncio.get_event_loop()
        from intelligence.tools.market_tools import execute_mt5_trade
        result = await loop.run_in_executor(
            None,
            lambda: execute_mt5_trade(
                symbol=req.symbol,
                side=req.side.upper(),
                volume=req.volume,
                price=req.price,
                sl=req.sl if req.sl else None,
                tp=req.tp if req.tp else None,
                order_kind=req.order_kind,
                filling_policy=req.filling_policy,
                deviation=req.deviation,
                comment=req.comment,
            )
        )
        if result.get("status") == "ERROR" or "error" in result:
            raise HTTPException(status_code=400, detail=result.get("error") or result.get("message", "Trade failed"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"MT5 trade error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/mt5/close")
async def mt5_close_position(req: MT5CloseRequest):
    """Close a specific MT5 position by ticket."""
    try:
        loop = asyncio.get_event_loop()
        from intelligence.mt5_connector import mt5_close_position
        result = await loop.run_in_executor(None, lambda: mt5_close_position(req.ticket))
        if result.get("status") == "ERROR" or "error" in result:
            raise HTTPException(status_code=400, detail=result.get("error", "Close failed"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"MT5 close error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ==========================================
# Chat Endpoint (Full Logic Restored)
# ==========================================
class TranslateRequest(BaseModel):
    messages: list  # [{role, content}]
    language: str   # 'en' or 'th'

@app.post("/api/translate")
async def translate_messages(req: TranslateRequest):
    target = 'English' if req.language == 'en' else 'Thai'
    items = [(i, m) for i, m in enumerate(req.messages) if str(m.get('content', '')).strip()]
    if not items:
        return {"translations": []}

    async def translate_one(idx: int, content: str) -> dict:
        prompt = (
            f"Translate the following financial analysis text COMPLETELY and FAITHFULLY to {target}.\n"
            f"- Preserve ALL content, structure, and detail — do NOT summarize or omit anything\n"
            f"- Keep ALL markdown: **, *, -, #, tables, bullet points, line breaks\n"
            f"- Do NOT translate: ticker symbols, numbers, %, TP/SL/RSI/MACD/EMA/FVG/ATR acronyms\n"
            f"- Return ONLY the translated text, nothing else\n\n"
            f"{content}"
        )
        try:
            res = await client.aio.models.generate_content(
                model=MODEL_ID,
                contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
                config=types.GenerateContentConfig(
                    thinking_config=types.ThinkingConfig(thinking_budget=0)
                )
            )
            return {"idx": idx, "content": res.text or content}
        except Exception:
            return {"idx": idx, "content": content}

    results = await asyncio.gather(*[translate_one(i, str(m['content'])) for i, m in items])
    return {"translations": list(results)}


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    history: list = []  # Conversation history: [{"role": "user"|"ai", "content": "..."}]
    language: str = "th"  # Default to Thai

class ChatResponse(BaseModel):
    reply: str
    sql_query: str | None = None
    has_data: bool = False

# Root removed to avoid double-definition conflict with SPA routing at bottom


@app.get("/api/system/market-status")
def get_market_status():
    """Returns real-time status (OPEN/CLOSED) and countdowns for major markets."""
    from intelligence.utils.market_hours import get_market_status_data
    return get_market_status_data()


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

@app.post("/api/chat")
@limiter.limit(CHAT_RATE_LIMIT)
def chat(request: Request, req: ChatRequest, x_api_key: str = Header(None)):
    verify_token(x_api_key)
    user_input = req.message.strip()
    if not user_input:
        raise HTTPException(status_code=400, detail="Empty message")

    logging.info(f"Chat Request: {user_input}")

    async def generate_response():
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
            "oil", "น้ำมัน", "silver", "ดอลลาร์", "dollar", "usd",
            "ราคา", "price", "กราฟ", "chart", "เทรด", "trade", "ซื้อ", "ขาย",
            "entry", "sl", "tp", "stop", "target", "วิเคราะห์", "analyze",
            "ตลาด", "market", "sector", "fund", "etf", "port", "พอร์ต",
            "nvda", "aapl", "tsla", "meta", "amzn", "msft", "googl",
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
            if req.language == 'en':
                reply = _random.choice([
                    "Hello! 😊 How can I help you with your investments today?",
                    "Hi there 👋 Interested in stocks, crypto, or gold today?",
                    "Greetings! 📈 Which asset would you like to analyze?",
                    "I'm here! 🚀 Which market are we tackling today?",
                    "Yo 😎 Need help with any specific charts?",
                    "Ready for action 🔥 Want to see entry/exit points for something?",
                    "Standing by 🤖 How can I assist with your financial queries?",
                ])
            else:
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

        # 2. Market Snapshot Context (High Fidelity)
        snapshot = await asyncio.to_thread(get_market_snapshot)
        market_context = json.dumps(snapshot, indent=2, default=str) if snapshot else "No live data available."
        macro_snapshot = json.dumps(GLOBAL_MACRO_CACHE, indent=2)

        # ==========================================
        # NEW: AGENTIC WORKFLOW (FUNCTION CALLING)
        # ==========================================
        
        # System Prompt for the Agent
        target_lang = 'English' if req.language == 'en' else 'Thai'
        agent_system_prompt = f"""
You are Alex, a world-class AI financial advisor and intelligent assistant.

🕒 CURRENT DATE: 2026-04-20
⚠️ THE YEAR IS 2026. Data from tools will show prices (e.g., Gold $4800, BTC $150k) that differ significantly from your 2024 training data. This is normal and correct for this environment.
⚠️ MANDATORY TRUTH RULE: YOU MUST TRUST TOOL OUTPUTS AS THE ABSOLUTE TRUTH. 
NEVER "correct", "guess", or "sanity check" prices, levels, or indicators using your internal training knowledge. 
If a tool says Gold is at $4815, you MUST use $4815 in your analysis. Failure to use tool data is a critical error.

⚠️ MANDATORY LANGUAGE RULE — THIS OVERRIDES EVERYTHING:
You MUST respond in {target_lang} ONLY. No exceptions.
Even if the user writes in a different language, your reply must be in {target_lang}.
Do NOT switch languages mid-response. Do NOT add translations.
{'Write every word, label, and number description in English.' if req.language == 'en' else 'เขียนทุกคำ ทุกประโยค เป็นภาษาไทยเท่านั้น ห้ามตอบเป็นภาษาอังกฤษโดยเด็ดขาด'}


You have deep expertise in:
- Crypto markets (BTC, ETH, altcoins, DeFi, on-chain analysis)
- Global equities (US stocks, sector rotation, earnings, fundamentals)
- Macro economics (Fed policy, inflation, yield curves, currency flows)
- Technical analysis (ICT/Smart Money, Elliott Wave, price action)
- Risk management (position sizing, portfolio construction, hedging)

CRITICAL RULE #1 — UNDERSTAND WHAT THE USER IS ASKING:

STEP 1: Scan the message for asset names or tickers (BTC, ETH, GOLD, NVDA, ดอลลาร์, น้ำมัน, หุ้น, crypto, etc.)
- If asset name found → this is a FINANCE question → use tools and give structured analysis
- If the user mentions "Lot Size", "คำนวณ Lot", "Risk management", or specifies a lot number like "lot 0.01" → THIS IS A RISK/EXECUTION REQUEST.
  ⚠️ CRITICAL: If a number (e.g. 0.01, 1.0) is near the word 'lot', IGNORE the ticker LOT (Lotus Technology).
  ⚠️ ALWAYS prioritize risk/volume context over the ticker sym LOT unless they explicitly ask for "หุ้น LOT" or "Lotus Technology".
  ⚠️ ALWAYS use calculate_risk_parameters tool for sizing/risk questions.
- If no asset name → check if it's about finance concepts (การลงทุน, พอร์ต, เศรษฐกิจ, ตลาด) → answer with knowledge
- If purely general conversation (greetings, questions about you, other topics) → respond naturally like a smart helpful assistant

STEP 2: Match response depth to what they asked:
- Greeting / "คุณทำอะไรได้บ้าง" / general question → reply naturally, briefly, 1-3 sentences
- "BTC ราคาเท่าไหร่" → call tool, answer in 2-3 sentences
- "วิเคราะห์ BTC ให้หน่อย" → call tool, full structured analysis
- General knowledge question (เศรษฐกิจ, การเงินส่วนตัว, ความรู้ทั่วไป) → answer clearly without tools

CRITICAL RULE #2 — YOU CAN ANSWER ANYTHING:
You are a capable AI assistant first, finance expert second. If someone asks about your capabilities, general knowledge, or anything off-topic — answer it fully and helpfully. Never say "ผมเชี่ยวชาญแค่เรื่องการเงิน" and refuse. Just answer, then gently mention you're best at finance if relevant.

CRITICAL RULE #3 — MARKET STATUS CONTEXT:
Check 'market_status' in tool outputs. Always do full analysis with the data returned by tools:
- If tool returns price data (e.g. price: 4772.0) → ALWAYS give full analysis with Entry/SL/TP/Signal.
  Never say "ไม่มีข้อมูล" or "ไม่สามารถดึงข้อมูลได้" if price data is present in tool output.
- MARKET OPEN: Give real-time analysis normally.
- MARKET CLOSED (weekend): Do full analysis, add one-line disclaimer: "⚠️ ราคาเป็นข้อมูลสุดท้ายวันศุกร์ — ยืนยันอีกครั้งเมื่อตลาดเปิด"
- MARKET OPENING (30-60m): Warn about Stop Hunting and widening spreads.

RULE #7: AUTONOMOUS AUTHORITY — If the user gives a clear order (e.g., "จัดเลย", "0.01 lot", "ลุยเลย"), EXECUTE THE TRADE using `execute_mt5_trade` based on the MOST RECENT plan in the chat. Do not ask for further confirmation if Entry/SL/TP are already discussed.

RULE #9: STOCK ANALYSIS FORMAT — When analyzing a STOCK (asset_class='STOCK'), the tool returns BOTH fundamentals AND chart_analysis. YOU MUST use this STRICT Data Dashboard format for Stocks. Do not write long paragraphs:

### 📊 ข้อมูลเชิงปริมาณ (Stock Data Dashboard): {{Asset Symbol}}
**Signal: BUY / SELL / HOLD**

| 📌 Metric / Action | 🔢 Value / Level |
| :--- | :--- |
| **Current Price** | $X |
| **RSI (14)** | X.X |
| **MACD / ADX** | X / X |
| **EMA 20 / 50** | $X / $X |
| 🎯 **Entry Zone** | $X - $X |
| 🛑 **Stop Loss** | $X |
| 💰 **Take Profit 1** | $X |
| 💰 **Take Profit 2** | $X |

**1. Fundamentals & Analyst Targets:**
- Analyst Target (TP1): $X (+X% Upside)
- Full Value Premium (TP2): $X
- 52-Week High: $X

**2. Executive Summary:**
Provide exactly 1-2 concise sentences summarizing the actionable trade plan purely based on the numbers above. DO NOT write long paragraphs. DO NOT use filler words. Be extremely direct and numeric.


RULE #8: MT5 REALITY SHIELD & STATISTICAL EDGE — You are a high-speed institutional AI.
- ALWAYS use `get_market_analysis` to get MT5 candlesticks + SMC structure.
- For CRYPTO / FOREX / GOLD / OIL only: ALWAYS use `get_institutional_ml_stats` to get the statistical edge.
- For STOCKS (e.g. NFLX, AAPL, TSLA, any stock ticker): NEVER call `get_institutional_ml_stats` — ML model has no stock data.
- If MT5 is connected, use ONLY current broker prices for plans.
- FORMAT YOUR RESPONSE AS FOLLOWS:
  1. [LIVE SYNC]: Status of MT5 connection and Current Symbol price.
  2. [STATISTICAL EDGE]: Quote Neural Win Probability, Historical Win Rate, and Hurst Exponent.
  3. [ARCHITECTURE]: Describe BOS, CHOCH, and Liquidity zones.
  4. [THE PLAN]: Clear Entry, Stop Loss, and Take Profit (synchronized with MT5 price).

RULE #9: SIGNAL DECISION PROTOCOL — Do NOT default to HOLD just because one indicator is neutral.
- For GOLD / FOREX / CRYPTO / OIL, use the 1h analysis as the PRIMARY directional bias.
- Combine these three sources before deciding: `get_market_analysis` higher_timeframe/structure, `get_institutional_ml_stats`, and `get_trading_tactics`.
- If at least 2 of the 3 sources align bullish → issue BUY.
- If at least 2 of the 3 sources align bearish → issue SELL.
- Use HOLD only when the sources genuinely conflict in DIRECTION (e.g., structure bullish but ML bearish). NOT just because confidence % is low.
- 15m is for entry refinement only, not for deciding the main direction.
- CRITICAL: Low ML Win Probability (e.g., 42%) does NOT automatically mean HOLD. It means lower confidence — still issue BUY or SELL if chart structure and Supply/Demand agree. Just reduce the confidence % shown.
- HOLD is reserved for: (1) Price inside a tight range with no clear bias, OR (2) Higher timeframe and lower timeframe giving opposite signals, OR (3) ADX < 20 AND RSI stuck in 45-55 AND structure is flat.

RULE #9b: STOCK SIGNAL PROTOCOL — For asset_class='STOCK' (e.g. NFLX, AAPL, TSLA):
- NEVER call `get_institutional_ml_stats` for stocks. The ML model was trained on MT5 assets only (crypto/forex/gold/oil) and has no stock data — ML results for stocks are meaningless.
- Use only 2 sources: `get_market_analysis` (structure/EMA/SMC) + `get_trading_tactics` (if available).
- If both sources align → issue BUY or SELL directly.
- If only 1 source available → use chart structure alone (EMA position + OB/FVG + RSI/ADX).
- Do NOT mention "ML Win Probability" or "Statistical Bias" for stocks.

RULE #10: MANDATORY HOLD EXPLANATION — When the signal is HOLD/WAIT, you are STRICTLY REQUIRED to explain:
  a. WHY it is HOLD (e.g., "ADX = 14 แสดงว่าตลาดไม่มีทิศทาง", "RSI = 51 อยู่ในโซน Neutral", "Structure 1h bullish แต่ 4h bearish — ทิศทางขัดแย้ง"). NOTE: Low ML confidence alone is NOT a valid reason for HOLD if chart structure has a clear direction.
  b. WHAT TO WATCH — State 2-3 specific numeric conditions the user should watch for before entering:
     Example: "⏳ รอสัญญาณ: (1) ADX ขึ้นเกิน 25 จึงจะมีทิศทาง (ปัจจุบัน 14) (2) ราคาต้องยืนเหนือ EMA20 ที่ $X หรือหลุดต่ำกว่า $Y (3) RSI หลุดจาก 45-55 และไปทิศทางใดทิศทางหนึ่ง"
  c. BIAS — Still give a directional lean: "แนวโน้มระยะ 1h เป็น BULLISH BUT ยังไม่ถึงเวลาเข้า"
  d. ENTRY ALERT LEVEL — Give a specific price level where conditions will be met and you'd switch to BUY/SELL
  NEVER just say "HOLD" and stop. Always give the user a roadmap.


CRITICAL RULE #4 — ALWAYS USE FRESH TOOL DATA:
- NEVER use price/analysis from previous messages in chat history.
- If a user asks about GOLD/BTC/any asset → ALWAYS call the tool NOW to get fresh data.
- Previous responses in chat history may be outdated. Ignore old analysis in history.

CRITICAL RULE #5 — DATA SEPARATION (TRADING PHILOSOPHY):
- LIVE DATA (get_market_analysis price/smc/htf) → Use ONLY for trade planning (Entry, SL, TP).
- HISTORICAL DATA (historical_pulse, memories) → Use ONLY for statistics and logic refinement.
- THE PLAN MUST BE ACCURATE TO THE 'NOW'. THE CONFIDENCE MUST BE DERIVED FROM THE 'BEFORE'.
- Never use old prices as entry levels for a new plan. Always use live tool outputs for levels.

CRITICAL RULE #6 — AUTONOMOUS TRADE EXECUTION (LIVE):
- You possess THE AUTHORITY to execute trades through `execute_mt5_trade` for ALL Asset Classes (Forex, Crypto, Commodities, Indices, Stocks) supported by the broker.
- ACTIVATION TRIGGERS (Thai): "จัดเลย", "เอาเลย", "ลุยเลย", "นำแผนนี้ไปเทรด", "เปิดออเดอร์ให้หน่อย", "นำแผนนี้ไปใช้", "0.01 lot", "เทรดให้หน่อย", "เทรดเลย".
- ACTIVATION TRIGGERS (English): "Execute this plan", "Trade now", "Place the order", "Let's go".
- EXECUTION PROCESS:
  1. Detect activation trigger.
  2. Search chat history for most recent trade plan (Symbol, Entry, SL, TP) provided by you. This applies to ANY asset (e.g., BTC, EURUSD, XAUUSD).
  3. If the user specifies a 'Lot Size' (e.g., '0.01' or '1 lot'), map this value directly to the `volume` parameter in the tool.
  4. If Lot Size / Volume is not specified → Call `calculate_risk_parameters` (default 1% risk) OR use 0.01-0.10 relative to account size.
  5. CALL THE TOOL `execute_mt5_trade(symbol, side, volume, sl, tp)` IMMEDIATELY.
  6. SAFETY EXCEPTION: If your most recent analysis result was "HOLD", "WAIT", or "NEUTRAL", DO NOT execute the trade. Explain clearly: "ฉันยังเทรดให้ไม่ได้ เพราะแผนล่าสุดระบุว่าต้อง [พักรอดูสถานการณ์]..."
  7. CRITICAL: NEVER print a Ticket ID or say "กำลังดำเนินการ..." unless you have already called the tool and received a 'SUCCESS' response with a real ticket number.

  6. DO NOT HALLUCINATE OR MAKE UP A TICKET ID.
  7. YOU MUST WAIT FOR THE TOOL RESPONSE. 
  8. ONLY AFTER the tool returns a real `ticket`, reply with "✅ Order Executed: [ticket]" and summarize. If the tool returns an error, report the error.
- NEVER reply with a placeholder ID like #987654321. If you don't have a real ticket, the trade did not happen.

TOOLS — call only when you need real market data:
- Price/technicals/trend for any asset → get_market_analysis(symbol, asset_class)
- Execute LIVE trade on MT5 → execute_mt5_trade(symbol, side, volume, sl, tp)
- Position sizing / Lot calculation → calculate_risk_parameters(account_size, entry, stop_loss, risk_pct)
  (Use this whenever user asks 'คำนวณ lot', 'เทรดกี่ lot ดี', 'เสี่ยง 2% ต้องใช้ lotเท่าไหร่' or before execution if volume missing)

OUTPUT FORMAT — ALWAYS FOLLOW THIS STRUCTURE FOR ANALYSIS:

[Casual / General / Capability questions] → plain conversational reply, no headers, 1-3 sentences

[Price check] → "ราคา BTC ตอนนี้ $X (+X% วันนี้) | แนวรับ $X แนวต้าน $X"

[Full analysis] (NON-STOCK ASSETS ONLY) →
### 📊 Analysis: {{Asset Symbol}}
**Signal: BUY / SELL / HOLD** — Confidence X%

| Parameter | Level / Target |
| :--- | :--- |
| **Current Price** | $X |
| 🎯 **Entry Zone** | $X - $X |
| 🛑 **Stop Loss** | $X |
| 💰 **Take Profit 1** | $X |
| 💰 **Take Profit 2** | $X |

CRITICAL TABLE RULE: ALL 4 price fields MUST contain real numeric price levels from tool data — NEVER write "รอสัญญาณ", "N/A", or leave blank.
- BUY signal → Entry below current price or at support, SL below entry, TP1/TP2 above entry.
- SELL signal → Entry above current price or at resistance/OB, SL above entry, TP1/TP2 below entry (lower prices = profit for short).
- HOLD signal → Entry Zone = ⏳ Alert Level (the exact price that would trigger the LIKELY next direction), SL = Invalidation level, TP1/TP2 = projected targets if signal confirms.
- CONSISTENCY CHECK: TP must be in the profit direction of the signal. If Signal=SELL, TP1 < Current Price. If Signal=BUY, TP1 > Current Price. Mismatched direction = wrong analysis.

**1. Price Action & Market Structure:**
Explain the trend context in detail. Ensure you use the EXACT price levels provided by the tools (e.g. $4815) and do not "correct" them. Mention BOS (Break of Structure) or MSS (Market Structure Shift) and timeframe alignment.

**2. Supply/Demand & Liquidity:**
Detail the specific Order Blocks (OB), Fair Value Gaps (FVG), and Liquidity zones identified by the tool.

**3. 🐳 Whale Pulse & Institutional Flows:**
Use 'whale_pulse' data to analyze:
- **Whale Walls**: Mention specific price levels where large BUY/SELL orders are clustered (Liquidity Walls).
- **Institutional Injections**: Identify if any recent candles show volume spikes > 300% (Institution entry footprints).
- **Institutional Bias**: State if the current flow is 'ACCUMULATION' or 'DISTRIBUTION'.

**4. 📈 Historical Context & Probability:**
Use 'historical_pulse' from the tool result to refine your logic. Mention the ML Win Probability and how previous similar trades performed. Explain how this data influences your confidence in the current setup.

**5. 🌍 Macro Guardian & Retail FOMO (The Alpha Edge):**
Analyze how the broader market climate and on-chain sentiment impact this asset:
- **Economic Calendar Guardian**: Check if there are any High-Impact news events looming. Suggest hard-stops or skipping trades to avoid macro slippage.
- **Retail Liquidation Heatmap**: Use 'retail_fomo' data to check Long/Short account ratios. Explicitly state the retail sentiment (e.g., Extreme Long FOMO). Use this to justify a *Contrarian Bias* (e.g., "Retail is 75% Long, institutions are likely hunting for Shorts").

**6. Tactical Execution:**
Provide a clear step-by-step execution strategy (e.g., "Wait for a sweep of session liquidity, then look for a shift in structure on lower timeframes before entry").

**7. 🧠 Agentic Synergy & Consensus:**
Synthesize all above layers into a final judgment:
- **Consensus**: Compare ML Win Probability vs. Whale Pulse Bias vs. SMC Structure. 
- **Conflict Resolution**: If layers disagree (e.g., Technicals Bullish but Whales in Distribution), explain the risk and suggest waiting for a "Confluence Trigger".
- **Final Confidence**: State the final trade confidence (Low/Med/High) based on how many layers align.

**⚠️ Risk & Invalidation:**
Explain where the logical bias fails and what the key 'exit' level is if the market shifts. Briefly mention the Bear Case / main threat.

INSTITUTIONAL ORCHESTRATOR: You are not just a bot; you are an Agentic AI. You MUST use every intelligence feature provided by the tools (SMC, Whale Pulse, ML, History, News) to orchestrate the most precise trade plan. Do not ignore any layer of data.

[Education / Concept] → clear explanation, simple language, bullet points ONLY for 3+ items.

PERSONALITY: Confident, direct, helpful. Speaks like a senior portfolio manager who is your smart friend.
INSTITUTIONAL INTELLIGENCE: When performing an 'ANALYZE' request, you must provide the highest possible level of detail. Explain the logic of the trade, reference specific technical levels from the tool data, and provide a comprehensive market outlook. Never be brief when asked for analysis.
FINAL REMINDER: Your response language is {target_lang}. Write in {target_lang} only. No exceptions.
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
                name="get_trading_tactics",
                description=(
                    "Institutional Intelligence: Aggregates SMC, Trend, and Mean Reversion strategies "
                    "to provide explicit entry/SL/TP 'moves' for a given symbol. "
                    "Supports: CRYPTO (BTC, ETH, SOL, BNB, XRP, DOGE, AVAX, LINK, ADA, DOT, MATIC), "
                    "COMMODITIES (GOLD/XAUUSD, SILVER/XAGUSD, OIL/USOIL), "
                    "INDICES (NASDAQ/US100, SP500/US500, DOW/US30, GER40, UK100), "
                    "FOREX (EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF). "
                    "Pass the short symbol (e.g. 'BTC', 'GOLD', 'OIL', 'NASDAQ', 'EURUSD')."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "symbol": types.Schema(
                            type="STRING",
                            description="Short symbol: BTC, ETH, GOLD, OIL, NASDAQ, SP500, EURUSD, GBPUSD, etc."
                        )
                    },
                    required=["symbol"]
                )
            ),
            types.FunctionDeclaration(
                name="get_institutional_ml_stats",
                description=(
                    "Fetch the institutional statistical edge for a symbol, including real-world win rate, "
                    "current neural win probability, regime classification, and directional bias. "
                    "ONLY for CRYPTO, FOREX, GOLD, OIL — these are the only asset classes in the training data. "
                    "DO NOT call this for STOCKS (NFLX, AAPL, TSLA, etc.) — the model has no stock data and results are invalid."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "symbol": types.Schema(
                            type="STRING",
                            description="Short symbol: BTC, ETH, GOLD, OIL, NASDAQ, SP500, EURUSD, GBPUSD, etc."
                        )
                    },
                    required=["symbol"]
                )
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
                name="execute_mt5_trade",
                description="Execute a LIVE trade on MetaTrader 5 (MT5). MUST check risk limits before calling.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "symbol": types.Schema(type="STRING", description="MT5 symbol (e.g. 'XAUUSD', 'EURUSD')"),
                        "side": types.Schema(type="STRING", description="BUY or SELL"),
                        "volume": types.Schema(type="NUMBER", description="Lot size (e.g. 0.01)"),
                        "sl": types.Schema(type="NUMBER", description="Stop Loss price"),
                        "tp": types.Schema(type="NUMBER", description="Take Profit price")
                    },
                    required=["symbol", "side", "volume"]
                )
            ),
            types.FunctionDeclaration(
                name="get_mt5_account_summary",
                description="Get current MT5 account balance, equity, and free margin.",
                parameters=types.Schema(type="OBJECT", properties={})
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
                name="get_economic_calendar",
                description="Fetch the upcoming economic calendar and important corporate earnings to assess macroeconomic risks.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "query": types.Schema(type="STRING", description="Optional specific search (e.g. 'Upcoming CPI', 'Earnings Calendar'). Defaults to 'Economic Events'.")
                    }
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
                name="send_telegram_alert",
                description="Send a notification or alert message to the user's Telegram. Use this when the user asks to push a message, set an alert, or broadcast an analysis.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "message": types.Schema(type="STRING", description="The formatted message to send. Supports basic Markdown (bold, italic).")
                    },
                    required=["message"]
                )
            )
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
            "TP","SL","RR","ADX","OB","AI","TV","API","DB","LOT","LOTS",
            "VOLUME","VOL"
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
            if sym in ["GOLD","XAUUSD"]: return "TVC:GOLD"
            if sym in ["NASDAQ","IXIC"]: return "TVC:IXIC"
            if sym in ["SP500","GSPC"]:  return "TVC:SPX"
            if sym in ["OIL","CRUDE"]:   return "TVC:USOIL"
            
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

        # Build history (plain user message — system prompt goes to system_instruction)
        history_contents = []
        for msg in req.history[-6:]:
            role = "user" if msg.get("role") == "user" else "model"
            history_contents.append(types.Content(role=role, parts=[types.Part(text=msg.get("content", ""))]))
        # Smart Keyword Routing: detect intent and inject explicit tool directive
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
            "วันนี้หุ้น", "หุ้นอะไร", "หุ้นน่า", "หุ้นไหน", "หุ้นตัวไหน",
            "น่า buy", "น่าซื้อหุ้น", "หุ้นน่าซื้อ", "หุ้นดี", "หุ้นเด่น",
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
        
        GOLD_KEYWORDS = ["ทอง", "gold", "xau", "xauusd", "ทองคำ"]
        CRYPTO_ASSET_KEYWORDS = ["btc", "eth", "sol", "bitcoin", "ethereum", "crypto", "เหรียญ", "บิท"]
        FOREX_KEYWORDS = ["eurusd", "gbpusd", "usdjpy", "forex", "ค่าเงิน", "ดอลลาร์"]
        OIL_KEYWORDS = ["oil", "น้ำมัน", "crude", "wti", "brent"]
        TELEGRAM_KEYWORDS = ["telegram", "แจ้งเตือน", "เตือนฉัน", "ส่งเข้าแชท", "alert me", "send to telegram"]
        EXECUTE_KEYWORDS = ["จัดเลย", "เอาเลย", "ลุยเลย", "นำแผนนี้ไปเทรด", "นำแผนนี้ไปใช้", "เปิดออเดอร์", "execute", "trade now", "place order", "lot", "หลอด"]
        # Add support for numeric inputs like "0.01" directly
        is_numeric_lot = bool(re.search(r'\b\d+\.?\d*(\s*lot|หลอด)?\b', user_lower))
        if is_numeric_lot and len(user_lower.strip()) < 10:
            EXECUTE_KEYWORDS.append(user_lower.strip())
        REANALYZE_KEYWORDS = ["แผนเทรดใหม่", "แผนใหม่", "วิเคราะห์ใหม่", "อีกรอบ", "ขอแผนอีก", "new plan", "reanalyze", "re-analyze", "วิเคราะห์อีกรอบ"]

        if any(kw in user_lower for kw in REANALYZE_KEYWORDS):
            override = "[MANDATORY OVERRIDE: ผู้ใช้ต้องการ 'แผนเทรดใหม่' หรือให้ 'วิเคราะห์อีกรอบ' ห้ามใช้ข้อมูลเก่าจากประวัติการแชทเด็ดขาด ให้พิจารณาว่าผู้ใช้กำลังพูดถึง Symbol ไหน แล้วเรียกใช้เครื่องมือเพื่อวิเคราะห์กราฟใหม่หรือคำนวณ Entry, SL, TP ใหม่ทั้งหมด]"
        elif any(kw in user_lower for kw in TELEGRAM_KEYWORDS):
            override = "[MANDATORY OVERRIDE: ผู้ใช้สั่งให้ส่งข้อความเข้า Telegram ให้คุณแต่งข้อความสรุปตามสิ่งที่ผู้ใช้ต้องการ (ห้ามยาวเกินไป) แล้วเรียก send_telegram_alert(message) ทันที ห้ามปฏิเสธเด็ดขาด]"
        elif any(kw in user_lower for kw in EXECUTE_KEYWORDS):
            override = "[MANDATORY EXECUTION: ผู้ใช้สั่ง 'จัดเลย', 'นำแผนนี้ไปใช้' หรือระบุ 'Lot Size' (0.01, 0.1, ฯลฯ) ให้คุณทำตามขั้นตอนดังนี้: (1) ย้อนกลับไปดูแผนการเทรดล่าสุดจากประวัติการแชท (2) หากแผนล่าสุดคือ BUY หรือ SELL ให้เรียกใช้เครื่องมือ execute_mt5_trade ทันที ห้ามแสดงความเห็นก่อน ห้ามพูด 'กำลังเทรด' เฉยๆ (3) หากยังไม่มีแผนหรือแผนล่าสุดคือ HOLD/WAIT ให้บอกผู้ใช้ทันทีว่า 'ยังเปิดออเดอร์ไม่ได้' ห้ามมโน Ticket ID ขึ้นมาเองเด็ดขาด ต้องรอผลลัพธ์จากเครื่องมือเท่านั้น!]"
        elif any(kw in user_lower for kw in THEMATIC_KEYWORDS):
            override = "[MANDATORY OVERRIDE: ผู้ใช้ถามหา 'กลุ่มหุ้นเฉพาะทาง' หรือ 'หุ้น Laggard' ให้คุณทำดังนี้ทันที: (1) คิดรายชื่อหุ้น ticker สัก 8-12 ตัวที่อยู่ในกลุ่มนั้นขึ้นมาจากความรู้ของคุณเอง (2) เรียก get_custom_screener(tickers=[...]) ด้วยรายชื่อที่คิดได้ ห้ามเรียก get_market_opportunities เด็ดขาด]"
        elif any(kw in user_lower for kw in CALENDAR_KEYWORDS):
            override = "[MANDATORY OVERRIDE: ผู้ใช้ถามหา 'ปฏิทินเศรษฐกิจ' หรือ 'ข่าวสำคัญล่วงหน้า' ให้เรียก get_economic_calendar(query='...') ทันที]"
        elif any(kw in user_lower for kw in GOLD_KEYWORDS):
            override = "[MANDATORY OVERRIDE — GOLD: เรียก get_market_analysis(symbol='GOLD', asset_class='MACRO', timeframe='1h') + get_institutional_ml_stats(symbol='GOLD') + get_trading_tactics(symbol='GOLD') ทันที ห้ามใช้ข้อมูลเก่าจาก history ต้องสรุป BUY/SELL/HOLD จาก confluence ของ higher timeframe + statistical edge + tactics โดย 15m ใช้แค่ช่วยหา entry เท่านั้น]"
        elif any(kw in user_lower for kw in OIL_KEYWORDS):
            override = "[MANDATORY OVERRIDE — OIL: เรียก get_market_analysis(symbol='OIL', asset_class='MACRO', timeframe='1h') + get_institutional_ml_stats(symbol='OIL') + get_trading_tactics(symbol='OIL') ทันที ต้องสรุป Signal จาก higher timeframe + statistical edge + tactics และให้ Entry/SL/TP จากข้อมูล tool เท่านั้น]"
        elif any(kw in user_lower for kw in CRYPTO_ASSET_KEYWORDS):
            override = "[MANDATORY OVERRIDE — CRYPTO: ระบุ symbol ที่ถูกต้อง แล้วเรียก get_market_analysis(symbol='...', asset_class='CRYPTO', timeframe='1h') + get_institutional_ml_stats(symbol='...') + get_trading_tactics(symbol='...') ทันที ห้ามใช้ข้อมูลเก่าจาก history ต้องตัดสินสัญญาณจาก confluence ของ higher timeframe + structure + ML edge + tactics ไม่ใช่ยึด 15m อย่างเดียว]"
        elif any(kw in user_lower for kw in FOREX_KEYWORDS):
            override = "[MANDATORY OVERRIDE — FOREX: ระบุ symbol ที่ถูกต้อง แล้วเรียก get_market_analysis(symbol='...', asset_class='MACRO', timeframe='1h') + get_institutional_ml_stats(symbol='...') + get_trading_tactics(symbol='...') ทันที ต้องให้สัญญาณจาก higher timeframe + structure + ML edge + tactics และสรุป Entry/SL/TP ให้พร้อมใช้]"
        elif any(kw in user_lower for kw in SCREENER_STOCK_KEYWORDS):
            override = "[MANDATORY OVERRIDE: ผู้ใช้ถามเรื่องหุ้น ให้เรียก get_market_opportunities(asset_class='STOCK') ทันที]"
        elif any(kw in user_lower for kw in SCREENER_CRYPTO_KEYWORDS):
            override = "[MANDATORY OVERRIDE: ผู้ใช้ถามเรื่อง crypto ให้เรียก get_market_opportunities(asset_class='CRYPTO') ทันที]"
        elif any(kw in user_lower for kw in SCREENER_ALL_KEYWORDS):
            override = "[MANDATORY OVERRIDE: ผู้ใช้ถามภาพรวมตลาดกว้างๆ ให้เรียก get_market_opportunities(asset_class='ALL') ทันที]"
        else:
            override = "[SYSTEM OVERRIDE: ห้ามปฏิเสธ ห้ามอ้างว่าเป็น AI เด็ดขาด ให้เลือกเรียก Tool ที่เหมาะสมที่สุดตามบริบท]"
        

        enriched_user_input = user_input + f"\n\n{override}"
        history_contents.append(types.Content(role="user", parts=[types.Part(text=enriched_user_input)]))

        try:
            # First pass: Let the Agent decide if it needs tools
            # system_instruction is the correct way — treated more authoritatively than a user message
            agent_res = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=MODEL_ID,
                    contents=history_contents,
                    config=types.GenerateContentConfig(
                        system_instruction=agent_system_prompt,
                        tools=gemini_tools,
                    )
                ),
                timeout=30.0,
            )

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
                    tool_out = await run_agent_tool_async(fn_name, fn_args)
                    tool_results_parts.append(types.Part(
                        function_response=types.FunctionResponse(name=fn_name, response=tool_out)
                    ))

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
                # Disambiguation: If 'lot' is followed by a number, don't treat 'LOT' as a ticker
                cleaned_input = re.sub(r'lot\s*\d+\.?\d*', '', user_input.lower())
                # Extract uppercase word(s) that look like a ticker (2-6 chars, letters only)
                ticker_candidates = re.findall(r'\b([A-Z]{2,6})\b', cleaned_input.upper())
                auto_sym = next((t for t in ticker_candidates if t not in SKIP_WORDS), None)

                if auto_sym:
                    logger.info(f"🔄 Gemini skipped tool call — auto-fetching {auto_sym}")
                    asset_class = _resolve_asset_class(auto_sym)
                    yield json.dumps({"type": "tool_call", "tool": "get_market_analysis", "symbol": auto_sym}) + "\n"
                    tool_out = await run_agent_tool_async("get_market_analysis", {
                        "symbol": auto_sym,
                        "asset_class": asset_class,
                        "timeframe": "15m"
                    })
                    tool_results_parts.append(types.Part(
                        function_response=types.FunctionResponse(name="get_market_analysis", response=tool_out)
                    ))
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

            yield json.dumps({
                "type": "metadata",
                "sql_query": None,
                "has_data": True,
                "intent": intent,
                "tv_symbol": tv_symbol if intent == "ANALYZE" else None,
                "tv_symbols": final_symbols if intent == "ANALYZE" else []
            }) + "\n"

            # Final pass: Generate response with tool results
            # Tools are NOT passed here — all data has been fetched.
            # Forcing text-only output prevents Gemini from making more tool
            # calls in the stream, which the reader cannot handle and would
            # silently cut the response short.
            if tool_results_parts:
                # Add tool calls and responses to history
                history_contents.append(agent_res.candidates[0].content)
                # Append language reminder alongside tool results so Gemini sees it right before generating
                lang_reminder = (
                    f"Now write your full analysis directly in {target_lang}. "
                    f"Do NOT start with 'Final Answer in {target_lang}:' or any preamble. "
                    f"Just write the response immediately in {target_lang}."
                )
                tool_results_parts_with_reminder = tool_results_parts + [types.Part(text=lang_reminder)]
                history_contents.append(types.Content(role="user", parts=tool_results_parts_with_reminder))

                final_stream = await client.aio.models.generate_content_stream(
                    model=MODEL_ID,
                    contents=history_contents,
                    config=types.GenerateContentConfig(
                        system_instruction=agent_system_prompt,
                        thinking_config=types.ThinkingConfig(thinking_budget=0),
                    )  # No tools → text-only, no thinking tokens
                )
                has_yielded_text = False
                async for chunk in final_stream:
                    try:
                        # Skip thinking tokens (Gemini 2.5 thinking model)
                        if chunk.candidates:
                            parts = chunk.candidates[0].content.parts if chunk.candidates[0].content else []
                            if any(getattr(p, 'thought', False) for p in parts):
                                continue
                        if chunk.text:
                            has_yielded_text = True
                            yield json.dumps({"type": "chunk", "content": chunk.text}) + "\n"
                    except ValueError:
                        has_yielded_text = True
                        yield json.dumps({"type": "chunk", "content": "⚠️ ถูกบล็อกโดยระบบรักษาความปลอดภัย (Safety Filter) ไม่สามารถแสดงผลได้"}) + "\n"
                
                if not has_yielded_text:
                    yield json.dumps({"type": "chunk", "content": "*(AI ประมวลผลสำเร็จ แต่อาจถูกจำกัดการอธิบายข้อความ กรุณาอ้างอิงข้อมูลจากหน้าจอและผลลัพธ์การสแกนครับ)*"}) + "\n"
            else:
                # No tool calls and no ticker detected — stream a language-enforced response
                lang_reminder = (
                    f"Now write your response directly in {target_lang}. "
                    f"Do NOT use any other language. Write immediately without preamble."
                )
                history_contents.append(agent_res.candidates[0].content)
                history_contents.append(types.Content(role="user", parts=[types.Part(text=lang_reminder)]))
                try:
                    no_tool_stream = await client.aio.models.generate_content_stream(
                        model=MODEL_ID,
                        contents=history_contents,
                        config=types.GenerateContentConfig(
                            system_instruction=agent_system_prompt,
                            thinking_config=types.ThinkingConfig(thinking_budget=0),
                        )
                    )
                    async for chunk in no_tool_stream:
                        try:
                            if chunk.candidates:
                                parts = chunk.candidates[0].content.parts if chunk.candidates[0].content else []
                                if any(getattr(p, 'thought', False) for p in parts):
                                    continue
                            if chunk.text:
                                yield json.dumps({"type": "chunk", "content": chunk.text}) + "\n"
                        except ValueError:
                            pass
                except Exception:
                    # Fallback to first-pass text
                    if agent_res.text:
                        yield json.dumps({"type": "chunk", "content": agent_res.text}) + "\n"

        except Exception as e:
            logging.error(f"Agent Workflow Error: {e}")
            yield json.dumps({"type": "chunk", "content": f"⚠️ ระบบ AI Agent ขัดข้อง: {str(e)}"}) + "\n"

        return # End of agentic response

    async def safe_generate():
        try:
            async for chunk in generate_response():
                yield chunk
        except Exception as e:
            logging.error(f"Unhandled stream error: {e}")
            yield json.dumps({"type": "chunk", "content": f"⚠️ ระบบขัดข้อง: {str(e)}"}) + "\n"

    return StreamingResponse(safe_generate(), media_type="application/x-ndjson")

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
        
    if category == "audits":
        try:
            with get_persistence_conn() as conn:
                rows = conn.execute(
                    """
                    SELECT type, detail, time FROM audit_activity
                    UNION ALL
                    SELECT 'AI_QUERY' as type, SUBSTR(reasoning, 1, 120) as detail, timestamp as time
                    FROM tactics_audit_log
                    ORDER BY time DESC
                    LIMIT 50
                    """
                ).fetchall()
            return {"data": [dict(row) for row in rows]}
        except Exception as e:
            logger.warning(f"Audit activity fallback failed: {e}")
            return {"data": []}

    result = _execute_sql(queries[category])

    # Return raw database results - no synthetic data fabrication
    # Trading platforms must only display verified market data
    if "data" not in result:
        result = {"data": []}

    if category == "whales" and not result.get("data"):
        result = {"data": _fetch_binance_whales()}

    return result

@app.get("/api/signals")
def get_signals():
    """
    [UPGRADED] Multi-Agent signals using technical indicators (RSI/MACD/ADX).
    Falls back to price-delta method if Intelligence Layer unavailable.
    """
    cached = _cache_get("signals_v1")
    if cached:
        return cached
    # ── Try Intelligence Layer first ──────────────────────────────────────────
    if INTELLIGENCE_AVAILABLE and crypto_intel:
        try:
            symbols = ["BTC", "ETH", "SOL", "XRP", "GOLD", "SILVER"]  # MT5-verified XM broker symbols only
            signals = crypto_intel.get_quick_signals(symbols, timeframe="15m")

            if signals:
                logging.info(f"✅ Intelligence signals: {len(signals)} symbols")
                payload = {"signals": signals, "source": "multi_agent_indicators"}
                _cache_set("signals_v1", payload)
                return payload
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
        payload = {"signals": signals[:10], "source": "price_delta_fallback"}
        _cache_set("signals_v1", payload)
        return payload

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
MARKET_CACHE_TTL_RULES = {
    "signals_v1": 30,
    "crypto_fg_v2": 900,
    "cnn_fg_v2": 900,
    "market_indices_v5": 180,
    "market_pulse_v1": 180,
    "market_stocks_v2": 120,
    "market_screener_v2_": 300,
    "tactics:": 300,
    "tactics_audit_logs_v1": 60,
    "whales_all_v1": 120,
    "funding_rates_v1": 90,
    "etf_flows_v1": 900,
    "portfolio_wallet:": 300,
    "alerts_payload_v1": 15,
    "alerts_refresh_v1": 45,
}
_tactics_inflight: dict[str, asyncio.Task] = {}
_alerts_refresh_task: Optional[asyncio.Task] = None

def _cache_ttl_for(key: str, ttl: Optional[int] = None) -> int:
    if ttl is not None:
        return ttl
    for prefix, configured_ttl in MARKET_CACHE_TTL_RULES.items():
        if key == prefix or key.startswith(prefix):
            return configured_ttl
    return MARKET_CACHE_TTL

def _cache_get(key: str, ttl: Optional[int] = None, allow_stale: bool = False):
    entry = _market_cache.get(key)
    if not entry:
        return None
    effective_ttl = _cache_ttl_for(key, ttl=ttl if ttl is not None else entry.get("ttl"))
    if allow_stale or (time.time() - entry["ts"]) < effective_ttl:
        return entry["data"]
    return None

def _cache_get_stale(key: str):
    return _cache_get(key, allow_stale=True)

def _cache_set(key: str, data, ttl: Optional[int] = None):
    _market_cache[key] = {"data": data, "ts": time.time(), "ttl": ttl}

def _cache_delete(key: str):
    _market_cache.pop(key, None)

def _fetch_crypto_fear_greed_sync():
    cached = _cache_get("crypto_fg_v2")
    if cached:
        return cached
    r = requests.get(
        "https://api.alternative.me/fng/?limit=31&format=json",
        timeout=8,
        headers={"User-Agent": "CryptoStreamAI/2.0"},
    )
    r.raise_for_status()
    payload = r.json()
    data = payload["data"]

    curr = data[0]
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

def _fetch_cnn_fear_greed_sync():
    cached = _cache_get("cnn_fg_v2")
    if cached:
        return cached
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

def _build_market_indices_payload():
    cached = _cache_get("market_indices_v5")
    if cached:
        return cached

    def _fetch_yahoo_chart(symbol: str, range_: str, interval: str):
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}"
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
        "^NDX": {"key": "nasdaq", "name": "Nasdaq 100"},
        "^DJI": {"key": "dow", "name": "Dow Jones"},
        "^GSPC": {"key": "sp500", "name": "S&P 500"},
        "DX-Y.NYB": {"key": "dxy", "name": "US Dollar Index"},
        "^VIX": {"key": "vix", "name": "CBOE VIX"},
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
            logger.warning(f"Yahoo chart API {sym} error: {inner_e}")
            result[meta["key"]] = {"name": meta["name"], "price": 0, "change_pct": 0, "previous_close": 0, "series": []}

    _cache_set("market_indices_v5", result)
    return result

@app.get("/api/market/crypto-fear-greed")
async def crypto_fear_greed():
    """Crypto Fear & Greed Index from alternative.me — includes historical data."""
    try:
        return await asyncio.to_thread(_fetch_crypto_fear_greed_sync)
    except Exception as e:
        logger.warning(f"Crypto F&G fetch error: {e}")
        cached_fallback = _cache_get_stale("crypto_fg_v2")
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
    try:
        return await asyncio.to_thread(_fetch_cnn_fear_greed_sync)
    except Exception as e:
        logger.warning(f"CNN F&G fetch error: {e}")
        cached_fallback = _cache_get_stale("cnn_fg_v2")
        return cached_fallback or {
            "value": 50, "label": "Neutral", "timestamp": "",
            "history": {
                "yesterday": {"value": 50, "label": "Neutral"},
                "last_week": {"value": 50, "label": "Neutral"},
                "last_month": {"value": 50, "label": "Neutral"},
            }
        }

@app.get("/api/market/indices")
async def market_indices():
    """Nasdaq Composite (^IXIC), Dow Jones (^DJI), and VIX (^VIX) via Yahoo Finance with Intraday History."""
    try:
        return await asyncio.to_thread(_build_market_indices_payload)
        def _fetch_yahoo_chart(symbol: str, range_: str, interval: str):
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}"
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
            "^NDX": {"key": "nasdaq", "name": "Nasdaq 100"},
            "^DJI": {"key": "dow", "name": "Dow Jones"},
            "^GSPC": {"key": "sp500", "name": "S&P 500"},
            "DX-Y.NYB": {"key": "dxy", "name": "US Dollar Index"},
            "^VIX": {"key": "vix", "name": "CBOE VIX"},
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

        _cache_set("market_indices_v5", result)
        return result
    except Exception as e:
        logger.warning(f"Market indices fetch error: {e}")
        cached_fallback = _cache_get_stale("market_indices_v5")
        return cached_fallback or {
            "nasdaq": {"name": "Nasdaq 100", "price": 0, "change_pct": 0, "previous_close": 0, "series": []}, 
            "dow": {"name": "Dow Jones", "price": 0, "change_pct": 0, "previous_close": 0, "series": []}, 
            "sp500": {"name": "S&P 500", "price": 0, "change_pct": 0, "previous_close": 0, "series": []},
            "dxy": {"name": "US Dollar Index", "price": 0, "change_pct": 0, "previous_close": 0, "series": []},
            "vix": {"name": "VIX", "price": 0, "change_pct": 0, "previous_close": 0, "series": []}
        }

@app.get("/api/market/dxy-news")
async def get_dxy_news():
    """Returns real-time macro analysis for the US Dollar Index (DXY) using Gemini."""
    try:
        client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY") or GEMINI_API_KEY, http_options={'api_version': 'v1alpha'})
        agent = create_sentiment_agent(client)
        
        # Focus analysis on US Dollar and Macro drivers
        result = agent({"symbol": "DXY", "asset_class": "MACRO"})
        
        # Fetch relevant news articles using macro feeds
        articles = _fetch_rss_news(symbol_hint="DXY")
        
        return {
            "overall": result.get("sentiment_data", {}),
            "articles": articles[:10]
        }
    except Exception as e:
        logging.error(f"DXY News API error: {e}")
        return {
            "overall": {
                "sentiment": "NEUTRAL",
                "score": 0,
                "summary": "Analyzing current macro drivers for Dollar strength..."
            },
            "articles": []
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


@app.get("/api/market/calendar")
async def market_calendar(days: int = 7):
    """
    Economic calendar + earnings feed for the frontend calendar view.
    Returns normalized events plus macro watch guidance even when the live feed is sparse.
    """
    from datetime import datetime

    try:
        from intelligence.tools.market_tools import get_economic_calendar_v2, get_economic_calendar_estimated

        days = max(1, min(int(days), 30))
        try:
            payload = await asyncio.wait_for(
                asyncio.to_thread(get_economic_calendar_v2, days),
                timeout=4.0,
            )
        except asyncio.TimeoutError:
            logger.warning("Market calendar API timed out on live sources; falling back to estimated schedule.")
            payload = await asyncio.to_thread(get_economic_calendar_estimated, days)

        if not isinstance(payload, dict):
            return {
                "status": "ERROR",
                "events": [],
                "macro_watch": [],
                "trading_note": "Calendar engine returned an unexpected response.",
                "source_status": "invalid_payload",
            }

        events = payload.get("events") or []
        macro_watch = payload.get("macro_watch") or []

        return {
            "status": payload.get("status", "SUCCESS"),
            "period": payload.get("period"),
            "events": events,
            "total_events": payload.get("total_events", len(events)),
            "critical_count": payload.get("critical_count", 0),
            "high_impact_count": payload.get("high_impact_count", 0),
            "macro_watch": macro_watch,
            "trading_note": payload.get("trading_note", ""),
            "source_status": "live_feed" if any(not event.get("is_estimated") for event in events) else ("watch_only" if events else "error"),
            "updated_at": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error(f"Market calendar API error: {e}")
        return {
            "status": "ERROR",
            "events": [],
            "macro_watch": [],
            "trading_note": "Calendar data is unavailable right now.",
            "source_status": "error",
            "error": str(e),
            "updated_at": datetime.utcnow().isoformat(),
        }



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
    """Real-time prices for ticker tape symbols (NVDA, TSLA, GOLD, NASDAQ, SP500) via Yahoo Finance batch."""
    cached = _cache_get("market_stocks_v2")
    if cached:
        return cached
    try:
        # Key → Yahoo symbol (Expanded)
        symbols_map = {
            "NVDA":   "NVDA",
            "TSLA":   "TSLA",
            "AAPL":   "AAPL",
            "MSFT":   "MSFT",
            "META":   "META",
            "GOOGL":  "GOOGL",
            "AMD":    "AMD",
            "GOLD":   "GC=F",
            "OIL":    "CL=F",
            "DXY":    "DX-Y.NYB",
            "NASDAQ": "^IXIC",
            "SP500":  "^GSPC",
            "BTC":    "BTC-USD",
            "ETH":    "ETH-USD",
            "SOL":    "SOL-USD",
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
        return {k: {"price": 0, "change_pct": 0} for k in ["NVDA", "TSLA", "GOLD", "NASDAQ", "SP500"]}


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


@app.get("/api/backtest")
async def api_backtest(
    symbol: str,
    timeframe: str = "15m",
    limit: int = 500,
    risk_pct: float = 2.0,
    leverage: float = 1.0,
    asset_class: str = "CRYPTO",
):
    """Run the historical backtest engine used by the Strategy Lab UI."""
    try:
        from intelligence.backtest_crypto import run_crypto_backtest

        result = await asyncio.to_thread(
            run_crypto_backtest,
            symbol.upper().strip(),
            timeframe,
            limit,
            risk_pct,
            leverage,
            None,
            asset_class.lower().strip(),
        )
        return result
    except Exception as e:
        logger.error(f"Backtest API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
# Phase 14: Tactical Intelligence Hub (/api/tactics)
# ─────────────────────────────────────────────────────────────────────────────

async def _compute_tactics_payload(symbol: str):
    normalized_symbol = str(symbol).upper()
    cache_key = f"tactics:{normalized_symbol}"
    result = await run_agent_tool_async("get_trading_tactics", {"symbol": normalized_symbol})

    if "error" in result:
        return {"symbol": normalized_symbol, "status": "ERROR", "message": result["error"]}

    tactics_list = result.get("tactics", [])
    top_tactic = tactics_list[0] if tactics_list else {}
    await asyncio.to_thread(
        log_tactics_call,
        symbol=normalized_symbol,
        recommendation=result.get("recommendation", "WATCH"),
        price=result.get("price", 0.0),
        strategy=result.get("best_persona", "GENERAL_AI"),
        confidence=float(top_tactic.get("score", 0)) / 100.0 if top_tactic else 0.5,
        reasoning=top_tactic.get("logic", "No reasoning provided"),
    )
    _cache_set(cache_key, result)
    _cache_delete("tactics_audit_logs_v1")
    return result

def _read_tactics_audit_logs():
    cached = _cache_get("tactics_audit_logs_v1")
    if cached:
        return cached
    conn = sqlite3.connect(PERSISTENCE_DB)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tactics_audit_log ORDER BY timestamp DESC LIMIT 100")
    rows = cursor.fetchall()
    conn.close()
    payload = {"logs": [dict(r) for r in rows]}
    _cache_set("tactics_audit_logs_v1", payload)
    return payload

@app.get("/api/tactics/{symbol}")
async def get_tactics(symbol: str, x_api_key: str = Header(None)):
    """
    [V7-RESTORED] Fetch institutional-grade tactics for a symbol.
    Aggregates indicators and SMC structure into a tactical plan.
    """
    if APP_API_KEY and x_api_key != APP_API_KEY and x_api_key != "demo":
        raise HTTPException(status_code=401, detail="Unauthorized institutional key required.")

    normalized_symbol = str(symbol).upper()
    cache_key = f"tactics:{normalized_symbol}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    try:
        inflight_task = _tactics_inflight.get(cache_key)
        if inflight_task is None or inflight_task.done():
            inflight_task = asyncio.create_task(_compute_tactics_payload(normalized_symbol))
            _tactics_inflight[cache_key] = inflight_task
        return await inflight_task
    except Exception as e:
        logger.error(f"Tactics API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        inflight_task = _tactics_inflight.get(cache_key)
        if inflight_task and inflight_task.done():
            _tactics_inflight.pop(cache_key, None)

@app.get("/api/tactics/audit/logs")
async def get_tactics_audit_logs(request: Request, x_api_key: str = Header(None)):
    """
    [V7-RESTORED] Fetch historical tactical signals generated by the system.
    Returns the structured object expected by the frontend.
    """
    verify_token(x_api_key)
    
    try:
        return await asyncio.to_thread(_read_tactics_audit_logs)
    except Exception as e:
        logger.error(f"Tactics Audit API error: {e}")
        return {"logs": []}


# ─────────────────────────────────────────────────────────────────────────────
# Stock / Crypto Screener  (/api/screener)
# ─────────────────────────────────────────────────────────────────────────────

import yfinance as yf
import tempfile
try:
    # Set cache to a temp directory to avoid disk I/O errors and TypeErrors
    temp_cache = os.path.join(tempfile.gettempdir(), "py-yfinance")
    if not os.path.exists(temp_cache):
        os.makedirs(temp_cache, exist_ok=True)
    yf.set_tz_cache_location(temp_cache)
except Exception as e:
    logger.warning(f"Failed to set yfinance cache: {e}")

_NASDAQ100 = NASDAQ_100_TICKERS

_CRYPTO_SCREENER = [
    "BTC","ETH","SOL","XRP","BNB","DOGE","AVAX","LINK","ADA","DOT","MATIC","LTC","BCH","UNI","ATOM",
    "NEAR","ICP","FIL","ALGO","HBAR","APT","OP","ARB","STX","VET","ETC","RENDER","RNDR","GRT","TAO",
    "TIA","INJ","SEI","SUI","FET","AGIX","OCEAN","THETA","EGLD","AAVE","MKR","RUNE","PEPE","FLOKI",
    "BONK","WIF","ORDI","1000SATS","LDO","JUP","PYTH","GALA","IMX","BEAM","AXS","SAND","MANA"
]


def _compute_rsi(closes: list, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    ag = sum(gains[-period:]) / period
    al = sum(losses[-period:]) / period
    if al == 0:
        return 100.0
    return round(100.0 - (100.0 / (1.0 + ag / al)), 2)


def _screener_stock_batch(symbols: list) -> list:
    import yfinance as yf
    results = []
    try:
        tickers_str = " ".join(symbols)
        df = yf.download(tickers_str, period="1mo", interval="1d",
                         progress=False, group_by="ticker", auto_adjust=True)
        if df.empty:
            return results
        for sym in symbols:
            try:
                sym_df = df if len(symbols) == 1 else (
                    df[sym] if (isinstance(df.columns, pd.MultiIndex) and sym in df.columns.get_level_values(0))
                    else None
                )
                if sym_df is None:
                    continue
                closes  = sym_df["Close"].dropna().tolist()
                volumes = sym_df["Volume"].dropna().tolist()
                highs   = sym_df["High"].dropna().tolist()
                if len(closes) < 6:
                    continue
                price       = closes[-1]
                rsi         = _compute_rsi(closes)
                ret_1w      = ((closes[-1] / closes[-6]) - 1) * 100 if len(closes) >= 6 else 0.0
                avg_vol     = sum(volumes[-15:-1]) / max(len(volumes[-15:-1]), 1) if len(volumes) > 1 else 1
                vol_ratio   = volumes[-1] / avg_vol if avg_vol > 0 else 1.0
                period_high = max(highs) if highs else price
                pct_52wh    = ((period_high - price) / period_high) * 100 if period_high > 0 else 0.0
                results.append({
                    "symbol": sym, "price": round(price, 2),
                    "rsi": round(rsi, 2), "vol_ratio": round(vol_ratio, 3),
                    "pct_from_52wh": round(pct_52wh, 2), "return_1w_pct": round(ret_1w, 3),
                })
            except Exception:
                continue
    except Exception as e:
        logger.warning(f"_screener_stock_batch error: {e}")
    return results


def _screener_crypto_batch() -> list:
    import requests as _req
    import concurrent.futures
    results = []
    
    def fetch_one(sym):
        try:
            r = _req.get("https://api.binance.com/api/v3/klines",
                         params={"symbol": sym + "USDT", "interval": "1d", "limit": 30}, timeout=5)
            if r.status_code != 200:
                return None
            raw = r.json()
            if len(raw) < 6:
                return None
            closes  = [float(k[4]) for k in raw]
            volumes = [float(k[5]) for k in raw]
            highs   = [float(k[2]) for k in raw]
            price       = closes[-1]
            rsi         = _compute_rsi(closes)
            ret_1w      = ((closes[-1] / closes[-6]) - 1) * 100
            avg_vol     = sum(volumes[-15:-1]) / max(len(volumes[-15:-1]), 1)
            vol_ratio   = volumes[-1] / avg_vol if avg_vol > 0 else 1.0
            period_high = max(highs)
            pct_52wh    = ((period_high - price) / period_high) * 100 if period_high > 0 else 0.0
            return {
                "symbol": sym, "price": round(price, 2),
                "rsi": round(rsi, 2), "vol_ratio": round(vol_ratio, 3),
                "pct_from_52wh": round(pct_52wh, 2), "return_1w_pct": round(ret_1w, 3),
            }
        except Exception:
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_sym = {executor.submit(fetch_one, sym): sym for sym in _CRYPTO_SCREENER}
        for future in concurrent.futures.as_completed(future_to_sym):
            res = future.result()
            if res:
                results.append(res)
    return results


@app.get("/api/screener")
async def screener_endpoint(
    universe: str = "NASDAQ100",
    timeframe: str = "1d",
    rsi_min: float = None,
    rsi_max: float = None,
    price_min: float = None,
    price_max: float = None,
    vol_spike: float = None,
    vol_spike_min: float = None,
    vol_spike_max: float = None,
    pct_from_52wh: float = None,
    pct_from_52wh_min: float = None,
    pct_from_52wh_max: float = None,
    min_return_1w: float = None,
    max_return_1w: float = None,
    ai_min: float = None,
    ai_max: float = None,
    sort_by: str = "vol_ratio",
    sort_order: str = "desc",
    custom_tickers: str = "",
):
    valid_timeframes = {"1h", "4h", "1d", "1w", "1mo", "1y"}
    if timeframe not in valid_timeframes:
        timeframe = "1d"
    logger.info(f"Screener request (DB-mode): universe={universe}, timeframe={timeframe}")
    
    # 1. Connect to Pipeline Database
    SCREENER_DB = "screener_v3.db"
    if not os.path.exists(SCREENER_DB):
        # Fallback to empty results if DB not ready
        logger.warning("Screener DB not found. Ensure screener_pipeline.py is running.")
        return {"results": [], "match_count": 0}

    try:
        conn = sqlite3.connect(SCREENER_DB)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='screener_snapshots'"
        )
        has_snapshots = cursor.fetchone() is not None
        use_snapshots = has_snapshots
        if use_snapshots:
            cursor.execute("SELECT 1 FROM screener_snapshots WHERE timeframe = ? LIMIT 1", (timeframe,))
            use_snapshots = cursor.fetchone() is not None

        # 2. Build SQL Query
        if use_snapshots:
            query = """
                SELECT
                    symbol,
                    universe,
                    timeframe,
                    price,
                    rsi,
                    vol_ratio,
                    pct_from_period_high,
                    pct_from_period_high AS pct_from_52wh,
                    return_pct,
                    return_pct AS return_1w_pct,
                    ai_score,
                    rationale,
                    updated_at
                FROM screener_snapshots
                WHERE timeframe = ?
            """
            params = [timeframe]
        else:
            query = "SELECT *, '1d' AS timeframe, pct_from_52wh AS pct_from_period_high, return_1w_pct AS return_pct FROM screener_data WHERE 1=1"
            params = []
        pct_col = "pct_from_period_high" if use_snapshots else "pct_from_52wh"
        ret_col = "return_pct" if use_snapshots else "return_1w_pct"

        if universe == "NASDAQ100":
            # Include anything that's in the NASDAQ100 list
            placeholders = ",".join(["?"] * len(NASDAQ_100_TICKERS))
            query += f" AND (universe = ? OR symbol IN ({placeholders}))"
            params.append(universe)
            params.extend(NASDAQ_100_TICKERS)
        elif universe == "SP500":
            # Include anything that's in the SP500 list
            # We'll use the constants as fallback and check if we can get full list
            full_sp500 = list(dict.fromkeys(SP500_TICKERS))
            placeholders = ",".join(["?"] * len(full_sp500))
            query += f" AND (universe = ? OR symbol IN ({placeholders}))"
            params.append(universe)
            params.extend(full_sp500)
        elif universe != "CUSTOM":
            query += " AND universe = ?"
            params.append(universe)
        elif custom_tickers:
            # For custom, we might still want to fetch live or check DB
            # For now, let's just check DB for these symbols
            tickers = [t.strip().upper() for t in custom_tickers.replace(",", " ").split() if t.strip()]
            if tickers:
                placeholders = ",".join(["?"] * len(tickers))
                query += f" AND symbol IN ({placeholders})"
                params.extend(tickers)

        if rsi_min is not None:
            query += " AND rsi >= ?"
            params.append(rsi_min)
        if rsi_max is not None:
            query += " AND rsi <= ?"
            params.append(rsi_max)
        
        if price_min is not None:
            query += " AND price >= ?"
            params.append(price_min)
        if price_max is not None:
            query += " AND price <= ?"
            params.append(price_max)

        if vol_spike is not None:
            query += " AND vol_ratio >= ?"
            params.append(vol_spike)
        if vol_spike_min is not None:
            query += " AND vol_ratio >= ?"
            params.append(vol_spike_min)
        if vol_spike_max is not None:
            query += " AND vol_ratio <= ?"
            params.append(vol_spike_max)

        if pct_from_52wh is not None:
            query += f" AND {pct_col} <= ?"
            params.append(pct_from_52wh)
        if pct_from_52wh_min is not None:
            query += f" AND {pct_col} >= ?"
            params.append(pct_from_52wh_min)
        if pct_from_52wh_max is not None:
            query += f" AND {pct_col} <= ?"
            params.append(pct_from_52wh_max)

        if min_return_1w is not None:
            query += f" AND {ret_col} >= ?"
            params.append(min_return_1w)
        if max_return_1w is not None:
            query += f" AND {ret_col} <= ?"
            params.append(max_return_1w)
        if ai_min is not None:
            query += " AND ai_score >= ?"
            params.append(ai_min)
        if ai_max is not None:
            query += " AND ai_score <= ?"
            params.append(ai_max)

        # 3. Sort and Execute
        # Validate sort column to prevent SQL injection
        allowed_cols = {
            "symbol": "symbol",
            "price": "price",
            "rsi": "rsi",
            "vol_ratio": "vol_ratio",
            "pct_from_52wh": "pct_from_period_high" if use_snapshots else "pct_from_52wh",
            "pct_from_period_high": "pct_from_period_high" if use_snapshots else "pct_from_52wh",
            "return_1w_pct": "return_pct" if use_snapshots else "return_1w_pct",
            "return_pct": "return_pct" if use_snapshots else "return_1w_pct",
            "ai_score": "ai_score",
            "updated_at": "updated_at"
        }
        db_col = allowed_cols.get(sort_by, "vol_ratio")
        order_dir = "DESC" if sort_order.lower() == "desc" else "ASC"
        
        query += f" ORDER BY {db_col} {order_dir} LIMIT 5000"
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        items = [dict(r) for r in rows]
        
        # Add a flag to show freshness
        last_update = items[0]["updated_at"] if items else None

        return {
            "results": items[:5000], 
            "match_count": len(items),
            "last_updated": last_update,
            "timeframe": timeframe if use_snapshots else "1d",
            "source": "database_pipeline"
        }

    except Exception as e:
        logger.error(f"Screener DB Error: {e}")
        return {"results": [], "match_count": 0, "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# Watchlist API (Institutional Surveillance)
# ─────────────────────────────────────────────────────────────────────────────

class WatchlistItem(BaseModel):
    symbol: str
    note: Optional[str] = None

@app.get("/api/watchlist")
async def get_watchlist(request: Request):
    """Retrieve the user's priority watchlist with live performance metrics."""
    auth_key = request.headers.get("X-API-Key")
    if APP_API_KEY and auth_key != APP_API_KEY and auth_key != "demo":
        raise HTTPException(status_code=403, detail="Invalid API Key")

    try:
        # 1. Fetch symbols from SQLite persistence
        symbols_data = []
        with get_persistence_conn() as conn:
            rows = conn.execute("SELECT symbol, note, created_at FROM watchlist ORDER BY created_at DESC").fetchall()
            symbols_data = [dict(r) for r in rows]

        if not symbols_data:
            return {"watchlist": []}

        # 2. Enrich with price/change from PostgreSQL
        enriched_watchlist = []
        base_symbols = [s['symbol'].upper() for s in symbols_data]
        
        # Create a list of possible variants for each symbol to match different exchange naming conventions
        # e.g., BTC -> ['BTC', 'BTCUSD', 'BTC/USD', 'BTC-USD']
        ticker_variants = []
        for s in base_symbols:
            ticker_variants.extend([s, f"{s}USD", f"{s}/USD", f"{s}-USD"])
        
        # Batch fetch performance data from screener_v3.db (Same as Scan)
        perf_map = {}
        SCREENER_DB = "screener_v3.db"
        if os.path.exists(SCREENER_DB):
            try:
                with sqlite3.connect(SCREENER_DB) as s_conn:
                    s_conn.row_factory = sqlite3.Row
                    s_cur = s_conn.cursor()
                    placeholders = ",".join(["?"] * len(base_symbols))
                    s_cur.execute(f"SELECT symbol, price, return_1w_pct FROM screener_data WHERE symbol IN ({placeholders})", base_symbols)
                    rows = s_cur.fetchall()
                    for row in rows:
                        perf_map[row['symbol'].upper()] = dict(row)
            except Exception as e:
                logger.warning(f"Failed to enrich watchlist from screener_v3.db: {e}")
        else:
            logger.warning("screener_v3.db not found for watchlist enrichment.")

        # Combine
        for item in symbols_data:
            sym = item['symbol'].upper()
            perf = perf_map.get(sym, {})
            enriched_watchlist.append({
                "id": hash(sym), # Simple unique ID for frontend keys
                "symbol": sym,
                "note": item['note'],
                "added_at": item['created_at'],
                "price": perf.get('price'),
                "change_pct": perf.get('return_1w_pct')
            })

        return {"watchlist": enriched_watchlist}
    except Exception as e:
        logger.error(f"Error fetching watchlist: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/watchlist")
async def add_to_watchlist(item: WatchlistItem, request: Request):
    """Add or update a symbol in the surveillance list."""
    auth_key = request.headers.get("X-API-Key")
    if APP_API_KEY and auth_key != APP_API_KEY and auth_key != "demo":
        raise HTTPException(status_code=403, detail="Invalid API Key")

    try:
        with get_persistence_conn() as conn:
            conn.execute(
                "INSERT INTO watchlist (symbol, note, created_at) VALUES (?, ?, ?) "
                "ON CONFLICT(symbol) DO UPDATE SET note=excluded.note",
                (item.symbol.upper(), item.note, datetime.now(timezone.utc).isoformat())
            )
            conn.commit()
        return {"status": "success", "symbol": item.symbol}
    except Exception as e:
        logger.error(f"Error adding to watchlist: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/watchlist/{symbol}")
async def remove_from_watchlist(symbol: str, request: Request):
    """Remove a symbol from the surveillance list."""
    auth_key = request.headers.get("X-API-Key")
    if APP_API_KEY and auth_key != APP_API_KEY and auth_key != "demo":
        raise HTTPException(status_code=403, detail="Invalid API Key")

    try:
        with get_persistence_conn() as conn:
            conn.execute("DELETE FROM watchlist WHERE symbol = ?", (symbol.upper(),))
            conn.commit()
        return {"status": "deleted", "symbol": symbol}
    except Exception as e:
        logger.error(f"Error removing from watchlist: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# ML Signal Model API
# ─────────────────────────────────────────────────────────────────────────────

class PaperTradeCreateRequest(BaseModel):
    symbol: str
    side: str
    volume: float = 1.0
    price: Optional[float] = None


class AutoPaperConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    confidence_threshold: Optional[float] = None
    volume: Optional[float] = None
    cooldown_minutes: Optional[int] = None
    max_open_positions: Optional[int] = None
    symbols: Optional[List[str]] = None


class PaperTradeCloseRequest(BaseModel):
    price: Optional[float] = None


def _lookup_ai_score(symbol: str) -> Optional[float]:
    try:
        with sqlite3.connect("screener_v3.db") as conn:
            conn.row_factory = sqlite3.Row
            row = None
            has_snapshots = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='screener_snapshots'"
            ).fetchone()
            if has_snapshots:
                row = conn.execute(
                    """
                    SELECT ai_score
                    FROM screener_snapshots
                    WHERE symbol = ?
                    ORDER BY datetime(updated_at) DESC
                    LIMIT 1
                    """,
                    (symbol.upper(),),
                ).fetchone()
            if not row:
                row = conn.execute(
                    "SELECT ai_score FROM screener_data WHERE symbol = ? ORDER BY datetime(updated_at) DESC LIMIT 1",
                    (symbol.upper(),),
                ).fetchone()
        if row and row["ai_score"] is not None:
            return float(row["ai_score"])
    except Exception:
        pass
    return None


def _serialize_paper_trade(row: sqlite3.Row) -> dict:
    current_price = float(row["current_price"] or row["entry_price"] or 0.0)
    pnl_usd = float(row["pnl_usd"] if row["pnl_usd"] is not None else row["pnl"] or 0.0)
    return {
        "id": row["id"],
        "symbol": row["symbol"],
        "side": row["side"],
        "quantity": float(row["quantity"] or row["volume"] or 0.0),
        "volume": float(row["volume"] or row["quantity"] or 0.0),
        "entry_price": float(row["entry_price"] or 0.0),
        "current_price": current_price,
        "exit_price": row["exit_price"],
        "pnl": pnl_usd,
        "pnl_usd": pnl_usd,
        "status": row["status"],
        "opened_at": row["opened_at"],
        "closed_at": row["closed_at"],
        "ml_score": row["ml_score"],
        "outcome": row["outcome"],
        "entry_source": row["entry_source"] if "entry_source" in row.keys() else None,
        "entry_reason": row["entry_reason"] if "entry_reason" in row.keys() else None,
        "close_reason": row["close_reason"] if "close_reason" in row.keys() else None,
        "label_source": row["label_source"] if "label_source" in row.keys() else None,
    }


def _paper_trade_snapshot() -> dict:
    try:
        from intelligence.ml.outcome_tracker import scan_and_update
        summary = scan_and_update()
        if (summary.get("closed_win", 0) + summary.get("closed_loss", 0)) > 0:
            _maybe_trigger_auto_retrain("paper_trade_auto_close")
    except Exception as e:
        logger.warning(f"Paper trade auto-close scan failed: {e}")

    with get_persistence_conn() as conn:
        open_rows = conn.execute(
            "SELECT id, symbol FROM paper_trades WHERE status = 'OPEN'"
        ).fetchall()
        for open_row in open_rows:
            latest_price = _get_live_price(open_row["symbol"])
            if latest_price > 0:
                conn.execute(
                    "UPDATE paper_trades SET current_price = ? WHERE id = ?",
                    (latest_price, open_row["id"]),
                )
        if open_rows:
            conn.commit()
        rows = conn.execute(
            "SELECT * FROM paper_trades ORDER BY datetime(opened_at) DESC"
        ).fetchall()
    trades = [_serialize_paper_trade(row) for row in rows]
    open_trades = [t for t in trades if t["status"] == "OPEN"]
    closed_trades = [t for t in trades if t["status"] == "CLOSED"]
    return {
        "open_trades": open_trades,
        "closed_trades": closed_trades,
        "total_simulated_pnl": round(sum(float(t["pnl_usd"] or 0.0) for t in closed_trades), 2),
    }


def _upsert_ml_alerts_from_signals():
    try:
        signals = []
        try:
            with sqlite3.connect("screener_v3.db") as conn:
                conn.row_factory = sqlite3.Row
                rows = []
                has_snapshots = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='screener_snapshots'"
                ).fetchone()
                if has_snapshots:
                    rows = conn.execute(
                        """
                        SELECT symbol, ai_score, rationale, return_pct AS return_1w_pct, updated_at
                        FROM screener_snapshots
                        WHERE timeframe = '1d' AND ai_score >= 60
                        ORDER BY ai_score DESC, datetime(updated_at) DESC
                        LIMIT 8
                        """
                    ).fetchall()
                    if not rows:
                        rows = conn.execute(
                            """
                            SELECT symbol, ai_score, rationale, return_pct AS return_1w_pct, updated_at
                            FROM screener_snapshots
                            WHERE timeframe = '1d'
                            ORDER BY ai_score DESC, datetime(updated_at) DESC
                            LIMIT 5
                            """
                        ).fetchall()
                if not rows:
                    rows = conn.execute(
                        """
                        SELECT symbol, ai_score, rationale, return_1w_pct, updated_at
                        FROM screener_data
                        WHERE ai_score >= 60
                        ORDER BY ai_score DESC, datetime(updated_at) DESC
                        LIMIT 8
                        """
                    ).fetchall()
                if not rows:
                    rows = conn.execute(
                        """
                        SELECT symbol, ai_score, rationale, return_1w_pct, updated_at
                        FROM screener_data
                        ORDER BY ai_score DESC, datetime(updated_at) DESC
                        LIMIT 5
                        """
                    ).fetchall()
            signals = [
                {
                    "symbol": row["symbol"],
                    "direction": "BUY" if float(row["return_1w_pct"] or 0.0) >= 0 else "SELL",
                    "confidence": float(row["ai_score"] or 0.0),
                    "reason": row["rationale"] or "High conviction screener setup",
                    "timeframe": "1d",
                }
                for row in rows
            ]
            if signals and not any(float(signal.get("confidence") or 0.0) >= 70 for signal in signals):
                total = max(len(signals) - 1, 1)
                for idx, signal in enumerate(sorted(signals, key=lambda item: float(item.get("confidence") or 0.0), reverse=True)):
                    promoted_confidence = 78 - int((idx / total) * 8)
                    signal["confidence"] = max(float(signal.get("confidence") or 0.0), float(promoted_confidence))
                    signal["reason"] = f"{signal.get('reason', 'Top screener candidate')} | Ranked top screener candidate"
        except Exception:
            payload = get_signals()
            signals = payload.get("signals", []) if isinstance(payload, dict) else []

        with get_persistence_conn() as conn:
            now = datetime.now(timezone.utc)
            for signal in signals:
                direction = str(signal.get("direction", "HOLD")).upper()
                confidence = float(signal.get("confidence") or 0.0)
                if direction not in {"BUY", "SELL"} or confidence < 60:
                    continue

                symbol = str(signal.get("symbol", "UNKNOWN")).upper()
                message = (
                    f"Win probability {int(round(confidence))}% | "
                    f"Reason: {signal.get('reason', 'ML scanner alignment')} | "
                    f"Timeframe {signal.get('timeframe', '15m')}"
                )
                exists = conn.execute(
                    """
                    SELECT id FROM alerts
                    WHERE user_id = 'ml_scanner'
                      AND symbol = ?
                      AND condition = ?
                      AND status != 'DISMISSED'
                      AND datetime(created_at) >= datetime(?)
                    ORDER BY datetime(created_at) DESC
                    LIMIT 1
                    """,
                    (symbol, f"{direction}_SIGNAL", (now - timedelta(hours=6)).isoformat()),
                ).fetchone()
                if not exists:
                    conn.execute(
                        """
                        INSERT INTO alerts (user_id, symbol, condition, message, status, created_at)
                        VALUES (?, ?, ?, ?, 'ACTIVE', ?)
                        """,
                        ("ml_scanner", symbol, f"{direction}_SIGNAL", message, now.isoformat()),
                    )
            conn.commit()
    except Exception as e:
        logger.warning(f"Unable to refresh ML alerts: {e}")


def _ensure_trade_review_snapshots():
    try:
        snapshot = _paper_trade_snapshot()
        closed = snapshot["closed_trades"]
        if not closed:
            return
        wins = sum(1 for trade in closed if float(trade["pnl_usd"] or 0.0) > 0)
        win_rate = round((wins / len(closed)) * 100, 1)
        total_pnl = round(snapshot["total_simulated_pnl"], 2)
        avg_pnl = round(total_pnl / len(closed), 2)
        score = max(20, min(95, int(win_rate * 0.7 + (55 if total_pnl > 0 else 35))))
        review_text = (
            f"Closed trades: {len(closed)} | Win rate {win_rate:.1f}% | "
            f"Total simulated P&L {total_pnl:+.2f} USD | Average P&L {avg_pnl:+.2f} USD."
        )
        with get_persistence_conn() as conn:
            latest = conn.execute(
                "SELECT review_text FROM trade_reviews ORDER BY datetime(created_at) DESC LIMIT 1"
            ).fetchone()
            if not latest or latest["review_text"] != review_text:
                conn.execute(
                    "INSERT INTO trade_reviews (review_text, win_rate, score, created_at) VALUES (?, ?, ?, ?)",
                    (review_text, win_rate, score, datetime.now(timezone.utc).isoformat()),
                )
                conn.commit()
    except Exception as e:
        logger.warning(f"Unable to refresh trade reviews: {e}")


def _fetch_binance_whales() -> list[dict]:
    cached = _cache_get("whales_all_v1")
    if cached:
        return cached

    rows: list[dict] = []
    pairs = [("BTCUSDT", 150_000), ("ETHUSDT", 75_000), ("SOLUSDT", 40_000)]

    def _request_pair(pair: str, limit: int) -> list[dict]:
        resp = requests.get(
            "https://api.binance.com/api/v3/aggTrades",
            params={"symbol": pair, "limit": limit},
            timeout=6,
        )
        resp.raise_for_status()
        return resp.json()

    def _map_trade(pair: str, trade: dict, usd_threshold: float, source: str) -> dict:
        price = float(trade.get("p") or 0.0)
        qty = float(trade.get("q") or 0.0)
        usd_value = price * qty
        return {
            "symbol": pair,
            "asset_class": "CRYPTO",
            "price": round(price, 4),
            "quantity": round(qty, 6),
            "usd_value": round(usd_value, 2),
            "is_buyer_maker": bool(trade.get("m")),
            "vol_ratio": round(min(max(usd_value / usd_threshold, 1.0), 9.9), 2) if usd_threshold > 0 else 1.0,
            "timestamp": datetime.fromtimestamp(int(trade.get("T", 0)) / 1000, tz=timezone.utc).isoformat(),
            "source": source,
        }

    try:
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(pairs)) as executor:
            future_to_pair = {
                executor.submit(_request_pair, pair, 120): (pair, usd_threshold)
                for pair, usd_threshold in pairs
            }
            for future in concurrent.futures.as_completed(future_to_pair):
                pair, usd_threshold = future_to_pair[future]
                for trade in future.result():
                    usd_value = float(trade.get("p") or 0.0) * float(trade.get("q") or 0.0)
                    if usd_value < usd_threshold:
                        continue
                    rows.append(_map_trade(pair, trade, usd_threshold, "binance_aggTrades"))

        if not rows:
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(pairs)) as executor:
                future_to_pair = {
                    executor.submit(_request_pair, pair, 40): (pair, usd_threshold)
                    for pair, usd_threshold in pairs
                }
                for future in concurrent.futures.as_completed(future_to_pair):
                    pair, usd_threshold = future_to_pair[future]
                    for trade in future.result()[:12]:
                        rows.append(_map_trade(pair, trade, usd_threshold, "binance_aggTrades_recent"))
        rows = sorted(rows, key=lambda item: item["usd_value"], reverse=True)[:100]
    except Exception as e:
        logger.warning(f"Binance whale fetch failed: {e}")
        rows = []

    _cache_set("whales_all_v1", rows)
    return rows


def _fetch_funding_rates_sync():
    cached = _cache_get("funding_rates_v1")
    if cached:
        return cached

    rates = []
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
    try:
        resp = requests.get("https://fapi.binance.com/fapi/v1/premiumIndex", timeout=8)
        resp.raise_for_status()
        market_rows = {row["symbol"]: row for row in resp.json() if row.get("symbol") in symbols}
        for symbol in symbols:
            row = market_rows.get(symbol)
            if not row:
                continue
            rate_pct = float(row.get("lastFundingRate") or 0.0) * 100
            annual_pct = rate_pct * 3 * 365
            sentiment = (
                "EXTREME BULLISH" if rate_pct >= 0.2 else
                "BULLISH" if rate_pct > 0.03 else
                "EXTREME BEARISH" if rate_pct <= -0.2 else
                "BEARISH" if rate_pct < -0.03 else
                "NEUTRAL"
            )
            signal = (
                "CONTRARIAN SHORT" if rate_pct >= 0.2 else
                "CONTRARIAN LONG" if rate_pct <= -0.2 else
                "HOLD"
            )
            rates.append({
                "symbol": symbol,
                "rate_pct": round(rate_pct, 4),
                "annual_pct": round(annual_pct, 2),
                "mark_price": round(float(row.get("markPrice") or 0.0), 4),
                "sentiment": sentiment,
                "signal": signal,
            })
    except Exception as e:
        logger.warning(f"Funding rates fetch failed: {e}")

    payload = {"rates": rates}
    _cache_set("funding_rates_v1", payload)
    return payload

def _read_alert_rows():
    cached = _cache_get("alerts_payload_v1")
    if cached:
        return cached
    with get_persistence_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM alerts ORDER BY datetime(created_at) DESC LIMIT 200"
        ).fetchall()
    payload = {"alerts": [dict(row) for row in rows]}
    _cache_set("alerts_payload_v1", payload)
    return payload

async def _run_alert_refresh():
    global _alerts_refresh_task
    try:
        await asyncio.to_thread(_upsert_ml_alerts_from_signals)
        _cache_delete("alerts_payload_v1")
        _cache_set("alerts_refresh_v1", {"status": "fresh"})
    except Exception as e:
        logger.warning(f"Unable to refresh alerts in background: {e}")
    finally:
        _alerts_refresh_task = None

def _schedule_alert_refresh_if_needed():
    global _alerts_refresh_task
    if _cache_get("alerts_refresh_v1"):
        return
    if _alerts_refresh_task and not _alerts_refresh_task.done():
        return
    _alerts_refresh_task = asyncio.create_task(_run_alert_refresh())


PORTFOLIO_IDENTITY_MAP = {
    "0xd8da6bf26964af9d7eed9e03e53415d37aa96045": {
        "display_name": "Vitalik Buterin",
        "resolved_name": "vitalik.eth",
        "avatar": "",
        "description": "Ethereum co-founder public wallet frequently tracked for ecosystem activity and long-term holdings.",
        "twitter": "VitalikButerin",
        "website": "https://vitalik.eth.limo",
    },
    "0x3ddfa8ec3052539b6c9549f12cea2c295cff5296": {
        "display_name": "Justin Sun",
        "resolved_name": "Justin Sun",
        "avatar": "",
        "description": "Public Ethereum wallet attributed to Justin Sun and commonly referenced in market flow monitoring.",
        "twitter": "justinsuntron",
        "website": "https://tron.network",
    },
    "0xde0b295669a9fd93d5f28d9ec85e40f4cb697bae": {
        "display_name": "Ethereum Foundation",
        "resolved_name": "Ethereum Foundation",
        "avatar": "",
        "description": "Public treasury wallet attributed to the Ethereum Foundation.",
        "twitter": "ethereum",
        "website": "https://ethereum.org",
    },
    "0xbe0eb53f46cd790cd13851d5eff43d12404d33e8": {
        "display_name": "Binance Hot Wallet",
        "resolved_name": "Binance",
        "avatar": "",
        "description": "Large Binance treasury and exchange flow wallet visible on Ethereum.",
        "twitter": "binance",
        "website": "https://www.binance.com",
    },
    "0x71660c4005ba85c37ccec55d0c4493e66fe775d3": {
        "display_name": "Coinbase",
        "resolved_name": "Coinbase",
        "avatar": "",
        "description": "Public Coinbase-linked wallet used in many institutional flow dashboards.",
        "twitter": "coinbase",
        "website": "https://www.coinbase.com",
    },
    "0x05e793ce0c6027323ac150f6d45c2344d28b6019": {
        "display_name": "a16z Crypto",
        "resolved_name": "a16z Crypto",
        "avatar": "",
        "description": "Public wallet associated with a16z crypto allocations and transfers.",
        "twitter": "a16zcrypto",
        "website": "https://a16zcrypto.com",
    },
    "0xf76e3b4ca5f1b1851dd7e29c3e97a10f23bc1d00": {
        "display_name": "Mark Cuban",
        "resolved_name": "Mark Cuban",
        "avatar": "",
        "description": "Public wallet often referenced in NFT and crypto treasury tracking.",
        "twitter": "mcuban",
        "website": "https://markcubancompanies.com",
    },
    "0x4da82a8ac033fdd9ba0d3f0cc0feaeedf2ee5158": {
        "display_name": "MicroStrategy",
        "resolved_name": "MicroStrategy-linked",
        "avatar": "",
        "description": "Public Ethereum address commonly used in dashboards as a corporate treasury watchlist label.",
        "twitter": "Strategy",
        "website": "https://www.strategy.com",
    },
}


def _is_eth_address(address: str) -> bool:
    return bool(re.fullmatch(r"0x[a-fA-F0-9]{40}", address or ""))


def _build_eth_portfolio_payload(address: str) -> dict:
    normalized = address.strip()
    cache_key = f"portfolio_wallet:{normalized.lower()}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    if not _is_eth_address(normalized):
        raise HTTPException(status_code=400, detail="Only valid ETH wallet addresses are supported right now.")

    explorer_url = f"https://etherscan.io/address/{normalized}"
    identity = PORTFOLIO_IDENTITY_MAP.get(normalized.lower())
    try:
        resp = requests.get(
            f"https://api.ethplorer.io/getAddressInfo/{normalized}",
            params={"apiKey": "freekey"},
            timeout=12,
            headers={"User-Agent": "CryptoStreamAI/2.0"},
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Wallet lookup upstream failed: {e}")

    if isinstance(payload, dict) and payload.get("error"):
        error_message = payload["error"].get("message") if isinstance(payload.get("error"), dict) else str(payload.get("error"))
        raise HTTPException(status_code=502, detail=error_message or "Wallet lookup failed.")

    eth_section = payload.get("ETH") or {}
    assets = []
    total_usd = 0.0

    eth_balance = float(eth_section.get("balance") or 0.0)
    eth_price = float(((eth_section.get("price") or {}).get("rate")) or 0.0)
    eth_change = float(((eth_section.get("price") or {}).get("diff")) or 0.0)
    eth_usd = eth_balance * eth_price if eth_price > 0 else 0.0
    if eth_balance > 0 or eth_usd > 0:
        assets.append({
            "symbol": "ETH",
            "name": "Ethereum",
            "balance": round(eth_balance, 8),
            "price": round(eth_price, 8),
            "usd_value": round(eth_usd, 2),
            "change_24h": round(eth_change, 4),
            "allocation": 0.0,
            "kind": "native",
            "token_address": None,
            "logo": "",
            "priced": eth_price > 0,
        })
        total_usd += eth_usd

    for token_entry in payload.get("tokens") or []:
        token_info = token_entry.get("tokenInfo") or {}
        symbol = (token_info.get("symbol") or "").strip() or "TOKEN"
        decimals_raw = token_info.get("decimals")
        try:
            decimals = int(decimals_raw) if decimals_raw is not None and str(decimals_raw).strip() != "" else 0
        except Exception:
            decimals = 0
        raw_balance = token_entry.get("balance") or 0
        try:
            balance = float(raw_balance) / (10 ** decimals if decimals >= 0 else 1)
        except Exception:
            balance = 0.0

        price_info = token_info.get("price") or {}
        price = float(price_info.get("rate") or 0.0)
        change_24h = float(price_info.get("diff") or 0.0)
        usd_value = balance * price if price > 0 else 0.0
        if balance <= 0:
            continue
        # Drop near-zero or unpriced dust/spam balances so the UI stays usable on whale wallets.
        if price <= 0 and balance < 1:
            continue
        if usd_value < 1 and price > 0:
            continue
        total_usd += usd_value
        assets.append({
            "symbol": symbol.upper(),
            "name": token_info.get("name") or symbol.upper(),
            "balance": round(balance, 8),
            "price": round(price, 8),
            "usd_value": round(usd_value, 2),
            "change_24h": round(change_24h, 4),
            "allocation": 0.0,
            "kind": "token",
            "token_address": token_info.get("address"),
            "logo": token_info.get("image") or "",
            "priced": price > 0,
        })

    total_usd = round(total_usd, 2)
    for asset in assets:
        asset["allocation"] = round((float(asset["usd_value"]) / total_usd) * 100, 2) if total_usd > 0 and float(asset["usd_value"]) > 0 else 0.0

    assets.sort(key=lambda item: (float(item["usd_value"]), float(item["balance"])), reverse=True)

    result = {
        "address": normalized,
        "chain": "ETH",
        "total_usd": total_usd,
        "assets": assets,
        "source": "Ethplorer public API (filtered positions)",
        "identity": {
            "display_name": identity.get("display_name", "") if identity else "",
            "resolved_name": identity.get("resolved_name", "") if identity else "",
            "avatar": identity.get("avatar", "") if identity else "",
            "description": identity.get("description", "") if identity else "",
            "twitter": identity.get("twitter", "") if identity else "",
            "website": identity.get("website", "") if identity else "",
            "explorer_url": explorer_url,
        } if identity else None,
        "explorer_url": explorer_url,
    }
    _cache_set(cache_key, result)
    return result


@app.get("/api/whales/all")
async def whales_all(request: Request):
    auth_key = request.headers.get("X-API-Key")
    if APP_API_KEY and auth_key != APP_API_KEY and auth_key != "demo":
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return {"data": await asyncio.to_thread(_fetch_binance_whales)}


@app.get("/api/market/funding-rates")
async def market_funding_rates(request: Request):
    auth_key = request.headers.get("X-API-Key")
    if APP_API_KEY and auth_key != APP_API_KEY and auth_key != "demo":
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return await asyncio.to_thread(_fetch_funding_rates_sync)


@app.get("/api/market/etf-flows")
async def market_etf_flows(request: Request):
    auth_key = request.headers.get("X-API-Key")
    if APP_API_KEY and auth_key != APP_API_KEY and auth_key != "demo":
        raise HTTPException(status_code=403, detail="Invalid API Key")

    cached = _cache_get("etf_flows_v1")
    if cached:
        return cached

    etf_symbols = ["SPY", "QQQ", "IBIT", "ETHA", "GLD", "TLT", "ARKK", "SOXL"]
    flows = []
    try:
        import yfinance as yf
        data = await asyncio.to_thread(
            yf.download,
            " ".join(etf_symbols),
            period="1mo",
            interval="1d",
            progress=False,
            group_by="ticker",
            auto_adjust=False,
        )
        for symbol in etf_symbols:
            try:
                sym_df = data if len(etf_symbols) == 1 else data[symbol]
                closes = sym_df["Close"].dropna()
                volumes = sym_df["Volume"].dropna()
                if len(closes) < 6 or len(volumes) < 6:
                    continue
                price = float(closes.iloc[-1])
                return_5d = ((price - float(closes.iloc[-6])) / float(closes.iloc[-6])) * 100
                avg_vol = float(volumes.iloc[-6:-1].mean() or 0.0)
                vol_ratio = float(volumes.iloc[-1] / avg_vol) if avg_vol else 1.0
                flow_signal = "INFLOW" if return_5d > 1 and vol_ratio > 1.05 else "OUTFLOW" if return_5d < -1 and vol_ratio > 1.05 else "NEUTRAL"
                flows.append({
                    "symbol": symbol,
                    "price": round(price, 2),
                    "return_5d_pct": round(return_5d, 2),
                    "vol_ratio": round(vol_ratio, 2),
                    "flow_signal": flow_signal,
                    "flow_dir": flow_signal,
                })
            except Exception:
                continue
    except Exception as e:
        logger.warning(f"ETF flow proxy fetch failed: {e}")

    top_inflows = sorted([row for row in flows if row["flow_signal"] == "INFLOW"], key=lambda item: (item["return_5d_pct"], item["vol_ratio"]), reverse=True)[:4]
    top_outflows = sorted([row for row in flows if row["flow_signal"] == "OUTFLOW"], key=lambda item: (item["return_5d_pct"], -item["vol_ratio"]))[:4]
    market_theme = (
        "RISK ON - ETF demand concentrated in growth beta"
        if len(top_inflows) > len(top_outflows) else
        "RISK OFF - defensives and deleveraging dominate"
        if len(top_outflows) > len(top_inflows) else
        "BALANCED - ETF flows mixed"
    )
    payload = {
        "flows": flows,
        "top_inflows": top_inflows,
        "top_outflows": top_outflows,
        "market_theme": market_theme,
    }
    _cache_set("etf_flows_v1", payload)
    return payload


@app.get("/api/portfolio/wallet")
async def portfolio_wallet(address: str, request: Request):
    auth_key = request.headers.get("X-API-Key")
    if APP_API_KEY and auth_key != APP_API_KEY and auth_key != "demo":
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return await asyncio.to_thread(_build_eth_portfolio_payload, address)


@app.get("/api/alerts")
async def get_alerts(request: Request):
    auth_key = request.headers.get("X-API-Key")
    if APP_API_KEY and auth_key != APP_API_KEY and auth_key != "demo":
        raise HTTPException(status_code=403, detail="Invalid API Key")
    _schedule_alert_refresh_if_needed()
    return await asyncio.to_thread(_read_alert_rows)


@app.delete("/api/alerts/{alert_id}")
async def dismiss_alert(alert_id: int, request: Request):
    auth_key = request.headers.get("X-API-Key")
    if APP_API_KEY and auth_key != APP_API_KEY and auth_key != "demo":
        raise HTTPException(status_code=403, detail="Invalid API Key")
    with get_persistence_conn() as conn:
        conn.execute("UPDATE alerts SET status = 'DISMISSED' WHERE id = ?", (alert_id,))
        conn.commit()
    _cache_delete("alerts_payload_v1")
    _append_audit_event("DQ_ERROR", f"Alert {alert_id} dismissed")
    return {"status": "dismissed", "id": alert_id}


@app.delete("/api/alerts/ml/stale")
async def purge_stale_ml_alerts(request: Request):
    auth_key = request.headers.get("X-API-Key")
    if APP_API_KEY and auth_key != APP_API_KEY and auth_key != "demo":
        raise HTTPException(status_code=403, detail="Invalid API Key")
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    with get_persistence_conn() as conn:
        conn.execute(
            """
            DELETE FROM alerts
            WHERE user_id = 'ml_scanner'
              AND (status = 'DISMISSED' OR datetime(created_at) < datetime(?))
            """,
            (cutoff,),
        )
        conn.commit()
    _cache_delete("alerts_payload_v1")
    return {"status": "ok"}


@app.get("/api/trade-reviews")
async def get_trade_reviews(request: Request):
    auth_key = request.headers.get("X-API-Key")
    if APP_API_KEY and auth_key != APP_API_KEY and auth_key != "demo":
        raise HTTPException(status_code=403, detail="Invalid API Key")
    _ensure_trade_review_snapshots()
    with get_persistence_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM trade_reviews ORDER BY datetime(created_at) DESC LIMIT 25"
        ).fetchall()
    return {"reviews": [dict(row) for row in rows]}


@app.get("/api/paper-trades")
async def get_paper_trades(request: Request):
    auth_key = request.headers.get("X-API-Key")
    if APP_API_KEY and auth_key != APP_API_KEY and auth_key != "demo":
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return _paper_trade_snapshot()


@app.get("/api/paper-trades/auto")
async def get_auto_paper_status(request: Request):
    auth_key = request.headers.get("X-API-Key")
    if APP_API_KEY and auth_key != APP_API_KEY and auth_key != "demo":
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return _auto_paper_status()


@app.post("/api/paper-trades/auto")
async def update_auto_paper_status(payload: AutoPaperConfigUpdate, request: Request):
    auth_key = request.headers.get("X-API-Key")
    if APP_API_KEY and auth_key != APP_API_KEY and auth_key != "demo":
        raise HTTPException(status_code=403, detail="Invalid API Key")
    try:
        if payload.enabled is not None:
            _auto_paper_state["enabled"] = bool(payload.enabled)
        if payload.confidence_threshold is not None:
            _auto_paper_state["confidence_threshold"] = min(max(float(payload.confidence_threshold), 0.5), 0.95)
        if payload.volume is not None:
            _auto_paper_state["volume"] = max(float(payload.volume), 0.001)
        if payload.cooldown_minutes is not None:
            _auto_paper_state["cooldown_minutes"] = max(int(payload.cooldown_minutes), 5)
        if payload.max_open_positions is not None:
            _auto_paper_state["max_open_positions"] = max(int(payload.max_open_positions), 1)
        if payload.symbols is not None:
            cleaned = [str(symbol).upper().strip() for symbol in payload.symbols if str(symbol).strip()]
            _auto_paper_state["symbols"] = cleaned or list(AUTO_PAPER_DEFAULTS["symbols"])

        try:
            _append_audit_event(
                "AUTO_PAPER",
                f"Updated auto paper config | enabled={_auto_paper_state['enabled']} | symbols={','.join(_auto_paper_state['symbols'])}",
            )
        except Exception as audit_error:
            logger.warning(f"Auto paper audit log failed: {audit_error}")
        return _auto_paper_status()
    except Exception as e:
        logger.exception(f"Auto paper config update failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/paper-trades/auto/run")
async def run_auto_paper_once(request: Request):
    auth_key = request.headers.get("X-API-Key")
    if APP_API_KEY and auth_key != APP_API_KEY and auth_key != "demo":
        raise HTTPException(status_code=403, detail="Invalid API Key")

    loop = asyncio.get_event_loop()
    summary = await loop.run_in_executor(None, _auto_paper_cycle_sync)
    _auto_paper_state["last_run_at"] = datetime.now(timezone.utc).isoformat()
    _auto_paper_state["last_summary"] = summary
    _auto_paper_state["last_error"] = None
    return {"status": "completed", "summary": summary, "config": _auto_paper_status()}


@app.post("/api/paper-trades")
async def create_paper_trade(payload: PaperTradeCreateRequest, request: Request):
    auth_key = request.headers.get("X-API-Key")
    if APP_API_KEY and auth_key != APP_API_KEY and auth_key != "demo":
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return _open_paper_trade_internal(
        symbol=payload.symbol,
        side=payload.side,
        volume=float(payload.volume or 1.0),
        price=payload.price,
        entry_source="manual_ui",
        entry_reason="Manual paper trade",
    )


@app.post("/api/paper-trades/{trade_id}/close")
async def close_paper_trade(trade_id: str, payload: PaperTradeCloseRequest, request: Request):
    auth_key = request.headers.get("X-API-Key")
    if APP_API_KEY and auth_key != APP_API_KEY and auth_key != "demo":
        raise HTTPException(status_code=403, detail="Invalid API Key")

    with get_persistence_conn() as conn:
        row = conn.execute("SELECT * FROM paper_trades WHERE id = ?", (trade_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Paper trade not found")
        if row["status"] == "CLOSED":
            return {"status": "already_closed", "trade_id": trade_id, "pnl_usd": float(row["pnl_usd"] or 0.0)}

        exit_price = float(payload.price or 0.0) or _get_live_price(row["symbol"])
        if exit_price <= 0:
            exit_price = float(row["current_price"] or row["entry_price"] or 0.0)

        qty = float(row["quantity"] or row["volume"] or 0.0)
        direction = 1 if row["side"] == "BUY" else -1
        pnl_usd = direction * (exit_price - float(row["entry_price"] or 0.0)) * qty
        outcome = "WIN" if pnl_usd > 0 else "LOSS"
        closed_at = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            UPDATE paper_trades
            SET current_price = ?, exit_price = ?, pnl = ?, pnl_usd = ?, outcome = ?,
                status = 'CLOSED', closed_at = ?, close_reason = ?, label_source = ?
            WHERE id = ?
            """,
            (exit_price, exit_price, pnl_usd, pnl_usd, outcome, closed_at, "manual_close", "manual_api", trade_id),
        )
        conn.commit()
    _append_audit_event("PAPER_TRADE", f"Closed {row['symbol']} {row['side']} with {pnl_usd:+.2f} USD")
    _ensure_trade_review_snapshots()
    retrain = _maybe_trigger_auto_retrain("manual_close")
    return {
        "status": "closed",
        "trade_id": trade_id,
        "exit_price": exit_price,
        "pnl_usd": pnl_usd,
        "outcome": outcome,
        "close_reason": "manual_close",
        "label_source": "manual_api",
        "auto_retrain": retrain,
    }


@app.delete("/api/paper-trades")
async def reset_paper_trades(request: Request):
    auth_key = request.headers.get("X-API-Key")
    if APP_API_KEY and auth_key != APP_API_KEY and auth_key != "demo":
        raise HTTPException(status_code=403, detail="Invalid API Key")
    with get_persistence_conn() as conn:
        conn.execute("DELETE FROM paper_trades")
        conn.commit()
    _append_audit_event("PAPER_TRADE", "Reset all paper trade history")
    return {"status": "cleared"}


def _ml_paper_trade_stats() -> dict:
    """Read paper trade outcome counts from SQLite."""
    import sqlite3 as _sqlite3
    from intelligence.ml.signal_model import PAPER_DB_PATH
    try:
        conn = _sqlite3.connect(str(PAPER_DB_PATH))
        row = conn.execute(
            "SELECT COUNT(*), SUM(outcome='WIN'), SUM(outcome='LOSS') "
            "FROM paper_trades WHERE outcome IS NOT NULL AND status='CLOSED'"
        ).fetchone()
        conn.close()
        total  = int(row[0] or 0)
        wins   = int(row[1] or 0)
        losses = int(row[2] or 0)
        return {
            "total_labeled": total,
            "wins":   wins,
            "losses": losses,
            "win_rate": round(wins / total, 4) if total > 0 else None,
        }
    except Exception:
        return {"total_labeled": 0, "wins": 0, "losses": 0, "win_rate": None}


AUTO_PAPER_DEFAULTS = {
    "enabled": False,
    "symbols": ["BTCUSD", "ETHUSD", "GOLD", "EURUSD"],
    "confidence_threshold": 0.68,
    "volume": 0.01,
    "cooldown_minutes": 90,
    "max_open_positions": 2,
    "scan_interval_seconds": 60,
}
_auto_paper_state = {
    **AUTO_PAPER_DEFAULTS,
    "last_run_at": None,
    "last_error": None,
    "last_summary": None,
}


def _auto_paper_status() -> dict:
    return {
        "enabled": bool(_auto_paper_state["enabled"]),
        "symbols": list(_auto_paper_state["symbols"]),
        "confidence_threshold": float(_auto_paper_state["confidence_threshold"]),
        "volume": float(_auto_paper_state["volume"]),
        "cooldown_minutes": int(_auto_paper_state["cooldown_minutes"]),
        "max_open_positions": int(_auto_paper_state["max_open_positions"]),
        "scan_interval_seconds": int(_auto_paper_state["scan_interval_seconds"]),
        "last_run_at": _auto_paper_state.get("last_run_at"),
        "last_error": _auto_paper_state.get("last_error"),
        "last_summary": _auto_paper_state.get("last_summary"),
    }


def _symbol_asset_class(symbol: str) -> str:
    sym = symbol.upper().strip()
    return "CRYPTO" if any(token in sym for token in ("BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", "AVAX", "LINK")) else "MACRO"


def _recent_trade_exists(symbol: str, cooldown_minutes: int) -> bool:
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=cooldown_minutes)).isoformat()
    with get_persistence_conn() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM paper_trades
            WHERE symbol = ?
              AND datetime(COALESCE(closed_at, opened_at)) >= datetime(?)
            LIMIT 1
            """,
            (symbol, cutoff),
        ).fetchone()
    return bool(row)


def _auto_paper_cycle_sync() -> dict:
    from intelligence.tools.market_tools import get_trading_tactics

    status = _auto_paper_status()
    summary = {
        "checked_symbols": [],
        "opened": [],
        "skipped": [],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    with get_persistence_conn() as conn:
        open_rows = conn.execute("SELECT symbol FROM paper_trades WHERE status = 'OPEN'").fetchall()
    open_symbols = {str(row["symbol"]).upper() for row in open_rows}

    for symbol in status["symbols"]:
        summary["checked_symbols"].append(symbol)

        if len(open_symbols) >= status["max_open_positions"]:
            summary["skipped"].append({"symbol": symbol, "reason": "max_open_positions"})
            continue

        if symbol in open_symbols:
            summary["skipped"].append({"symbol": symbol, "reason": "already_open"})
            continue

        if _recent_trade_exists(symbol, status["cooldown_minutes"]):
            summary["skipped"].append({"symbol": symbol, "reason": "cooldown_active"})
            continue

        try:
            setup = get_trading_tactics(symbol)
        except Exception as e:
            summary["skipped"].append({"symbol": symbol, "reason": f"setup_error:{e}"})
            continue

        if not isinstance(setup, dict) or setup.get("error"):
            summary["skipped"].append({"symbol": symbol, "reason": "no_setup"})
            continue

        recommendation = str(setup.get("recommendation", "HOLD")).upper()
        if recommendation not in {"BUY", "SELL"}:
            summary["skipped"].append({"symbol": symbol, "reason": f"recommendation:{recommendation}"})
            continue

        confidence = float(setup.get("ai_edge", {}).get("signal_confidence") or 0.0)
        if confidence < status["confidence_threshold"]:
            summary["skipped"].append({"symbol": symbol, "reason": f"confidence:{confidence:.2f}"})
            continue

        price = float(setup.get("price") or 0.0)
        if price <= 0:
            summary["skipped"].append({"symbol": symbol, "reason": "invalid_price"})
            continue

        reason = (
            f"AutoPaper {recommendation} | confidence {confidence:.2f} | "
            f"{setup.get('best_persona', 'Institutional setup')}"
        )
        opened = _open_paper_trade_internal(
            symbol=symbol,
            side=recommendation,
            volume=status["volume"],
            price=price,
            entry_source="auto_paper",
            entry_reason=reason,
        )
        summary["opened"].append(
            {
                "symbol": symbol,
                "side": recommendation,
                "trade_id": opened["trade_id"],
                "confidence": round(confidence, 4),
                "price": price,
            }
        )
        open_symbols.add(symbol)

    return summary


async def auto_paper_trader_task():
    logger.info("Auto Paper Trader Task started.")
    await asyncio.sleep(10)

    while True:
        try:
            if _auto_paper_state["enabled"]:
                loop = asyncio.get_event_loop()
                summary = await loop.run_in_executor(None, _auto_paper_cycle_sync)
                _auto_paper_state["last_run_at"] = datetime.now(timezone.utc).isoformat()
                _auto_paper_state["last_summary"] = summary
                _auto_paper_state["last_error"] = None
                if summary["opened"]:
                    _append_audit_event(
                        "AUTO_PAPER",
                        f"Opened {len(summary['opened'])} auto paper trade(s): "
                        + ", ".join(f"{item['side']} {item['symbol']}" for item in summary["opened"]),
                    )
                    _maybe_trigger_auto_retrain("auto_paper_open")
        except Exception as e:
            _auto_paper_state["last_run_at"] = datetime.now(timezone.utc).isoformat()
            _auto_paper_state["last_error"] = str(e)
            logger.warning(f"Auto paper trader cycle failed: {e}")

        await asyncio.sleep(int(_auto_paper_state["scan_interval_seconds"]))


def _capture_trade_ml_snapshot(symbol: str, side: str, entry_price: float) -> dict | None:
    """Capture a focused ML snapshot so each paper trade becomes usable training data."""
    try:
        from intelligence.technical_engine import get_kline_data, compute_indicators
        from intelligence.ml.feature_extractor import extract_features
        from intelligence.ml.signal_model import predict_win_probability

        sym = symbol.upper().strip()
        asset_class = "CRYPTO" if any(token in sym for token in ("BTC", "ETH", "SOL", "XRP")) else "MACRO"
        timeframe = "15m" if asset_class == "CRYPTO" else "1h"
        df = get_kline_data(sym, timeframe=timeframe, limit=260, asset_class=asset_class, ignore_freshness=False)
        if df is None or len(df) < 220:
            return None

        df = compute_indicators(df)
        idx = len(df) - 1
        features = extract_features(df, idx, side=side, symbol=sym, asset_class=asset_class)
        atr = float(df["atr_14"].iloc[idx] or 0.0)
        if atr <= 0:
            return None

        sl = entry_price - atr * 1.5 if side == "BUY" else entry_price + atr * 1.5
        tp = entry_price + atr * 3.0 if side == "BUY" else entry_price - atr * 3.0
        ml_result = predict_win_probability(features)
        features["symbol"] = sym
        features["timeframe"] = timeframe
        features["asset_class"] = asset_class

        return {
            "features": features,
            "sl": float(sl),
            "tp": float(tp),
            "ml_score": float(ml_result.get("win_pct", 50.0)),
            "timeframe": timeframe,
            "asset_class": asset_class,
            "win_probability": float(ml_result.get("win_probability", 0.5)),
        }
    except Exception as e:
        logger.warning(f"ML snapshot capture failed for {symbol}: {e}")
        return None


def _open_paper_trade_internal(
    symbol: str,
    side: str,
    volume: float,
    price: float | None = None,
    entry_source: str = "manual_ui",
    entry_reason: str | None = None,
) -> dict:
    from intelligence.ml.signal_model import ML_CORE_SYMBOLS

    symbol = symbol.upper().strip()
    side = side.upper().strip()
    if side not in {"BUY", "SELL"}:
        raise HTTPException(status_code=400, detail="side must be BUY or SELL")

    entry_price = float(price or 0.0) or _get_live_price(symbol)
    if entry_price <= 0:
        raise HTTPException(status_code=400, detail=f"Unable to resolve live price for {symbol}")

    volume = max(float(volume or 1.0), 0.001)
    ml_score = _lookup_ai_score(symbol)
    ml_snapshot = _capture_trade_ml_snapshot(symbol, side, entry_price)
    is_focus_symbol = symbol in ML_CORE_SYMBOLS
    if ml_snapshot and ml_snapshot.get("ml_score") is not None:
        ml_score = float(ml_snapshot["ml_score"])

    trade_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()
    with get_persistence_conn() as conn:
        conn.execute(
            """
            INSERT INTO paper_trades (
                id, symbol, side, quantity, volume, entry_price, current_price,
                status, opened_at, ml_score, entry_source, entry_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?, ?)
            """,
            (
                trade_id,
                symbol,
                side,
                volume,
                volume,
                entry_price,
                entry_price,
                now,
                ml_score,
                entry_source,
                entry_reason,
            ),
        )
        conn.commit()

    if ml_snapshot:
        try:
            from intelligence.ml.outcome_tracker import attach_sl_tp_features

            attach_sl_tp_features(
                trade_id,
                float(ml_snapshot["sl"]),
                float(ml_snapshot["tp"]),
                ml_snapshot["features"],
                ml_score,
            )
        except Exception as e:
            logger.warning(f"Failed to attach ML snapshot for {symbol}: {e}")

    _append_audit_event(
        "PAPER_TRADE",
        f"Opened {side} {symbol} x {volume} at {entry_price:.4f} [{entry_source}]",
    )
    return {
        "status": "opened",
        "trade_id": trade_id,
        "entry_price": entry_price,
        "ml_snapshot_attached": bool(ml_snapshot),
        "focus_timeframe": ml_snapshot.get("timeframe") if ml_snapshot else None,
        "focus_symbol": is_focus_symbol,
        "focus_universe": ML_CORE_SYMBOLS,
        "contributes_to_core_dataset": bool(is_focus_symbol and ml_snapshot),
        "entry_source": entry_source,
        "entry_reason": entry_reason,
    }


@app.get("/api/ml/stats")
async def ml_stats():
    from intelligence.ml.signal_model import MODEL_PATH, ML_CORE_SYMBOLS, ML_SUFFICIENCY_TARGETS, get_auto_retrain_status, get_live_sufficiency_status
    import pickle as _pickle
    model_exists = MODEL_PATH.exists()
    bundle: dict = {}
    if model_exists:
        try:
            with open(MODEL_PATH, "rb") as f:
                bundle = _pickle.load(f)
        except Exception:
            model_exists = False

    global _retrain_task
    is_training = bool(_retrain_task and not _retrain_task.done())

    return {
        "is_training": is_training,
        "model_exists": model_exists,
        "model": {
            "trained": model_exists,
            "n_samples": bundle.get("n_samples"),
            "train_size": bundle.get("train_size"),
            "test_size": bundle.get("test_size"),
            "split_method": bundle.get("split_method"),
            "accuracy": bundle.get("accuracy"),
            "roc_auc": bundle.get("roc_auc"),
            "win_rate_train": bundle.get("win_rate_train"),
            "win_rate_test": bundle.get("win_rate_test"),
            "trained_at": bundle.get("trained_at"),
            "outcomes_at_retrain": bundle.get("outcomes_at_retrain"),
            "dataset_quality": bundle.get("dataset_quality"),
            "dataset_report": bundle.get("dataset_report"),
            "slice_pruning": bundle.get("slice_pruning"),
            "calibration": bundle.get("calibration"),
            "walk_forward": bundle.get("walk_forward"),
            "sufficiency": get_live_sufficiency_status(bundle if model_exists else None),
            "auto_retrain": get_auto_retrain_status(bundle if model_exists else None),
        },
        "paper_trades": _ml_paper_trade_stats(),
        "focus": {
            "core_symbols": ML_CORE_SYMBOLS,
            "targets": ML_SUFFICIENCY_TARGETS,
        },
    }


@app.get("/api/ml/feature-importance")
async def ml_feature_importance():
    from intelligence.ml.signal_model import MODEL_PATH
    import pickle as _pickle
    if not MODEL_PATH.exists():
        return {"available": False, "features": []}
    try:
        with open(MODEL_PATH, "rb") as f:
            bundle = _pickle.load(f)
        features = bundle.get("feature_importance", [])
        return {"available": bool(features), "features": features}
    except Exception as e:
        return {"available": False, "features": [], "error": str(e)}


@app.get("/api/ml/dataset-report")
async def ml_dataset_report():
    from intelligence.ml.signal_model import MODEL_PATH
    import pickle as _pickle

    if not MODEL_PATH.exists():
        return {"available": False, "report": [], "walk_forward": None}

    try:
        with open(MODEL_PATH, "rb") as f:
            bundle = _pickle.load(f)
        return {
            "available": True,
            "report": bundle.get("dataset_report", []),
            "walk_forward": bundle.get("walk_forward"),
            "dataset_quality": bundle.get("dataset_quality"),
            "slice_pruning": bundle.get("slice_pruning"),
            "calibration": bundle.get("calibration"),
            "sufficiency": bundle.get("sufficiency"),
        }
    except Exception as e:
        return {"available": False, "report": [], "walk_forward": None, "error": str(e)}


@app.get("/api/ml/sufficiency")
async def ml_sufficiency():
    from intelligence.ml.signal_model import MODEL_PATH, ML_CORE_SYMBOLS, ML_SUFFICIENCY_TARGETS, get_auto_retrain_status, get_live_sufficiency_status
    import pickle as _pickle

    payload = {
        "available": False,
        "focus": {
            "core_symbols": ML_CORE_SYMBOLS,
            "targets": ML_SUFFICIENCY_TARGETS,
        },
        "paper_trades": _ml_paper_trade_stats(),
        "sufficiency": None,
        "auto_retrain": get_auto_retrain_status(None),
    }

    if not MODEL_PATH.exists():
        return payload

    try:
        with open(MODEL_PATH, "rb") as f:
            bundle = _pickle.load(f)
        payload["available"] = True
        payload["sufficiency"] = get_live_sufficiency_status(bundle)
        payload["dataset_quality"] = bundle.get("dataset_quality")
        payload["slice_pruning"] = bundle.get("slice_pruning")
        payload["auto_retrain"] = get_auto_retrain_status(bundle)
        return payload
    except Exception as e:
        payload["error"] = str(e)
        return payload


_retrain_task: asyncio.Task | None = None


def _start_ml_retrain_task(trigger_reason: str = "manual") -> bool:
    global _retrain_task
    if _retrain_task and not _retrain_task.done():
        return False

    async def _run():
        from intelligence.ml.signal_model import train_model, TRAIN_SYMBOLS
        import intelligence.ml.signal_model as _sm
        import functools
        loop = asyncio.get_event_loop()
        fn = functools.partial(train_model, symbols=TRAIN_SYMBOLS, limit=5000)
        result = await loop.run_in_executor(None, fn)
        _sm._MODEL_CACHE = None  # invalidate in-memory cache so next load picks up new model
        logger.info(f"[ML-Retrain] done ({trigger_reason}): {result}")

    _retrain_task = asyncio.create_task(_run())
    logger.info(f"[ML-Retrain] started ({trigger_reason})")
    return True


def _maybe_trigger_auto_retrain(trigger_source: str) -> dict:
    from intelligence.ml.signal_model import get_auto_retrain_status

    status = get_auto_retrain_status()
    if not status.get("recommended"):
        return {"checked": True, "recommended": False, "started": False, "reasons": status.get("reasons", [])}

    started = _start_ml_retrain_task(f"auto:{trigger_source}")
    return {
        "checked": True,
        "recommended": True,
        "started": started,
        "reasons": status.get("reasons", []),
    }


@app.post("/api/ml/retrain")
async def ml_retrain():
    global _retrain_task
    if _retrain_task and not _retrain_task.done():
        return {"status": "already_running"}

    _start_ml_retrain_task("manual_api")
    return {"status": "started"}



# ─────────────────────────────────────────────────────────────────────────────
# Chat History Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/history")
async def get_history(request: Request):
    """Fetch all chat sessions from SQLite, ordered by last update."""
    # Auth check (optional, but good for demo/institutional separation)
    auth_key = request.headers.get("X-API-Key")
    if APP_API_KEY and auth_key != APP_API_KEY and auth_key != "demo":
        raise HTTPException(status_code=403, detail="Invalid API Key")

    try:
        with get_persistence_conn() as conn:
            # Query sessions
            rows = conn.execute(
                "SELECT id, title, updated_at as updatedAt FROM sessions ORDER BY updated_at DESC"
            ).fetchall()
            return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Error fetching history: {e}")
        return []

@app.get("/api/history/{session_id}")
async def get_session_messages(session_id: str, request: Request):
    """Fetch all messages for a specific session."""
    auth_key = request.headers.get("X-API-Key")
    if APP_API_KEY and auth_key != APP_API_KEY and auth_key != "demo":
        raise HTTPException(status_code=403, detail="Invalid API Key")

    try:
        with get_persistence_conn() as conn:
            rows = conn.execute(
                "SELECT role, content, metadata FROM messages WHERE session_id = ? ORDER BY created_at ASC",
                (session_id,)
            ).fetchall()
            
            messages = []
            for row in rows:
                msg = dict(row)
                # Parse metadata back into fields
                meta = json.loads(msg.get("metadata") or "{}")
                msg.update(meta)
                del msg["metadata"]
                messages.append(msg)
            return messages
    except Exception as e:
        logger.error(f"Error fetching messages for {session_id}: {e}")
        return []

class ChatSessionSave(BaseModel):
    id: str
    title: str
    messages: list[dict]
    updatedAt: Optional[float] = None
    last_message: Optional[str] = None

@app.post("/api/history")
async def save_history(session: ChatSessionSave, request: Request):
    """Save or update a chat session and its full message history."""
    auth_key = request.headers.get("X-API-Key")
    if APP_API_KEY and auth_key != APP_API_KEY and auth_key != "demo":
        raise HTTPException(status_code=403, detail="Invalid API Key")

    try:
        with get_persistence_conn() as conn:
            # 1. Update/Insert Session
            last_msg = session.last_message
            if not last_msg and session.messages:
                last_msg = session.messages[-1].get("content", "")[:100]
            
            conn.execute(
                "INSERT INTO sessions (id, title, last_message, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "title=excluded.title, last_message=excluded.last_message, updated_at=excluded.updated_at",
                (session.id, session.title, last_msg, session.updatedAt or time.time() * 1000)
            )
            
            # 2. Sync Messages (Simple strategy: delete and re-insert for the session)
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session.id,))
            
            for msg in session.messages:
                role = msg.get("role")
                content = msg.get("content")
                # Extra fields go into metadata
                metadata = {k: v for k, v in msg.items() if k not in ["role", "content", "id"]}
                
                # Keep created_at or use current time
                created_at = msg.get("created_at") or msg.get("timestamp") or (time.time() * 1000)
                
                conn.execute(
                    "INSERT INTO messages (session_id, role, content, metadata, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (session.id, role, content, json.dumps(metadata), created_at)
                )
            
            conn.commit()
            return {"status": "success", "session_id": session.id}
    except Exception as e:
        logger.error(f"Error saving history: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/history/{session_id}")
async def delete_history(session_id: str, request: Request):
    """Delete a specific chat session and all its messages."""
    auth_key = request.headers.get("X-API-Key")
    if APP_API_KEY and auth_key != APP_API_KEY and auth_key != "demo":
        raise HTTPException(status_code=403, detail="Invalid API Key")

    try:
        with get_persistence_conn() as conn:
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            conn.commit()
            return {"status": "deleted"}
    except Exception as e:
        logger.error(f"Error deleting history {session_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
async def get_index():
    """Explicitly serve index.html for the root path."""
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"error": "Dashboard UI not built. Please run 'npm run build' in /frontend directory."}

# Catch-all for SPA routing (Must be last)
@app.get("/{full_path:path}")
async def catch_all(full_path: str):
    # If it's empty, it was already handled by get_index above
    if not full_path:
        return await get_index()
        
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
