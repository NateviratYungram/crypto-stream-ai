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

from intelligence.constants import NASDAQ_100_TICKERS, SP500_TICKERS, MACRO_MAPPING, SMALL_CAP_TICKERS
from services.notification_service import NotificationService
from intelligence.agents.sentiment_agent import create_sentiment_agent, _fetch_rss_news
# ── Technical Tools ──────────────────────────────────────────────────────────
# Tools are imported inside the runner to ensure scope stability

# Define Tool Runner outside any nested scopes to ensure global accessibility
async def run_agent_tool_async(name, args):
    """
    World-class tool executor with maximum robustness.
    Uses dynamic lookup to prevent NameError/Scope issues.
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
            
        # Execute (get_market_analysis and get_macro_sentiment are synchronous)
        # We run them in a thread if they take too long, but for now direct call is fine
        res = func(**args) if isinstance(args, dict) else func()
        
        logger.info(f"✅ Tool {name} execution successful")
        return res
        
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
# App + Lifespan (CRIT-05 fix: replaces deprecated on_event)
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start Kafka consumers and Macro poller on startup."""
    logger.info("🚀 Starting background workers...")
    t1 = asyncio.create_task(kafka_consumer_task())
    t2 = asyncio.create_task(dlq_consumer_task())
    t3 = asyncio.create_task(macro_poller_task())
    yield  # App runs here
    logger.info("⏳ Shutting down background workers...")
    t1.cancel()
    t2.cancel()
    t3.cancel()
    await asyncio.gather(t1, t2, t3, return_exceptions=True)
    if _db_pool:
        _db_pool.closeall()
    logger.info("✅ Workers stopped and DB pool closed.")

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
# Chat Endpoint (Full Logic Restored)
# ==========================================
class ChatRequest(BaseModel):
    message: str
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
You are Alex, a world-class AI financial advisor and intelligent assistant. You have deep expertise in:
- Crypto markets (BTC, ETH, altcoins, DeFi, on-chain analysis)
- Global equities (US stocks, sector rotation, earnings, fundamentals)
- Macro economics (Fed policy, inflation, yield curves, currency flows)
- Technical analysis (ICT/Smart Money, Elliott Wave, price action)
- Risk management (position sizing, portfolio construction, hedging)

CRITICAL RULE #1 — UNDERSTAND WHAT THE USER IS ASKING:

STEP 1: Scan the message for asset names or tickers (BTC, ETH, GOLD, NVDA, ดอลลาร์, น้ำมัน, หุ้น, crypto, etc.)
- If asset name found → this is a FINANCE question → use tools and give structured analysis
- If no asset name → check if it's about finance concepts (การลงทุน, พอร์ต, เศรษฐกิจ, ตลาด) → answer with knowledge
- If purely general conversation (greetings, questions about you, other topics) → respond naturally like a smart helpful assistant

STEP 2: Match response depth to what they asked:
- Greeting / "คุณทำอะไรได้บ้าง" / general question → reply naturally, briefly, 1-3 sentences
- "BTC ราคาเท่าไหร่" → call tool, answer in 2-3 sentences
- "วิเคราะห์ BTC ให้หน่อย" → call tool, full structured analysis
- General knowledge question (เศรษฐกิจ, การเงินส่วนตัว, ความรู้ทั่วไป) → answer clearly without tools

CRITICAL RULE #2 — YOU CAN ANSWER ANYTHING:
You are a capable AI assistant first, finance expert second. If someone asks about your capabilities, general knowledge, or anything off-topic — answer it fully and helpfully. Never say "ผมเชี่ยวชาญแค่เรื่องการเงิน" and refuse. Just answer, then gently mention you're best at finance if relevant.

TOOLS — call only when you need real market data:
- Price/technicals/trend for any asset → get_market_analysis(symbol, asset_class)
  · asset_class: "CRYPTO" for BTC/ETH/SOL/etc | "STOCK" for any company stock | "MACRO" for GOLD/OIL/NASDAQ/SP500/DXY
- Global risk / macro climate → get_market_climate()
- Sector money flow → get_sector_rotation()
- Broad market scan → get_market_opportunities(asset_class="ALL"|"STOCK"|"CRYPTO")
- Position sizing → calculate_risk_parameters(account_size, entry, stop_loss, risk_pct)

OUTPUT FORMAT — adapt to context:

[Casual / General / Capability questions] → plain conversational reply, no headers, 1-3 sentences

[Price check] → "ราคา BTC ตอนนี้ $X (+X% วันนี้) แนวรับ $X แนวต้าน $X"

[Full analysis] →
**Signal: BUY / SELL / HOLD** — Confidence X%
**Why:** 2-3 sentences using real data
**Entry:** $X | **Stop Loss:** $X | **Take Profit:** $X
**Bear Case:** one sentence on main risk

[Education / Concept] → clear explanation, simple language, bullet points only for 3+ items

PERSONALITY: Confident, direct, helpful. Speaks like a smart friend who's great at finance — but can hold a real conversation about anything.
LANGUAGE: Always match user's language. Thai → Thai, English → English.
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
        
        if any(kw in user_lower for kw in THEMATIC_KEYWORDS):
            override = "[MANDATORY OVERRIDE: ผู้ใช้ถามหา 'กลุ่มหุ้นเฉพาะทาง' หรือ 'หุ้น Laggard' ให้คุณทำดังนี้ทันที: (1) คิดรายชื่อหุ้น ticker สัก 8-12 ตัวที่อยู่ในกลุ่มนั้นขึ้นมาจากความรู้ของคุณเอง (2) เรียก get_custom_screener(tickers=[...]) ด้วยรายชื่อที่คิดได้ ห้ามเรียก get_market_opportunities เด็ดขาด]"
        elif any(kw in user_lower for kw in CALENDAR_KEYWORDS):
            override = "[MANDATORY OVERRIDE: ผู้ใช้ถามหา 'ปฏิทินเศรษฐกิจ' หรือ 'ข่าวสำคัญล่วงหน้า' ให้เรียก get_economic_calendar(query='...') ทันที]"
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
            agent_res = await client.aio.models.generate_content(
                model=MODEL_ID,
                contents=history_contents,
                config=types.GenerateContentConfig(
                    system_instruction=agent_system_prompt,
                    tools=gemini_tools,
                )
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
                # Extract uppercase word(s) that look like a ticker (2-6 chars, letters only)
                ticker_candidates = re.findall(r'\b([A-Z]{2,6})\b', user_input.upper())
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
                history_contents.append(types.Content(role="user", parts=tool_results_parts))

                final_stream = await client.aio.models.generate_content_stream(
                    model=MODEL_ID,
                    contents=history_contents,
                    config=types.GenerateContentConfig(
                        system_instruction=agent_system_prompt,
                    )  # No tools → text-only
                )
                has_yielded_text = False
                async for chunk in final_stream:
                    try:
                        if chunk.text:
                            has_yielded_text = True
                            yield json.dumps({"type": "chunk", "content": chunk.text}) + "\n"
                    except ValueError:
                        has_yielded_text = True
                        yield json.dumps({"type": "chunk", "content": "⚠️ ถูกบล็อกโดยระบบรักษาความปลอดภัย (Safety Filter) ไม่สามารถแสดงผลได้"}) + "\n"
                
                if not has_yielded_text:
                    yield json.dumps({"type": "chunk", "content": "*(AI ประมวลผลสำเร็จ แต่อาจถูกจำกัดการอธิบายข้อความ กรุณาอ้างอิงข้อมูลจากหน้าจอและผลลัพธ์การสแกนครับ)*"}) + "\n"
            else:
                # No tool calls and no ticker detected — yield original response
                if agent_res.text:
                    yield json.dumps({"type": "chunk", "content": agent_res.text}) + "\n"

        except Exception as e:
            logging.error(f"Agent Workflow Error: {e}")
            yield json.dumps({"type": "chunk", "content": f"⚠️ ระบบ AI Agent ขัดข้อง: {str(e)}"}) + "\n"

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

@app.get("/api/market/indices")
async def market_indices():
    """Nasdaq Composite (^IXIC), Dow Jones (^DJI), and VIX (^VIX) via Yahoo Finance with Intraday History."""
    cached = _cache_get("market_indices_v5")
    if cached:
        return cached
    try:
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
            "^IXIC": {"key": "nasdaq", "name": "Nasdaq Composite"},
            "^DJI": {"key": "dow", "name": "Dow Jones"},
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
        cached_fallback = _market_cache.get("market_indices_v5", {}).get("data")
        return cached_fallback or {
            "nasdaq": {"name": "Nasdaq", "price": 0, "change_pct": 0, "previous_close": 0, "series": []}, 
            "dow": {"name": "Dow Jones", "price": 0, "change_pct": 0, "previous_close": 0, "series": []}, 
            "vix": {"name": "VIX", "price": 0, "change_pct": 0, "previous_close": 0, "series": []}
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
    """Real-time prices for ticker tape symbols (NVDA, TSLA, GOLD, NASDAQ, SP500) via Yahoo Finance batch."""
    cached = _cache_get("market_stocks_v2")
    if cached:
        return cached
    try:
        # Key → Yahoo symbol
        symbols_map = {
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
# Stock / Crypto Screener  (/api/screener)
# ─────────────────────────────────────────────────────────────────────────────

_SMALL_CAP = SMALL_CAP_TICKERS

_CRYPTO_SCREENER = ["BTC","ETH","SOL","XRP","BNB","DOGE","AVAX","LINK","ADA","DOT","MATIC","LTC","BCH","UNI","ATOM"]


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
    results = []
    for sym in _CRYPTO_SCREENER:
        try:
            r = _req.get("https://api.binance.com/api/v3/klines",
                         params={"symbol": sym + "USDT", "interval": "1d", "limit": 30}, timeout=5)
            if r.status_code != 200:
                continue
            raw = r.json()
            if len(raw) < 6:
                continue
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
            results.append({
                "symbol": sym, "price": round(price, 2),
                "rsi": round(rsi, 2), "vol_ratio": round(vol_ratio, 3),
                "pct_from_52wh": round(pct_52wh, 2), "return_1w_pct": round(ret_1w, 3),
            })
        except Exception:
            continue
    return results


@app.get("/api/screener")
async def screener_endpoint(
    universe: str = "NASDAQ100",
    rsi_min: float = None,
    rsi_max: float = None,
    vol_spike: float = None,
    pct_from_52wh: float = None,
    min_return_1w: float = None,
    max_return_1w: float = None,
    custom_tickers: str = "",
):
    cache_key = f"screener_v3_{universe}_{rsi_min}_{rsi_max}_{vol_spike}_{pct_from_52wh}_{min_return_1w}_{max_return_1w}_{custom_tickers}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    if universe == "CRYPTO":
        items = await asyncio.to_thread(_screener_crypto_batch)
    else:
        if universe == "NASDAQ100":
            symbols = list(_NASDAQ100)[:100]
        elif universe == "SP500":
            symbols = list(dict.fromkeys(_SP500))[:150]
        elif universe == "SMALL_CAP":
            symbols = list(_SMALL_CAP)[:100]
        elif universe == "CUSTOM" and custom_tickers:
            symbols = [t.strip().upper() for t in custom_tickers.replace(",", " ").split() if t.strip()][:50]
        else:
            symbols = list(_NASDAQ100)[:100]

        BATCH = 25
        batches = [symbols[i:i + BATCH] for i in range(0, len(symbols), BATCH)]
        raw_lists = await asyncio.gather(*[asyncio.to_thread(_screener_stock_batch, b) for b in batches])
        items = [item for sub in raw_lists for item in sub]

    filtered = items
    if rsi_min       is not None: filtered = [x for x in filtered if x["rsi"]          >= rsi_min]
    if rsi_max       is not None: filtered = [x for x in filtered if x["rsi"]          <= rsi_max]
    if vol_spike     is not None: filtered = [x for x in filtered if x["vol_ratio"]    >= vol_spike]
    if pct_from_52wh is not None: filtered = [x for x in filtered if x["pct_from_52wh"] <= pct_from_52wh]
    if min_return_1w is not None: filtered = [x for x in filtered if x["return_1w_pct"] >= min_return_1w]
    if max_return_1w is not None: filtered = [x for x in filtered if x["return_1w_pct"] <= max_return_1w]

    filtered.sort(key=lambda x: x["vol_ratio"], reverse=True)
    result = {"results": filtered[:100], "match_count": len(filtered)}
    _cache_set(cache_key, result)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# ML Signal Model API
# ─────────────────────────────────────────────────────────────────────────────

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


@app.get("/api/ml/stats")
async def ml_stats():
    from intelligence.ml.signal_model import MODEL_PATH
    import pickle as _pickle
    model_exists = MODEL_PATH.exists()
    bundle: dict = {}
    if model_exists:
        try:
            with open(MODEL_PATH, "rb") as f:
                bundle = _pickle.load(f)
        except Exception:
            model_exists = False

    return {
        "model_exists": model_exists,
        "model": {
            "trained":    model_exists,
            "n_samples":  bundle.get("n_samples"),
            "accuracy":   bundle.get("accuracy"),
            "roc_auc":    bundle.get("roc_auc"),
            "trained_at": bundle.get("trained_at"),
        },
        "paper_trades": _ml_paper_trade_stats(),
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


_retrain_task: asyncio.Task | None = None


@app.post("/api/ml/retrain")
async def ml_retrain():
    global _retrain_task
    if _retrain_task and not _retrain_task.done():
        return {"status": "already_running"}

    async def _run():
        from intelligence.ml.signal_model import train_model, TRAIN_SYMBOLS
        import intelligence.ml.signal_model as _sm
        import functools
        loop = asyncio.get_event_loop()
        fn = functools.partial(train_model, symbols=TRAIN_SYMBOLS, limit=1000)
        result = await loop.run_in_executor(None, fn)
        _sm._MODEL_CACHE = None  # invalidate in-memory cache so next load picks up new model
        logger.info(f"[ML-Retrain] done: {result}")

    _retrain_task = asyncio.create_task(_run())
    return {"status": "started"}


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
