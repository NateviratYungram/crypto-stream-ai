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
import copy
import re
import sys
import hashlib
import shutil
import tempfile
import unicodedata
from chat_server_query_helpers import (
    _extract_historical_years as _query_extract_historical_years,
    _extract_index_history_targets as _query_extract_index_history_targets,
    _extract_stock_history_direction as _query_extract_stock_history_direction,
    _extract_stock_history_universe as _query_extract_stock_history_universe,
    _is_broad_stock_history_query as _query_is_broad_stock_history_query,
    _is_capability_question as _query_is_capability_question,
    _is_explicit_stock_ranking_request as _query_is_explicit_stock_ranking_request,
    _is_ranked_stock_history_query as _query_is_ranked_stock_history_query,
    _is_stock_top_performer_history_question as _query_is_stock_top_performer_history_question,
    _normalize_query_text as _query_normalize_query_text,
)
from chat_server_symbol_helpers import (
    TRADE_SYMBOL_ALIASES as _helper_trade_symbol_aliases_map,
    _canonical_trade_symbol as _helper_canonical_trade_symbol,
    _telegram_extract_symbol as _helper_telegram_extract_symbol,
    _telegram_symbols_from_text as _helper_telegram_symbols_from_text,
    _trade_symbol_aliases as _helper_trade_symbol_aliases,
    resolve_trade_symbol as _helper_resolve_trade_symbol,
)
from chat_server_telegram_helpers import (
    _telegram_extract_profile_patch as _helper_telegram_extract_profile_patch,
    _telegram_format_readiness as _helper_telegram_format_readiness,
    _telegram_profile_text as _helper_telegram_profile_text,
)
from chat_server_signal_helpers import (
    _telegram_format_signal as _helper_telegram_format_signal,
)
from chat_server_best_setup_helpers import (
    _daily_risk_guard_summary as _helper_daily_risk_guard_summary,
    _build_best_setup_metrics as _helper_build_best_setup_metrics,
    _build_setup_feedback_summary as _helper_build_setup_feedback_summary,
    _build_trade_memory_document as _helper_build_trade_memory_document,
    _best_setup_cache_key as _helper_best_setup_cache_key,
    _best_setup_entry_decision as _helper_best_setup_entry_decision,
    _best_setup_int_env as _helper_best_setup_int_env,
    _best_setup_recommendations as _helper_best_setup_recommendations,
    _best_setup_risk_summary as _helper_best_setup_risk_summary,
    _best_setup_run_id as _helper_best_setup_run_id,
    _best_outcome_label as _helper_best_outcome_label,
    _best_setup_score_explain as _helper_best_setup_score_explain,
    _parse_percent_like as _helper_parse_percent_like,
    _pre_graph_rag_readiness_summary as _helper_pre_graph_rag_readiness_summary,
    _telegram_format_feedback as _helper_telegram_format_feedback,
    _trade_memory_sync_error as _helper_trade_memory_sync_error,
    _trade_memory_sync_skip as _helper_trade_memory_sync_skip,
    _trade_memory_sync_success as _helper_trade_memory_sync_success,
)
from chat_server_format_helpers import (
    _format_historical_stock_rankings as _helper_format_historical_stock_rankings,
    _format_index_historical_summary as _helper_format_index_historical_summary,
)
from chat_server_payload_helpers import (
    _calendar_has_content as _helper_calendar_has_content,
    _etf_flows_has_content as _helper_etf_flows_has_content,
    _has_non_empty_sequence as _helper_has_non_empty_sequence,
    _market_indices_has_content as _helper_market_indices_has_content,
    _market_sentiment_has_content as _helper_market_sentiment_has_content,
    _market_stocks_has_content as _helper_market_stocks_has_content,
    _metric_label as _helper_metric_label,
    _metric_number as _helper_metric_number,
    _payload_updated_at as _helper_payload_updated_at,
    _utc_now_iso as _helper_utc_now_iso,
    _with_data_quality as _helper_with_data_quality,
)
from chat_server_cache_helpers import (
    _cache_health_summary as _helper_cache_health_summary,
    _cache_ttl_for as _helper_cache_ttl_for,
    _is_persistent_market_cache_key as _helper_is_persistent_market_cache_key,
    _market_cache_snapshot_path as _helper_market_cache_snapshot_path,
    _read_market_cache_snapshot as _helper_read_market_cache_snapshot,
    _write_market_cache_snapshot as _helper_write_market_cache_snapshot,
)
from chat_server_wallet_helpers import (
    _build_eth_assets as _helper_build_eth_assets,
    _build_eth_portfolio_result as _helper_build_eth_portfolio_result,
    _is_eth_address as _helper_is_eth_address,
)
from chat_server_paper_helpers import (
    _num as _helper_num,
    _paper_summary as _helper_paper_summary,
    _serialize_paper_trade as _helper_serialize_paper_trade,
)
from chat_server_news_helpers import (
    _estimate_news_bias as _helper_estimate_news_bias,
    _extract_news_watch_symbol as _helper_extract_news_watch_symbol,
    _make_news_watch_hash as _helper_make_news_watch_hash,
    _news_watch_aliases as _helper_news_watch_aliases,
    _score_news_watch_article as _helper_score_news_watch_article,
)
from chat_server_graph_helpers import (
    _best_paper_entry_reason as _helper_best_paper_entry_reason,
    _build_best_alternative_candidates_payload as _helper_build_best_alternative_candidates_payload,
    _build_trade_graph_guard_result as _helper_build_trade_graph_guard_result,
    _build_signal_snapshot_metrics as _helper_build_signal_snapshot_metrics,
    _build_signal_snapshot_record as _helper_build_signal_snapshot_record,
    _format_best_alternative_report as _helper_format_best_alternative_report,
    _format_open_best_paper_blocked_exception as _helper_format_open_best_paper_blocked_exception,
    _format_open_best_paper_result as _helper_format_open_best_paper_result,
    _format_trade_graph_report as _helper_format_trade_graph_report,
    _format_why_setup_report as _helper_format_why_setup_report,
    _precheck_open_best_paper_payload as _helper_precheck_open_best_paper_payload,
    _resolve_best_paper_volume as _helper_resolve_best_paper_volume,
    _current_market_regime as _helper_current_market_regime,
    _setup_node_key as _helper_setup_node_key,
    _signal_outcome_label as _helper_signal_outcome_label,
    _signal_snapshot_id as _helper_signal_snapshot_id,
    _trade_graph_key as _helper_trade_graph_key,
)
from chat_server_telegram_format_helpers import (
    _telegram_blocked_trade_keyboard as _helper_telegram_blocked_trade_keyboard,
    _telegram_extract_blockers as _helper_telegram_extract_blockers,
    _telegram_format_blocked_detail as _helper_telegram_format_blocked_detail,
    _telegram_format_blocked_trade as _helper_telegram_format_blocked_trade,
    _telegram_format_mt5_snapshot as _helper_telegram_format_mt5_snapshot,
    _telegram_format_paper_dashboard as _helper_telegram_format_paper_dashboard,
    _telegram_trade_keyboard as _helper_telegram_trade_keyboard,
)
from chat_server_signal_list_helpers import (
    _build_price_delta_fallback_signals as _helper_build_price_delta_fallback_signals,
    _filter_signal_rows as _helper_filter_signal_rows,
)
from chat_server_alert_helpers import (
    _build_best_confirmation_alert_request as _helper_build_best_confirmation_alert_request,
    _build_best_entry_alert_request as _helper_build_best_entry_alert_request,
    _telegram_parse_alert_request as _helper_telegram_parse_alert_request,
)

# Fix Windows console encoding for emojis
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from contextlib import asynccontextmanager
from typing import Any, Dict, Optional, List

# ── Rotating log (never grows unbounded, never committed to git) ────────────
class SecretRedactionFilter(logging.Filter):
    _PATTERNS = [
        re.compile(r"bot\d+:[A-Za-z0-9_-]{20,}"),
        re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{20,}\b"),
    ]

    def __init__(self):
        super().__init__()
        try:
            from dotenv import load_dotenv as _load_dotenv
            _load_dotenv()
        except Exception:
            pass
        env_names = [
            "TELEGRAM_BOT_TOKEN",
            "GEMINI_API_KEY",
            "APP_API_KEY",
            "MCP_API_KEY",
            "JWT_SECRET_KEY",
        ]
        self._secrets = [
            value
            for value in (os.environ.get(name) for name in env_names)
            if value and len(value) >= 8 and value.lower() not in {"demo", "changeme"}
        ]

    def _redact(self, value):
        if not isinstance(value, (str, bytes)):
            return value
        if isinstance(value, bytes):
            try:
                value = value.decode("utf-8")
            except Exception:
                return value
        text = str(value)
        for pattern in self._PATTERNS:
            text = pattern.sub("[REDACTED_SECRET]", text)
        for secret in self._secrets:
            text = text.replace(secret, "[REDACTED_SECRET]")
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._redact(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {key: self._redact(value) for key, value in record.args.items()}
            else:
                record.args = tuple(self._redact(arg) for arg in record.args)
        return True


_secret_redaction_filter = SecretRedactionFilter()
log_handler = logging.handlers.RotatingFileHandler(
    "server.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8" # 5MB × 3 = 15MB max
)
log_handler.addFilter(_secret_redaction_filter)
stream_handler = logging.StreamHandler()
stream_handler.addFilter(_secret_redaction_filter)
logging.basicConfig(
    handlers=[log_handler, stream_handler],
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    force=True,
)
logger = logging.getLogger("cryptostream")
logger.info("=== CryptoStream AI Server Starting ===")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, PlainTextResponse
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
            timeout_overrides = {
                "get_market_analysis": 35.0,
                "get_trading_tactics": 35.0,
                "get_index_historical_summary": 35.0,
                "get_historical_stock_rankings": 120.0,
            }
            timeout_seconds = timeout_overrides.get(name, 18.0)
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
MCP_API_KEY    = os.environ.get("MCP_API_KEY", "CHANGE_ME_LOCAL_DEV_KEY")
APP_API_KEY    = os.environ.get("APP_API_KEY", "")
APP_ENV        = (os.environ.get("APP_ENV") or os.environ.get("ENVIRONMENT") or "development").strip().lower()
ALLOW_DEMO_API_KEY = (os.environ.get("ALLOW_DEMO_API_KEY", "1" if APP_ENV in {"development", "dev", "local", "test"} else "0").strip().lower() in {"1", "true", "yes", "on"})
KAFKA_BROKER   = os.environ.get("KAFKA_BROKER", "localhost:9092")
MCP_URL        = os.environ.get("MCP_URL", "http://localhost:8000")
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
    if APP_ENV in {"development", "dev", "local", "test"}:
        logger.warning("⚠️  APP_API_KEY not set — local development mode will rely on demo access only.")
    else:
        logger.error("❌ APP_API_KEY missing in non-development environment")
        raise RuntimeError("APP_API_KEY must be set outside development/test environments")

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


def _check_socket(name: str, target: str, timeout: float = 2.0) -> Dict[str, Any]:
    """Lightweight TCP readiness check for internal Docker services."""
    import socket

    host, _, port_text = target.partition(":")
    try:
        with socket.create_connection((host, int(port_text)), timeout=timeout):
            return {"status": "ok", "target": target}
    except Exception as exc:
        return {"status": "error", "target": target, "error": str(exc)}


def _readiness_db_connect():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        connect_timeout=2,
    )


def _check_datalake() -> Dict[str, Any]:
    root = os.environ.get("DATALAKE_READ_PATH", os.path.join(BASE_DIR, "datalake"))
    try:
        if not os.path.isdir(root):
            return {"status": "error", "path": root, "error": "data lake path does not exist"}
        now = datetime.now(timezone.utc)
        candidate_days = [now - timedelta(days=offset) for offset in range(3)]
        checked_partitions = []
        for day in candidate_days:
            partition = os.path.join(
                root,
                f"year={day:%Y}",
                f"month={day:%m}",
                f"day={day:%d}",
            )
            checked_partitions.append(os.path.relpath(partition, root))
            if not os.path.isdir(partition):
                continue
            with os.scandir(partition) as entries:
                for entry in entries:
                    if entry.is_file() and entry.name.endswith(".parquet"):
                        stat = entry.stat()
                        return {
                            "status": "ok",
                            "path": root,
                            "partition": os.path.relpath(partition, root),
                            "sample_file": entry.name,
                            "sample_modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                        }
        return {"status": "error", "path": root, "checked_partitions": checked_partitions}
    except Exception as exc:
        return {"status": "error", "path": root, "error": str(exc)}


def _check_rag_vector() -> Dict[str, Any]:
    conn = None
    try:
        conn = _readiness_db_connect()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS chunks,
                       COUNT(*) FILTER (WHERE embedding IS NOT NULL) AS embedded_chunks
                FROM knowledge_chunks
                """
            )
            chunks, embedded_chunks = cur.fetchone()
        status = "ok" if embedded_chunks else "error"
        return {"status": status, "chunks": int(chunks), "embedded_chunks": int(embedded_chunks)}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
    finally:
        if conn:
            conn.close()


def _check_anomaly_pipeline(hours: int = 72) -> Dict[str, Any]:
    conn = None
    try:
        conn = _readiness_db_connect()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS event_count
                FROM data_anomaly_events
                WHERE detected_at >= NOW() - (%s || ' hours')::interval
                """,
                (hours,),
            )
            event_count = int(cur.fetchone()["event_count"])
            cur.execute(
                """
                SELECT symbol, COUNT(*) AS count
                FROM data_anomaly_events
                WHERE detected_at >= NOW() - (%s || ' hours')::interval
                GROUP BY symbol
                ORDER BY count DESC, symbol
                LIMIT 5
                """,
                (hours,),
            )
            top_symbols = [dict(row) for row in cur.fetchall()]
        return {
            "status": "ok",
            "hours": hours,
            "event_count": event_count,
            "top_symbols": top_symbols,
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
    finally:
        if conn:
            conn.close()


def _check_lineage() -> Dict[str, Any]:
    url = os.environ.get("MARQUEZ_URL", "http://marquez:5000")
    try:
        response = requests.get(f"{url.rstrip('/')}/api/v1/namespaces", timeout=2)
        response.raise_for_status()
        payload = response.json()
        return {
            "status": "ok",
            "url": url,
            "namespace_count": len(payload.get("namespaces", [])),
        }
    except Exception as exc:
        return {"status": "error", "url": url, "error": str(exc)}


def _check_mt5_runtime() -> Dict[str, Any]:
    cached = GLOBAL_ACCOUNT_CACHE.get("summary", {})
    cached_at = GLOBAL_ACCOUNT_CACHE.get("updated_at", 0)
    cache_age = time.time() - cached_at if cached_at else None
    if cached and cache_age is not None and cache_age <= 60:
        return {
            "status": "ok",
            "connected": True,
            "live_execution_enabled": bool(cached.get("bridge_live_trading_enabled", not os.getenv("MT5_BRIDGE_URL"))),
            "source": "cache",
            "cache_age_seconds": round(cache_age, 1),
            "account": cached,
            "positions_count": len(GLOBAL_ACCOUNT_CACHE.get("positions", [])),
        }

    try:
        from intelligence.mt5_connector import get_mt5_account_info, get_mt5_positions

        account = get_mt5_account_info()
        if "error" in account:
            return {"status": "not_ready", "connected": False, "error": account["error"]}
        positions = get_mt5_positions()
        GLOBAL_ACCOUNT_CACHE["summary"] = account
        GLOBAL_ACCOUNT_CACHE["positions"] = positions
        GLOBAL_ACCOUNT_CACHE["updated_at"] = time.time()
        GLOBAL_ACCOUNT_CACHE["connected"] = True
        return {
            "status": "ok",
            "connected": True,
            "live_execution_enabled": bool(account.get("bridge_live_trading_enabled", not os.getenv("MT5_BRIDGE_URL"))),
            "source": "direct",
            "account": account,
            "positions_count": len(positions),
        }
    except Exception as exc:
        return {"status": "not_ready", "connected": False, "error": str(exc)}


def _check_ai_trading_quality() -> Dict[str, Any]:
    try:
        from intelligence.ml.trading_quality_gate import get_trading_quality_gate

        gate = get_trading_quality_gate(force_refresh=True)
        return {
            "status": "ok" if gate.get("live_ready") else "not_ready",
            "live_ready": bool(gate.get("live_ready")),
            "mode": gate.get("mode"),
            "blockers": gate.get("blockers", []),
            "paper_label_progress": gate.get("paper_label_progress", {}),
            "model_quality": gate.get("model_quality", {}),
            "paper_quality": gate.get("paper_quality", {}),
        }
    except Exception as exc:
        return {"status": "error", "live_ready": False, "error": str(exc)}


def build_system_readiness() -> Dict[str, Any]:
    checks: Dict[str, Any] = {}

    conn = None
    try:
        conn = _readiness_db_connect()
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        checks["postgres"] = {"status": "ok"}
    except Exception as exc:
        checks["postgres"] = {"status": "error", "error": str(exc)}
    finally:
        if conn:
            conn.close()

    try:
        schema = _get_schema()
        checks["mcp"] = {"status": "ok" if schema else "error", "url": MCP_URL}
    except Exception as exc:
        checks["mcp"] = {"status": "error", "url": MCP_URL, "error": str(exc)}

    checks["kafka"] = _check_socket("kafka", KAFKA_BROKER)
    checks["rag_vector"] = _check_rag_vector()
    checks["anomaly_pipeline"] = _check_anomaly_pipeline(hours=72)
    checks["data_lake"] = _check_datalake()
    checks["lineage"] = _check_lineage()

    telegram = notifier.telegram_status()
    checks["telegram"] = {
        "status": "ok" if telegram.get("configured") else "not_configured",
        **telegram,
    }
    checks["mt5"] = _check_mt5_runtime()
    checks["ai_trading_quality"] = _check_ai_trading_quality()

    core_names = [
        "postgres",
        "mcp",
        "kafka",
        "rag_vector",
        "anomaly_pipeline",
        "data_lake",
        "lineage",
    ]
    external_names = ["telegram", "mt5", "ai_trading_quality"]
    all_names = core_names + external_names
    ok_count = sum(1 for name in all_names if checks[name].get("status") == "ok")

    core_ready = all(checks[name].get("status") == "ok" for name in core_names)
    ready_for_notifications = checks["telegram"].get("status") == "ok"
    ready_for_live_trading = (
        checks["mt5"].get("connected") is True
        and checks["mt5"].get("live_execution_enabled", True) is True
        and checks["ai_trading_quality"].get("live_ready") is True
    )
    ready_for_mt5_execution = (
        checks["mt5"].get("connected") is True
        and checks["mt5"].get("live_execution_enabled", True) is True
    )

    next_actions = []
    if not ready_for_notifications:
        next_actions.append("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID, then restart chat-server.")
    if not ready_for_live_trading:
        if not ready_for_mt5_execution:
            next_actions.append("Install/log in to MetaTrader5 and start the MT5 bridge before enabling live trading.")
        else:
            next_actions.append("Keep live orders blocked until ML and paper-trade quality gates pass.")
    if not core_ready:
        next_actions.append("Fix any core check with status=error before exposing the app to users.")

    return {
        "status": "ok" if core_ready else "degraded",
        "overall_percent": round((ok_count / len(all_names)) * 100),
        "ready_for_users": core_ready,
        "ready_for_analysis": core_ready,
        "ready_for_notifications": ready_for_notifications,
        "ready_for_live_trading": ready_for_live_trading,
        "ready_for_mt5_execution": ready_for_mt5_execution,
        "ready_for_live_ai_trading": ready_for_live_trading,
        "core_ready": core_ready,
        "external_ready": ready_for_notifications and ready_for_mt5_execution,
        "checks": checks,
        "next_actions": next_actions,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def format_readiness_for_chat(readiness: Dict[str, Any]) -> str:
    checks = readiness.get("checks", {})
    core_ready = readiness.get("core_ready")
    notification_ready = readiness.get("ready_for_notifications")
    trading_ready = readiness.get("ready_for_live_trading")
    mt5_execution_ready = readiness.get("ready_for_mt5_execution")
    overall = readiness.get("overall_percent")
    anomaly_count = checks.get("anomaly_pipeline", {}).get("event_count", 0)
    rag_chunks = checks.get("rag_vector", {}).get("embedded_chunks", 0)
    lake_sample = checks.get("data_lake", {}).get("sample_file", "latest partition not found")

    core_text = "พร้อม" if core_ready else "ยังไม่พร้อมครบ"
    telegram_text = "พร้อม" if notification_ready else "ยังไม่พร้อม: ขาด TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID"
    mt5_check = checks.get("mt5", {})
    if trading_ready:
        mt5_text = "พร้อม"
    elif mt5_execution_ready:
        ai_gate = checks.get("ai_trading_quality", {})
        mt5_text = (
            "MT5 bridge พร้อม แต่ AI live-trading gate ยังบล็อกอยู่: "
            f"{', '.join(ai_gate.get('blockers', [])[:6]) or 'quality gate not ready'}"
        )
    elif mt5_check.get("connected") and not mt5_check.get("live_execution_enabled", True):
        mt5_text = "เชื่อมต่อบัญชีแล้ว แต่ยังปิด live execution: set MT5_BRIDGE_ENABLE_LIVE_TRADING=1"
    else:
        mt5_text = f"ยังไม่พร้อม: {mt5_check.get('error', 'MT5 ยังไม่ connected')}"

    return (
        f"ผลตรวจระบบล่าสุด: {overall}%\n"
        f"- Core AI/data platform: {core_text} (Postgres, MCP, Kafka, RAG vector, anomaly pipeline, data lake, lineage)\n"
        f"- RAG: พร้อมใช้งานแบบ vector แล้ว มี embedded chunks {rag_chunks} ชิ้น\n"
        f"- Anomaly pipeline: พร้อม มีข้อมูลตรวจล่าสุด {anomaly_count} events ใน 72 ชั่วโมง\n"
        f"- Data lake: พร้อม มีตัวอย่างไฟล์ล่าสุด {lake_sample}\n"
        f"- Telegram notification: {telegram_text}\n"
        f"- MT5 live trading: {mt5_text}\n\n"
        "สรุป: พร้อมตอบ user และวิเคราะห์จริงแล้ว แต่ live trading/Telegram จะนับเป็น 100% ได้ก็ต่อเมื่อใส่ secret/เชื่อมต่อโปรแกรมจริงครบก่อนครับ"
    )

# ==========================================
# Persistence DB (SQLite) for History
# ==========================================
DEFAULT_PERSISTENCE_DB = os.path.join(BASE_DIR, "data", "persistence.db")
LEGACY_PERSISTENCE_DB = os.path.join(BASE_DIR, "persistence.db")
PERSISTENCE_DB = os.environ.get("PAPER_TRADE_DB") or DEFAULT_PERSISTENCE_DB
PERSISTENCE_DB_FALLBACK = os.path.join(tempfile.gettempdir(), "crypto-stream-ai", "persistence.db")
_ACTIVE_PERSISTENCE_DB = PERSISTENCE_DB


def _ensure_persistence_db_path() -> None:
    db_dir = os.path.dirname(PERSISTENCE_DB)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    if (
        os.path.abspath(PERSISTENCE_DB) != os.path.abspath(LEGACY_PERSISTENCE_DB)
        and not os.path.exists(PERSISTENCE_DB)
        and os.path.exists(LEGACY_PERSISTENCE_DB)
    ):
        shutil.copy2(LEGACY_PERSISTENCE_DB, PERSISTENCE_DB)
        logger.info("Migrated legacy persistence DB to %s", PERSISTENCE_DB)


def _activate_persistence_fallback(reason: Exception | str) -> str:
    global _ACTIVE_PERSISTENCE_DB

    fallback_dir = os.path.dirname(PERSISTENCE_DB_FALLBACK)
    if fallback_dir:
        os.makedirs(fallback_dir, exist_ok=True)

    if (
        os.path.abspath(_ACTIVE_PERSISTENCE_DB) != os.path.abspath(PERSISTENCE_DB_FALLBACK)
        and not os.path.exists(PERSISTENCE_DB_FALLBACK)
        and os.path.exists(PERSISTENCE_DB)
    ):
        try:
            shutil.copy2(PERSISTENCE_DB, PERSISTENCE_DB_FALLBACK)
        except Exception as exc:
            logger.warning("Persistence fallback copy failed: %s", exc)

    _ACTIVE_PERSISTENCE_DB = PERSISTENCE_DB_FALLBACK
    logger.warning(
        "SQLite persistence switched to temp fallback at %s due to %s",
        PERSISTENCE_DB_FALLBACK,
        reason,
    )
    return _ACTIVE_PERSISTENCE_DB

def init_persistence_db():
    """Ensure SQLite tables exist and are synchronized with current schema."""
    import sqlite3
    try:
        _ensure_persistence_db_path()
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
                price REAL,
                timeframe TEXT,
                entry_source TEXT,
                message TEXT,
                meta_json TEXT,
                status TEXT DEFAULT 'ACTIVE',
                triggered_at DATETIME,
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

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS telegram_user_profiles (
                chat_id TEXT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                preferred_symbols_json TEXT,
                default_lot REAL,
                risk_pct REAL,
                language TEXT,
                answer_style TEXT,
                notes TEXT,
                created_at DATETIME,
                updated_at DATETIME
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS telegram_trade_confirmations (
                id TEXT PRIMARY KEY,
                chat_id TEXT,
                symbol TEXT,
                side TEXT,
                volume REAL,
                sl REAL,
                tp REAL,
                price REAL,
                request_json TEXT,
                status TEXT DEFAULT 'PENDING',
                result_json TEXT,
                created_at DATETIME,
                expires_at DATETIME,
                decided_at DATETIME
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS telegram_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT,
                username TEXT,
                action TEXT,
                message TEXT,
                payload_json TEXT,
                created_at DATETIME
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS telegram_setup_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT,
                symbol TEXT,
                side TEXT,
                rating TEXT,
                source TEXT,
                score REAL,
                payload_json TEXT,
                created_at DATETIME
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS best_setup_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT UNIQUE,
                symbol TEXT,
                side TEXT,
                score REAL,
                price REAL,
                entry_low REAL,
                entry_high REAL,
                stop_loss REAL,
                take_profit_1 REAL,
                take_profit_2 REAL,
                decision_action TEXT,
                no_trade INTEGER DEFAULT 0,
                model_weighted INTEGER DEFAULT 0,
                payload_json TEXT,
                created_at DATETIME,
                outcome_1h TEXT,
                return_1h REAL,
                outcome_4h TEXT,
                return_4h REAL,
                outcome_24h TEXT,
                return_24h REAL,
                evaluated_at DATETIME
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS signal_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id TEXT UNIQUE,
                symbol TEXT,
                canonical_symbol TEXT,
                side TEXT,
                timeframe TEXT,
                price REAL,
                confidence REAL,
                win_probability REAL,
                source TEXT,
                market_regime TEXT,
                graph_guard_json TEXT,
                payload_json TEXT,
                created_at DATETIME,
                outcome_1h TEXT,
                return_1h REAL,
                outcome_4h TEXT,
                return_4h REAL,
                outcome_24h TEXT,
                return_24h REAL,
                evaluated_at DATETIME
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ml_promotion_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trigger_reason TEXT,
                status TEXT,
                reason TEXT,
                accuracy REAL,
                roc_auc REAL,
                walk_forward_auc REAL,
                n_samples INTEGER,
                trained_at TEXT,
                override_reason TEXT,
                blockers_json TEXT,
                paper_label_quality_json TEXT,
                result_json TEXT,
                created_at TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ml_symbol_policy_overrides (
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                action TEXT NOT NULL,
                size_multiplier REAL,
                note TEXT,
                updated_at TEXT,
                PRIMARY KEY(symbol, side)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trade_graph_nodes (
                node_key TEXT PRIMARY KEY,
                node_type TEXT,
                label TEXT,
                properties_json TEXT,
                updated_at DATETIME
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trade_graph_edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_key TEXT,
                target_key TEXT,
                edge_type TEXT,
                weight REAL DEFAULT 1.0,
                evidence_json TEXT,
                updated_at DATETIME,
                UNIQUE(source_key, target_key, edge_type)
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
            "price": "ALTER TABLE alerts ADD COLUMN price REAL",
            "timeframe": "ALTER TABLE alerts ADD COLUMN timeframe TEXT",
            "entry_source": "ALTER TABLE alerts ADD COLUMN entry_source TEXT",
            "message": "ALTER TABLE alerts ADD COLUMN message TEXT",
            "meta_json": "ALTER TABLE alerts ADD COLUMN meta_json TEXT",
            "status": "ALTER TABLE alerts ADD COLUMN status TEXT DEFAULT 'ACTIVE'",
            "triggered_at": "ALTER TABLE alerts ADD COLUMN triggered_at DATETIME",
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
            "signal_grade": "ALTER TABLE paper_trades ADD COLUMN signal_grade TEXT",
            "macro_bias": "ALTER TABLE paper_trades ADD COLUMN macro_bias TEXT",
        }
        for col_name, sql in paper_trade_migrations.items():
            if col_name not in pt_cols:
                logger.info(f"Paper trade migration: adding {col_name}")
                cursor.execute(sql)

        cursor.execute("PRAGMA table_info(telegram_user_profiles)")
        tg_cols = [c[1] for c in cursor.fetchall()]
        telegram_profile_migrations = {
            "username": "ALTER TABLE telegram_user_profiles ADD COLUMN username TEXT",
            "first_name": "ALTER TABLE telegram_user_profiles ADD COLUMN first_name TEXT",
            "preferred_symbols_json": "ALTER TABLE telegram_user_profiles ADD COLUMN preferred_symbols_json TEXT",
            "default_lot": "ALTER TABLE telegram_user_profiles ADD COLUMN default_lot REAL",
            "risk_pct": "ALTER TABLE telegram_user_profiles ADD COLUMN risk_pct REAL",
            "language": "ALTER TABLE telegram_user_profiles ADD COLUMN language TEXT",
            "answer_style": "ALTER TABLE telegram_user_profiles ADD COLUMN answer_style TEXT",
            "notes": "ALTER TABLE telegram_user_profiles ADD COLUMN notes TEXT",
            "created_at": "ALTER TABLE telegram_user_profiles ADD COLUMN created_at DATETIME",
            "updated_at": "ALTER TABLE telegram_user_profiles ADD COLUMN updated_at DATETIME",
        }
        for col_name, sql in telegram_profile_migrations.items():
            if col_name not in tg_cols:
                logger.info(f"Telegram profile migration: adding {col_name}")
                cursor.execute(sql)

        cursor.execute("PRAGMA table_info(telegram_trade_confirmations)")
        tc_cols = [c[1] for c in cursor.fetchall()]
        telegram_trade_migrations = {
            "chat_id": "ALTER TABLE telegram_trade_confirmations ADD COLUMN chat_id TEXT",
            "symbol": "ALTER TABLE telegram_trade_confirmations ADD COLUMN symbol TEXT",
            "side": "ALTER TABLE telegram_trade_confirmations ADD COLUMN side TEXT",
            "volume": "ALTER TABLE telegram_trade_confirmations ADD COLUMN volume REAL",
            "sl": "ALTER TABLE telegram_trade_confirmations ADD COLUMN sl REAL",
            "tp": "ALTER TABLE telegram_trade_confirmations ADD COLUMN tp REAL",
            "price": "ALTER TABLE telegram_trade_confirmations ADD COLUMN price REAL",
            "request_json": "ALTER TABLE telegram_trade_confirmations ADD COLUMN request_json TEXT",
            "status": "ALTER TABLE telegram_trade_confirmations ADD COLUMN status TEXT DEFAULT 'PENDING'",
            "result_json": "ALTER TABLE telegram_trade_confirmations ADD COLUMN result_json TEXT",
            "created_at": "ALTER TABLE telegram_trade_confirmations ADD COLUMN created_at DATETIME",
            "expires_at": "ALTER TABLE telegram_trade_confirmations ADD COLUMN expires_at DATETIME",
            "decided_at": "ALTER TABLE telegram_trade_confirmations ADD COLUMN decided_at DATETIME",
        }
        for col_name, sql in telegram_trade_migrations.items():
            if col_name not in tc_cols:
                logger.info(f"Telegram trade confirmation migration: adding {col_name}")
                cursor.execute(sql)

        cursor.execute("PRAGMA table_info(telegram_audit_log)")
        tal_cols = [c[1] for c in cursor.fetchall()]
        telegram_audit_migrations = {
            "chat_id": "ALTER TABLE telegram_audit_log ADD COLUMN chat_id TEXT",
            "username": "ALTER TABLE telegram_audit_log ADD COLUMN username TEXT",
            "action": "ALTER TABLE telegram_audit_log ADD COLUMN action TEXT",
            "message": "ALTER TABLE telegram_audit_log ADD COLUMN message TEXT",
            "payload_json": "ALTER TABLE telegram_audit_log ADD COLUMN payload_json TEXT",
            "created_at": "ALTER TABLE telegram_audit_log ADD COLUMN created_at DATETIME",
        }
        for col_name, sql in telegram_audit_migrations.items():
            if col_name not in tal_cols:
                logger.info(f"Telegram audit migration: adding {col_name}")
                cursor.execute(sql)

        cursor.execute("PRAGMA table_info(best_setup_outcomes)")
        bso_cols = [c[1] for c in cursor.fetchall()]
        best_outcome_migrations = {
            "run_id": "ALTER TABLE best_setup_outcomes ADD COLUMN run_id TEXT",
            "symbol": "ALTER TABLE best_setup_outcomes ADD COLUMN symbol TEXT",
            "side": "ALTER TABLE best_setup_outcomes ADD COLUMN side TEXT",
            "score": "ALTER TABLE best_setup_outcomes ADD COLUMN score REAL",
            "price": "ALTER TABLE best_setup_outcomes ADD COLUMN price REAL",
            "entry_low": "ALTER TABLE best_setup_outcomes ADD COLUMN entry_low REAL",
            "entry_high": "ALTER TABLE best_setup_outcomes ADD COLUMN entry_high REAL",
            "stop_loss": "ALTER TABLE best_setup_outcomes ADD COLUMN stop_loss REAL",
            "take_profit_1": "ALTER TABLE best_setup_outcomes ADD COLUMN take_profit_1 REAL",
            "take_profit_2": "ALTER TABLE best_setup_outcomes ADD COLUMN take_profit_2 REAL",
            "decision_action": "ALTER TABLE best_setup_outcomes ADD COLUMN decision_action TEXT",
            "no_trade": "ALTER TABLE best_setup_outcomes ADD COLUMN no_trade INTEGER DEFAULT 0",
            "model_weighted": "ALTER TABLE best_setup_outcomes ADD COLUMN model_weighted INTEGER DEFAULT 0",
            "payload_json": "ALTER TABLE best_setup_outcomes ADD COLUMN payload_json TEXT",
            "created_at": "ALTER TABLE best_setup_outcomes ADD COLUMN created_at DATETIME",
            "outcome_1h": "ALTER TABLE best_setup_outcomes ADD COLUMN outcome_1h TEXT",
            "return_1h": "ALTER TABLE best_setup_outcomes ADD COLUMN return_1h REAL",
            "outcome_4h": "ALTER TABLE best_setup_outcomes ADD COLUMN outcome_4h TEXT",
            "return_4h": "ALTER TABLE best_setup_outcomes ADD COLUMN return_4h REAL",
            "outcome_24h": "ALTER TABLE best_setup_outcomes ADD COLUMN outcome_24h TEXT",
            "return_24h": "ALTER TABLE best_setup_outcomes ADD COLUMN return_24h REAL",
            "evaluated_at": "ALTER TABLE best_setup_outcomes ADD COLUMN evaluated_at DATETIME",
        }
        for col_name, sql in best_outcome_migrations.items():
            if col_name not in bso_cols:
                logger.info(f"Best setup outcome migration: adding {col_name}")
                cursor.execute(sql)
        try:
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_best_setup_outcomes_run_id ON best_setup_outcomes(run_id)")
        except Exception as exc:
            logger.warning(f"Best setup outcome unique index skipped: {exc}")

        cursor.execute("PRAGMA table_info(signal_snapshots)")
        sig_cols = [c[1] for c in cursor.fetchall()]
        signal_snapshot_migrations = {
            "signal_id": "ALTER TABLE signal_snapshots ADD COLUMN signal_id TEXT",
            "symbol": "ALTER TABLE signal_snapshots ADD COLUMN symbol TEXT",
            "canonical_symbol": "ALTER TABLE signal_snapshots ADD COLUMN canonical_symbol TEXT",
            "side": "ALTER TABLE signal_snapshots ADD COLUMN side TEXT",
            "timeframe": "ALTER TABLE signal_snapshots ADD COLUMN timeframe TEXT",
            "price": "ALTER TABLE signal_snapshots ADD COLUMN price REAL",
            "confidence": "ALTER TABLE signal_snapshots ADD COLUMN confidence REAL",
            "win_probability": "ALTER TABLE signal_snapshots ADD COLUMN win_probability REAL",
            "source": "ALTER TABLE signal_snapshots ADD COLUMN source TEXT",
            "market_regime": "ALTER TABLE signal_snapshots ADD COLUMN market_regime TEXT",
            "graph_guard_json": "ALTER TABLE signal_snapshots ADD COLUMN graph_guard_json TEXT",
            "payload_json": "ALTER TABLE signal_snapshots ADD COLUMN payload_json TEXT",
            "created_at": "ALTER TABLE signal_snapshots ADD COLUMN created_at DATETIME",
            "outcome_1h": "ALTER TABLE signal_snapshots ADD COLUMN outcome_1h TEXT",
            "return_1h": "ALTER TABLE signal_snapshots ADD COLUMN return_1h REAL",
            "outcome_4h": "ALTER TABLE signal_snapshots ADD COLUMN outcome_4h TEXT",
            "return_4h": "ALTER TABLE signal_snapshots ADD COLUMN return_4h REAL",
            "outcome_24h": "ALTER TABLE signal_snapshots ADD COLUMN outcome_24h TEXT",
            "return_24h": "ALTER TABLE signal_snapshots ADD COLUMN return_24h REAL",
            "evaluated_at": "ALTER TABLE signal_snapshots ADD COLUMN evaluated_at DATETIME",
        }
        for col_name, sql in signal_snapshot_migrations.items():
            if col_name not in sig_cols:
                logger.info(f"Signal snapshot migration: adding {col_name}")
                cursor.execute(sql)
        try:
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_signal_snapshots_signal_id ON signal_snapshots(signal_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_signal_snapshots_symbol_side ON signal_snapshots(canonical_symbol, side)")
        except Exception as exc:
            logger.warning(f"Signal snapshot index skipped: {exc}")

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
        with get_persistence_conn() as conn:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute("""
                INSERT INTO tactics_audit_log (symbol, recommendation, price, strategy, confidence, reasoning, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (symbol.upper(), recommendation, price, strategy, confidence, reasoning, now))
            conn.commit()
    except Exception as e:
        logger.error(f"❌ Failed to log tactics call: {e}")

@contextmanager
def get_persistence_conn():
    import sqlite3
    _ensure_persistence_db_path()
    db_path = _ACTIVE_PERSISTENCE_DB
    try:
        conn = sqlite3.connect(db_path, timeout=15)
    except sqlite3.OperationalError as exc:
        normalized = str(exc).lower()
        if "disk i/o error" not in normalized and "unable to open database file" not in normalized:
            raise
        db_path = _activate_persistence_fallback(exc)
        conn = sqlite3.connect(db_path, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=15000")
        conn.execute("PRAGMA journal_mode=WAL")
    except Exception:
        pass
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
    t9 = asyncio.create_task(telegram_bot_poller_task())
    t10 = asyncio.create_task(best_setup_scanner_task())
    t11 = asyncio.create_task(best_outcome_evaluator_task())
    t12 = asyncio.create_task(trade_memory_sync_task())
    t13 = asyncio.create_task(trade_graph_rebuild_task())
    t14 = asyncio.create_task(news_watch_poller_task())
    
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
    t9.cancel()
    t10.cancel()
    t11.cancel()
    t12.cancel()
    t13.cancel()
    t14.cancel()
    await asyncio.gather(t1, t2, t3, t4, t5, t6, t7, t8, t9, t10, t11, t12, t13, return_exceptions=True)
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

def _telegram_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "Status", "callback_data": "tg:status"},
                {"text": "Best Now", "callback_data": "tg:best"},
            ],
            [
                {"text": "Best Alt", "callback_data": "tg:bestalt"},
                {"text": "Graph", "callback_data": "tg:graph"},
            ],
            [
                {"text": "Open Best Paper", "callback_data": "tg:openbestpaper"},
            ],
            [
                {"text": "Signals", "callback_data": "tg:signals"},
                {"text": "MT5", "callback_data": "tg:mt5"},
            ],
            [
                {"text": "Paper AI", "callback_data": "tg:paper"},
                {"text": "RAG", "callback_data": "tg:rag"},
            ],
            [
                {"text": "Profile", "callback_data": "tg:profile"},
                {"text": "Help", "callback_data": "tg:help"},
            ],
        ]
    }


def _telegram_paper_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "Run Paper Scan Now", "callback_data": "tg:paper_scan"},
            ],
            [
                {"text": "Status", "callback_data": "tg:status"},
                {"text": "Signals", "callback_data": "tg:signals"},
            ],
            [
                {"text": "MT5", "callback_data": "tg:mt5"},
                {"text": "RAG", "callback_data": "tg:rag"},
            ],
        ]
    }


def _telegram_help_text() -> str:
    return (
        "CryptoStream AI Telegram bot\n\n"
        "Commands:\n"
        "/status - system readiness\n"
        "/best - best gated setup right now\n"
        "/bestalt - best alternative by Graph Guard\n"
        "/openbestpaper - open paper evidence trade from /bestalt\n"
        "/whybest - explain why the best setup is enter/wait/no-trade\n"
        "/why BTC BUY - explain a specific setup decision\n"
        "/beststats - measured /best accuracy tracker\n"
        "/graph BTCUSD BUY - Graph RAG memory for a setup\n"
        "/riskguard - daily risk guard status\n"
        "/signals - latest AI signal snapshot\n"
        "/signal BTC - trade plan for BTC, ETH, GOLD, EURUSD, etc.\n"
        "/mt5 - MT5 account and open positions\n"
        "/paper - paper trading / AI quality gate\n"
        "/paperscan - run one auto-paper scan now\n"
        "/feedback - Telegram setup feedback learning\n"
        "/rag - RAG corpus and retrieval stats\n"
        "/alerts - latest active alerts\n"
        "/audit - latest Telegram agent audit events\n"
        "/profile - your saved finance preferences\n"
        "/watch BTC GOLD - remember preferred symbols\n"
        "/setlot 0.01 - remember default lot\n"
        "/setrisk 1 - remember risk percent per trade\n"
        "/alert GOLD above 4700 - create a price alert\n"
        "/trade SYMBOL SIDE VOLUME SL TP - create a confirm/cancel live-order draft\n\n"
        "Live orders are blocked unless MT5 preflight and ML/paper-trade readiness pass."
    )




TRADE_SYMBOL_ALIASES = _helper_trade_symbol_aliases_map
_telegram_extract_symbol = _helper_telegram_extract_symbol
_trade_symbol_aliases = _helper_trade_symbol_aliases
_canonical_trade_symbol = _helper_canonical_trade_symbol
resolve_trade_symbol = _helper_resolve_trade_symbol
_telegram_symbols_from_text = _helper_telegram_symbols_from_text
_normalize_query_text = _query_normalize_query_text
_extract_historical_years = _query_extract_historical_years
_extract_index_history_targets = _query_extract_index_history_targets
_is_broad_stock_history_query = _query_is_broad_stock_history_query
_is_capability_question = _query_is_capability_question
_is_stock_top_performer_history_question = _query_is_stock_top_performer_history_question
_extract_stock_history_direction = _query_extract_stock_history_direction
_extract_stock_history_universe = _query_extract_stock_history_universe
_is_ranked_stock_history_query = _query_is_ranked_stock_history_query
_is_explicit_stock_ranking_request = _query_is_explicit_stock_ranking_request




_normalize_query_text = _query_normalize_query_text
_extract_historical_years = _query_extract_historical_years
_extract_index_history_targets = _query_extract_index_history_targets
_is_broad_stock_history_query = _query_is_broad_stock_history_query
_is_capability_question = _query_is_capability_question
_is_stock_top_performer_history_question = _query_is_stock_top_performer_history_question
_extract_stock_history_direction = _query_extract_stock_history_direction
_extract_stock_history_universe = _query_extract_stock_history_universe
_is_ranked_stock_history_query = _query_is_ranked_stock_history_query
_is_explicit_stock_ranking_request = _query_is_explicit_stock_ranking_request




def _format_historical_stock_rankings(summary: dict, language: str = "th") -> str:
    return _helper_format_historical_stock_rankings(summary, language=language)


def _format_index_historical_summary(summary: dict, language: str = "th") -> str:
    return _helper_format_index_historical_summary(summary, language=language)


def _get_index_historical_summary_fast(years: int = 10, indices: list[str] | None = None) -> dict:
    import yfinance as yf

    years = max(1, min(int(years or 10), 15))
    requested = [str(item).upper().strip() for item in (indices or ["NASDAQ_100", "SP500", "NASDAQ_COMPOSITE"])]
    alias_map = {
        "NASDAQ_100": "NASDAQ_100",
        "NASDAQ100": "NASDAQ_100",
        "NDX": "NASDAQ_100",
        "SP500": "SP500",
        "S&P500": "SP500",
        "S&P 500": "SP500",
        "NASDAQ_COMPOSITE": "NASDAQ_COMPOSITE",
        "NASDAQ": "NASDAQ_COMPOSITE",
        "IXIC": "NASDAQ_COMPOSITE",
    }
    ticker_map = {
        "NASDAQ_100": "^NDX",
        "SP500": "^GSPC",
        "NASDAQ_COMPOSITE": "^IXIC",
    }
    labels = {
        "NASDAQ_100": "NASDAQ 100",
        "SP500": "S&P 500",
        "NASDAQ_COMPOSITE": "NASDAQ Composite",
    }

    normalized: list[str] = []
    for item in requested:
        canonical = alias_map.get(item, item)
        if canonical in ticker_map and canonical not in normalized:
            normalized.append(canonical)
    if not normalized:
        normalized = ["NASDAQ_100", "SP500", "NASDAQ_COMPOSITE"]

    try:
        yf_symbols = [ticker_map[item] for item in normalized]
        data = yf.download(
            yf_symbols,
            period=f"{years}y",
            interval="1d",
            auto_adjust=True,
            progress=False,
            group_by="ticker",
            threads=False,
        )
        if data is None or data.empty:
            return {"status": "ERROR", "error": "No historical index data returned"}

        summaries: dict[str, dict] = {}
        ranking: list[tuple[str, float]] = []
        for key in normalized:
            ticker = ticker_map[key]
            try:
                if isinstance(data.columns, pd.MultiIndex):
                    close = data[ticker]["Close"].dropna() if ticker in data.columns.get_level_values(0) else pd.Series(dtype=float)
                else:
                    close = data["Close"].dropna()
            except Exception:
                close = pd.Series(dtype=float)

            if close.empty or len(close) < 30:
                continue

            start_price = float(close.iloc[0])
            end_price = float(close.iloc[-1])
            total_return = (end_price / start_price) - 1.0 if start_price > 0 else 0.0
            observed_years = max((close.index[-1] - close.index[0]).days / 365.25, 0.25)
            cagr = (end_price / start_price) ** (1.0 / observed_years) - 1.0 if start_price > 0 else 0.0
            running_max = close.cummax()
            drawdown = (close / running_max) - 1.0
            max_drawdown = float(drawdown.min()) if not drawdown.empty else 0.0
            ma50 = float(close.tail(50).mean()) if len(close) >= 50 else end_price
            ma200 = float(close.tail(200).mean()) if len(close) >= 200 else float(close.mean())
            trend = "bullish" if end_price >= ma50 >= ma200 else "mixed" if end_price >= ma200 else "bearish"
            one_year_return = ((end_price / float(close.iloc[-252])) - 1.0) if len(close) >= 252 else None

            summaries[key] = {
                "label": labels[key],
                "ticker": ticker,
                "start_date": close.index[0].strftime("%Y-%m-%d"),
                "end_date": close.index[-1].strftime("%Y-%m-%d"),
                "start_price": round(start_price, 2),
                "end_price": round(end_price, 2),
                "total_return_pct": round(total_return * 100, 2),
                "cagr_pct": round(cagr * 100, 2),
                "max_drawdown_pct": round(max_drawdown * 100, 2),
                "one_year_return_pct": round(one_year_return * 100, 2) if one_year_return is not None else None,
                "current_vs_ma50_pct": round(((end_price / ma50) - 1.0) * 100, 2) if ma50 else None,
                "current_vs_ma200_pct": round(((end_price / ma200) - 1.0) * 100, 2) if ma200 else None,
                "trend": trend,
            }
            ranking.append((key, total_return))

        if not summaries:
            return {"status": "ERROR", "error": "Unable to compute index summaries from historical data"}

        ranking.sort(key=lambda item: item[1], reverse=True)
        return {
            "status": "SUCCESS",
            "years": years,
            "indices": summaries,
            "best_index": ranking[0][0],
            "worst_index": ranking[-1][0],
            "ranking": [item[0] for item in ranking],
        }
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc)}


def _telegram_default_profile(chat_id: str) -> dict:
    return {
        "chat_id": str(chat_id),
        "username": None,
        "first_name": None,
        "preferred_symbols": [],
        "default_lot": None,
        "risk_pct": None,
        "language": "th",
        "answer_style": "concise",
        "notes": None,
    }


def _telegram_get_profile(chat_id: str) -> dict:
    profile = _telegram_default_profile(chat_id)
    try:
        with get_persistence_conn() as conn:
            row = conn.execute(
                "SELECT * FROM telegram_user_profiles WHERE chat_id = ?",
                (str(chat_id),),
            ).fetchone()
        if not row:
            return profile
        profile.update({
            "username": row["username"],
            "first_name": row["first_name"],
            "default_lot": row["default_lot"],
            "risk_pct": row["risk_pct"],
            "language": row["language"] or "th",
            "answer_style": row["answer_style"] or "concise",
            "notes": row["notes"],
        })
        try:
            profile["preferred_symbols"] = json.loads(row["preferred_symbols_json"] or "[]")
        except Exception:
            profile["preferred_symbols"] = []
    except Exception as exc:
        logger.warning(f"Telegram profile read failed: {exc}")
    return profile


def _telegram_save_profile(chat_id: str, patch: dict) -> dict:
    current = _telegram_get_profile(chat_id)
    merged_symbols = set(current.get("preferred_symbols") or [])
    for symbol in patch.get("preferred_symbols") or []:
        merged_symbols.add(str(symbol).upper().strip())
    preferred_symbols = sorted(symbol for symbol in merged_symbols if symbol)

    updated = {
        **current,
        **{key: value for key, value in patch.items() if key != "preferred_symbols" and value is not None},
        "preferred_symbols": preferred_symbols,
    }
    now = datetime.now(timezone.utc).isoformat()
    try:
        with get_persistence_conn() as conn:
            conn.execute(
                """
                INSERT INTO telegram_user_profiles (
                    chat_id, username, first_name, preferred_symbols_json, default_lot,
                    risk_pct, language, answer_style, notes, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    username=excluded.username,
                    first_name=excluded.first_name,
                    preferred_symbols_json=excluded.preferred_symbols_json,
                    default_lot=excluded.default_lot,
                    risk_pct=excluded.risk_pct,
                    language=excluded.language,
                    answer_style=excluded.answer_style,
                    notes=excluded.notes,
                    updated_at=excluded.updated_at
                """,
                (
                    str(chat_id),
                    updated.get("username"),
                    updated.get("first_name"),
                    json.dumps(preferred_symbols, ensure_ascii=False),
                    updated.get("default_lot"),
                    updated.get("risk_pct"),
                    updated.get("language") or "th",
                    updated.get("answer_style") or "concise",
                    updated.get("notes"),
                    current.get("created_at") or now,
                    now,
                ),
            )
            conn.commit()
    except Exception as exc:
        logger.warning(f"Telegram profile save failed: {exc}")
    return updated




def _telegram_extract_profile_patch(text: str, user: dict | None = None) -> dict:
    return _helper_telegram_extract_profile_patch(text, _telegram_symbols_from_text, user=user)


def _telegram_profile_text(profile: dict) -> str:
    return _helper_telegram_profile_text(profile)


def _telegram_format_readiness(readiness: dict) -> str:
    return _helper_telegram_format_readiness(readiness)


def _telegram_format_signal(symbol: str, setup: dict) -> str:
    return _helper_telegram_format_signal(symbol, setup, _trade_graph_guard)


def _telegram_tactics_symbol(symbol: str) -> str:
    return str(resolve_trade_symbol(symbol).get("tactics_symbol") or symbol).upper()


def _telegram_paper_gate_symbol(symbol: str) -> str:
    return str(resolve_trade_symbol(symbol).get("paper_symbol") or symbol).upper()


def _parse_percent_like(value: Any, default: float = 0.0) -> float:
    return _helper_parse_percent_like(value, default)


def _ml_model_trust_snapshot() -> dict[str, Any]:
    try:
        import pickle as _pickle
        from intelligence.ml.signal_model import MODEL_PATH

        if not MODEL_PATH.exists():
            return {
                "available": False,
                "trusted": False,
                "reason": "model_missing",
                "thresholds": {
                    "min_roc_auc": BEST_SETUP_MIN_MODEL_AUC,
                    "min_accuracy": BEST_SETUP_MIN_MODEL_ACCURACY,
                },
            }
        with open(MODEL_PATH, "rb") as f:
            bundle = _pickle.load(f)
        auc = float(bundle.get("roc_auc") or 0.0)
        accuracy = float(bundle.get("accuracy") or 0.0)
        promotion_gate = bundle.get("promotion_gate") or {}
        blockers = list(promotion_gate.get("blockers") or [])
        if auc < BEST_SETUP_MIN_MODEL_AUC:
            blockers.append(f"roc_auc {auc:.4f} < {BEST_SETUP_MIN_MODEL_AUC:.4f}")
        if accuracy < BEST_SETUP_MIN_MODEL_ACCURACY:
            blockers.append(f"accuracy {accuracy:.4f} < {BEST_SETUP_MIN_MODEL_ACCURACY:.4f}")
        return {
            "available": True,
            "trusted": not blockers,
            "roc_auc": round(auc, 4),
            "accuracy": round(accuracy, 4),
            "n_samples": int(bundle.get("n_samples") or 0),
            "trained_at": bundle.get("trained_at"),
            "blockers": blockers,
            "thresholds": {
                "min_roc_auc": BEST_SETUP_MIN_MODEL_AUC,
                "min_accuracy": BEST_SETUP_MIN_MODEL_ACCURACY,
            },
        }
    except Exception as exc:
        return {"available": False, "trusted": False, "reason": str(exc), "blockers": [str(exc)]}


def _best_setup_int_env(name: str, default: int, minimum: int) -> int:
    return _helper_best_setup_int_env(name, default, minimum)


BEST_SETUP_SCAN_INTERVAL_SECONDS = max(_best_setup_int_env("BEST_SETUP_SCAN_INTERVAL_SECONDS", 120, 30), 30)
BEST_SETUP_CACHE_TTL_SECONDS = max(_best_setup_int_env("BEST_SETUP_CACHE_TTL_SECONDS", 300, 60), 60)
BEST_SETUP_MIN_MODEL_AUC = float(os.getenv("BEST_SETUP_MIN_MODEL_AUC", "0.52"))
BEST_SETUP_MIN_MODEL_ACCURACY = float(os.getenv("BEST_SETUP_MIN_MODEL_ACCURACY", "0.40"))
BEST_SETUP_MIN_ACTIONABLE_SCORE = float(os.getenv("BEST_SETUP_MIN_ACTIONABLE_SCORE", "0.50"))
BEST_SETUP_QUARANTINE_ADJUSTMENT = float(os.getenv("BEST_SETUP_QUARANTINE_ADJUSTMENT", "-0.12"))
BEST_OUTCOME_EVAL_INTERVAL_SECONDS = max(_best_setup_int_env("BEST_OUTCOME_EVAL_INTERVAL_SECONDS", 900, 120), 120)
TRADE_MEMORY_SYNC_INTERVAL_SECONDS = max(_best_setup_int_env("TRADE_MEMORY_SYNC_INTERVAL_SECONDS", 1800, 300), 300)
TRADE_GRAPH_REBUILD_INTERVAL_SECONDS = max(_best_setup_int_env("TRADE_GRAPH_REBUILD_INTERVAL_SECONDS", 1800, 600), 600)
TRADE_GRAPH_GUARD_MIN_EVALUATED = max(_best_setup_int_env("TRADE_GRAPH_GUARD_MIN_EVALUATED", 20, 5), 5)
TRADE_GRAPH_GUARD_MIN_WIN_RATE = float(os.getenv("TRADE_GRAPH_GUARD_MIN_WIN_RATE", "0.35"))
TRADE_GRAPH_GUARD_MIN_AVG_RETURN = float(os.getenv("TRADE_GRAPH_GUARD_MIN_AVG_RETURN", "-0.005"))
_best_setup_cache: dict[str, dict[str, Any]] = {}
_best_setup_state: dict[str, Any] = {
    "last_run_at": None,
    "last_error": None,
    "last_payload": None,
}
_best_outcome_eval_state: dict[str, Any] = {
    "last_run_at": None,
    "last_result": None,
    "last_error": None,
}
_trade_graph_state: dict[str, Any] = {
    "last_run_at": None,
    "last_result": None,
    "last_error": None,
}


def _best_setup_cache_key(universe: list[str]) -> str:
    return _helper_best_setup_cache_key(universe, _telegram_paper_gate_symbol)


def _best_setup_entry_decision(item: dict[str, Any]) -> dict[str, Any]:
    return _helper_best_setup_entry_decision(item, graph_guard_fn=_trade_graph_guard, num_fn=_num)


def _best_setup_score_explain(
    *,
    confidence: float,
    win_prob: float,
    win_rate: float,
    avg_pnl: float,
    feedback_adjustment: float,
    weights: dict[str, float],
    model_trust: dict[str, Any],
) -> dict[str, Any]:
    return _helper_best_setup_score_explain(
        confidence=confidence,
        win_prob=win_prob,
        win_rate=win_rate,
        avg_pnl=avg_pnl,
        feedback_adjustment=feedback_adjustment,
        weights=weights,
        model_trust=model_trust,
    )


def _best_setup_risk_summary(item: dict[str, Any], chat_id: str | None = None) -> dict[str, Any]:
    return _helper_best_setup_risk_summary(
        item,
        num_fn=_num,
        account_summary=GLOBAL_ACCOUNT_CACHE.get("summary") or {},
        chat_id=chat_id,
        profile_getter=_telegram_get_profile,
        calculator=globals().get("calculate_crypto_risk"),
    )


BEST_OUTCOME_HORIZONS = {"1h": 1, "4h": 4, "24h": 24}


def _best_setup_run_id(payload: dict[str, Any], top: dict[str, Any]) -> str:
    return _helper_best_setup_run_id(payload, top)


def _record_best_setup_snapshot(payload: dict[str, Any]) -> None:
    top = (payload.get("candidates") or [{}])[0]
    if not top:
        return
    entry = top.get("entry_zone") or {}
    decision = top.get("entry_decision") or {}
    run_id = _best_setup_run_id(payload, top)
    with get_persistence_conn() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO best_setup_outcomes (
                run_id, symbol, side, score, price, entry_low, entry_high,
                stop_loss, take_profit_1, take_profit_2, decision_action,
                no_trade, model_weighted, payload_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                top.get("symbol"),
                top.get("side"),
                float(top.get("score", 0.0) or 0.0),
                _num(top.get("price")),
                _num(entry.get("low")),
                _num(entry.get("high")),
                _num(top.get("stop_loss")),
                _num(top.get("take_profit_1")),
                _num(top.get("take_profit_2")),
                decision.get("action"),
                1 if payload.get("no_trade") else 0,
                1 if top.get("ml_weighted") else 0,
                json.dumps(
                    {
                        "score_explain": top.get("score_explain"),
                        "risk_summary": top.get("risk_summary"),
                        "no_trade_reason": payload.get("no_trade_reason"),
                        "model_trust": payload.get("model_trust"),
                    },
                    ensure_ascii=False,
                    default=str,
                ),
                payload.get("generated_at") or datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()


def _best_outcome_label(row: sqlite3.Row, current_price: float) -> tuple[str, float]:
    return _helper_best_outcome_label(row, current_price)


def _evaluate_best_setup_outcomes(limit: int = 120) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    checked = 0
    updated = 0
    price_cache: dict[str, float] = {}
    with get_persistence_conn() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM best_setup_outcomes
            WHERE outcome_1h IS NULL OR outcome_4h IS NULL OR outcome_24h IS NULL
            ORDER BY datetime(created_at) ASC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        for row in rows:
            checked += 1
            try:
                created = datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            age_hours = (now - created).total_seconds() / 3600.0
            due = [label for label, hours in BEST_OUTCOME_HORIZONS.items() if age_hours >= hours and row[f"outcome_{label}"] is None]
            if not due:
                continue
            symbol = str(row["symbol"] or "")
            if symbol not in price_cache:
                price_cache[symbol] = _get_live_price(symbol)
            current_price = price_cache[symbol]
            label, signed_return = _best_outcome_label(row, current_price)
            updates = []
            params: list[Any] = []
            for horizon in due:
                updates.append(f"outcome_{horizon} = ?")
                params.append(label)
                updates.append(f"return_{horizon} = ?")
                params.append(round(signed_return, 6))
            updates.append("evaluated_at = ?")
            params.append(now.isoformat())
            params.append(row["id"])
            conn.execute(
                f"UPDATE best_setup_outcomes SET {', '.join(updates)} WHERE id = ?",
                tuple(params),
            )
            updated += 1
        if updated:
            conn.commit()
    return {"checked": checked, "updated": updated, "evaluated_at": now.isoformat()}


def _best_setup_metrics(limit: int = 500, evaluate: bool = True) -> dict[str, Any]:
    eval_summary = _evaluate_best_setup_outcomes() if evaluate else {"checked": 0, "updated": 0, "skipped": "evaluation_disabled"}
    with get_persistence_conn() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM best_setup_outcomes
            ORDER BY datetime(created_at) DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    return _helper_build_best_setup_metrics(rows, eval_summary, BEST_OUTCOME_HORIZONS)


def _daily_risk_guard(chat_id: str | None = None) -> dict[str, Any]:
    account = GLOBAL_ACCOUNT_CACHE.get("summary") or {}
    balance = _num(account.get("balance")) or _num(account.get("equity")) or 10000.0
    daily_loss_limit_pct = float(os.getenv("DAILY_LOSS_LIMIT_PCT", "2.0"))
    max_daily_trades = int(os.getenv("MAX_DAILY_TRADES", "10"))
    today = datetime.now(timezone.utc).date().isoformat()
    with get_persistence_conn() as conn:
        closed = conn.execute(
            """
            SELECT COUNT(*) AS trades,
                   COALESCE(SUM(pnl_usd), 0) AS pnl_usd,
                   SUM(CASE WHEN COALESCE(pnl_usd, 0) < 0 THEN 1 ELSE 0 END) AS losses
            FROM paper_trades
            WHERE date(closed_at) = date(?)
            """,
            (today,),
        ).fetchone()
        opened = conn.execute(
            "SELECT COUNT(*) AS trades FROM paper_trades WHERE date(opened_at) = date(?)",
            (today,),
        ).fetchone()
        open_row = conn.execute("SELECT COUNT(*) AS open_trades FROM paper_trades WHERE status = 'OPEN'").fetchone()
    return _helper_daily_risk_guard_summary(
        balance=balance,
        daily_loss_limit_pct=daily_loss_limit_pct,
        max_daily_trades=max_daily_trades,
        today=today,
        closed=closed,
        opened=opened,
        open_row=open_row,
        chat_id=chat_id,
    )


def _assert_daily_risk_guard_allows(action: str, chat_id: str | None = None) -> dict[str, Any]:
    guard = _daily_risk_guard(chat_id)
    if guard.get("blockers"):
        raise HTTPException(
            status_code=409,
            detail={
                "status": "GUARD_BLOCKED",
                "action": action,
                "message": "Daily risk guard blocked opening a new position.",
                "guard": guard,
            },
        )
    return guard


_trade_memory_sync_state: dict[str, Any] = {"last_sync_at": None, "last_result": None, "last_error": None}


def _build_trade_memory_document() -> str:
    metrics = _best_setup_metrics(limit=500, evaluate=False)
    feedback = _setup_feedback_summary(limit=300)
    risk_guard = _daily_risk_guard()
    return _helper_build_trade_memory_document(
        metrics,
        feedback,
        risk_guard,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def _sync_trade_memory_to_rag(force: bool = False) -> dict[str, Any]:
    now = time.time()
    last_sync = float(_trade_memory_sync_state.get("last_sync_epoch") or 0.0)
    if not force and last_sync and (now - last_sync) < 1800:
        return _helper_trade_memory_sync_skip(
            _trade_memory_sync_state.get("last_sync_at"),
            _trade_memory_sync_state.get("last_result"),
        )
    try:
        from intelligence.rag import ingest_knowledge_document

        content = _build_trade_memory_document()
        previous_disable = os.environ.get("RAG_DISABLE_EMBEDDINGS")
        os.environ["RAG_DISABLE_EMBEDDINGS"] = "1"
        try:
            result = ingest_knowledge_document(
                source_uri="system://cryptostream/trade-memory",
                title="CryptoStream AI Trade Memory",
                source_type="trade_memory",
                content=content,
                metadata={
                    "tenant_id": "public",
                    "source": "best_setup_outcomes",
                    "no_extra_embedding_cost": True,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                },
                chunk_chars=1800,
                overlap=120,
                max_chunks=8,
            )
        finally:
            if previous_disable is None:
                os.environ.pop("RAG_DISABLE_EMBEDDINGS", None)
            else:
                os.environ["RAG_DISABLE_EMBEDDINGS"] = previous_disable
        state_update, response = _helper_trade_memory_sync_success(now, datetime.now(timezone.utc).isoformat(), result)
        _trade_memory_sync_state.update(state_update)
        return response
    except Exception as exc:
        state_update, response = _helper_trade_memory_sync_error(now, datetime.now(timezone.utc).isoformat(), str(exc))
        _trade_memory_sync_state.update(state_update)
        return response


def _pre_graph_rag_readiness() -> dict[str, Any]:
    metrics = _best_setup_metrics(limit=1000, evaluate=False)
    feedback = _setup_feedback_summary(limit=500)
    rag_stats: dict[str, Any] = {"status": "UNKNOWN"}
    try:
        from intelligence.rag import get_knowledge_stats

        rag_stats = get_knowledge_stats()
    except Exception as exc:
        rag_stats = {"status": "ERROR", "error": str(exc)}
    return _helper_pre_graph_rag_readiness_summary(
        metrics,
        feedback,
        rag_stats,
        _trade_memory_sync_state,
        _best_outcome_eval_state,
        _trade_graph_state,
        best_outcome_eval_interval_seconds=BEST_OUTCOME_EVAL_INTERVAL_SECONDS,
        trade_memory_sync_interval_seconds=TRADE_MEMORY_SYNC_INTERVAL_SECONDS,
        trade_graph_rebuild_interval_seconds=TRADE_GRAPH_REBUILD_INTERVAL_SECONDS,
    )


def _trade_graph_key(node_type: str, *parts: Any) -> str:
    return _helper_trade_graph_key(node_type, *parts)


def _upsert_trade_graph_node(
    conn: sqlite3.Connection,
    node_type: str,
    label: str,
    properties: dict[str, Any] | None = None,
) -> str:
    node_key = _trade_graph_key(node_type, label)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO trade_graph_nodes (node_key, node_type, label, properties_json, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(node_key) DO UPDATE SET
            node_type = excluded.node_type,
            label = excluded.label,
            properties_json = excluded.properties_json,
            updated_at = excluded.updated_at
        """,
        (
            node_key,
            node_type.upper(),
            str(label or "UNKNOWN").upper(),
            json.dumps(properties or {}, ensure_ascii=False, default=str),
            now,
        ),
    )
    return node_key


def _upsert_trade_graph_edge(
    conn: sqlite3.Connection,
    source_key: str,
    target_key: str,
    edge_type: str,
    weight: float = 1.0,
    evidence: dict[str, Any] | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO trade_graph_edges (source_key, target_key, edge_type, weight, evidence_json, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_key, target_key, edge_type) DO UPDATE SET
            weight = excluded.weight,
            evidence_json = excluded.evidence_json,
            updated_at = excluded.updated_at
        """,
        (
            source_key,
            target_key,
            edge_type.upper(),
            float(weight or 0.0),
            json.dumps(evidence or {}, ensure_ascii=False, default=str),
            now,
        ),
    )


def _setup_node_key(symbol: str, side: str) -> str:
    return _helper_setup_node_key(symbol, side)


def _current_market_regime() -> dict[str, Any]:
    macro = GLOBAL_MACRO_CACHE if isinstance(GLOBAL_MACRO_CACHE, dict) else {}
    return _helper_current_market_regime(macro)


def _signal_snapshot_id(symbol: str, side: str, timeframe: str, source: str, created_at: str) -> str:
    return _helper_signal_snapshot_id(symbol, side, timeframe, source, created_at)


def _record_signal_snapshot(
    payload: dict[str, Any],
    source: str,
    timeframe: str = "15m",
) -> dict[str, Any]:
    record = _helper_build_signal_snapshot_record(
        payload,
        source,
        timeframe=timeframe,
        resolve_trade_symbol_fn=resolve_trade_symbol,
        num_fn=_num,
        parse_percent_like_fn=_parse_percent_like,
        current_market_regime_fn=_current_market_regime,
        trade_graph_guard_fn=_trade_graph_guard,
        signal_snapshot_id_fn=_signal_snapshot_id,
    )
    if record.get("status") != "OK":
        return record
    with get_persistence_conn() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO signal_snapshots (
                signal_id, symbol, canonical_symbol, side, timeframe, price, confidence,
                win_probability, source, market_regime, graph_guard_json, payload_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["signal_id"],
                record["symbol"],
                record["canonical_symbol"],
                record["side"],
                record["timeframe"],
                record["price"],
                record["confidence"],
                record["win_probability"],
                record["source"],
                record["market_regime"],
                record["graph_guard_json"],
                record["payload_json"],
                record["created_at"],
            ),
        )
        conn.commit()
    return {
        "status": "OK",
        "signal_id": record["signal_id"],
        "symbol": record["canonical_symbol"],
        "side": record["side"],
        "market_regime": record["market_regime"],
    }


def _signal_outcome_label(row: sqlite3.Row, current_price: float) -> tuple[str, float]:
    return _helper_signal_outcome_label(row, current_price)


def _evaluate_signal_snapshots(limit: int = 200) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    updated = 0
    checked = 0
    price_cache: dict[str, float] = {}
    with get_persistence_conn() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM signal_snapshots
            WHERE side IN ('BUY','SELL')
              AND (outcome_1h IS NULL OR outcome_4h IS NULL OR outcome_24h IS NULL)
            ORDER BY datetime(created_at) ASC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        for row in rows:
            checked += 1
            try:
                created = datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
            except Exception:
                continue
            age_hours = (now - created).total_seconds() / 3600.0
            due = [label for label, hours in BEST_OUTCOME_HORIZONS.items() if age_hours >= hours and row[f"outcome_{label}"] is None]
            if not due:
                continue
            symbol = str(row["canonical_symbol"] or row["symbol"] or "").upper()
            if symbol not in price_cache:
                try:
                    price_cache[symbol] = float(_get_live_price(symbol) or 0.0)
                except Exception:
                    price_cache[symbol] = 0.0
            current_price = price_cache.get(symbol, 0.0)
            if current_price <= 0:
                continue
            label, signed_return = _signal_outcome_label(row, current_price)
            updates = []
            values: list[Any] = []
            for horizon in due:
                updates.append(f"outcome_{horizon} = ?")
                values.append(label)
                updates.append(f"return_{horizon} = ?")
                values.append(signed_return)
            updates.append("evaluated_at = ?")
            values.append(now.isoformat())
            values.append(row["id"])
            conn.execute(f"UPDATE signal_snapshots SET {', '.join(updates)} WHERE id = ?", values)
            updated += len(due)
        conn.commit()
    return {"status": "OK", "checked": checked, "updated": updated}


def _signal_snapshot_metrics(limit: int = 1000, evaluate: bool = False) -> dict[str, Any]:
    evaluation = _evaluate_signal_snapshots(200) if evaluate else {"skipped": "evaluation_disabled"}
    with get_persistence_conn() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM signal_snapshots
            ORDER BY datetime(created_at) DESC
            LIMIT ?
            """,
            (min(max(int(limit), 50), 5000),),
        ).fetchall()
    return _helper_build_signal_snapshot_metrics(rows, evaluation)


def _build_trade_knowledge_graph(limit: int = 1000) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    limit = min(max(int(limit or 1000), 100), 5000)
    with get_persistence_conn() as conn:
        best_rows = conn.execute(
            """
            SELECT *
            FROM best_setup_outcomes
            ORDER BY datetime(created_at) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        feedback_rows = conn.execute(
            """
            SELECT *
            FROM telegram_setup_feedback
            ORDER BY datetime(created_at) DESC
            LIMIT ?
            """,
            (min(limit, 1000),),
        ).fetchall()
        paper_rows = conn.execute(
            """
            SELECT *
            FROM paper_trades
            ORDER BY datetime(COALESCE(closed_at, opened_at)) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        signal_rows = conn.execute(
            """
            SELECT *
            FROM signal_snapshots
            ORDER BY datetime(created_at) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        conn.execute("DELETE FROM trade_graph_edges")
        conn.execute("DELETE FROM trade_graph_nodes")

        for row in best_rows:
            symbol = str(row["symbol"] or "UNKNOWN").upper()
            side = str(row["side"] or "UNKNOWN").upper()
            decision = str(row["decision_action"] or "UNKNOWN").upper()
            setup_label = f"{symbol}:{side}"
            symbol_key = _upsert_trade_graph_node(conn, "SYMBOL", symbol, {"source": "best_setup_outcomes"})
            setup_key = _upsert_trade_graph_node(
                conn,
                "SETUP",
                setup_label,
                {
                    "symbol": symbol,
                    "side": side,
                    "latest_score": row["score"],
                    "latest_price": row["price"],
                    "entry_low": row["entry_low"],
                    "entry_high": row["entry_high"],
                    "stop_loss": row["stop_loss"],
                    "take_profit_1": row["take_profit_1"],
                    "take_profit_2": row["take_profit_2"],
                    "source": "best_setup_outcomes",
                },
            )
            decision_key = _upsert_trade_graph_node(conn, "DECISION", decision, {"source": "best_setup_outcomes"})
            _upsert_trade_graph_edge(conn, symbol_key, setup_key, "HAS_SETUP", 1.0, {"run_id": row["run_id"]})
            _upsert_trade_graph_edge(conn, setup_key, decision_key, "HAS_DECISION", 1.0, {"run_id": row["run_id"]})

            for horizon in BEST_OUTCOME_HORIZONS:
                outcome = row[f"outcome_{horizon}"]
                if not outcome:
                    continue
                return_value = float(row[f"return_{horizon}"] or 0.0)
                outcome_key = _upsert_trade_graph_node(
                    conn,
                    "OUTCOME",
                    f"{horizon}:{outcome}",
                    {"horizon": horizon, "outcome": outcome, "source": "best_setup_outcomes"},
                )
                _upsert_trade_graph_edge(
                    conn,
                    setup_key,
                    outcome_key,
                    f"LED_TO_{horizon.upper()}",
                    return_value,
                    {"run_id": row["run_id"], "return": return_value, "created_at": row["created_at"]},
                )

        rating_weights = {"GOOD": 1.0, "BAD": -1.0, "WRONG": -1.25, "LATE": -0.5}
        for row in feedback_rows:
            symbol = str(row["symbol"] or "UNKNOWN").upper()
            side = str(row["side"] or "UNKNOWN").upper()
            rating = str(row["rating"] or "UNKNOWN").upper()
            setup_key = _upsert_trade_graph_node(
                conn,
                "SETUP",
                f"{symbol}:{side}",
                {"symbol": symbol, "side": side, "source": "telegram_setup_feedback"},
            )
            feedback_key = _upsert_trade_graph_node(
                conn,
                "FEEDBACK",
                rating,
                {"source": "telegram_setup_feedback"},
            )
            _upsert_trade_graph_edge(
                conn,
                setup_key,
                feedback_key,
                "RECEIVED_FEEDBACK",
                rating_weights.get(rating, 0.0),
                {"feedback_id": row["id"], "score": row["score"], "created_at": row["created_at"]},
            )

        for row in paper_rows:
            symbol = str(row["symbol"] or "UNKNOWN").upper()
            side = str(row["side"] or "UNKNOWN").upper()
            status = str(row["status"] or "UNKNOWN").upper()
            outcome = str(row["outcome"] or status or "UNKNOWN").upper()
            setup_key = _upsert_trade_graph_node(
                conn,
                "SETUP",
                f"{symbol}:{side}",
                {"symbol": symbol, "side": side, "source": "paper_trades"},
            )
            paper_outcome_key = _upsert_trade_graph_node(
                conn,
                "PAPER_OUTCOME",
                outcome,
                {"source": "paper_trades"},
            )
            _upsert_trade_graph_edge(
                conn,
                setup_key,
                paper_outcome_key,
                "PAPER_OUTCOME",
                float(row["pnl_usd"] or row["pnl"] or 0.0),
                {
                    "trade_id": row["id"],
                    "entry_source": row["entry_source"],
                    "close_reason": row["close_reason"],
                    "opened_at": row["opened_at"],
                    "closed_at": row["closed_at"],
                },
            )

        for row in signal_rows:
            symbol = str(row["canonical_symbol"] or row["symbol"] or "UNKNOWN").upper()
            side = str(row["side"] or "UNKNOWN").upper()
            if side not in {"BUY", "SELL"}:
                continue
            setup_key = _upsert_trade_graph_node(
                conn,
                "SETUP",
                f"{symbol}:{side}",
                {"symbol": symbol, "side": side, "source": "signal_snapshots"},
            )
            regime = str(row["market_regime"] or "NEUTRAL").upper()
            regime_key = _upsert_trade_graph_node(
                conn,
                "MARKET_REGIME",
                regime,
                {"source": "signal_snapshots"},
            )
            _upsert_trade_graph_edge(
                conn,
                setup_key,
                regime_key,
                "OCCURRED_IN_REGIME",
                1.0,
                {"signal_id": row["signal_id"], "created_at": row["created_at"]},
            )
            for horizon in BEST_OUTCOME_HORIZONS:
                outcome = row[f"outcome_{horizon}"]
                if not outcome:
                    continue
                return_value = float(row[f"return_{horizon}"] or 0.0)
                outcome_key = _upsert_trade_graph_node(
                    conn,
                    "SIGNAL_OUTCOME",
                    f"{horizon}:{outcome}",
                    {"horizon": horizon, "outcome": outcome, "source": "signal_snapshots"},
                )
                _upsert_trade_graph_edge(
                    conn,
                    setup_key,
                    outcome_key,
                    f"SIGNAL_LED_TO_{horizon.upper()}",
                    return_value,
                    {"signal_id": row["signal_id"], "return": return_value, "created_at": row["created_at"]},
                )

        counts = {
            "nodes": int(conn.execute("SELECT COUNT(*) AS c FROM trade_graph_nodes").fetchone()["c"] or 0),
            "edges": int(conn.execute("SELECT COUNT(*) AS c FROM trade_graph_edges").fetchone()["c"] or 0),
            "best_snapshots": len(best_rows),
            "feedback_labels": len(feedback_rows),
            "paper_trades": len(paper_rows),
            "signal_snapshots": len(signal_rows),
        }
        meta_key = _upsert_trade_graph_node(conn, "GRAPH_META", "TRADE_GRAPH", {"built_at": now, **counts})
        _upsert_trade_graph_edge(conn, meta_key, meta_key, "BUILT_AT", 1.0, {"built_at": now})
        conn.commit()
    result = {"status": "OK", "built_at": now, "counts": counts, "cost": "local_sqlite_no_extra_cost"}
    _trade_graph_state.update({"last_run_at": now, "last_result": result, "last_error": None})
    return result


def _trade_graph_status() -> dict[str, Any]:
    with get_persistence_conn() as conn:
        node_count = int(conn.execute("SELECT COUNT(*) AS c FROM trade_graph_nodes").fetchone()["c"] or 0)
        edge_count = int(conn.execute("SELECT COUNT(*) AS c FROM trade_graph_edges").fetchone()["c"] or 0)
        by_type = [
            dict(row)
            for row in conn.execute(
                """
                SELECT node_type, COUNT(*) AS count
                FROM trade_graph_nodes
                GROUP BY node_type
                ORDER BY count DESC
                """
            ).fetchall()
        ]
        meta = conn.execute(
            """
            SELECT properties_json, updated_at
            FROM trade_graph_nodes
            WHERE node_key = 'graph_meta:TRADE_GRAPH'
            """
        ).fetchone()
    return {
        "status": "OK" if node_count and edge_count else "EMPTY",
        "nodes": node_count,
        "edges": edge_count,
        "by_type": by_type,
        "last_build": json.loads(meta["properties_json"] or "{}") if meta else None,
        "last_build_at": meta["updated_at"] if meta else None,
        "background_rebuild": {
            "interval_seconds": TRADE_GRAPH_REBUILD_INTERVAL_SECONDS,
            **_trade_graph_state,
        },
    }


def _query_trade_graph(symbol: str | None = None, side: str | None = None, limit: int = 25) -> dict[str, Any]:
    limit = min(max(int(limit or 25), 5), 100)
    symbol_filter = _canonical_trade_symbol(symbol)
    symbol_aliases = _trade_symbol_aliases(symbol_filter or symbol)
    side_filter = str(side or "").upper().strip()
    where = []
    params: list[Any] = []
    if symbol_aliases:
        where.append(f"UPPER(symbol) IN ({','.join('?' for _ in symbol_aliases)})")
        params.extend(symbol_aliases)
    if side_filter:
        where.append("UPPER(side) = ?")
        params.append(side_filter)
    where_sql = "WHERE " + " AND ".join(where) if where else ""
    with get_persistence_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT symbol, side,
                   COUNT(*) AS snapshots,
                   AVG(score) AS avg_score,
                   SUM(CASE WHEN outcome_4h IS NOT NULL THEN 1 ELSE 0 END) AS evaluated_4h,
                   SUM(CASE WHEN outcome_4h IN ('TP1','WIN') THEN 1 ELSE 0 END) AS wins_4h,
                   AVG(CASE WHEN outcome_4h IS NOT NULL THEN return_4h ELSE NULL END) AS avg_return_4h,
                   MAX(created_at) AS last_seen_at
            FROM best_setup_outcomes
            {where_sql}
            GROUP BY symbol, side
            ORDER BY evaluated_4h DESC, snapshots DESC
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()
        feedback = _setup_feedback_summary(limit=500)
        setup_summaries = []
        for row in rows:
            setup_key = f"{row['symbol']}:{row['side']}"
            evaluated = int(row["evaluated_4h"] or 0)
            wins = int(row["wins_4h"] or 0)
            graph_key = _setup_node_key(row["symbol"], row["side"])
            edges = [
                dict(edge)
                for edge in conn.execute(
                    """
                    SELECT edge_type, target_key, weight, evidence_json, updated_at
                    FROM trade_graph_edges
                    WHERE source_key = ?
                    ORDER BY updated_at DESC
                    LIMIT 12
                    """,
                    (graph_key,),
                ).fetchall()
            ]
            setup_summaries.append(
                {
                    "setup": setup_key,
                    "symbol": row["symbol"],
                    "side": row["side"],
                    "snapshots": int(row["snapshots"] or 0),
                    "avg_score": round(float(row["avg_score"] or 0.0), 4),
                    "evaluated_4h": evaluated,
                    "win_rate_4h": round(wins / max(evaluated, 1), 4),
                    "avg_return_4h": round(float(row["avg_return_4h"] or 0.0), 6),
                    "feedback_adjustment": round(float((feedback.get("score_adjustments") or {}).get(setup_key, 0.0)), 4),
                    "last_seen_at": row["last_seen_at"],
                    "edges": edges,
                }
            )
        if not setup_summaries:
            paper_rows = conn.execute(
                f"""
                SELECT symbol, side,
                       COUNT(*) AS trades,
                       SUM(CASE WHEN status = 'CLOSED' THEN 1 ELSE 0 END) AS closed_trades,
                       SUM(CASE WHEN COALESCE(pnl_usd, pnl, 0) > 0 THEN 1 ELSE 0 END) AS wins,
                       AVG(CASE WHEN status = 'CLOSED' THEN COALESCE(pnl_usd, pnl, 0) ELSE NULL END) AS avg_pnl_usd,
                       MAX(COALESCE(closed_at, opened_at)) AS last_seen_at
                FROM paper_trades
                {where_sql}
                GROUP BY symbol, side
                ORDER BY closed_trades DESC, trades DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
            for row in paper_rows:
                closed = int(row["closed_trades"] or 0)
                wins = int(row["wins"] or 0)
                graph_key = _setup_node_key(row["symbol"], row["side"])
                edges = [
                    dict(edge)
                    for edge in conn.execute(
                        """
                        SELECT edge_type, target_key, weight, evidence_json, updated_at
                        FROM trade_graph_edges
                        WHERE source_key = ?
                        ORDER BY updated_at DESC
                        LIMIT 12
                        """,
                        (graph_key,),
                    ).fetchall()
                ]
                setup_summaries.append(
                    {
                        "setup": f"{row['symbol']}:{row['side']}",
                        "symbol": row["symbol"],
                        "side": row["side"],
                        "snapshots": int(row["trades"] or 0),
                        "avg_score": 0.0,
                        "evaluated_4h": closed,
                        "win_rate_4h": round(wins / max(closed, 1), 4),
                        "avg_return_4h": round(float(row["avg_pnl_usd"] or 0.0), 6),
                        "feedback_adjustment": 0.0,
                        "last_seen_at": row["last_seen_at"],
                        "source": "paper_trades_fallback",
                        "edges": edges,
                    }
                )
    return {
        "status": "OK",
        "query": {
            "symbol": symbol_filter or None,
            "symbol_aliases": symbol_aliases,
            "side": side_filter or None,
            "limit": limit,
        },
        "setups": setup_summaries,
        "summary": {
            "setups_returned": len(setup_summaries),
            "graph_status": _trade_graph_status(),
        },
    }


def _trade_graph_context_for_query(text: str) -> dict[str, Any]:
    raw = str(text or "")
    symbol = _canonical_trade_symbol(_telegram_extract_symbol(raw, default="")) if "_telegram_extract_symbol" in globals() else ""
    lower = raw.lower()
    side = ""
    if any(term in lower for term in (" buy", "ซื้อ", "long")):
        side = "BUY"
    elif any(term in lower for term in (" sell", "ขาย", "short")):
        side = "SELL"
    try:
        query = _query_trade_graph(symbol=symbol or None, side=side or None, limit=5)
        fallback_reason = None
        if symbol and not query.get("setups"):
            fallback_reason = f"no exact graph history for {symbol}; using nearest available setup history"
            query = _query_trade_graph(symbol=None, side=side or None, limit=5)
        return {
            "status": query.get("status"),
            "symbol": symbol or None,
            "side": side or None,
            "fallback_reason": fallback_reason,
            "top_setups": [
                {
                    "setup": item.get("setup"),
                    "snapshots": item.get("snapshots"),
                    "evaluated_4h": item.get("evaluated_4h"),
                    "win_rate_4h": item.get("win_rate_4h"),
                    "avg_return_4h": item.get("avg_return_4h"),
                    "feedback_adjustment": item.get("feedback_adjustment"),
                }
                for item in query.get("setups", [])[:5]
            ],
            "graph": query.get("summary", {}).get("graph_status", {}),
        }
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc), "symbol": symbol or None, "side": side or None}


def _trade_graph_guard(symbol: str | None, side: str | None) -> dict[str, Any]:
    canonical = _canonical_trade_symbol(symbol)
    side_upper = str(side or "").upper().strip()
    guard_thresholds = {
        "min_evaluated": TRADE_GRAPH_GUARD_MIN_EVALUATED,
        "min_win_rate": TRADE_GRAPH_GUARD_MIN_WIN_RATE,
        "min_avg_return": TRADE_GRAPH_GUARD_MIN_AVG_RETURN,
        "quarantine_adjustment": BEST_SETUP_QUARANTINE_ADJUSTMENT,
    }
    if not canonical or side_upper not in {"BUY", "SELL"}:
        return _helper_build_trade_graph_guard_result(
            canonical=canonical,
            original_symbol=symbol,
            side_upper=side_upper,
            **guard_thresholds,
        )
    try:
        graph = _query_trade_graph(symbol=canonical, side=side_upper, limit=5)
        setups = graph.get("setups") or []
    except Exception as exc:
        return _helper_build_trade_graph_guard_result(
            canonical=canonical,
            side_upper=side_upper,
            graph_error=exc,
            **guard_thresholds,
        )
    return _helper_build_trade_graph_guard_result(
        canonical=canonical,
        side_upper=side_upper,
        graph=graph,
        setups=setups,
        **guard_thresholds,
    )


def _assert_trade_graph_guard_allows(symbol: str, side: str, action: str) -> dict[str, Any]:
    guard = _trade_graph_guard(symbol, side)
    if guard.get("blockers"):
        raise HTTPException(
            status_code=409,
            detail={
                "status": "GRAPH_GUARD_BLOCKED",
                "action": action,
                "message": "Graph RAG guard blocked this setup based on historical outcomes.",
                "guard": guard,
            },
        )
    return guard


def _telegram_format_trade_graph(text: str = "") -> str:
    parts = str(text or "").split()
    symbol = ""
    side = ""
    if len(parts) >= 2:
        symbol = _canonical_trade_symbol(parts[1])
    if len(parts) >= 3 and parts[2].upper() in {"BUY", "SELL"}:
        side = parts[2].upper()
    if not symbol:
        symbol = _canonical_trade_symbol(_telegram_extract_symbol(text, default=""))
    status = _trade_graph_status()
    if status.get("status") != "OK":
        try:
            _build_trade_knowledge_graph(1500)
            status = _trade_graph_status()
        except Exception as exc:
            return f"Trade Graph RAG unavailable: {exc}"

    query = _query_trade_graph(symbol=symbol or None, side=side or None, limit=5)
    aliases = _trade_symbol_aliases(symbol)[:6] if symbol else []
    guard = _trade_graph_guard(symbol, side) if symbol and side in {"BUY", "SELL"} else None
    return _helper_format_trade_graph_report(
        status=status,
        query=query,
        symbol=symbol,
        side=side,
        aliases=aliases,
        guard=guard,
        rebuild_interval_seconds=TRADE_GRAPH_REBUILD_INTERVAL_SECONDS,
    )


def _telegram_format_why_setup(text: str, chat_id: str | None = None) -> str:
    parts = str(text or "").split()
    symbol = _canonical_trade_symbol(parts[1] if len(parts) >= 2 else _telegram_extract_symbol(text, default=""))
    side = parts[2].upper() if len(parts) >= 3 and parts[2].upper() in {"BUY", "SELL"} else ""
    if not side:
        lower = str(text or "").lower()
        side = "BUY" if any(token in lower for token in ("buy", "ซื้อ", "long")) else "SELL" if any(token in lower for token in ("sell", "ขาย", "short")) else "BUY"
    guard = _trade_graph_guard(symbol, side)
    graph = _query_trade_graph(symbol=symbol, side=side, limit=3)
    risk_guard = _daily_risk_guard(chat_id)
    signal_metrics = _signal_snapshot_metrics(limit=500, evaluate=False)
    setup_key = f"{guard.get('symbol') or symbol}:{side}"
    signal_row = (signal_metrics.get("by_setup") or {}).get(setup_key) or {}
    return _helper_format_why_setup_report(
        setup_key=setup_key,
        side=side,
        guard=guard,
        graph=graph,
        risk_guard=risk_guard,
        signal_row=signal_row,
    )


def _best_alternative_candidates(chat_id: str | None = None) -> dict[str, Any]:
    profile_symbols: list[str] = []
    if chat_id:
        try:
            profile_symbols = list(_telegram_get_profile(chat_id).get("preferred_symbols") or [])
        except Exception:
            profile_symbols = []
    signal_metrics = _signal_snapshot_metrics(limit=1000, evaluate=False)
    risk_guard = _daily_risk_guard(chat_id)
    return _helper_build_best_alternative_candidates_payload(
        profile_symbols=profile_symbols,
        signal_metrics=signal_metrics,
        risk_guard=risk_guard,
        trade_graph_guard_fn=_trade_graph_guard,
        canonical_symbol_fn=_canonical_trade_symbol,
        min_evaluated=TRADE_GRAPH_GUARD_MIN_EVALUATED,
    )


def _telegram_format_best_alternative(chat_id: str | None = None) -> str:
    payload = _best_alternative_candidates(chat_id)
    return _helper_format_best_alternative_report(payload)


def _open_best_paper_evidence(chat_id: str | None = None, volume: float | None = None) -> dict[str, Any]:
    payload = _best_alternative_candidates(chat_id)
    precheck = _helper_precheck_open_best_paper_payload(payload)
    if precheck.get("status") != "READY":
        return precheck
    best = precheck.get("best") or {}
    symbol = str(precheck.get("symbol") or "")
    side = str(precheck.get("side") or "")

    _assert_daily_risk_guard_allows("telegram_open_best_paper", chat_id)
    _assert_trade_graph_guard_allows(symbol, side, "telegram_open_best_paper")

    cooldown_minutes = int((_auto_paper_status() or {}).get("cooldown_minutes") or 30)
    cooldown_cutoff = (datetime.now(timezone.utc) - timedelta(minutes=cooldown_minutes)).isoformat()
    with get_persistence_conn() as conn:
        recent_bestalt = conn.execute(
            """
            SELECT *
            FROM paper_trades
            WHERE entry_source = 'bestalt_paper_evidence'
              AND datetime(COALESCE(closed_at, opened_at)) >= datetime(?)
            ORDER BY datetime(COALESCE(closed_at, opened_at)) DESC
            LIMIT 1
            """,
            (cooldown_cutoff,),
        ).fetchone()
    if recent_bestalt:
        trade = _serialize_paper_trade(recent_bestalt)
        return {
            "status": "COOLDOWN",
            "message": f"Recent /openbestpaper evidence already exists; wait {cooldown_minutes} minutes before opening another.",
            "cooldown_minutes": cooldown_minutes,
            "trade": trade,
            "best_alternative": payload,
        }

    with get_persistence_conn() as conn:
        existing = conn.execute(
            """
            SELECT *
            FROM paper_trades
            WHERE status = 'OPEN'
              AND UPPER(symbol) = ?
              AND UPPER(side) = ?
            ORDER BY datetime(opened_at) DESC
            LIMIT 1
            """,
            (symbol, side),
        ).fetchone()
    if existing:
        return {
            "status": "ALREADY_OPEN",
            "trade": _serialize_paper_trade(existing),
            "best_alternative": payload,
        }

    if _recent_trade_exists(symbol, cooldown_minutes):
        return {
            "status": "COOLDOWN",
            "message": f"Recent paper evidence already exists for {symbol}; wait {cooldown_minutes} minutes before opening another.",
            "cooldown_minutes": cooldown_minutes,
            "best_alternative": payload,
        }

    profile: dict[str, Any] = {}
    if chat_id:
        try:
            profile = _telegram_get_profile(chat_id)
        except Exception:
            profile = {}
    configured_volume = _helper_resolve_best_paper_volume(
        requested_volume=volume,
        profile=profile,
        auto_status=_auto_paper_status() or {},
        num_fn=_num,
    )

    setup: dict[str, Any] = {}
    tactics_symbol = _telegram_tactics_symbol(symbol)
    try:
        from intelligence.tools.market_tools import get_trading_tactics

        setup = get_trading_tactics(tactics_symbol) or {}
        try:
            _record_signal_snapshot(setup, "open_best_paper", "15m")
        except Exception as snap_exc:
            logger.warning("Open best paper signal snapshot failed for %s: %s", symbol, snap_exc)
    except Exception as exc:
        setup = {"error": str(exc), "symbol": tactics_symbol}

    entry_price = _telegram_resolve_paper_entry_price(symbol, side, setup.get("price"))
    if entry_price <= 0:
        return {
            "status": "PRICE_UNAVAILABLE",
            "message": f"Unable to resolve MT5 or market entry price for {symbol}.",
            "setup": setup,
            "best_alternative": payload,
        }

    reason = _helper_best_paper_entry_reason(best)
    opened = _open_paper_trade_internal(
        symbol=symbol,
        side=side,
        volume=configured_volume,
        price=entry_price,
        entry_source="bestalt_paper_evidence",
        entry_reason=reason,
    )
    opened["volume"] = configured_volume

    stop_loss = _num(setup.get("stop_loss") or setup.get("sl"))
    take_profit = _num(setup.get("take_profit_1") or setup.get("take_profit") or setup.get("tp"))
    if stop_loss and take_profit:
        try:
            from intelligence.ml.outcome_tracker import attach_sl_tp_features

            attach_sl_tp_features(
                opened["trade_id"],
                float(stop_loss),
                float(take_profit),
                {
                    "source": "bestalt_paper_evidence",
                    "symbol": symbol,
                    "side": side,
                    "best_mode": best.get("mode"),
                    "graph_reason": best.get("reason"),
                },
                None,
            )
            opened["levels_attached"] = True
            opened["stop_loss"] = float(stop_loss)
            opened["take_profit"] = float(take_profit)
        except Exception as attach_exc:
            opened["levels_attached"] = False
            opened["levels_error"] = str(attach_exc)
    else:
        opened["levels_attached"] = bool(opened.get("ml_snapshot_attached"))

    return {
        "status": "OPENED",
        "opened": opened,
        "setup": {
            "symbol": symbol,
            "tactics_symbol": tactics_symbol,
            "side": side,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
        },
        "best_alternative": payload,
        "risk_guard": _daily_risk_guard(chat_id),
    }


def _telegram_open_best_paper_text(chat_id: str | None = None) -> str:
    try:
        result = _open_best_paper_evidence(chat_id)
    except HTTPException as exc:
        return _helper_format_open_best_paper_blocked_exception(exc.detail, status_code=exc.status_code)
    except Exception as exc:
        return f"Open best paper failed: {exc}"

    return _helper_format_open_best_paper_result(result, num_fn=_num)


def _setup_feedback_summary(chat_id: str | None = None, limit: int = 200) -> dict[str, Any]:
    try:
        with get_persistence_conn() as conn:
            params: list[Any] = []
            where = ""
            if chat_id:
                where = "WHERE chat_id = ?"
                params.append(str(chat_id))
            rows = conn.execute(
                f"""
                SELECT chat_id, symbol, side, rating, source, score, payload_json, created_at
                FROM telegram_setup_feedback
                {where}
                ORDER BY datetime(created_at) DESC
                LIMIT ?
                """,
                (*params, int(limit)),
            ).fetchall()
    except Exception as exc:
        return {
            "available": False,
            "total": 0,
            "by_rating": {},
            "by_symbol_side": {},
            "recent": [],
            "score_adjustments": {},
            "recommendations": [],
            "error": str(exc),
        }
    return _helper_build_setup_feedback_summary(rows)


def _telegram_format_feedback(chat_id: str | None = None) -> str:
    return _helper_telegram_format_feedback(_setup_feedback_summary(chat_id=chat_id, limit=200))


def _build_best_setup_payload(universe: list[str] | None = None, use_cache: bool = True) -> dict[str, Any]:
    try:
        from intelligence.ml.performance_feedback import paper_entry_performance_gate
        from intelligence.tools.market_tools import get_trading_tactics
    except Exception as exc:
        return {"available": False, "error": str(exc), "candidates": [], "skipped": []}

    universe = universe or list(AUTO_PAPER_DEFAULTS.get("symbols") or [])
    cache_key = _best_setup_cache_key(universe)
    now = time.time()
    cached = _best_setup_cache.get(cache_key) or {}
    if use_cache and cached.get("payload"):
        payload = dict(cached["payload"])
        age_seconds = now - float(cached.get("loaded_at") or now)
        payload["cache"] = {
            "hit": True,
            "stale": bool(age_seconds > BEST_SETUP_CACHE_TTL_SECONDS),
            "age_seconds": round(age_seconds, 1),
            "ttl_seconds": BEST_SETUP_CACHE_TTL_SECONDS,
        }
        return payload

    model_trust = _ml_model_trust_snapshot()
    ml_weight = 0.32 if model_trust.get("trusted") else 0.0
    confidence_weight = 0.38 if model_trust.get("trusted") else 0.45
    paper_weight = 0.20 if model_trust.get("trusted") else 0.35
    pnl_weight = 0.10 if model_trust.get("trusted") else 0.20
    score_weights = {
        "confidence": confidence_weight,
        "ml_win_probability": ml_weight,
        "paper_win_rate": paper_weight,
        "paper_avg_pnl": pnl_weight,
    }
    human_feedback = _setup_feedback_summary(limit=200)
    feedback_adjustments = human_feedback.get("score_adjustments") or {}
    candidates: list[dict[str, Any]] = []
    skipped: list[str] = []
    quarantined: list[dict[str, Any]] = []

    for raw_symbol in universe[:12]:
        paper_symbol = _telegram_paper_gate_symbol(raw_symbol)
        tactics_symbol = _telegram_tactics_symbol(raw_symbol)
        try:
            setup = get_trading_tactics(tactics_symbol)
        except Exception as exc:
            skipped.append(f"{paper_symbol}: setup_error:{exc}")
            continue
        if not isinstance(setup, dict) or setup.get("error"):
            skipped.append(f"{paper_symbol}: no_setup")
            continue

        side = str(setup.get("recommendation") or "HOLD").upper().strip()
        if side not in {"BUY", "SELL"}:
            skipped.append(f"{paper_symbol}: HOLD")
            continue

        gate = paper_entry_performance_gate(paper_symbol, side, "auto_paper")
        if not bool(gate.get("ok", False)):
            skipped.append(f"{paper_symbol}: performance_block")
            continue
        graph_guard = _trade_graph_guard(paper_symbol, side)
        if graph_guard.get("blockers"):
            skipped.append(f"{paper_symbol}: graph_guard_block:{graph_guard.get('reason')}")
            continue

        edge = setup.get("ai_edge") or {}
        tactics = setup.get("tactics") or []
        top_score = _parse_percent_like((tactics[0] or {}).get("score") if tactics else None, 0.0)
        confidence = _parse_percent_like(edge.get("signal_confidence"), top_score)
        win_prob = _parse_percent_like(edge.get("win_pct") or edge.get("win_probability"), 0.0)
        symbol_stats = gate.get("symbol_stats") or {}
        side_stats = gate.get("symbol_side_stats") or {}
        avg_pnl = float(side_stats.get("avg_pnl", symbol_stats.get("avg_pnl", 0.0)) or 0.0)
        win_rate = float(side_stats.get("win_rate", symbol_stats.get("win_rate", 0.0)) or 0.0) / 100.0
        top_tactic = tactics[0] if tactics else {}
        feedback_key = f"{paper_symbol}:{side}"
        feedback_adjustment = float(feedback_adjustments.get(feedback_key, 0.0) or 0.0)
        feedback_quarantined = feedback_adjustment <= BEST_SETUP_QUARANTINE_ADJUSTMENT
        base_score = (
            (confidence * confidence_weight)
            + (win_prob * ml_weight)
            + (win_rate * paper_weight)
            + (min(max(avg_pnl, -1.0), 1.0) * pnl_weight)
        )
        score = max(base_score + feedback_adjustment, 0.0)
        if feedback_quarantined:
            quarantined.append(
                {
                    "symbol": paper_symbol,
                    "side": side,
                    "score": round(score, 4),
                    "feedback_adjustment": round(feedback_adjustment, 4),
                    "reason": "negative Telegram feedback cooldown",
                }
            )
            skipped.append(f"{paper_symbol}: feedback_cooldown")
            continue
        candidate = {
            "score": score,
            "base_score": base_score,
            "feedback_adjustment": feedback_adjustment,
            "symbol": paper_symbol,
            "side": side,
            "setup": setup,
            "confidence": confidence,
            "win_prob": win_prob,
            "win_rate": win_rate,
            "avg_pnl": avg_pnl,
            "warnings": gate.get("warnings") or [],
            "ml_weighted": bool(model_trust.get("trusted")),
            "reasoning": top_tactic.get("logic") or setup.get("best_persona") or "Multi-layer signal passed paper-performance gate.",
            "strategy": setup.get("best_persona") or top_tactic.get("strategy") or "Institutional setup",
            "price": setup.get("price"),
            "entry_zone": setup.get("entry_zone") or {},
            "stop_loss": setup.get("stop_loss"),
            "take_profit_1": setup.get("take_profit_1"),
            "take_profit_2": setup.get("take_profit_2"),
            "graph_guard": graph_guard,
        }
        candidate["entry_decision"] = _best_setup_entry_decision(candidate)
        candidate["score_explain"] = _best_setup_score_explain(
            confidence=confidence,
            win_prob=win_prob,
            win_rate=win_rate,
            avg_pnl=avg_pnl,
            feedback_adjustment=feedback_adjustment,
            weights=score_weights,
            model_trust=model_trust,
        )
        candidate["risk_summary"] = _best_setup_risk_summary(candidate)
        candidates.append(candidate)

    candidates.sort(key=lambda item: item["score"], reverse=True)
    no_trade = False
    no_trade_reason = None
    if not candidates:
        no_trade = True
        no_trade_reason = "no setup passed all gates"
    else:
        top = candidates[0]
        top_decision = top.get("entry_decision") or {}
        if float(top.get("score", 0.0) or 0.0) < BEST_SETUP_MIN_ACTIONABLE_SCORE:
            no_trade = True
            no_trade_reason = f"top score below {BEST_SETUP_MIN_ACTIONABLE_SCORE:.2f}"
        elif top_decision.get("action") == "WAIT_BETTER_RR":
            no_trade = True
            no_trade_reason = "risk/reward is not good enough"
    payload = {
        "available": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "universe": universe[:12],
        "candidates": candidates,
        "skipped": skipped,
        "quarantined": quarantined,
        "no_trade": no_trade,
        "no_trade_reason": no_trade_reason,
        "model_trust": model_trust,
        "human_feedback": human_feedback,
        "score_weights": score_weights,
        "thresholds": {
            "min_actionable_score": BEST_SETUP_MIN_ACTIONABLE_SCORE,
            "quarantine_adjustment": BEST_SETUP_QUARANTINE_ADJUSTMENT,
        },
        "cache": {"hit": False, "stale": False, "age_seconds": 0.0, "ttl_seconds": BEST_SETUP_CACHE_TTL_SECONDS},
    }
    try:
        _record_best_setup_snapshot(payload)
    except Exception as exc:
        logger.warning(f"Best setup outcome snapshot failed: {exc}")
    _best_setup_cache[cache_key] = {"loaded_at": now, "payload": payload}
    _best_setup_state["last_run_at"] = payload["generated_at"]
    _best_setup_state["last_payload"] = payload
    _best_setup_state["last_error"] = None
    return payload


def _telegram_format_best_setup(chat_id: str | None = None) -> str:
    profile_symbols: list[str] = []
    if chat_id:
        try:
            profile_symbols = list(_telegram_get_profile(chat_id).get("preferred_symbols") or [])
        except Exception:
            profile_symbols = []
    universe = profile_symbols or list(AUTO_PAPER_DEFAULTS.get("symbols") or [])
    payload = _build_best_setup_payload(universe=universe, use_cache=True)
    if not payload.get("available"):
        return f"Best setup unavailable: {payload.get('error', 'unknown error')}"

    candidates = payload.get("candidates") or []
    skipped = payload.get("skipped") or []
    if not candidates:
        return (
            "AI Finance Agent: Best setup right now\n"
            "- No BUY/SELL setup passed the paper-performance gate yet.\n"
            f"- Skipped: {', '.join(skipped[:8]) or 'none'}\n\n"
            "Action: keep paper scan running. Live trade stays blocked until evidence improves."
        )

    cache = payload.get("cache") or {}
    model_trust = payload.get("model_trust") or {}
    human_feedback = payload.get("human_feedback") or {}
    best = candidates[0]
    best_entry = best.get("entry_zone") or {}
    decision = best.get("entry_decision") or {}
    risk = _best_setup_risk_summary(best, chat_id)
    risk_guard = _daily_risk_guard(chat_id)
    no_trade = bool(payload.get("no_trade"))
    execution_blocked = bool(risk_guard.get("blockers"))
    lines = [
        "AI Finance Agent: Best setup right now",
        f"Top pick: {best['symbol']} {best['side']} | score={float(best['score']):.2f}",
        f"Mode: {'NO TRADE' if no_trade else 'ACTIONABLE WATCH'}"
        + (f" | {payload.get('no_trade_reason')}" if no_trade and payload.get("no_trade_reason") else ""),
        f"Execution guard: {'BLOCKED' if execution_blocked else risk_guard.get('status', 'ok')}",
        f"Decision: {decision.get('action', 'WAIT')} | {decision.get('reason', 'wait for confirmation')}",
        f"Risk/reward: {decision.get('rr', 'n/a')}R",
        f"Price: {best.get('price')}",
        f"Entry zone: {best_entry.get('low')} - {best_entry.get('high')}",
        f"Stop loss: {best.get('stop_loss')}",
        f"Take profit: {best.get('take_profit_1')} / {best.get('take_profit_2')}",
        f"Confidence: {float(best.get('confidence', 0.0)):.0%} | ML win: {float(best.get('win_prob', 0.0)):.0%}",
        f"Paper edge: win={float(best.get('win_rate', 0.0)):.0%}, avg_pnl={float(best.get('avg_pnl', 0.0)):+.4f}",
        f"Human feedback adj: {float(best.get('feedback_adjustment', 0.0)):+.3f} ({human_feedback.get('total', 0)} labels)",
    ]
    if risk.get("available"):
        lines.append(
            "Risk estimate: "
            f"{risk.get('risk_percent')}% = ${risk.get('risk_amount')} risk | "
            f"size~{risk.get('position_size_units')} units | value~${risk.get('position_value')}"
        )
    else:
        lines.append(f"Risk estimate: unavailable ({risk.get('reason', 'missing data')})")
    if model_trust.get("trusted"):
        lines.append(
            f"ML model: trusted | AUC={model_trust.get('roc_auc')} | accuracy={model_trust.get('accuracy')}"
        )
    else:
        blockers = model_trust.get("blockers") or [model_trust.get("reason", "model not trusted")]
        lines.append(
            f"ML model: DEGRADED | AUC={model_trust.get('roc_auc', 'n/a')} | not weighted in score"
        )
        lines.append(f"ML blocker: {blockers[0]}")
    lines.extend([
        "",
        "Why this one:",
        f"- {best.get('reasoning')}",
        "- It passed symbol and side paper-performance gates while weaker setups were filtered out.",
        "- Telegram feedback is now included as a bounded score adjustment.",
    ])
    if not model_trust.get("trusted"):
        lines.append("- Because ML quality is degraded, this ranking prioritizes tactics + realized paper edge.")
    lines.extend([
        "",
        "How to use it:",
        "- If Mode is NO TRADE, do not enter yet; use the setup for watchlist and alert only.",
        "- If Execution guard is BLOCKED, do not open new live/paper positions until the guard clears.",
        "- Treat the entry zone as the trigger area, not a blind market order.",
        "- If price reaches entry but momentum flips against the side, skip it.",
        "- Risk is invalidated at the stop loss; do not widen it after entry.",
    ])
    if best.get("warnings"):
        lines.append(f"- Caution: {'; '.join(best['warnings'][:2])}")

    lines.append("")
    lines.append("Next best alternatives:")
    for idx, item in enumerate(candidates[:3], start=1):
        entry = item.get("entry_zone") or {}
        lines.extend([
            f"{idx}. {item['symbol']} {item['side']} | score={item['score']:.2f}",
            f"   Decision: {(item.get('entry_decision') or {}).get('action', 'WAIT')} | RR={(item.get('entry_decision') or {}).get('rr', 'n/a')}R",
            f"   Feedback adj: {float(item.get('feedback_adjustment', 0.0)):+.3f}",
            f"   Price: {item.get('price')}",
            f"   Entry: {entry.get('low')} - {entry.get('high')}",
            f"   SL/TP: {item.get('stop_loss')} / {item.get('take_profit_1')} / {item.get('take_profit_2')}",
            f"   Confidence: {item['confidence']:.0%} | ML win: {item['win_prob']:.0%}",
            f"   Paper edge: win={item['win_rate']:.0%}, avg_pnl={item['avg_pnl']:+.4f}",
        ])
    if skipped:
        lines.append("")
        lines.append(f"Filtered out: {', '.join(skipped[:8])}")
    if payload.get("quarantined"):
        lines.append("")
        q = payload["quarantined"][0]
        lines.append(
            "Feedback cooldown: "
            f"{q.get('symbol')} {q.get('side')} is paused from top ranking "
            f"(adj={float(q.get('feedback_adjustment', 0.0)):+.3f})."
        )
    lines.append("")
    cache_label = "stale-cache" if cache.get("stale") else ("cache" if cache.get("hit") else "fresh")
    lines.append(f"Cache: {cache_label} | age={cache.get('age_seconds', 0)}s")
    lines.append("Analysis only. Live order still needs MT5 preflight + full ML readiness gate.")
    return "\n".join(lines)


def _telegram_best_feedback_keyboard(chat_id: str | None = None) -> dict:
    profile_symbols: list[str] = []
    if chat_id:
        try:
            profile_symbols = list(_telegram_get_profile(chat_id).get("preferred_symbols") or [])
        except Exception:
            profile_symbols = []
    payload = _build_best_setup_payload(
        universe=profile_symbols or list(AUTO_PAPER_DEFAULTS.get("symbols") or []),
        use_cache=True,
    )
    top = (payload.get("candidates") or [{}])[0]
    symbol = str(top.get("symbol") or "NA")[:12]
    side = str(top.get("side") or "NA")[:4]
    return {
        "inline_keyboard": [
            [
                {"text": "Explain score", "callback_data": "tg:best_explain"},
                {"text": "Alert at entry", "callback_data": "tg:best_alert"},
            ],
            [
                {"text": "Why wait?", "callback_data": "tg:no_trade"},
                {"text": "Confirm alert", "callback_data": "tg:best_confirm_alert"},
            ],
            [
                {"text": "Good setup", "callback_data": f"tg:setup_fb:GOOD:{symbol}:{side}"},
                {"text": "Bad setup", "callback_data": f"tg:setup_fb:BAD:{symbol}:{side}"},
            ],
            [
                {"text": "Too late", "callback_data": f"tg:setup_fb:LATE:{symbol}:{side}"},
                {"text": "Wrong direction", "callback_data": f"tg:setup_fb:WRONG:{symbol}:{side}"},
            ],
            [
                {"text": "Refresh Best", "callback_data": "tg:best"},
                {"text": "Paper AI", "callback_data": "tg:paper"},
            ],
            [
                {"text": "Accuracy", "callback_data": "tg:best_metrics"},
                {"text": "Risk Guard", "callback_data": "tg:risk_guard"},
            ],
        ]
    }


def _telegram_format_best_explain(chat_id: str | None = None) -> str:
    profile_symbols: list[str] = []
    if chat_id:
        try:
            profile_symbols = list(_telegram_get_profile(chat_id).get("preferred_symbols") or [])
        except Exception:
            profile_symbols = []
    payload = _build_best_setup_payload(
        universe=profile_symbols or list(AUTO_PAPER_DEFAULTS.get("symbols") or []),
        use_cache=True,
    )
    top = (payload.get("candidates") or [{}])[0]
    if not top:
        return "No best setup to explain yet."

    explain = top.get("score_explain") or {}
    components = explain.get("components") or {}
    risk = _best_setup_risk_summary(top, chat_id)
    thresholds = payload.get("thresholds") or {}
    lines = [
        f"Score explanation: {top.get('symbol')} {top.get('side')}",
        f"- Final score: {float(top.get('score', 0.0)):.4f}",
        f"- Base score: {float(top.get('base_score', 0.0)):.4f}",
        f"- Confidence contribution: {float(components.get('confidence', 0.0)):+.4f}",
        f"- ML win contribution: {float(components.get('ml_win_probability', 0.0)):+.4f}",
        f"- Paper win contribution: {float(components.get('paper_win_rate', 0.0)):+.4f}",
        f"- Paper PnL contribution: {float(components.get('paper_avg_pnl', 0.0)):+.4f}",
        f"- Human feedback: {float(components.get('human_feedback', 0.0)):+.4f}",
        f"- Model note: {explain.get('model_note')}",
        f"- No-trade threshold: {float(thresholds.get('min_actionable_score', BEST_SETUP_MIN_ACTIONABLE_SCORE)):.2f}",
    ]
    if payload.get("no_trade"):
        lines.append(f"- Current mode: NO TRADE ({payload.get('no_trade_reason')})")
    else:
        lines.append("- Current mode: actionable watch")
    if risk.get("available"):
        lines.extend(
            [
                "",
                "Risk sizing estimate:",
                f"- Account basis: ${risk.get('account_balance')}",
                f"- Risk: {risk.get('risk_percent')}% = ${risk.get('risk_amount')}",
                f"- Entry midpoint: {risk.get('entry_mid')}",
                f"- Stop loss: {risk.get('stop_loss')} ({risk.get('sl_distance_pct')}%)",
                f"- Position estimate: {risk.get('position_size_units')} units, value ${risk.get('position_value')}",
            ]
        )
    lines.append("")
    lines.append("This is an analysis score, not a guarantee. Live orders still require MT5 + readiness gates.")
    return "\n".join(lines)


def _telegram_format_no_trade_reason(chat_id: str | None = None) -> str:
    profile_symbols: list[str] = []
    if chat_id:
        try:
            profile_symbols = list(_telegram_get_profile(chat_id).get("preferred_symbols") or [])
        except Exception:
            profile_symbols = []
    payload = _build_best_setup_payload(
        universe=profile_symbols or list(AUTO_PAPER_DEFAULTS.get("symbols") or []),
        use_cache=True,
    )
    top = (payload.get("candidates") or [{}])[0]
    if not top:
        return (
            "Why no trade?\n"
            "- No setup passed the paper-performance gate.\n"
            f"- Filtered: {', '.join((payload.get('skipped') or [])[:8]) or 'none'}\n\n"
            "Next: keep paper scanner running and wait for cleaner evidence."
        )
    decision = top.get("entry_decision") or {}
    risk_guard = _daily_risk_guard(chat_id)
    lines = [
        "Why no trade / why wait?",
        f"- Top setup: {top.get('symbol')} {top.get('side')} score={float(top.get('score', 0.0)):.2f}",
        f"- Current mode: {'NO TRADE' if payload.get('no_trade') else 'ACTIONABLE WATCH'}",
        f"- Main reason: {payload.get('no_trade_reason') or decision.get('reason') or 'waiting for stronger confirmation'}",
        f"- Decision: {decision.get('action', 'WAIT')}",
        f"- RR: {decision.get('rr', 'n/a')}R",
        f"- ML weighted: {bool(top.get('ml_weighted'))}",
        f"- Human feedback adj: {float(top.get('feedback_adjustment', 0.0)):+.3f}",
        f"- Daily risk guard: {risk_guard.get('status')} ({', '.join(risk_guard.get('blockers') or risk_guard.get('warnings') or ['clear'])})",
        "",
        "Best next action:",
    ]
    if payload.get("no_trade"):
        lines.append("- Set alert at entry/confirmation and do not enter manually yet.")
    elif decision.get("action") == "ENTER_NOW":
        lines.append("- It is actionable only if your execution gate, spread, and risk size also pass.")
    else:
        lines.append("- Wait for price to reach the trigger condition; do not chase.")
    if payload.get("quarantined"):
        lines.append("")
        lines.append("Paused by feedback:")
        for item in payload.get("quarantined", [])[:5]:
            lines.append(f"- {item.get('symbol')} {item.get('side')}: {item.get('reason')}")
    return "\n".join(lines)


def _telegram_format_best_metrics() -> str:
    metrics = _best_setup_metrics(limit=500, evaluate=False)
    lines = [
        "Best setup accuracy tracker",
        f"- Total snapshots: {metrics.get('total_snapshots', 0)}",
    ]
    for horizon, row in (metrics.get("horizons") or {}).items():
        lines.append(
            f"- {horizon}: evaluated={row.get('evaluated', 0)}, "
            f"win_rate={float(row.get('win_rate', 0.0)):.0%}, avg_return={float(row.get('avg_return', 0.0)):+.4%}"
        )
    if metrics.get("by_symbol"):
        ranked = sorted(
            metrics["by_symbol"].items(),
            key=lambda item: (int(item[1].get("evaluated_4h", 0)), float(item[1].get("win_rate_4h", 0.0))),
            reverse=True,
        )
        lines.append("")
        lines.append("Symbol 4h record:")
        for symbol, row in ranked[:6]:
            lines.append(
                f"- {symbol}: snapshots={row.get('snapshots', 0)}, evaluated={row.get('evaluated_4h', 0)}, "
                f"win={float(row.get('win_rate_4h', 0.0)):.0%}, avg={float(row.get('avg_return_4h', 0.0)):+.4%}"
            )
    if metrics.get("recommendations"):
        lines.append("")
        lines.extend(metrics["recommendations"][:3])
    return "\n".join(lines)


def _telegram_format_risk_guard(chat_id: str | None = None) -> str:
    guard = _daily_risk_guard(chat_id)
    lines = [
        "Daily risk guard",
        f"- Status: {guard.get('status')}",
        f"- Balance basis: ${guard.get('balance_basis')}",
        f"- Daily loss limit: {guard.get('daily_loss_limit_pct')}% = ${guard.get('daily_loss_limit_usd')}",
        f"- Paper PnL today: ${guard.get('paper_pnl_usd_today')}",
        f"- Trades today: {guard.get('opened_trades_today')}/{guard.get('max_daily_trades')}",
        f"- Open trades: {guard.get('open_trades')}",
    ]
    if guard.get("blockers"):
        lines.append("Blockers:")
        lines.extend(f"- {item}" for item in guard["blockers"])
    elif guard.get("warnings"):
        lines.append("Warnings:")
        lines.extend(f"- {item}" for item in guard["warnings"])
    else:
        lines.append("Risk guard is clear for analysis/paper mode.")
    return "\n".join(lines)


def _telegram_save_setup_feedback(chat_id: str, rating: str, symbol: str, side: str) -> dict:
    payload = _build_best_setup_payload(use_cache=True)
    matching = None
    for item in payload.get("candidates") or []:
        if str(item.get("symbol")) == symbol and str(item.get("side")) == side:
            matching = item
            break
    created_at = datetime.now(timezone.utc).isoformat()
    with get_persistence_conn() as conn:
        conn.execute(
            """
            INSERT INTO telegram_setup_feedback (
                chat_id, symbol, side, rating, source, score, payload_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(chat_id),
                symbol,
                side,
                rating,
                "telegram_best",
                float((matching or {}).get("score", 0.0) or 0.0),
                json.dumps({"match": matching, "model_trust": payload.get("model_trust")}, ensure_ascii=False, default=str),
                created_at,
            ),
        )
        conn.commit()
    return {"rating": rating, "symbol": symbol, "side": side, "created_at": created_at}


async def best_setup_scanner_task():
    logger.info("Best Setup Scanner Task started.")
    await asyncio.sleep(15)
    while True:
        try:
            loop = asyncio.get_event_loop()
            payload = await loop.run_in_executor(
                None,
                lambda: _build_best_setup_payload(
                    universe=list(AUTO_PAPER_DEFAULTS.get("symbols") or []),
                    use_cache=False,
                ),
            )
            _best_setup_state["last_payload"] = payload
            _best_setup_state["last_run_at"] = payload.get("generated_at")
            _best_setup_state["last_error"] = None if payload.get("available") else payload.get("error")
            top = (payload.get("candidates") or [{}])[0]
            if top:
                logger.info(
                    "Best setup cache refreshed: %s %s score=%.2f",
                    top.get("symbol"),
                    top.get("side"),
                    float(top.get("score", 0.0) or 0.0),
                )
        except Exception as exc:
            _best_setup_state["last_run_at"] = datetime.now(timezone.utc).isoformat()
            _best_setup_state["last_error"] = str(exc)
            logger.warning(f"Best setup scanner failed: {exc}")

        await asyncio.sleep(BEST_SETUP_SCAN_INTERVAL_SECONDS)


async def best_outcome_evaluator_task():
    logger.info("Best Outcome Evaluator Task started.")
    await asyncio.sleep(45)
    while True:
        try:
            result = await asyncio.to_thread(_evaluate_best_setup_outcomes, 80)
            signal_result = await asyncio.to_thread(_evaluate_signal_snapshots, 120)
            _best_outcome_eval_state["last_run_at"] = datetime.now(timezone.utc).isoformat()
            _best_outcome_eval_state["last_result"] = {"best_setups": result, "signals": signal_result}
            _best_outcome_eval_state["last_error"] = None
            total_updated = int(result.get("updated", 0) or 0) + int(signal_result.get("updated", 0) or 0)
            if total_updated:
                logger.info("Outcome evaluator updated %s snapshot horizon(s)", total_updated)
        except Exception as exc:
            _best_outcome_eval_state["last_run_at"] = datetime.now(timezone.utc).isoformat()
            _best_outcome_eval_state["last_error"] = str(exc)
            logger.warning(f"Best outcome evaluator failed: {exc}")
        await asyncio.sleep(BEST_OUTCOME_EVAL_INTERVAL_SECONDS)


async def trade_memory_sync_task():
    logger.info("Trade Memory RAG Sync Task started.")
    await asyncio.sleep(90)
    while True:
        try:
            result = await asyncio.to_thread(_sync_trade_memory_to_rag, False)
            if result.get("status") == "OK":
                logger.info("Trade memory synced to RAG without extra embedding cost.")
            elif result.get("status") == "ERROR":
                logger.warning("Trade memory RAG sync failed: %s", result.get("error"))
        except Exception as exc:
            _trade_memory_sync_state["last_error"] = str(exc)
            logger.warning(f"Trade memory sync task failed: {exc}")
        await asyncio.sleep(TRADE_MEMORY_SYNC_INTERVAL_SECONDS)


async def trade_graph_rebuild_task():
    logger.info("Trade Graph RAG Rebuild Task started.")
    await asyncio.sleep(120)
    while True:
        try:
            result = await asyncio.to_thread(_build_trade_knowledge_graph, 1500)
            _trade_graph_state["last_run_at"] = datetime.now(timezone.utc).isoformat()
            _trade_graph_state["last_result"] = result
            _trade_graph_state["last_error"] = None
            counts = result.get("counts") or {}
            logger.info(
                "Trade graph rebuilt: nodes=%s edges=%s snapshots=%s paper_trades=%s",
                counts.get("nodes"),
                counts.get("edges"),
                counts.get("best_snapshots"),
                counts.get("paper_trades"),
            )
        except Exception as exc:
            _trade_graph_state["last_run_at"] = datetime.now(timezone.utc).isoformat()
            _trade_graph_state["last_error"] = str(exc)
            logger.warning(f"Trade graph rebuild task failed: {exc}")
        await asyncio.sleep(TRADE_GRAPH_REBUILD_INTERVAL_SECONDS)


def _telegram_format_mt5() -> str:
    return _helper_telegram_format_mt5_snapshot(GLOBAL_ACCOUNT_CACHE)


def _telegram_format_paper() -> str:
    try:
        from intelligence.ml.trading_quality_gate import get_trading_quality_gate
        gate = get_trading_quality_gate(force_refresh=True)
    except Exception as exc:
        gate = {"error": str(exc)}
    try:
        status = _auto_paper_status()
        snapshot = _paper_trade_snapshot()
    except Exception as exc:
        return f"Paper status unavailable: {exc}"
    feedback = None
    try:
        from intelligence.ml.performance_feedback import get_feedback_snapshot

        feedback = get_feedback_snapshot(force_refresh=True)
    except Exception:
        pass
    quality = None
    try:
        from intelligence.ml.signal_model import get_paper_label_quality_report

        quality = get_paper_label_quality_report(force_refresh=True)
    except Exception:
        pass
    return _helper_telegram_format_paper_dashboard(
        gate=gate,
        status=status,
        snapshot=snapshot,
        feedback=feedback,
        quality=quality,
        num_fn=_num,
    )


def _telegram_format_rag() -> str:
    try:
        from intelligence.rag import get_knowledge_feedback_stats, get_knowledge_observability, get_knowledge_stats
        stats = get_knowledge_stats()
        feedback = get_knowledge_feedback_stats(limit=1)
        obs = get_knowledge_observability(limit=50, tenant_id="public")
        return (
            "RAG status\n"
            f"- Documents: {stats.get('documents', stats.get('document_count', 'n/a'))}\n"
            f"- Chunks: {stats.get('chunks', stats.get('chunk_count', 'n/a'))}\n"
            f"- Embedded chunks: {stats.get('embedded_chunks', 'n/a')}\n"
            f"- Retrievals: {obs.get('total_retrievals', obs.get('retrieval_count', 'n/a'))}\n"
            f"- Avg latency ms: {obs.get('avg_latency_ms', 'n/a')}\n"
            f"- Feedback: {feedback.get('summary', feedback)}"
        )
    except Exception as exc:
        readiness = build_system_readiness()
        rag = readiness.get("checks", {}).get("rag_vector", {})
        return (
            "RAG status\n"
            f"- Status: {rag.get('status', 'unknown')}\n"
            f"- Chunks: {rag.get('chunks')}\n"
            f"- Embedded chunks: {rag.get('embedded_chunks')}\n"
            f"- Detail unavailable: {exc}"
        )


def _telegram_format_alerts() -> str:
    try:
        rows = _read_alert_rows().get("alerts", [])
    except Exception as exc:
        return f"Alerts unavailable: {exc}"
    if not rows:
        return "No alerts found."
    lines = ["Latest alerts"]
    for row in rows[:8]:
        lines.append(
            f"- #{row.get('id')} {row.get('symbol')} {row.get('condition')} {row.get('price')} [{row.get('status')}]"
        )
    return "\n".join(lines)


def _telegram_format_audit(chat_id: str) -> str:
    try:
        with get_persistence_conn() as conn:
            rows = conn.execute(
                """
                SELECT action, message, created_at
                FROM telegram_audit_log
                WHERE chat_id = ?
                ORDER BY datetime(created_at) DESC
                LIMIT 10
                """,
                (str(chat_id),),
            ).fetchall()
    except Exception as exc:
        return f"Audit unavailable: {exc}"
    if not rows:
        return "No Telegram audit events yet."
    lines = ["Latest Telegram audit events"]
    for row in rows:
        msg = str(row["message"] or "").replace("\n", " ")[:80]
        lines.append(f"- {row['created_at']} | {row['action']} | {msg}")
    return "\n".join(lines)


def _telegram_audit(chat_id: str, action: str, message: str = "", payload: dict | None = None, user: dict | None = None) -> None:
    try:
        with get_persistence_conn() as conn:
            conn.execute(
                """
                INSERT INTO telegram_audit_log (chat_id, username, action, message, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(chat_id),
                    (user or {}).get("username"),
                    action,
                    str(message or "")[:1000],
                    json.dumps(payload or {}, ensure_ascii=False, default=str),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()
    except Exception as exc:
        logger.warning(f"Telegram audit write failed: {exc}")


def _telegram_parse_alert_request(text: str) -> dict | None:
    return _helper_telegram_parse_alert_request(
        text,
        symbol_extractor=lambda raw, default: _telegram_extract_symbol(raw, default=default),
        live_price_fn=_get_live_price,
        trigger_terms=("/alert", "alert", "เตือน", "แจ้งเตือน"),
        above_terms=("above", "over", ">", "มากกว่า", "สูงกว่า", "ทะลุ"),
        below_terms=("below", "under", "<", "ต่ำกว่า", "หลุด"),
    )


def _telegram_create_price_alert(chat_id: str, request: dict) -> dict:
    symbol = str(request.get("symbol") or "").upper().strip()
    condition = _normalize_alert_condition(str(request.get("condition") or ""))
    price = float(request.get("price") or 0.0)
    if not symbol or price <= 0:
        raise ValueError("symbol and positive price are required")

    now = datetime.now(timezone.utc).isoformat()
    meta_json = json.dumps({"source": "telegram_bot", "chat_id": str(chat_id)}, ensure_ascii=False)
    message = request.get("message") or f"Telegram alert: {symbol} {condition} ${price:,.2f}"
    with get_persistence_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO alerts (
                user_id, symbol, condition, price, timeframe, entry_source,
                message, meta_json, status, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?)
            """,
            (
                f"telegram:{chat_id}",
                symbol,
                condition,
                price,
                request.get("timeframe") or "15m",
                "telegram_bot",
                message,
                meta_json,
                now,
            ),
        )
        conn.commit()
        alert_id = int(cursor.lastrowid)
    _cache_delete("alerts_payload_v1")
    _append_audit_event("TELEGRAM_ALERT", f"Created alert #{alert_id}: {symbol} {condition} {price}")
    return {"id": alert_id, "symbol": symbol, "condition": condition, "price": price}


def _telegram_create_best_entry_alert(chat_id: str) -> dict:
    profile_symbols: list[str] = []
    try:
        profile_symbols = list(_telegram_get_profile(chat_id).get("preferred_symbols") or [])
    except Exception:
        profile_symbols = []
    payload = _build_best_setup_payload(
        universe=profile_symbols or list(AUTO_PAPER_DEFAULTS.get("symbols") or []),
        use_cache=True,
    )
    top = (payload.get("candidates") or [{}])[0]
    if not top:
        raise ValueError("No best setup available for alert")

    request = _helper_build_best_entry_alert_request(top, payload, num_fn=_num)
    created = _telegram_create_price_alert(chat_id, request)
    created.update(request.get("metadata") or {})
    return created


def _telegram_create_best_confirmation_alert(chat_id: str) -> dict:
    profile_symbols: list[str] = []
    try:
        profile_symbols = list(_telegram_get_profile(chat_id).get("preferred_symbols") or [])
    except Exception:
        profile_symbols = []
    payload = _build_best_setup_payload(
        universe=profile_symbols or list(AUTO_PAPER_DEFAULTS.get("symbols") or []),
        use_cache=True,
    )
    top = (payload.get("candidates") or [{}])[0]
    if not top:
        raise ValueError("No best setup available for confirmation alert")

    request = _helper_build_best_confirmation_alert_request(top, payload, num_fn=_num)
    created = _telegram_create_price_alert(chat_id, request)
    created.update(request.get("metadata") or {})
    return created


def _telegram_trade_keyboard(confirmation_id: str) -> dict:
    return _helper_telegram_trade_keyboard(confirmation_id)


def _telegram_create_trade_confirmation(chat_id: str, request: dict) -> dict:
    confirmation_id = uuid.uuid4().hex[:12]
    now_dt = datetime.now(timezone.utc)
    expires_at = now_dt + timedelta(minutes=5)
    with get_persistence_conn() as conn:
        conn.execute(
            """
            INSERT INTO telegram_trade_confirmations (
                id, chat_id, symbol, side, volume, sl, tp, price, request_json,
                status, created_at, expires_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?)
            """,
            (
                confirmation_id,
                str(chat_id),
                str(request["symbol"]).upper(),
                str(request["side"]).upper(),
                float(request["volume"]),
                float(request["sl"]),
                float(request["tp"]),
                float(request.get("price") or 0.0) if request.get("price") is not None else None,
                json.dumps(request, ensure_ascii=False),
                now_dt.isoformat(),
                expires_at.isoformat(),
            ),
        )
        conn.commit()
    _append_audit_event("TELEGRAM_TRADE_DRAFT", f"Created trade confirmation {confirmation_id}")
    return {"id": confirmation_id, "expires_at": expires_at.isoformat(), **request}


def _telegram_get_trade_confirmation(confirmation_id: str, chat_id: str) -> sqlite3.Row | None:
    with get_persistence_conn() as conn:
        return conn.execute(
            """
            SELECT *
            FROM telegram_trade_confirmations
            WHERE id = ? AND chat_id = ?
            LIMIT 1
            """,
            (confirmation_id, str(chat_id)),
        ).fetchone()


def _telegram_update_trade_confirmation(confirmation_id: str, status: str, result: dict | None = None) -> None:
    with get_persistence_conn() as conn:
        conn.execute(
            """
            UPDATE telegram_trade_confirmations
            SET status = ?, result_json = ?, decided_at = ?
            WHERE id = ?
            """,
            (
                status,
                json.dumps(result or {}, ensure_ascii=False, default=str),
                datetime.now(timezone.utc).isoformat(),
                confirmation_id,
            ),
        )
        conn.commit()


def _telegram_blocked_trade_keyboard(confirmation_id: str) -> dict:
    return _helper_telegram_blocked_trade_keyboard(confirmation_id)


def _telegram_extract_blockers(result: dict) -> list[dict]:
    return _helper_telegram_extract_blockers(result)


def _telegram_format_blocked_trade(confirmation_id: str, result: dict) -> str:
    gate = None
    try:
        from intelligence.ml.trading_quality_gate import get_trading_quality_gate

        gate = get_trading_quality_gate(force_refresh=True)
    except Exception:
        pass
    return _helper_telegram_format_blocked_trade(confirmation_id, result, gate)


def _telegram_format_blocked_detail(confirmation_id: str) -> str:
    try:
        with get_persistence_conn() as conn:
            row = conn.execute(
                "SELECT * FROM telegram_trade_confirmations WHERE id = ? LIMIT 1",
                (confirmation_id,),
            ).fetchone()
        if not row:
            return "Blocked detail not found."
        result = json.loads(row["result_json"] or "{}")
        request = json.loads(row["request_json"] or "{}")
    except Exception as exc:
        return f"Blocked detail unavailable: {exc}"
    gate = None
    try:
        from intelligence.ml.trading_quality_gate import get_trading_quality_gate

        gate = get_trading_quality_gate(force_refresh=True)
    except Exception:
        pass
    return _helper_telegram_format_blocked_detail(confirmation_id, request, result, gate)


def _telegram_resolve_paper_entry_price(symbol: str, side: str, fallback_price: Any = None) -> float:
    """Resolve a paper entry from MT5 first so broker aliases like GOLD work."""
    try:
        price = float(fallback_price or 0.0)
        if price > 0:
            return price
    except Exception:
        pass

    side_upper = (side or "").upper().strip()
    try:
        from intelligence.mt5_connector import resolve_broker_symbol

        resolved = resolve_broker_symbol(symbol)
        quote = resolved.get("quote") or {}
        bid = float(quote.get("bid") or 0.0)
        ask = float(quote.get("ask") or 0.0)
        last = float(quote.get("last") or 0.0)
        if side_upper == "BUY" and ask > 0:
            return ask
        if side_upper == "SELL" and bid > 0:
            return bid
        if bid > 0 and ask > 0:
            return (bid + ask) / 2
        if last > 0:
            return last
    except Exception as exc:
        logger.warning("Telegram paper fallback MT5 quote failed for %s: %s", symbol, exc)

    try:
        price = _get_live_price(symbol)
        if price > 0:
            return price
    except Exception:
        pass
    return 0.0


def _telegram_existing_paper_for_confirmation(confirmation_id: str) -> dict | None:
    try:
        with get_persistence_conn() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM paper_trades
                WHERE entry_source = 'telegram_blocked_live_fallback'
                  AND entry_reason LIKE ?
                ORDER BY datetime(opened_at) DESC
                LIMIT 1
                """,
                (f"%{confirmation_id}%",),
            ).fetchone()
        return _serialize_paper_trade(row) if row else None
    except Exception as exc:
        logger.warning("Telegram duplicate paper lookup failed for %s: %s", confirmation_id, exc)
        return None


async def _telegram_open_paper_from_confirmation(chat_id: str, confirmation_id: str) -> None:
    row = await asyncio.to_thread(_telegram_get_trade_confirmation, confirmation_id, chat_id)
    if not row:
        await notifier.send_telegram_message(chat_id, "Trade confirmation not found.")
        return
    try:
        try:
            await asyncio.to_thread(_assert_daily_risk_guard_allows, "telegram_paper_fallback", chat_id)
        except HTTPException as guard_exc:
            detail = guard_exc.detail if isinstance(guard_exc.detail, dict) else {"message": str(guard_exc.detail)}
            guard = detail.get("guard") or {}
            await notifier.send_telegram_message(
                chat_id,
                "Paper fallback blocked by daily risk guard.\n"
                f"- Status: {guard.get('status')}\n"
                f"- Blockers: {', '.join(guard.get('blockers') or ['unknown'])}\n\n"
                "Use /riskguard and wait until the guard clears.",
                reply_markup=_telegram_keyboard(),
            )
            return
        request = json.loads(row["request_json"] or "{}")
        existing = await asyncio.to_thread(_telegram_existing_paper_for_confirmation, confirmation_id)
        if existing:
            await notifier.send_telegram_message(
                chat_id,
                "Paper trade already exists for this confirmation.\n"
                f"- Paper trade ID: {existing['id']}\n"
                f"- Symbol: {existing['symbol']}\n"
                f"- Side: {existing['side']}\n"
                f"- Status: {existing['status']}\n"
                f"- Entry price: {_num(existing.get('entry_price')):.5f}",
                reply_markup=_telegram_paper_keyboard(),
            )
            return
        entry_price = await asyncio.to_thread(
            _telegram_resolve_paper_entry_price,
            request["symbol"],
            request["side"],
            request.get("price"),
        )
        if entry_price <= 0:
            await notifier.send_telegram_message(
                chat_id,
                f"Paper fallback failed: unable to resolve MT5 or market entry price for {request['symbol']}.",
                reply_markup=_telegram_keyboard(),
            )
            return
        opened = await asyncio.to_thread(
            _open_paper_trade_internal,
            symbol=request["symbol"],
            side=request["side"],
            volume=float(request["volume"]),
            price=entry_price,
            entry_source="telegram_blocked_live_fallback",
            entry_reason=f"Paper fallback from blocked live confirmation {confirmation_id}",
        )
        try:
            from intelligence.ml.outcome_tracker import attach_sl_tp_features
            await asyncio.to_thread(
                attach_sl_tp_features,
                opened["trade_id"],
                float(request["sl"]),
                float(request["tp"]),
                {
                    "source": "telegram_blocked_live_fallback",
                    "confirmation_id": confirmation_id,
                    "symbol": request["symbol"],
                    "side": request["side"],
                },
                None,
            )
            opened["levels_attached"] = True
        except Exception as attach_exc:
            opened["levels_attached"] = False
            opened["levels_error"] = str(attach_exc)
        _telegram_audit(chat_id, "paper_trade_from_blocked_live", "", {"id": confirmation_id, "opened": opened})
        await notifier.send_telegram_message(
            chat_id,
            "Opened paper trade instead.\n"
            f"- Paper trade ID: {opened['trade_id']}\n"
            f"- Symbol: {request['symbol']}\n"
            f"- Side: {request['side']}\n"
            f"- Volume: {request['volume']}\n"
            f"- Entry price: {entry_price:.5f}\n"
            f"- SL/TP attached: {opened.get('levels_attached')}",
            reply_markup=_telegram_keyboard(),
        )
    except Exception as exc:
        await notifier.send_telegram_message(chat_id, f"Paper fallback failed: {exc}", reply_markup=_telegram_keyboard())


def _telegram_is_finance_text(text: str) -> bool:
    lower = str(text or "").lower()
    finance_terms = {
        "btc", "eth", "sol", "xrp", "gold", "xau", "eurusd", "usd", "oil", "nasdaq", "sp500",
        "stock", "crypto", "forex", "entry", "sell", "buy", "hold", "sl", "tp", "risk",
        "portfolio", "market", "price", "chart", "signal", "trend", "support", "resistance",
        "เทรด", "ซื้อ", "ขาย", "เข้า", "ออก", "ทอง", "หุ้น", "คริปโต", "ตลาด", "ราคา",
        "พอร์ต", "แนวรับ", "แนวต้าน", "กำไร", "ขาดทุน", "เสี่ยง", "วิเคราะห์",
    }
    return any(term in lower for term in finance_terms)


async def _telegram_finance_agent_answer(text: str, chat_id: str) -> str:
    readiness = await asyncio.to_thread(build_system_readiness)
    market_snapshot = await asyncio.to_thread(get_market_snapshot)
    profile = await asyncio.to_thread(_telegram_get_profile, chat_id)

    rag_context = {}
    try:
        await asyncio.to_thread(_sync_trade_memory_to_rag, False)
        from intelligence.rag import retrieve_knowledge_context
        rag_context = await asyncio.to_thread(
            retrieve_knowledge_context,
            query=text,
            limit=4,
            tenant_id="public",
            experiment_arm="telegram_agent",
        )
    except Exception as exc:
        rag_context = {"status": "ERROR", "error": str(exc)}

    signal_context = []
    try:
        if INTELLIGENCE_AVAILABLE and crypto_intel:
            signal_context = await asyncio.to_thread(
                lambda: crypto_intel.get_quick_signals(["BTC", "ETH", "GOLD", "EURUSD"], timeframe="15m")
            )
    except Exception as exc:
        signal_context = [{"error": str(exc)}]

    account = GLOBAL_ACCOUNT_CACHE.get("summary") or {}
    positions = GLOBAL_ACCOUNT_CACHE.get("positions") or []
    best_metrics = await asyncio.to_thread(_best_setup_metrics, 250, False)
    risk_guard = await asyncio.to_thread(_daily_risk_guard, chat_id)
    trade_graph_context = await asyncio.to_thread(_trade_graph_context_for_query, text)
    system_prompt = (
        "You are CryptoStream AI, an AI finance agent for trading and market analysis. "
        "Reply in Thai unless the user clearly asks for English. Be concise but useful. "
        "Use the provided system, market, RAG, trade graph, signal, and MT5 context as the source of truth. "
        "Use trade_graph_context to explain what similar symbol/side setups historically did, but do not overclaim precision. "
        "Use telegram_user_profile to personalize symbols, lot size, risk percentage, language, and answer style. "
        "If the profile is missing something important, infer conservatively and ask one short follow-up only when needed. "
        "Never claim a live trade was executed unless a tool result says SUCCESS. "
        "If asked whether to buy/sell, give a practical plan with signal, entry zone, stop loss, take profit, "
        "risk note, and why. If live AI trading is blocked, say it is analysis/paper mode only. "
        "Do not provide guaranteed-profit language."
    )
    prompt = {
        "user_message": text,
        "telegram_user_profile": profile,
        "system_readiness": {
            "overall_percent": readiness.get("overall_percent"),
            "ready_for_users": readiness.get("ready_for_users"),
            "ready_for_live_trading": readiness.get("ready_for_live_trading"),
            "ready_for_live_ai_trading": readiness.get("ready_for_live_ai_trading"),
            "ai_blockers": readiness.get("checks", {}).get("ai_trading_quality", {}).get("blockers", []),
        },
        "best_setup_accuracy": {
            "horizons": best_metrics.get("horizons", {}),
            "recommendations": best_metrics.get("recommendations", []),
        },
        "daily_risk_guard": risk_guard,
        "market_snapshot": market_snapshot,
        "rag_context": rag_context,
        "trade_graph_context": trade_graph_context,
        "signals": signal_context,
        "mt5": {
            "connected": bool(GLOBAL_ACCOUNT_CACHE.get("connected")),
            "account": {
                "balance": account.get("balance"),
                "equity": account.get("equity"),
                "currency": account.get("currency"),
                "trade_allowed": account.get("trade_allowed"),
                "expert_allowed": account.get("trade_expert"),
            },
            "positions_count": len(positions),
            "positions": positions[:5],
        },
    }

    try:
        result = await asyncio.wait_for(
            client.aio.models.generate_content(
                model=MODEL_ID,
                contents=[
                    types.Content(
                        role="user",
                        parts=[types.Part(text=json.dumps(prompt, ensure_ascii=False, default=str))],
                    )
                ],
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            ),
            timeout=25,
        )
        reply = getattr(result, "text", None) or ""
        if reply.strip():
            return reply.strip()[:3800]
    except Exception as exc:
        logger.warning(f"Telegram finance agent fallback failed: {exc}")

    if _telegram_is_finance_text(text):
        return (
            "ตอนนี้ผมตอบแบบ agent ไม่สำเร็จชั่วคราว แต่ระบบตลาดยังทำงานอยู่ครับ\n"
            "ลองใช้ /signal BTC, /signal GOLD, /signals, /status หรือ /paper ได้เลย"
        )
    return _telegram_help_text()


async def _telegram_execute_trade_command(chat_id: str, text: str) -> None:
    parts = str(text or "").split()
    if len(parts) < 6:
        await notifier.send_telegram_message(
            chat_id,
            "Usage: /trade SYMBOL SIDE VOLUME SL TP\nExample: /trade GOLD BUY 0.01 4500 4900\nThis creates a confirmation draft first.",
        )
        return
    _, symbol, side, volume, sl, tp, *rest = parts
    try:
        from intelligence.mt5_connector import validate_live_order_request
        request = {
            "symbol": symbol.upper().strip(),
            "side": side.upper().strip(),
            "volume": float(volume),
            "sl": float(sl),
            "tp": float(tp),
            "price": None,
        }
        preflight = validate_live_order_request(
            symbol=request["symbol"],
            action=request["side"],
            volume=request["volume"],
            sl=request["sl"],
            tp=request["tp"],
            price=request["price"],
        )
        graph_guard = _trade_graph_guard(request["symbol"], request["side"])
        if graph_guard.get("blockers"):
            await notifier.send_telegram_message(
                chat_id,
                "Trade draft rejected by Graph RAG guard.\n"
                f"- Symbol: {graph_guard.get('symbol')}\n"
                f"- Side: {graph_guard.get('side')}\n"
                f"- Reason: {graph_guard.get('reason')}\n\n"
                "Use /graph to inspect the setup memory.",
                reply_markup=_telegram_keyboard(),
            )
            _telegram_audit(chat_id, "trade_graph_guard_blocked", text, {"graph_guard": graph_guard})
            return
        if not preflight.get("passed"):
            await notifier.send_telegram_message(
                chat_id,
                "Trade draft rejected by preflight.\n"
                f"Issues: {', '.join(preflight.get('issues', []))}",
            )
            _telegram_audit(chat_id, "trade_preflight_blocked", text, {"preflight": preflight})
            return
        draft = await asyncio.to_thread(_telegram_create_trade_confirmation, chat_id, request)
    except Exception as exc:
        await notifier.send_telegram_message(chat_id, f"Trade draft failed: {exc}")
        return

    _telegram_audit(chat_id, "trade_confirmation_created", text, draft)
    await notifier.send_telegram_message(
        chat_id,
        "Trade confirmation required\n"
        f"- ID: {draft['id']}\n"
        f"- Symbol: {draft['symbol']}\n"
        f"- Side: {draft['side']}\n"
        f"- Volume: {draft['volume']}\n"
        f"- SL: {draft['sl']}\n"
        f"- TP: {draft['tp']}\n"
        "- Expires in: 5 minutes\n\n"
        "Press Confirm Trade to send this request through the live safety gates.",
        reply_markup=_telegram_trade_keyboard(draft["id"]),
    )


async def _telegram_confirm_trade(chat_id: str, confirmation_id: str) -> None:
    row = await asyncio.to_thread(_telegram_get_trade_confirmation, confirmation_id, chat_id)
    if not row:
        await notifier.send_telegram_message(chat_id, "Trade confirmation not found.")
        return
    if row["status"] != "PENDING":
        await notifier.send_telegram_message(chat_id, f"Trade confirmation is already {row['status']}.")
        return
    try:
        expires_at = datetime.fromisoformat(str(row["expires_at"]))
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires_at:
            await asyncio.to_thread(_telegram_update_trade_confirmation, confirmation_id, "EXPIRED", {"reason": "expired"})
            await notifier.send_telegram_message(chat_id, "Trade confirmation expired. Create a new /trade request.")
            return
    except Exception:
        pass

    request = json.loads(row["request_json"] or "{}")
    try:
        await asyncio.to_thread(_assert_daily_risk_guard_allows, "telegram_live_trade", chat_id)
    except HTTPException as guard_exc:
        detail = guard_exc.detail if isinstance(guard_exc.detail, dict) else {"message": str(guard_exc.detail)}
        result = {
            "status": "GUARD_BLOCKED",
            "message": detail.get("message", "Daily risk guard blocked live trade."),
            "guard": detail.get("guard"),
        }
        await asyncio.to_thread(_telegram_update_trade_confirmation, confirmation_id, "BLOCKED", result)
        await notifier.send_telegram_message(
            chat_id,
            "Live order blocked by daily risk guard.\n"
            f"- Blockers: {', '.join((result.get('guard') or {}).get('blockers') or ['unknown'])}\n\n"
            "Use /riskguard. I will not execute a new order while this guard is blocked.",
            reply_markup=_telegram_blocked_trade_keyboard(confirmation_id),
        )
        return
    try:
        from intelligence.tools.market_tools import execute_mt5_trade
        result = await asyncio.to_thread(
            execute_mt5_trade,
            symbol=request["symbol"],
            side=request["side"],
            volume=float(request["volume"]),
            sl=float(request["sl"]),
            tp=float(request["tp"]),
            price=request.get("price"),
            comment=f"CryptoStream Telegram Confirm {confirmation_id}",
        )
    except Exception as exc:
        result = {"status": "ERROR", "message": str(exc)}

    final_status = "EXECUTED" if result.get("status") == "SUCCESS" else "BLOCKED"
    await asyncio.to_thread(_telegram_update_trade_confirmation, confirmation_id, final_status, result)
    _telegram_audit(chat_id, f"trade_{final_status.lower()}", "", {"id": confirmation_id, "result": result})

    if result.get("status") == "SUCCESS":
        await notifier.send_telegram_message(
            chat_id,
            f"Live order executed.\nID: {confirmation_id}\nSymbol: {request['symbol']}\nSide: {request['side']}\nResult: {result}",
            reply_markup=_telegram_keyboard(),
        )
        return
    await notifier.send_telegram_message(
        chat_id,
        _telegram_format_blocked_trade(confirmation_id, result),
        reply_markup=_telegram_blocked_trade_keyboard(confirmation_id),
    )


async def _telegram_cancel_trade(chat_id: str, confirmation_id: str) -> None:
    row = await asyncio.to_thread(_telegram_get_trade_confirmation, confirmation_id, chat_id)
    if not row:
        await notifier.send_telegram_message(chat_id, "Trade confirmation not found.")
        return
    if row["status"] != "PENDING":
        await notifier.send_telegram_message(chat_id, f"Trade confirmation is already {row['status']}.")
        return
    await asyncio.to_thread(_telegram_update_trade_confirmation, confirmation_id, "CANCELLED", {"reason": "user_cancelled"})
    _telegram_audit(chat_id, "trade_cancelled", "", {"id": confirmation_id})
    await notifier.send_telegram_message(chat_id, f"Cancelled trade confirmation {confirmation_id}.", reply_markup=_telegram_keyboard())


async def _telegram_run_paper_scan(chat_id: str) -> None:
    try:
        summary = await asyncio.to_thread(_auto_paper_cycle_sync)
        _auto_paper_state["last_run_at"] = datetime.now(timezone.utc).isoformat()
        _auto_paper_state["last_summary"] = summary
        _auto_paper_state["last_error"] = None
        opened = len(summary.get("opened", []))
        shadow = len(summary.get("shadow_opened", []))
        expired = (summary.get("expired_labels") or {}).get("closed_count", 0)
        skipped = len(summary.get("skipped", []))
        paper_text = await asyncio.to_thread(_telegram_format_paper)
        await notifier.send_telegram_message(
            chat_id,
            "Paper scan completed\n"
            f"- Opened auto trades: {opened}\n"
            f"- Opened shadow labels: {shadow}\n"
            f"- Closed stale labels: {expired}\n"
            f"- Skipped candidates: {skipped}\n\n"
            + paper_text,
            reply_markup=_telegram_paper_keyboard(),
        )
    except Exception as exc:
        _auto_paper_state["last_run_at"] = datetime.now(timezone.utc).isoformat()
        _auto_paper_state["last_error"] = str(exc)
        await notifier.send_telegram_message(chat_id, f"Paper scan failed: {exc}", reply_markup=_telegram_paper_keyboard())


async def _telegram_reply_for_text(chat_id: str, text: str, user: dict | None = None) -> None:
    raw = str(text or "").strip()
    lower = raw.lower()
    command = lower.split()[0] if lower.startswith("/") else ""
    profile_patch = _telegram_extract_profile_patch(raw, user=user)
    if profile_patch:
        await asyncio.to_thread(_telegram_save_profile, chat_id, profile_patch)

    if command in {"/start", "/help", "/menu"}:
        await notifier.send_telegram_message(chat_id, _telegram_help_text(), reply_markup=_telegram_keyboard())
        return
    if command == "/profile":
        profile = await asyncio.to_thread(_telegram_get_profile, chat_id)
        await notifier.send_telegram_message(chat_id, _telegram_profile_text(profile), reply_markup=_telegram_keyboard())
        return
    if command == "/forgetprofile":
        try:
            with get_persistence_conn() as conn:
                conn.execute("DELETE FROM telegram_user_profiles WHERE chat_id = ?", (str(chat_id),))
                conn.commit()
            await notifier.send_telegram_message(chat_id, "ลบ finance profile ของ Telegram chat นี้แล้วครับ", reply_markup=_telegram_keyboard())
        except Exception as exc:
            await notifier.send_telegram_message(chat_id, f"ลบ profile ไม่สำเร็จ: {exc}")
        return
    if command == "/watch":
        symbols = _telegram_symbols_from_text(raw)
        profile = await asyncio.to_thread(_telegram_save_profile, chat_id, {"preferred_symbols": symbols})
        await notifier.send_telegram_message(chat_id, "จำ watchlist แล้วครับ\n\n" + _telegram_profile_text(profile), reply_markup=_telegram_keyboard())
        return
    if command == "/setlot":
        parts = raw.split()
        if len(parts) < 2:
            await notifier.send_telegram_message(chat_id, "ใช้แบบนี้ครับ: /setlot 0.01")
            return
        try:
            default_lot = max(float(parts[1]), 0.001)
        except Exception:
            await notifier.send_telegram_message(chat_id, "lot ต้องเป็นตัวเลข เช่น /setlot 0.01")
            return
        profile = await asyncio.to_thread(_telegram_save_profile, chat_id, {"default_lot": default_lot})
        await notifier.send_telegram_message(chat_id, "จำ lot ปกติแล้วครับ\n\n" + _telegram_profile_text(profile), reply_markup=_telegram_keyboard())
        return
    if command == "/setrisk":
        parts = raw.split()
        if len(parts) < 2:
            await notifier.send_telegram_message(chat_id, "ใช้แบบนี้ครับ: /setrisk 1")
            return
        try:
            risk_pct = min(max(float(parts[1].replace("%", "")), 0.1), 10.0)
        except Exception:
            await notifier.send_telegram_message(chat_id, "risk ต้องเป็นตัวเลข เช่น /setrisk 1")
            return
        profile = await asyncio.to_thread(_telegram_save_profile, chat_id, {"risk_pct": risk_pct})
        await notifier.send_telegram_message(chat_id, "จำ risk ต่อไม้แล้วครับ\n\n" + _telegram_profile_text(profile), reply_markup=_telegram_keyboard())
        return
    if command == "/status" or "status" in lower or "พร้อม" in lower:
        readiness = await asyncio.to_thread(build_system_readiness)
        await notifier.send_telegram_message(chat_id, _telegram_format_readiness(readiness), reply_markup=_telegram_keyboard())
        return
    if command == "/best":
        await notifier.send_telegram_message(
            chat_id,
            await asyncio.to_thread(_telegram_format_best_setup, chat_id),
            reply_markup=await asyncio.to_thread(_telegram_best_feedback_keyboard, chat_id),
        )
        return
    if command in {"/bestalt", "/alternative", "/alts"}:
        await notifier.send_telegram_message(
            chat_id,
            await asyncio.to_thread(_telegram_format_best_alternative, chat_id),
            reply_markup=_telegram_keyboard(),
        )
        return
    if command in {"/openbestpaper", "/openbest", "/paperbest"}:
        await notifier.send_telegram_message(
            chat_id,
            await asyncio.to_thread(_telegram_open_best_paper_text, chat_id),
            reply_markup=_telegram_keyboard(),
        )
        return
    if command in {"/whybest", "/notrade", "/whywait"}:
        await notifier.send_telegram_message(
            chat_id,
            await asyncio.to_thread(_telegram_format_no_trade_reason, chat_id),
            reply_markup=await asyncio.to_thread(_telegram_best_feedback_keyboard, chat_id),
        )
        return
    if command == "/why":
        await notifier.send_telegram_message(
            chat_id,
            await asyncio.to_thread(_telegram_format_why_setup, raw, chat_id),
            reply_markup=_telegram_keyboard(),
        )
        return
    if command in {"/beststats", "/accuracy"}:
        await notifier.send_telegram_message(
            chat_id,
            await asyncio.to_thread(_telegram_format_best_metrics),
            reply_markup=await asyncio.to_thread(_telegram_best_feedback_keyboard, chat_id),
        )
        return
    if command in {"/riskguard", "/dailyguard"}:
        await notifier.send_telegram_message(
            chat_id,
            await asyncio.to_thread(_telegram_format_risk_guard, chat_id),
            reply_markup=await asyncio.to_thread(_telegram_best_feedback_keyboard, chat_id),
        )
        return
    if command == "/mt5":
        await notifier.send_telegram_message(chat_id, _telegram_format_mt5(), reply_markup=_telegram_keyboard())
        return
    if command == "/paper":
        await notifier.send_telegram_message(chat_id, await asyncio.to_thread(_telegram_format_paper), reply_markup=_telegram_paper_keyboard())
        return
    if command in {"/feedback", "/learn"}:
        await notifier.send_telegram_message(chat_id, await asyncio.to_thread(_telegram_format_feedback, chat_id), reply_markup=_telegram_keyboard())
        return
    if command == "/rag":
        await notifier.send_telegram_message(chat_id, await asyncio.to_thread(_telegram_format_rag), reply_markup=_telegram_keyboard())
        return
    if command in {"/graph", "/memory"}:
        await notifier.send_telegram_message(chat_id, await asyncio.to_thread(_telegram_format_trade_graph, raw), reply_markup=_telegram_keyboard())
        return
    if command == "/alerts":
        await notifier.send_telegram_message(chat_id, await asyncio.to_thread(_telegram_format_alerts), reply_markup=_telegram_keyboard())
        return
    if command == "/audit":
        await notifier.send_telegram_message(chat_id, await asyncio.to_thread(_telegram_format_audit, chat_id), reply_markup=_telegram_keyboard())
        return
    if command == "/alert" or "alert" in lower or "เตือน" in lower or "แจ้งเตือน" in lower:
        alert_request = _telegram_parse_alert_request(raw)
        if not alert_request:
            await notifier.send_telegram_message(
                chat_id,
                "สร้าง alert ไม่สำเร็จครับ ใช้แบบนี้ได้:\n/alert GOLD above 4700\n/alert BTC below 78000",
            )
            return
        try:
            alert = await asyncio.to_thread(_telegram_create_price_alert, chat_id, alert_request)
            _telegram_audit(chat_id, "alert_created", raw, alert)
            await notifier.send_telegram_message(
                chat_id,
                "สร้าง price alert แล้วครับ\n"
                f"- ID: {alert['id']}\n"
                f"- Symbol: {alert['symbol']}\n"
                f"- Condition: {alert['condition']}\n"
                f"- Price: {alert['price']}",
                reply_markup=_telegram_keyboard(),
            )
        except Exception as exc:
            await notifier.send_telegram_message(chat_id, f"สร้าง alert ไม่สำเร็จ: {exc}")
        return
    if command == "/trade":
        await _telegram_execute_trade_command(chat_id, raw)
        return
    if command == "/paperscan":
        await _telegram_run_paper_scan(chat_id)
        return

    if command == "/signals":
        symbols = ["BTC", "ETH", "GOLD", "EURUSD"]
        try:
            signals = await asyncio.to_thread(lambda: crypto_intel.get_quick_signals(symbols, timeframe="15m")) if INTELLIGENCE_AVAILABLE and crypto_intel else []
            if not signals:
                await notifier.send_telegram_message(chat_id, "No signals available right now.", reply_markup=_telegram_keyboard())
                return
            lines = ["Latest AI signals"]
            for item in signals[:6]:
                lines.append(
                    f"- {item.get('symbol')}: {item.get('candidate_direction') or item.get('direction')} "
                    f"prob={item.get('ml_win_prob')} tradeable={item.get('tradeable')}"
                )
            await notifier.send_telegram_message(chat_id, "\n".join(lines), reply_markup=_telegram_keyboard())
        except Exception as exc:
            await notifier.send_telegram_message(chat_id, f"Signal fetch failed: {exc}")
        return

    if command == "/signal" or any(token in lower for token in ("btc", "eth", "gold", "xau", "eurusd", "signal", "วิเคราะห์")):
        parts = raw.split()
        symbol = parts[1].upper().strip() if command == "/signal" and len(parts) > 1 else _telegram_extract_symbol(raw)
        try:
            from intelligence.tools.market_tools import get_trading_tactics
            setup = await asyncio.to_thread(get_trading_tactics, symbol)
            try:
                await asyncio.to_thread(_record_signal_snapshot, setup, "telegram_signal", "15m")
            except Exception as snap_exc:
                logger.debug(f"Telegram signal snapshot skipped: {snap_exc}")
            await notifier.send_telegram_message(chat_id, _telegram_format_signal(symbol, setup), reply_markup=_telegram_keyboard())
        except Exception as exc:
            await notifier.send_telegram_message(chat_id, f"Analysis failed for {symbol}: {exc}")
        return

    reply = await _telegram_finance_agent_answer(raw, chat_id)
    await notifier.send_telegram_message(chat_id, reply, reply_markup=_telegram_keyboard())


async def _telegram_handle_update(update: dict) -> None:
    callback = update.get("callback_query") or {}
    if callback:
        callback_id = callback.get("id")
        data = str(callback.get("data") or "")
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id") or "")
        if callback_id:
            await notifier.answer_callback_query(callback_id, "Working...")
        if not notifier.is_chat_allowed(chat_id):
            await notifier.send_telegram_message(chat_id, "This chat is not authorized.")
            return
        if data.startswith("tg:trade_confirm:"):
            confirmation_id = data.rsplit(":", 1)[-1]
            await _telegram_confirm_trade(chat_id, confirmation_id)
            return
        if data.startswith("tg:trade_cancel:"):
            confirmation_id = data.rsplit(":", 1)[-1]
            await _telegram_cancel_trade(chat_id, confirmation_id)
            return
        if data.startswith("tg:why_blocked:"):
            confirmation_id = data.rsplit(":", 1)[-1]
            await notifier.send_telegram_message(
                chat_id,
                await asyncio.to_thread(_telegram_format_blocked_detail, confirmation_id),
                reply_markup=_telegram_blocked_trade_keyboard(confirmation_id),
            )
            return
        if data.startswith("tg:paper_trade:"):
            confirmation_id = data.rsplit(":", 1)[-1]
            await _telegram_open_paper_from_confirmation(chat_id, confirmation_id)
            return
        if data == "tg:paper_scan":
            await _telegram_run_paper_scan(chat_id)
            return
        if data == "tg:best_explain":
            await notifier.send_telegram_message(
                chat_id,
                await asyncio.to_thread(_telegram_format_best_explain, chat_id),
                reply_markup=_telegram_best_feedback_keyboard(chat_id),
            )
            return
        if data == "tg:no_trade":
            await notifier.send_telegram_message(
                chat_id,
                await asyncio.to_thread(_telegram_format_no_trade_reason, chat_id),
                reply_markup=_telegram_best_feedback_keyboard(chat_id),
            )
            return
        if data == "tg:best_metrics":
            await notifier.send_telegram_message(
                chat_id,
                await asyncio.to_thread(_telegram_format_best_metrics),
                reply_markup=_telegram_best_feedback_keyboard(chat_id),
            )
            return
        if data == "tg:risk_guard":
            await notifier.send_telegram_message(
                chat_id,
                await asyncio.to_thread(_telegram_format_risk_guard, chat_id),
                reply_markup=_telegram_best_feedback_keyboard(chat_id),
            )
            return
        if data == "tg:best_alert":
            try:
                created = await asyncio.to_thread(_telegram_create_best_entry_alert, chat_id)
                warning = ""
                if created.get("no_trade"):
                    warning = f"\n\nNote: current mode is NO TRADE ({created.get('no_trade_reason')}). This alert is for watching, not auto-entry."
                await notifier.send_telegram_message(
                    chat_id,
                    "Entry alert created.\n"
                    f"- ID: {created.get('id')}\n"
                    f"- Setup: {created.get('symbol')} {created.get('side')}\n"
                    f"- Trigger: {created.get('condition')} {created.get('price')}\n"
                    f"- Decision: {created.get('decision')}"
                    f"{warning}",
                    reply_markup=_telegram_keyboard(),
                )
            except Exception as exc:
                await notifier.send_telegram_message(chat_id, f"Entry alert failed: {exc}", reply_markup=_telegram_keyboard())
            return
        if data == "tg:best_confirm_alert":
            try:
                created = await asyncio.to_thread(_telegram_create_best_confirmation_alert, chat_id)
                warning = ""
                if created.get("no_trade"):
                    warning = f"\n\nNote: current mode is NO TRADE ({created.get('no_trade_reason')}). This alert is for confirmation watch only."
                await notifier.send_telegram_message(
                    chat_id,
                    "Confirmation alert created.\n"
                    f"- ID: {created.get('id')}\n"
                    f"- Setup: {created.get('symbol')} {created.get('side')}\n"
                    f"- Trigger: {created.get('condition')} {created.get('price')}\n"
                    f"- Decision: {created.get('decision')}\n"
                    "- When it fires, re-check momentum, spread, RR, and risk guard before entry."
                    f"{warning}",
                    reply_markup=_telegram_keyboard(),
                )
            except Exception as exc:
                await notifier.send_telegram_message(chat_id, f"Confirmation alert failed: {exc}", reply_markup=_telegram_keyboard())
            return
        if data.startswith("tg:setup_fb:"):
            parts = data.split(":")
            rating = parts[2] if len(parts) > 2 else "UNKNOWN"
            symbol = parts[3] if len(parts) > 3 else "NA"
            side = parts[4] if len(parts) > 4 else "NA"
            try:
                saved = await asyncio.to_thread(_telegram_save_setup_feedback, chat_id, rating, symbol, side)
                _best_setup_cache.clear()
                _telegram_audit(chat_id, "setup_feedback", data, saved)
                await notifier.send_telegram_message(
                    chat_id,
                    "Feedback saved.\n"
                    f"- Setup: {symbol} {side}\n"
                    f"- Rating: {rating}\n\n"
                    "I will use this to improve future ranking and annotation quality.",
                    reply_markup=_telegram_keyboard(),
                )
            except Exception as exc:
                await notifier.send_telegram_message(chat_id, f"Feedback failed: {exc}", reply_markup=_telegram_keyboard())
            return
        command_map = {
            "tg:status": "/status",
            "tg:best": "/best",
            "tg:bestalt": "/bestalt",
            "tg:openbestpaper": "/openbestpaper",
            "tg:signals": "/signals",
            "tg:mt5": "/mt5",
            "tg:paper": "/paper",
            "tg:rag": "/rag",
            "tg:graph": "/graph",
            "tg:profile": "/profile",
            "tg:help": "/help",
        }
        await _telegram_reply_for_text(chat_id, command_map.get(data, "/help"))
        return

    message = update.get("message") or update.get("edited_message") or {}
    chat = message.get("chat") or {}
    chat_id = str(chat.get("id") or "")
    text = str(message.get("text") or "").strip()
    if not chat_id or not text:
        return
    if not notifier.is_chat_allowed(chat_id):
        await notifier.send_telegram_message(chat_id, "This chat is not authorized.")
        return
    _telegram_audit(chat_id, "message_received", text, user=message.get("from") or {})
    await _telegram_reply_for_text(chat_id, text, user=message.get("from") or {})


async def telegram_bot_poller_task():
    """Receive Telegram user commands and route them into the existing AI stack."""
    enabled = str(os.getenv("TELEGRAM_BOT_POLLING_ENABLED", "1")).strip().lower() not in {"0", "false", "no", "off"}
    status = notifier.telegram_status()
    if not enabled:
        logger.info("Telegram bot polling disabled by TELEGRAM_BOT_POLLING_ENABLED=0")
        return
    if not status.get("polling_ready"):
        logger.info("Telegram bot polling skipped: token or allowed chat id is missing")
        return

    await asyncio.sleep(6)
    await notifier.delete_webhook()
    logger.info("Telegram bot poller started.")

    while True:
        try:
            updates = await notifier.get_updates(timeout=20, limit=20)
            for update in updates:
                await _telegram_handle_update(update)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(f"Telegram bot poller error: {exc}")
            await asyncio.sleep(5)


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
                    "bridge_connected": acc_info.get("bridge_connected"),
                    "bridge_live_trading_enabled": acc_info.get("bridge_live_trading_enabled"),
                    "bridge_url": acc_info.get("bridge_url"),
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
    from intelligence.constants import YFINANCE_DISABLED_TICKERS
    
    poll_mapping = {
        sym: ticker
        for sym, ticker in MACRO_MAPPING.items()
        if ticker not in YFINANCE_DISABLED_TICKERS and not str(ticker).endswith("-USD")
    }
    tickers = list(dict.fromkeys(poll_mapping.values()))
    
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
                for sym, ticker in poll_mapping.items():
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
                            except Exception as e_fast:
                                logger.warning(f"fast_info failed for {ticker}: {e_fast} — trying history fallback")
                                # Deep fallback: try current price from history
                                try:
                                    hist = t_obj.history(period="5d")
                                    if not hist.empty:
                                        price = float(hist['Close'].iloc[-1])
                                        prev_close = float(hist['Close'].iloc[-2]) if len(hist) > 1 else price
                                        delta = ((price - prev_close) / (prev_close if prev_close != 0 else 1)) * 100
                                except Exception as e_hist:
                                    logger.warning(f"All price lookups failed for {ticker}: {e_hist} — skipping ticker")
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
_kafka_decode_skip_counts: dict[str, int] = {}


def _decode_kafka_json(value: bytes, topic: str) -> dict | None:
    try:
        return json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _kafka_decode_skip_counts[topic] = _kafka_decode_skip_counts.get(topic, 0) + 1
        count = _kafka_decode_skip_counts[topic]
        if count <= 5 or count % 100000 == 0:
            logger.warning(f"Kafka {topic}: skipped malformed message #{count} ({exc})")
    return None


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
            data = _decode_kafka_json(msg.value, "trade_stream")
            if data is None:
                continue
            
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
        except Exception as e:
            logger.warning(f"Kafka trade consumer stop failed: {e}")

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
            data = _decode_kafka_json(msg.value, "trade_stream_dlq")
            if data is None:
                continue
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
        except Exception as e:
            logger.warning(f"Kafka DLQ consumer stop failed: {e}")

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
            "market_regime": _current_market_regime(),
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
    timeframe: str = "1h"
    order_kind: str = "MARKET"
    filling_policy: str = "IOC"
    deviation: int = 20
    comment: str = "CryptoStream AI Trade"

class MT5CloseRequest(BaseModel):
    ticket: int

@app.get("/api/mt5/quote")
def mt5_quote(symbol: str = "GOLD", x_api_key: str = Header(None)):
    verify_token(x_api_key)
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
def mt5_account(x_api_key: str = Header(None)):
    verify_token(x_api_key)
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
def mt5_positions(x_api_key: str = Header(None)):
    verify_token(x_api_key)
    try:
        from intelligence.mt5_connector import get_mt5_positions
        return {"positions": get_mt5_positions()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/mt5/preflight")
async def mt5_preflight(req: MT5TradeRequest, x_api_key: str = Header(None)):
    """Check whether a live MT5 order would be allowed before sending it."""
    verify_token(x_api_key)

    def _run():
        from intelligence.ml.readiness import live_execution_gate
        from intelligence.mt5_connector import (
            initialize_mt5,
            resolve_broker_symbol,
            validate_live_order_request,
        )

        basic = validate_live_order_request(
            req.symbol,
            req.side,
            req.volume,
            sl=req.sl,
            tp=req.tp,
            price=req.price,
        )
        graph_guard = _trade_graph_guard(req.symbol, req.side)
        mt5_connected = initialize_mt5()
        resolution = resolve_broker_symbol(req.symbol) if mt5_connected and basic["passed"] else None
        ready, readiness = live_execution_gate({"symbol": req.symbol, "timeframe": req.timeframe})
        return {
            "ready_for_live_order": bool(
                basic["passed"]
                and graph_guard.get("allowed", True)
                and mt5_connected
                and ready
                and resolution
                and resolution.get("status") == "SUCCESS"
            ),
            "preflight": basic,
            "graph_guard": graph_guard,
            "mt5_connected": mt5_connected,
            "symbol_resolution": resolution,
            "readiness_passed": bool(ready),
            "readiness": {
                "passed": bool(readiness.get("passed")),
                "blockers": readiness.get("blockers", []),
                "thresholds": readiness.get("thresholds", {}),
                "paper": readiness.get("paper", {}),
                "model": readiness.get("model", {}),
            },
        }

    try:
        return await asyncio.to_thread(_run)
    except Exception as e:
        logger.error(f"MT5 preflight error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/mt5/trade")
async def mt5_execute(req: MT5TradeRequest, x_api_key: str = Header(None)):
    """Send a live market order to MT5."""
    verify_token(x_api_key)
    try:
        _assert_daily_risk_guard_allows("api_live_trade")
        _assert_trade_graph_guard_allows(req.symbol, req.side, "api_live_trade")
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
        if result.get("status") != "SUCCESS":
            raise HTTPException(status_code=409, detail=result)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"MT5 trade error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/mt5/close")
async def mt5_close_position(req: MT5CloseRequest, x_api_key: str = Header(None)):
    """Close a specific MT5 position by ticket."""
    verify_token(x_api_key)
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


class KnowledgeIngestRequest(BaseModel):
    source_uri: str
    content: str
    title: str | None = None
    source_type: str = "text"
    tenant_id: str = "public"
    metadata: Dict[str, Any] | None = None


class KnowledgeRetrieveRequest(BaseModel):
    query: str
    limit: int = 5
    source_type: str | None = None
    min_similarity: float = 0.0
    tenant_id: str = "public"
    user_id: str | None = None
    experiment_id: str | None = None
    experiment_arm: str | None = None
    rerank: bool = True


class KnowledgeFeedbackRequest(BaseModel):
    retrieval_id: str | None = None
    rating: str
    useful: bool | None = None
    query: str | None = None
    selected_citation: str | None = None
    comment: str | None = None
    expected_answer: str | None = None
    metadata: Dict[str, Any] | None = None


class DataAnomalyRequest(BaseModel):
    symbol: str | None = None
    severity: str | None = None
    hours: int = 24
    limit: int = 20


class DataAnomalySummaryRequest(BaseModel):
    hours: int = 24


class HistoricalRankingRefreshRequest(BaseModel):
    years: list[int] = [1, 3, 5, 10]
    full_window_only: bool = True

# Root removed to avoid double-definition conflict with SPA routing at bottom


@app.post("/api/rag/ingest")
def rag_ingest(req: KnowledgeIngestRequest, x_api_key: str = Header(None)):
    verify_token(x_api_key)
    from intelligence.rag import ingest_knowledge_document

    result = ingest_knowledge_document(
        source_uri=req.source_uri,
        content=req.content,
        title=req.title,
        source_type=req.source_type,
        metadata={**(req.metadata or {}), "tenant_id": req.tenant_id},
    )
    if result.get("status") == "ERROR":
        raise HTTPException(status_code=400, detail=result)
    return result


@app.post("/api/rag/retrieve")
def rag_retrieve(req: KnowledgeRetrieveRequest, x_api_key: str = Header(None)):
    verify_token(x_api_key)
    from intelligence.rag import retrieve_knowledge_context

    result = retrieve_knowledge_context(
        query=req.query,
        limit=req.limit,
        source_type=req.source_type,
        min_similarity=req.min_similarity,
        tenant_id=req.tenant_id,
        user_id=req.user_id,
        experiment_id=req.experiment_id or "rag_hybrid_rerank_v1",
        experiment_arm=req.experiment_arm,
        rerank=req.rerank,
    )
    if result.get("status") == "ERROR":
        raise HTTPException(status_code=400, detail=result)
    return result


@app.post("/api/rag/feedback")
def rag_feedback(req: KnowledgeFeedbackRequest, x_api_key: str = Header(None)):
    verify_token(x_api_key)
    from intelligence.rag import record_knowledge_feedback

    result = record_knowledge_feedback(
        retrieval_id=req.retrieval_id,
        rating=req.rating,
        useful=req.useful,
        query=req.query,
        selected_citation=req.selected_citation,
        comment=req.comment,
        expected_answer=req.expected_answer,
        metadata={**(req.metadata or {}), "source": "api"},
    )
    if result.get("status") == "ERROR":
        raise HTTPException(status_code=400, detail=result)
    return result


@app.get("/api/rag/feedback/stats")
def rag_feedback_stats(limit: int = 20, x_api_key: str = Header(None)):
    verify_token(x_api_key)
    from intelligence.rag import get_knowledge_feedback_stats

    result = get_knowledge_feedback_stats(limit=limit)
    if result.get("status") == "ERROR":
        raise HTTPException(status_code=400, detail=result)
    return result


@app.get("/api/rag/observability")
def rag_observability(limit: int = 50, tenant_id: str = "public", x_api_key: str = Header(None)):
    verify_token(x_api_key)
    from intelligence.rag import get_knowledge_observability

    result = get_knowledge_observability(limit=limit, tenant_id=tenant_id)
    if result.get("status") == "ERROR":
        raise HTTPException(status_code=400, detail=result)
    return result




@app.get("/metrics", response_class=PlainTextResponse)
def _metric_label(value: Any) -> str:
    return _helper_metric_label(value)


def _metric_number(value: Any) -> float:
    return _helper_metric_number(value)


def prometheus_metrics():
    """Expose app-level metrics for Prometheus without leaking secrets."""
    from intelligence.rag import get_knowledge_feedback_stats, get_knowledge_observability, get_knowledge_stats

    tenants = [
        _metric_label(tenant.strip())
        for tenant in os.getenv("RAG_METRICS_TENANTS", "public").split(",")
        if tenant.strip()
    ] or ["public"]
    lines = [
        "# HELP cryptostream_rag_retrievals_total Total RAG retrieval events recorded in PostgreSQL.",
        "# TYPE cryptostream_rag_retrievals_total counter",
        "# HELP cryptostream_rag_latency_avg_ms Average RAG retrieval latency in milliseconds.",
        "# TYPE cryptostream_rag_latency_avg_ms gauge",
        "# HELP cryptostream_rag_latency_p95_ms P95 RAG retrieval latency in milliseconds.",
        "# TYPE cryptostream_rag_latency_p95_ms gauge",
        "# HELP cryptostream_rag_estimated_cost_usd_total Estimated cumulative embedding cost in USD.",
        "# TYPE cryptostream_rag_estimated_cost_usd_total counter",
        "# HELP cryptostream_rag_tokens_total Total RAG query plus returned context tokens.",
        "# TYPE cryptostream_rag_tokens_total counter",
        "# HELP cryptostream_rag_annotation_queue_items Retrievals currently visible in the annotation queue.",
        "# TYPE cryptostream_rag_annotation_queue_items gauge",
        "# HELP cryptostream_rag_query_embedding_cache_hit_ratio Share of retrievals served with cached query embeddings.",
        "# TYPE cryptostream_rag_query_embedding_cache_hit_ratio gauge",
        "# HELP cryptostream_rag_feedback_negative_ratio Share of feedback marked negative.",
        "# TYPE cryptostream_rag_feedback_negative_ratio gauge",
        "# HELP cryptostream_rag_documents_total Total documents in the RAG corpus.",
        "# TYPE cryptostream_rag_documents_total gauge",
        "# HELP cryptostream_rag_chunks_total Total chunks in the RAG corpus.",
        "# TYPE cryptostream_rag_chunks_total gauge",
        "# HELP cryptostream_rag_embedded_chunks_total Total chunks with embeddings.",
        "# TYPE cryptostream_rag_embedded_chunks_total gauge",
    ]

    try:
        stats = get_knowledge_stats()
    except Exception as exc:
        logger.warning(f"RAG metrics stats unavailable: {exc}")
        stats = {"status": "ERROR"}
    if stats.get("status") == "SUCCESS":
        lines.append(f"cryptostream_rag_documents_total {_metric_number(stats.get('documents'))}")
        lines.append(f"cryptostream_rag_chunks_total {_metric_number(stats.get('chunks'))}")
        lines.append(f"cryptostream_rag_embedded_chunks_total {_metric_number(stats.get('embedded_chunks'))}")

    try:
        feedback = get_knowledge_feedback_stats(limit=1)
    except Exception as exc:
        logger.warning(f"RAG feedback metrics unavailable: {exc}")
        feedback = {"status": "ERROR"}
    if feedback.get("status") == "SUCCESS":
        total_feedback = _metric_number(feedback.get("feedback_count"))
        negative_feedback = _metric_number(feedback.get("negative_count"))
        negative_ratio = negative_feedback / total_feedback if total_feedback else 0.0
        lines.append(f"cryptostream_rag_feedback_negative_ratio {negative_ratio:.6f}")

    for tenant_id in tenants:
        try:
            obs = get_knowledge_observability(limit=50, tenant_id=tenant_id)
        except Exception as exc:
            logger.warning(f"RAG observability metrics unavailable for {tenant_id}: {exc}")
            continue
        if obs.get("status") != "SUCCESS":
            continue
        summary = obs.get("summary") or {}
        label = f'tenant_id="{tenant_id}"'
        lines.append(f"cryptostream_rag_retrievals_total{{{label}}} {_metric_number(summary.get('retrieval_count'))}")
        lines.append(f"cryptostream_rag_latency_avg_ms{{{label}}} {_metric_number(summary.get('avg_latency_ms'))}")
        lines.append(f"cryptostream_rag_latency_p95_ms{{{label}}} {_metric_number(summary.get('p95_latency_ms'))}")
        lines.append(
            f"cryptostream_rag_estimated_cost_usd_total{{{label}}} "
            f"{_metric_number(summary.get('estimated_cost_usd')):.8f}"
        )
        lines.append(f"cryptostream_rag_tokens_total{{{label}}} {_metric_number(summary.get('total_tokens'))}")
        retrieval_count = _metric_number(summary.get("retrieval_count"))
        cache_hits = _metric_number(summary.get("query_cache_hits"))
        cache_hit_ratio = cache_hits / retrieval_count if retrieval_count else 0.0
        lines.append(f"cryptostream_rag_query_embedding_cache_hit_ratio{{{label}}} {cache_hit_ratio:.6f}")
        lines.append(
            f"cryptostream_rag_annotation_queue_items{{{label}}} "
            f"{len(obs.get('annotation_queue') or [])}"
        )

        for arm in obs.get("by_experiment") or []:
            arm_label = f'tenant_id="{tenant_id}",arm="{_metric_label(arm.get("arm"))}"'
            lines.append(
                f"cryptostream_rag_experiment_retrievals_total{{{arm_label}}} "
                f"{_metric_number(arm.get('retrieval_count'))}"
            )
            lines.append(
                f"cryptostream_rag_experiment_latency_avg_ms{{{arm_label}}} "
                f"{_metric_number(arm.get('avg_latency_ms'))}"
            )
            lines.append(
                f"cryptostream_rag_experiment_estimated_cost_usd_total{{{arm_label}}} "
                f"{_metric_number(arm.get('estimated_cost_usd')):.8f}"
            )

    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


@app.post("/api/anomalies/recent")
def recent_data_anomalies(req: DataAnomalyRequest, x_api_key: str = Header(None)):
    verify_token(x_api_key)
    from intelligence.tools.market_tools import get_data_anomalies

    result = get_data_anomalies(
        symbol=req.symbol,
        severity=req.severity,
        hours=req.hours,
        limit=req.limit,
    )
    if result.get("status") == "ERROR":
        raise HTTPException(status_code=400, detail=result)
    return result


@app.post("/api/anomalies/summary")
def data_anomaly_summary(req: DataAnomalySummaryRequest, x_api_key: str = Header(None)):
    verify_token(x_api_key)
    from intelligence.tools.market_tools import get_data_anomaly_summary

    result = get_data_anomaly_summary(hours=req.hours)
    if result.get("status") == "ERROR":
        raise HTTPException(status_code=400, detail=result)
    return result


@app.get("/api/historical-rankings")
def get_historical_rankings(
    years: int = 10,
    direction: str = "top",
    limit: int = 10,
    universe: str = "COMBINED",
    full_window_only: bool = True,
    x_api_key: str = Header(None),
):
    verify_token(x_api_key)
    from intelligence.tools.market_tools import get_historical_stock_rankings

    result = get_historical_stock_rankings(
        years=years,
        direction=direction,
        limit=limit,
        universe=universe,
        full_window_only=full_window_only,
    )
    if result.get("status") == "ERROR":
        raise HTTPException(status_code=400, detail=result)
    return result


@app.post("/api/historical-rankings/refresh")
def refresh_historical_rankings(req: HistoricalRankingRefreshRequest, x_api_key: str = Header(None)):
    verify_token(x_api_key)
    from intelligence.tools.market_tools import refresh_historical_stock_rankings

    result = refresh_historical_stock_rankings(
        years_list=req.years,
        full_window_only=req.full_window_only,
    )
    if result.get("status") == "ERROR":
        raise HTTPException(status_code=400, detail=result)
    return result


@app.get("/api/system/market-status")
def get_market_status():
    """Returns real-time status (OPEN/CLOSED) and countdowns for major markets."""
    from intelligence.utils.market_hours import get_market_status_data
    return get_market_status_data()


# ── Security ─────────────────────────────────────────────────────────────────
from fastapi import Header

# Concurrent Gemini request guard — prevent queue buildup under heavy load
_GEMINI_SEMAPHORE = asyncio.Semaphore(5)  # max 5 simultaneous AI calls

def verify_token(
    x_api_key: str = Header(None),
    *,
    detail: str = "Unauthorized",
    status_code: int = 403,
):
    """Validate API key. Demo access is opt-in and limited to development-style environments."""
    valid_keys = {APP_API_KEY} if APP_API_KEY else set()
    if ALLOW_DEMO_API_KEY:
        valid_keys.add("demo")
    if x_api_key not in valid_keys:
        logger.warning(f"Unauthorized access attempt — key: {str(x_api_key)[:8]}...")
        raise HTTPException(status_code=status_code, detail=detail)


def require_request_api_key(
    request: Request,
    *,
    detail: str = "Invalid API Key",
    status_code: int = 403,
):
    verify_token(
        request.headers.get("X-API-Key"),
        detail=detail,
        status_code=status_code,
    )

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

        async def _stream_historical_stock_rankings(
            years: int,
            direction: str,
            universe: str,
            limit: int = 10,
            full_window_only: bool = True,
        ):
            yield json.dumps({
                "type": "tool_call",
                "tool": "get_historical_stock_rankings",
                "years": years,
                "direction": direction,
                "limit": limit,
                "universe": universe,
            }) + "\n"
            yield json.dumps({
                "type": "status",
                "content": f"กำลังดึงข้อมูลหุ้นที่มีผลตอบแทนสูงสุดในช่วง {years} ปีที่ผ่านมาให้คุณนะครับ โปรดรอสักครู่"
            }) + "\n"

            try:
                from intelligence.tools.market_tools import get_historical_stock_rankings
                ranking_out = await asyncio.wait_for(
                    asyncio.to_thread(
                        get_historical_stock_rankings,
                        years,
                        direction,
                        limit,
                        universe,
                        full_window_only,
                    ),
                    timeout=90.0,
                )
            except asyncio.TimeoutError:
                ranking_out = {
                    "status": "ERROR",
                    "years": years,
                    "direction": direction,
                    "universe": universe,
                    "full_window_only": bool(full_window_only),
                    "error": "historical ranking request timed out",
                }
            except Exception as ranking_exc:
                ranking_out = {
                    "status": "ERROR",
                    "years": years,
                    "direction": direction,
                    "universe": universe,
                    "full_window_only": bool(full_window_only),
                    "error": str(ranking_exc),
                }

            yield json.dumps({
                "type": "metadata",
                "sql_query": None,
                "has_data": ranking_out.get("status") == "SUCCESS",
                "intent": "GENERAL",
                "tv_symbol": None,
                "tv_symbols": [],
            }) + "\n"
            yield json.dumps({
                "type": "chunk",
                "content": _format_historical_stock_rankings(ranking_out, req.language),
            }) + "\n"
            yield json.dumps({"type": "done", "intent": "GENERAL", "tvSymbol": None}) + "\n"

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

        async def _retry_plain_language_answer(extra_instruction: str) -> str:
            retry_contents = list(history_contents) + [
                types.Content(role="user", parts=[types.Part(text=extra_instruction)])
            ]
            try:
                retry_res = await asyncio.wait_for(
                    client.aio.models.generate_content(
                        model=MODEL_ID,
                        contents=retry_contents,
                        config=types.GenerateContentConfig(
                            system_instruction=agent_system_prompt,
                            thinking_config=types.ThinkingConfig(thinking_budget=0),
                        ),
                    ),
                    timeout=20.0,
                )
                return (retry_res.text or "").strip()
            except Exception as retry_exc:
                logger.warning(f"Plain-language retry failed: {retry_exc}")
                return ""

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

        user_lower = user_input.lower()
        READINESS_KEYWORDS = [
            "100%",
            "readiness",
            "system status",
            "system health",
            "ready for users",
            "all systems",
            "connected all systems",
            "พร้อม 100",
            "พร้อมไหม",
            "พร้อมใช้งาน",
            "พร้อมตอบ",
            "ทุกระบบ",
            "เชื่อมต่อทุกระบบ",
            "ใช้งานจริง",
            "production ready",
        ]
        if any(keyword in user_lower for keyword in READINESS_KEYWORDS):
            yield json.dumps({"type": "tool_call", "tool": "get_system_readiness", "symbol": "System"}) + "\n"
            readiness = await asyncio.to_thread(build_system_readiness)
            yield json.dumps({
                "type": "metadata",
                "sql_query": None,
                "has_data": readiness.get("ready_for_users", False),
                "intent": "GENERAL",
                "tv_symbol": None,
                "tv_symbols": [],
                "readiness": {
                    "overall_percent": readiness.get("overall_percent"),
                    "ready_for_users": readiness.get("ready_for_users"),
                    "ready_for_notifications": readiness.get("ready_for_notifications"),
                    "ready_for_live_trading": readiness.get("ready_for_live_trading"),
                },
            }) + "\n"
            yield json.dumps({"type": "chunk", "content": format_readiness_for_chat(readiness)}) + "\n"
            yield json.dumps({"type": "done", "intent": "GENERAL", "tvSymbol": None}) + "\n"
            return

        if _is_capability_question(user_input) and (
            _is_stock_top_performer_history_question(user_input) or _is_ranked_stock_history_query(user_input)
        ):
            capability_reply = (
                "ได้ครับ ผมตอบได้ โดยในโหมดนี้ผมสามารถจัดอันดับหุ้นที่ผลตอบแทนดีที่สุดหรือแย่ที่สุดย้อนหลัง 10 ปีจากกลุ่มหุ้นสหรัฐที่ระบบติดตามอยู่ได้ "
                "ถ้าต้องการให้ดึงเลย พิมพ์ว่า 'จัดอันดับหุ้น 10 ตัวแรกที่ขึ้นมากที่สุดใน 10 ปี' หรือ 'จัดอันดับหุ้น 10 ตัวแรกที่ลงมากที่สุดใน 10 ปี' และระบุเพิ่มได้ว่าต้องการเฉพาะ NASDAQ 100, S&P 500 หรือรวมทั้งสองกลุ่มครับ"
                if req.language != "en"
                else "Yes — I can do that. In this mode I can rank the best-performing stocks over the last 10 years from the US stock universe the system tracks. "
                     "If you want me to fetch it now, say 'Rank the top 10 stocks with the biggest gains over the last 10 years' and optionally specify NASDAQ 100, S&P 500, or both."
            )
            yield json.dumps({
                "type": "metadata",
                "sql_query": None,
                "has_data": True,
                "intent": "GENERAL",
                "tv_symbol": None,
                "tv_symbols": [],
            }) + "\n"
            yield json.dumps({"type": "chunk", "content": capability_reply}) + "\n"
            yield json.dumps({"type": "done", "intent": "GENERAL", "tvSymbol": None}) + "\n"
            return

        if _is_explicit_stock_ranking_request(user_input) and not _is_capability_question(user_input):
            requested_years = _extract_historical_years(user_input, default=10)
            requested_direction = _extract_stock_history_direction(user_input)
            requested_universe = _extract_stock_history_universe(user_input)
            async for chunk in _stream_historical_stock_rankings(
                requested_years,
                requested_direction,
                requested_universe,
                10,
                True,
            ):
                yield chunk
            return

        if (
            _is_stock_top_performer_history_question(user_input) or _is_ranked_stock_history_query(user_input)
        ) and not _is_capability_question(user_input):
            requested_years = _extract_historical_years(user_input, default=10)
            requested_direction = _extract_stock_history_direction(user_input)
            requested_universe = _extract_stock_history_universe(user_input)
            async for chunk in _stream_historical_stock_rankings(
                requested_years,
                requested_direction,
                requested_universe,
                10,
                True,
            ):
                yield chunk
            return

        historical_index_terms = [
            "ย้อนหลัง", "ที่ผ่านมา", "historical", "history", "last ", "over the last", "10 ปี", "5 ปี", "3 ปี", "1 ปี", "10ปี", "5ปี", "3ปี", "1ปี",
            "year", "years", "decade", "performance", "return", "ภาพรวม",
        ]
        conceptual_index_stop_terms = [
            "what is", "คืออะไร", "อธิบาย", "explain", "how it works", "how does", "ทำงานยังไง",
        ]
        requested_indices = _extract_index_history_targets(user_input)
        requested_years = _extract_historical_years(user_input, default=10)
        broad_stock_history_query = _is_broad_stock_history_query(user_input)
        if broad_stock_history_query and not requested_indices:
            requested_indices = ["NASDAQ_100", "SP500", "NASDAQ_COMPOSITE"]
        historical_index_trigger = (
            bool(requested_indices)
            and not any(term in user_lower for term in conceptual_index_stop_terms)
            and (
                any(term in user_lower for term in historical_index_terms)
                or broad_stock_history_query
                or len(requested_indices) >= 2
            )
        )
        if historical_index_trigger:
            yield json.dumps({
                "type": "tool_call",
                "tool": "get_index_historical_summary",
                "years": requested_years,
                "indices": requested_indices,
            }) + "\n"
            hist_out = await asyncio.to_thread(
                _get_index_historical_summary_fast,
                requested_years,
                requested_indices,
            )
            yield json.dumps({
                "type": "metadata",
                "sql_query": None,
                "has_data": hist_out.get("status") == "SUCCESS",
                "intent": "GENERAL",
                "tv_symbol": None,
                "tv_symbols": [],
            }) + "\n"
            yield json.dumps({
                "type": "chunk",
                "content": _format_index_historical_summary(hist_out, req.language),
            }) + "\n"
            yield json.dumps({"type": "done", "intent": "GENERAL", "tvSymbol": None}) + "\n"
            return

        news_watch_terms = [
            "แจ้งฉัน", "แจ้งเตือน", "เตือนฉัน", "แจ้งด้วย", "ส่งเข้า telegram",
            "notify me", "alert me", "let me know", "send to telegram",
        ]
        news_subject_terms = [
            "ข่าว", "headline", "breaking news", "big news", "news",
        ]
        if any(term in user_lower for term in news_watch_terms) and any(term in user_lower for term in news_subject_terms):
            watch_symbol = _extract_news_watch_symbol(user_input, default="BTC")
            if watch_symbol == "XAU":
                watch_symbol = "GOLD"
            try:
                created = await asyncio.to_thread(_create_news_watch_alert, watch_symbol, user_input, req.language)
            except Exception as exc:
                logger.warning(f"Unable to create chat news watcher: {exc}")
                message = (
                    "I understood the request, but saving the news watcher failed. Please try again in a moment."
                    if req.language == "en"
                    else "ผมเข้าใจคำสั่งแล้ว แต่บันทึก news watcher ไม่สำเร็จครับ ลองอีกครั้งในอีกสักครู่ได้เลย"
                )
                yield json.dumps({"type": "metadata", "sql_query": None, "has_data": False, "intent": "GENERAL", "tv_symbol": None, "tv_symbols": []}) + "\n"
                yield json.dumps({"type": "chunk", "content": message}) + "\n"
                yield json.dumps({"type": "done", "intent": "GENERAL", "tvSymbol": None}) + "\n"
                return
            tg_status = notifier.telegram_status()
            already_active = created.get("status") == "exists"
            if req.language == "en":
                if tg_status.get("configured"):
                    reply = (
                        f"News watcher is {'already active' if already_active else 'active'} for {watch_symbol}. "
                        "When a high-impact headline appears, I will send it to your configured Telegram chat automatically."
                    )
                else:
                    missing = ", ".join(tg_status.get("missing") or [])
                    reply = (
                        f"I created the news watcher for {watch_symbol}, but Telegram is not ready yet "
                        f"because {missing} is missing in the running process."
                    )
            else:
                if tg_status.get("configured"):
                    reply = (
                        (f"มี news watcher ของ {watch_symbol} อยู่แล้วครับ " if already_active else f"เปิด news watcher ให้ {watch_symbol} แล้วครับ ")
                        + "ถ้ามีข่าวแรงหรือ headline สำคัญเข้ามา ระบบจะส่งเข้า Telegram ที่ตั้งค่าไว้ให้อัตโนมัติ"
                    )
                else:
                    missing = ", ".join(tg_status.get("missing") or [])
                    reply = (
                        f"ผมสร้าง news watcher ให้ {watch_symbol} แล้ว แต่ Telegram ของโปรเซสนี้ยังไม่พร้อม "
                        f"เพราะยังไม่เห็นค่า {missing} ตอน runtime ครับ"
                    )

            yield json.dumps({"type": "metadata", "sql_query": None, "has_data": True, "intent": "GENERAL", "tv_symbol": None, "tv_symbols": []}) + "\n"
            yield json.dumps({"type": "chunk", "content": reply}) + "\n"
            yield json.dumps({"type": "done", "intent": "GENERAL", "tvSymbol": None}) + "\n"
            return

        news_query_terms = [
            "ข่าว", "news", "headline", "headlines", "breaking", "latest",
            "ล่าสุด", "เกิดอะไร", "มีอะไรเกิดขึ้น", "ข่าวอะไร", "มีข่าวอะไร",
        ]
        impact_query_terms = [
            "กระทบ", "impact", "affect", "effect", "bias", "sentiment", "มุมมอง", "ข้างไหน",
            "bullish", "bearish", "บวก", "ลบ",
        ]
        broad_asset_news_terms = [
            "crypto", "คริปโต", "bitcoin", "btc", "ethereum", "eth", "gold", "ทอง",
            "nasdaq", "หุ้น", "stock", "oil", "น้ำมัน", "forex", "ค่าเงิน",
        ]
        if any(term in user_lower for term in news_query_terms) and any(term in user_lower for term in broad_asset_news_terms):
            news_symbol = _extract_news_watch_symbol(user_input, default="BTC")
            yield json.dumps({"type": "tool_call", "tool": "get_news_impact", "symbol": news_symbol}) + "\n"
            news_out = await run_agent_tool_async("get_news_impact", {"symbol": news_symbol})
            headlines = list(news_out.get("top_headlines") or [])
            bias_key, sentiment_key = _estimate_news_bias(headlines)
            wants_impact = any(term in user_lower for term in impact_query_terms)

            yield json.dumps({
                "type": "metadata",
                "sql_query": None,
                "has_data": bool(headlines),
                "intent": "GENERAL",
                "tv_symbol": None,
                "tv_symbols": [],
            }) + "\n"

            if req.language == "en":
                if not headlines:
                    content = f"I could not find any fresh high-signal headlines for {news_symbol} right now."
                else:
                    bias_text = {
                        "bullish": "The near-term news tone leans bullish.",
                        "bearish": "The near-term news tone leans bearish.",
                        "mixed": "The near-term news tone is mixed.",
                    }[bias_key]
                    lines = [f"Latest {news_symbol} news:"]
                    lines.extend(f"- {headline}" for headline in headlines[:4])
                    if wants_impact:
                        lines.append("")
                        lines.append(bias_text)
                    content = "\n".join(lines)
            else:
                if not headlines:
                    content = f"ตอนนี้ผมยังไม่เจอ headline ใหม่ที่ชัดพอสำหรับ {news_symbol} ครับ"
                else:
                    bias_text = {
                        "bullish": "โทนข่าวระยะสั้นเอนบวกมากกว่า",
                        "bearish": "โทนข่าวระยะสั้นเอนลบมากกว่า",
                        "mixed": "โทนข่าวระยะสั้นยังคละกันอยู่",
                    }[bias_key]
                    lines = [f"ข่าวล่าสุดของ {news_symbol}:"]
                    lines.extend(f"- {headline}" for headline in headlines[:4])
                    if wants_impact:
                        lines.append("")
                        lines.append(f"ผลกระทบเบื้องต้น: {bias_text}")
                    content = "\n".join(lines)

            yield json.dumps({"type": "chunk", "content": content}) + "\n"
            yield json.dumps({"type": "done", "intent": "GENERAL", "tvSymbol": None}) + "\n"
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


REAL INTEGRATION RULE:
- For system readiness questions, rely on the `get_system_readiness` fast path/API state. Do not guess.
- Live MT5 execution is available ONLY when MT5 tooling returns connected=true and the execute tool returns SUCCESS.
- Telegram is available ONLY when TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are configured and the send tool returns SUCCESS.
- If MT5 or Telegram is not ready, say exactly what is missing. Never claim a trade, ticket, alert, or external action succeeded without tool proof.

USER-FACING OUTPUT RULE:
- Never answer with Python code, pseudo-code, raw function calls, or internal tool syntax.
- Never output examples such as `print(...)`, `get_market_opportunities(...)`, `get_market_analysis(...)`, or `execute_mt5_trade(...)`.
- Use tools internally, then explain the result in plain end-user language only.
- For leaderboard questions such as "top gainers", "strongest this week", "เดือนนี้อะไรขึ้นแรงสุด", or "ตัวไหนเด่นสุด", summarize the actual winners and why they stand out. Do not describe how to call a tool.

QUESTION-FIRST RULE:
- Answer the user's actual question first.
- Do not switch into full technical analysis, trade setup, or price table format unless the user explicitly asks for analysis, entry, setup, signal, TP/SL, chart view, or trade plan.
- If the user asks broad or informational questions (news, concepts, capabilities, macro context, comparisons, process, or "what happened"), answer them directly in normal language.
- If an asset is mentioned casually inside a broader question, do not assume the user wants chart analysis.

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

RULE #7: AUTONOMOUS AUTHORITY WITH HARD SAFETY — If the user gives a clear order (e.g., "จัดเลย", "0.01 lot", "ลุยเลย"), call `execute_mt5_trade` based on the MOST RECENT plan only when Symbol, Side, Volume, Entry/SL/TP are known. The tool must pass MT5 preflight, live bridge readiness, and ML/paper-trade readiness. If the tool returns BLOCKED/GUARD_BLOCKED/ERROR, report the blocker and do not claim execution.

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
  5. CALL THE TOOL `execute_mt5_trade(symbol, side, volume, sl, tp)` IMMEDIATELY only when the plan has a real Stop Loss and volume. The execution tool performs final live-readiness checks and may block.
  6. SAFETY EXCEPTION: If your most recent analysis result was "HOLD", "WAIT", or "NEUTRAL", DO NOT execute the trade. Explain clearly: "ฉันยังเทรดให้ไม่ได้ เพราะแผนล่าสุดระบุว่าต้อง [พักรอดูสถานการณ์]..."
  7. CRITICAL: NEVER print a Ticket ID or say "กำลังดำเนินการ..." unless you have already called the tool and received a 'SUCCESS' response with a real ticket/order number. If the response is BLOCKED/GUARD_BLOCKED/ERROR, explain exactly which gate blocked it.

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
                name="get_index_historical_summary",
                description=(
                    "Summarize long-term performance and current trend context for major US equity indices. "
                    "Best for questions like: '10 ปีที่ผ่านมา NASDAQ 100, S&P 500, NASDAQ Composite เป็นอย่างไร', "
                    "'compare US indices over the last 5 years', or 'ภาพรวมดัชนีหุ้นสหรัฐย้อนหลัง'."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "years": types.Schema(type="INTEGER", description="Lookback window in years, default 10, max 15."),
                        "indices": types.Schema(
                            type="ARRAY",
                            items=types.Schema(type="STRING"),
                            description="Optional subset of indices: NASDAQ_100, SP500, NASDAQ_COMPOSITE."
                        ),
                    }
                )
            ),
            types.FunctionDeclaration(
                name="get_historical_stock_rankings",
                description=(
                    "Rank US stocks by multi-year total return over a requested window. "
                    "Use for questions like 'top 10 best-performing stocks over the last 10 years' or "
                    "'หุ้น 10 ตัวที่ลงมากที่สุดใน 10 ปี'."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "years": types.Schema(type="INTEGER", description="Lookback window in years, default 10, max 15."),
                        "direction": types.Schema(type="STRING", description="'top' for best performers or 'bottom' for worst performers."),
                        "limit": types.Schema(type="INTEGER", description="Number of ranked stocks to return, default 10."),
                        "universe": types.Schema(type="STRING", description="COMBINED, NASDAQ100, or SP500."),
                        "full_window_only": types.Schema(type="BOOLEAN", description="Keep only stocks with near-full history across the requested window."),
                    }
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
                name="retrieve_knowledge_context",
                description=(
                    "Retrieve RAG context from the CryptoStream AI knowledge base. "
                    "Use this for questions that need ingested docs, project notes, research snippets, "
                    "or prior unstructured knowledge. Returns cited chunks from PostgreSQL/pgvector."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "query": types.Schema(type="STRING", description="Natural-language retrieval query"),
                        "limit": types.Schema(type="INTEGER", description="Number of chunks to retrieve, default 5"),
                        "source_type": types.Schema(type="STRING", description="Optional filter such as pdf, md, news, research, text")
                    },
                    required=["query"]
                )
            ),
            types.FunctionDeclaration(
                name="get_data_anomalies",
                description=(
                    "Retrieve recent market data anomalies detected by the Airflow anomaly detection pipeline. "
                    "Use when the user asks about abnormal prices, volume spikes, missing candles, data quality, "
                    "or whether recent market data looks reliable."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "symbol": types.Schema(type="STRING", description="Optional symbol filter, e.g. BTC-USD or NVDA"),
                        "severity": types.Schema(type="STRING", description="Optional severity filter: LOW, MEDIUM, HIGH, CRITICAL"),
                        "hours": types.Schema(type="INTEGER", description="Lookback window in hours, default 24"),
                        "limit": types.Schema(type="INTEGER", description="Maximum anomalies to return, default 20")
                    },
                )
            ),
            types.FunctionDeclaration(
                name="get_data_anomaly_summary",
                description=(
                    "Return aggregate anomaly counts from the market data anomaly pipeline. "
                    "Use for dashboard-style questions about total CRITICAL/HIGH anomalies and top affected symbols."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "hours": types.Schema(type="INTEGER", description="Lookback window in hours, default 24")
                    },
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
            "VOLUME","VOL","DATA","ANOMALY","ANOMALIES","QUALITY","PIPELINE",
            "CRYPTO","COIN","COINS","STOCK","STOCKS","FOREX","MARKET","MARKETS",
            "ASSET","ASSETS","NEWS","HEADLINE","HEADLINES"
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

        def _humanize_seconds(seconds: Any, language: str) -> str:
            try:
                total = int(seconds)
            except (TypeError, ValueError):
                total = 0
            if total <= 0:
                return "now" if language == "en" else "ตอนนี้"
            days, rem = divmod(total, 86400)
            hours, rem = divmod(rem, 3600)
            minutes, _ = divmod(rem, 60)
            parts = []
            if days:
                parts.append(f"{days}d" if language == "en" else f"{days} วัน")
            if hours:
                parts.append(f"{hours}h" if language == "en" else f"{hours} ชม.")
            if minutes and len(parts) < 2:
                parts.append(f"{minutes}m" if language == "en" else f"{minutes} นาที")
            return " ".join(parts) if parts else ("<1m" if language == "en" else "<1 นาที")

        def _is_market_status_query(text: str) -> bool:
            raw = text.strip().lower()
            market_terms = [
                "ตลาด", "market", "crypto", "forex", "gold", "หุ้น", "stock",
                "nasdaq", "nyse", "ทอง",
            ]
            status_terms = [
                "เปิด", "ปิด", "เปิดบ้าง", "ปิดบ้าง", "เปิดอยู่", "ปิดอยู่",
                "กี่โมงเปิด", "กี่โมงปิด", "status", "open today", "closed today",
                "what's open", "what is open", "market open", "market closed",
            ]
            return any(term in raw for term in market_terms) and any(term in raw for term in status_terms)

        def _looks_like_internal_tool_or_code_reply(text: str) -> bool:
            snippet = text.strip().lower()
            if not snippet:
                return False
            starts = (
                "print(",
                "```python",
                "```",
                "get_market_",
                "get_custom_screener(",
                "execute_mt5_trade(",
                "send_telegram_alert(",
            )
            contains = (
                "print(get_",
                "get_market_opportunities(",
                "get_market_analysis(",
                "get_institutional_ml_stats(",
                "get_trading_tactics(",
                "function_call",
                "tool_call",
            )
            return snippet.startswith(starts) or any(token in snippet for token in contains)

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

        if _is_market_status_query(user_input):
            from intelligence.utils.market_hours import get_market_status_data

            target_lang = 'English' if req.language == 'en' else 'Thai'
            status_data = get_market_status_data()
            crypto = status_data.get("crypto", {})
            forex = status_data.get("forex", {})
            stocks = status_data.get("stocks", {})

            yield json.dumps({
                "type": "metadata",
                "sql_query": None,
                "has_data": True,
                "intent": "GENERAL",
                "tv_symbol": None,
                "tv_symbols": [],
            }) + "\n"

            if req.language == 'en':
                content = (
                    "Current market status:\n"
                    f"- Crypto: {crypto.get('status', 'OPEN')} ({crypto.get('label', '24/7')})\n"
                    f"- Forex / Gold: {forex.get('status', 'UNKNOWN')} | next {str(forex.get('next_event', 'event')).lower()} in {_humanize_seconds(forex.get('seconds_remaining'), 'en')}\n"
                    f"- US Stocks: {stocks.get('status', 'UNKNOWN')} | next {str(stocks.get('next_event', 'event')).lower()} in {_humanize_seconds(stocks.get('seconds_remaining'), 'en')}\n"
                    "If you want, I can also break this down into Thailand time and tell you which one is best to watch next."
                )
            else:
                content = (
                    "สถานะตลาดตอนนี้:\n"
                    f"- Crypto: {crypto.get('status', 'OPEN')} ({crypto.get('label', '24/7')})\n"
                    f"- Forex / Gold: {forex.get('status', 'UNKNOWN')} | {('ปิดอีกใน' if forex.get('next_event') == 'CLOSE' else 'เปิดอีกใน')} {_humanize_seconds(forex.get('seconds_remaining'), 'th')}\n"
                    f"- หุ้นสหรัฐ: {stocks.get('status', 'UNKNOWN')} | {('ปิดอีกใน' if stocks.get('next_event') == 'CLOSE' else 'เปิดอีกใน')} {_humanize_seconds(stocks.get('seconds_remaining'), 'th')}\n"
                    "ถ้าต้องการ ผมสรุปต่อให้เป็นเวลาไทยและบอกได้ว่าช่วงไหนน่าจับตาที่สุดครับ"
                )

            yield json.dumps({"type": "chunk", "content": content}) + "\n"
            yield json.dumps({"type": "done", "intent": "GENERAL", "tvSymbol": None}) + "\n"
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
        INDEX_HISTORY_KEYWORDS = [
            "ย้อนหลัง", "ที่ผ่านมา", "historical", "history", "last ", "over the last", "year", "years",
            "decade", "ภาพรวม", "performance", "return", "nasdaq 100", "nasdaq composite", "s&p 500", "sp500",
        ]
        STOCK_HISTORY_KEYWORDS = [
            "ข้อมูลหุ้น 1ปี", "ข้อมูลหุ้น 1 ปี", "หุ้นย้อนหลัง", "หุ้น 1 ปี", "หุ้น 1ปี", "stock return", "stock performance",
            "market return", "equity performance", "ผลตอบแทนหุ้น", "ภาพรวมหุ้นย้อนหลัง",
        ]
        NEWS_KEYWORDS = [
            "ข่าว", "news", "headline", "headlines", "breaking", "latest",
            "ข่าวล่าสุด", "มีข่าวอะไร", "ข่าวอะไร", "เกิดอะไรขึ้น", "what happened",
        ]
        CONCEPTUAL_KEYWORDS = [
            "อธิบาย", "explain", "what is", "คืออะไร", "how it works", "how does", "ทำงานยังไง",
            "difference", "different", "ต่าง", "compare", "comparison", "เปรียบเทียบ",
            "พื้นฐาน", "basic", "basics", "เบื้องต้น", "เข้าใจง่าย", "ง่ายๆ", "simple",
        ]
        ANALYSIS_INTENT_KEYWORDS = [
            "วิเคราะห์", "analysis", "analyze", "trend", "outlook", "bias", "มุมมอง",
            "ราคา", "price", "chart", "กราฟ", "entry", "exit", "signal", "setup",
            "trade plan", "tp", "sl", "take profit", "stop loss", "แนวรับ", "แนวต้าน",
            "support", "resistance", "จุดเข้า", "จุดออก", "เข้าซื้อ", "เข้าขาย",
        ]
        # General market scan → force get_market_opportunities
        # Split into stock-only vs broad (ALL) to avoid scanning unnecessary asset classes
        ANOMALY_KEYWORDS = [
            "anomaly", "anomalies", "data anomaly", "data anomalies",
            "data quality", "dq", "missing candle", "missing candles",
            "volume spike", "price spike", "candle gap", "schema drift",
            "pipeline issue", "pipeline health",
        ]

        SCREENER_STOCK_KEYWORDS = [
            "หุ้นขึ้นแรง", "หุ้นลงแรง", "หุ้นขึ้นเยอะ", "หุ้นลงเยอะ",
            "วันนี้หุ้น", "หุ้นอะไร", "หุ้นน่า", "หุ้นไหน", "หุ้นตัวไหน",
            "น่า buy", "น่าซื้อหุ้น", "หุ้นน่าซื้อ", "หุ้นดี", "หุ้นเด่น",
            "stock scan", "scan หุ้น", "top gainer", "top loser",
            "หุ้นขึ้นเยอะที่สุด", "หุ้นตัวไหนขึ้นแรงสุด", "เดือนนี้หุ้น", "สัปดาห์นี้หุ้น",
            "หุ้นตัวไหนเด่นสุด", "best performing stock", "best performing stocks",
            "strongest stocks", "top stocks this month", "top stocks this week",
            "stocks up the most", "outperforming stocks", "monthly stock leaders",
        ]
        SCREENER_CRYPTO_KEYWORDS = [
            "crypto น่า", "เหรียญน่า", "เหรียญขึ้น", "เหรียญลง",
            "coin น่า", "วันนี้ crypto", "วันนี้เหรียญ",
            "คริปโตตัวไหนขึ้นแรงสุด", "เหรียญตัวไหนเด่นสุด", "เดือนนี้ crypto",
            "สัปดาห์นี้ crypto", "สัปดาห์นี้เหรียญ", "best performing crypto",
            "strongest crypto", "top crypto this month", "top crypto this week",
            "coins up the most", "crypto leaders", "top gaining coins",
        ]
        SCREENER_ALL_KEYWORDS = [
            "ขึ้นเยอะ", "ลงเยอะ", "น่าสนใจ", "น่าซื้อ",
            "market scan", "scan ตลาด", "ภาพรวมตลาด", "วันนี้ตลาด",
            "ตลาดเป็นยังไง", "ดูตลาดให้หน่อย", "สรุปตลาด", "วันนี้มีตัวไหนแววดี",
            "top movers", "best performers today", "strongest assets", "leaders this week",
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
        asks_for_news = any(kw in user_lower for kw in NEWS_KEYWORDS)
        asks_for_calendar = any(kw in user_lower for kw in CALENDAR_KEYWORDS)
        asks_for_concept = any(kw in user_lower for kw in CONCEPTUAL_KEYWORDS)
        asks_for_analysis = any(kw in user_lower for kw in ANALYSIS_INTENT_KEYWORDS)
        asks_for_broad_info = asks_for_news or asks_for_calendar or asks_for_concept

        if any(kw in user_lower for kw in ANOMALY_KEYWORDS):
            hours_match = re.search(r"\b(24|72|168)\b", user_lower)
            hours = int(hours_match.group(1)) if hours_match else 72
            yield json.dumps({"type": "tool_call", "tool": "get_data_anomaly_summary", "symbol": "Market"}) + "\n"
            summary_out = await run_agent_tool_async("get_data_anomaly_summary", {"hours": hours})
            yield json.dumps({
                "type": "metadata",
                "sql_query": None,
                "has_data": summary_out.get("status") == "SUCCESS",
                "intent": "GENERAL",
                "tv_symbol": None,
                "tv_symbols": [],
            }) + "\n"
            if summary_out.get("status") != "SUCCESS":
                yield json.dumps({"type": "chunk", "content": f"ยังดึงข้อมูล anomaly ไม่ได้: {summary_out.get('error', 'unknown error')}"}) + "\n"
                yield json.dumps({"type": "done", "intent": "GENERAL", "tvSymbol": None}) + "\n"
                return

            summary = summary_out.get("summary", {})
            top_symbols = summary_out.get("top_symbols", [])
            top_text = ", ".join(
                f"{item.get('symbol')} ({item.get('count')})"
                for item in top_symbols[:5]
            ) or "ไม่มี"
            content = (
                f"สรุป Data Anomalies {hours} ชั่วโมงล่าสุด:\n"
                f"- ทั้งหมด: {summary.get('total', 0)} events\n"
                f"- Critical: {summary.get('critical', 0)} | High: {summary.get('high', 0)}\n"
                f"- Price spikes: {summary.get('price_spikes', 0)} | Volume spikes: {summary.get('volume_spikes', 0)} | Range spikes: {summary.get('range_spikes', 0)} | Missing gaps: {summary.get('missing_gaps', 0)}\n"
                f"- Symbols ที่เจอบ่อย: {top_text}\n"
                "ระบบ anomaly pipeline และ Postgres พร้อมตอบคำถามด้าน data quality แล้วครับ"
            )
            yield json.dumps({"type": "chunk", "content": content}) + "\n"
            yield json.dumps({"type": "done", "intent": "GENERAL", "tvSymbol": None}) + "\n"
            return

        if any(kw in user_lower for kw in REANALYZE_KEYWORDS):
            override = "[MANDATORY OVERRIDE: ผู้ใช้ต้องการ 'แผนเทรดใหม่' หรือให้ 'วิเคราะห์อีกรอบ' ห้ามใช้ข้อมูลเก่าจากประวัติการแชทเด็ดขาด ให้พิจารณาว่าผู้ใช้กำลังพูดถึง Symbol ไหน แล้วเรียกใช้เครื่องมือเพื่อวิเคราะห์กราฟใหม่หรือคำนวณ Entry, SL, TP ใหม่ทั้งหมด]"
        elif any(kw in user_lower for kw in TELEGRAM_KEYWORDS):
            override = "[MANDATORY OVERRIDE: ผู้ใช้สั่งให้ส่งข้อความเข้า Telegram ให้คุณแต่งข้อความสรุปตามสิ่งที่ผู้ใช้ต้องการ (ห้ามยาวเกินไป) แล้วเรียก send_telegram_alert(message) ทันที ห้ามปฏิเสธเด็ดขาด]"
        elif any(kw in user_lower for kw in EXECUTE_KEYWORDS):
            override = "[MANDATORY EXECUTION: ผู้ใช้สั่ง 'จัดเลย', 'นำแผนนี้ไปใช้' หรือระบุ 'Lot Size' (0.01, 0.1, ฯลฯ) ให้คุณทำตามขั้นตอนดังนี้: (1) ย้อนกลับไปดูแผนการเทรดล่าสุดจากประวัติการแชท (2) หากแผนล่าสุดคือ BUY หรือ SELL ให้เรียกใช้เครื่องมือ execute_mt5_trade ทันที ห้ามแสดงความเห็นก่อน ห้ามพูด 'กำลังเทรด' เฉยๆ (3) หากยังไม่มีแผนหรือแผนล่าสุดคือ HOLD/WAIT ให้บอกผู้ใช้ทันทีว่า 'ยังเปิดออเดอร์ไม่ได้' ห้ามมโน Ticket ID ขึ้นมาเองเด็ดขาด ต้องรอผลลัพธ์จากเครื่องมือเท่านั้น!]"
        elif any(kw in user_lower for kw in ANOMALY_KEYWORDS):
            override = "[MANDATORY OVERRIDE - DATA ANOMALIES: Call get_data_anomaly_summary(hours=72) first. If the user asks for examples or details, also call get_data_anomalies(hours=72, limit=10). Do not interpret DATA as a ticker symbol.]"
        elif any(kw in user_lower for kw in THEMATIC_KEYWORDS):
            override = "[MANDATORY OVERRIDE: ผู้ใช้ถามหา 'กลุ่มหุ้นเฉพาะทาง' หรือ 'หุ้น Laggard' ให้คุณทำดังนี้ทันที: (1) คิดรายชื่อหุ้น ticker สัก 8-12 ตัวที่อยู่ในกลุ่มนั้นขึ้นมาจากความรู้ของคุณเอง (2) เรียก get_custom_screener(tickers=[...]) ด้วยรายชื่อที่คิดได้ ห้ามเรียก get_market_opportunities เด็ดขาด]"
        elif any(kw in user_lower for kw in CALENDAR_KEYWORDS):
            override = "[MANDATORY OVERRIDE: ผู้ใช้ถามหา 'ปฏิทินเศรษฐกิจ' หรือ 'ข่าวสำคัญล่วงหน้า' ให้เรียก get_economic_calendar(query='...') ทันที]"
        elif any(kw in user_lower for kw in STOCK_HISTORY_KEYWORDS) or _is_broad_stock_history_query(user_input):
            override = "[MANDATORY OVERRIDE: ผู้ใช้ถามข้อมูลหุ้น/ดัชนีย้อนหลัง 1 ปีหรือหลายปี โดยยังไม่ได้ระบุหุ้นรายตัวชัดเจน ให้เรียก get_index_historical_summary(years=..., indices=['NASDAQ_100','SP500','NASDAQ_COMPOSITE']) ก่อน แล้วสรุปภาพรวมผลตอบแทนของตลาดหุ้นสหรัฐเป็นภาษาคน ห้ามเปลี่ยนไปตอบ crypto, gold หรือ technical analysis]"
        elif (
            any(kw in user_lower for kw in INDEX_HISTORY_KEYWORDS)
            and _extract_index_history_targets(user_input)
            and not any(term in user_lower for term in conceptual_index_stop_terms)
            and (
                any(term in user_lower for term in historical_index_terms)
                or len(_extract_index_history_targets(user_input)) >= 2
            )
        ):
            override = "[MANDATORY OVERRIDE: ผู้ใช้ถามเชิงย้อนหลัง/ภาพรวมของดัชนีหุ้นสหรัฐ ให้เรียก get_index_historical_summary(years=..., indices=[...]) ก่อน แล้วสรุปผลตอบแทนรวม CAGR max drawdown และภาพปัจจุบันของแต่ละดัชนีเป็นภาษาคน ห้ามเปลี่ยนไปตอบ top gainer/loser ของคริปโตหรือหุ้นรายตัว]"
        elif asks_for_concept:
            override = "[MANDATORY OVERRIDE: ผู้ใช้ถามเชิงอธิบาย เปรียบเทียบ หรือความรู้พื้นฐาน ให้ตอบตรงคำถามแบบภาษาคนอ่านง่ายก่อน ห้ามเปลี่ยนเป็น technical analysis ห้ามเรียก get_market_analysis หรือทำตารางราคา เว้นแต่ผู้ใช้ขอราคาปัจจุบันหรือแผนเทรดโดยตรง]"
        elif any(kw in user_lower for kw in NEWS_KEYWORDS):
            override = "[MANDATORY OVERRIDE: ผู้ใช้ถามเรื่องข่าวล่าสุดหรือผลกระทบของข่าว ให้เรียก get_news_impact(symbol='...') ก่อนเสมอ แล้วสรุป headline สำคัญและผลกระทบเป็นภาษาคนอ่านง่าย ห้ามเปลี่ยนเป็นการวิเคราะห์เทคนิคหรือแผนเทรดทันที]"
        elif any(kw in user_lower for kw in GOLD_KEYWORDS) and asks_for_analysis and not asks_for_broad_info:
            override = "[MANDATORY OVERRIDE — GOLD: เรียก get_market_analysis(symbol='GOLD', asset_class='MACRO', timeframe='1h') + get_institutional_ml_stats(symbol='GOLD') + get_trading_tactics(symbol='GOLD') ทันที ห้ามใช้ข้อมูลเก่าจาก history ต้องสรุป BUY/SELL/HOLD จาก confluence ของ higher timeframe + statistical edge + tactics โดย 15m ใช้แค่ช่วยหา entry เท่านั้น]"
        elif any(kw in user_lower for kw in OIL_KEYWORDS) and asks_for_analysis and not asks_for_broad_info:
            override = "[MANDATORY OVERRIDE — OIL: เรียก get_market_analysis(symbol='OIL', asset_class='MACRO', timeframe='1h') + get_institutional_ml_stats(symbol='OIL') + get_trading_tactics(symbol='OIL') ทันที ต้องสรุป Signal จาก higher timeframe + statistical edge + tactics และให้ Entry/SL/TP จากข้อมูล tool เท่านั้น]"
        elif any(kw in user_lower for kw in CRYPTO_ASSET_KEYWORDS) and asks_for_analysis and not asks_for_broad_info:
            override = "[MANDATORY OVERRIDE — CRYPTO: ระบุ symbol ที่ถูกต้อง แล้วเรียก get_market_analysis(symbol='...', asset_class='CRYPTO', timeframe='1h') + get_institutional_ml_stats(symbol='...') + get_trading_tactics(symbol='...') ทันที ห้ามใช้ข้อมูลเก่าจาก history ต้องตัดสินสัญญาณจาก confluence ของ higher timeframe + structure + ML edge + tactics ไม่ใช่ยึด 15m อย่างเดียว]"
        elif any(kw in user_lower for kw in FOREX_KEYWORDS) and asks_for_analysis and not asks_for_broad_info:
            override = "[MANDATORY OVERRIDE — FOREX: ระบุ symbol ที่ถูกต้อง แล้วเรียก get_market_analysis(symbol='...', asset_class='MACRO', timeframe='1h') + get_institutional_ml_stats(symbol='...') + get_trading_tactics(symbol='...') ทันที ต้องให้สัญญาณจาก higher timeframe + structure + ML edge + tactics และสรุป Entry/SL/TP ให้พร้อมใช้]"
        elif any(kw in user_lower for kw in SCREENER_STOCK_KEYWORDS):
            override = "[MANDATORY OVERRIDE: ผู้ใช้ถามเรื่องหุ้น ให้เรียก get_market_opportunities(asset_class='STOCK') ทันที จากนั้นสรุปหุ้นที่เด่นที่สุดเป็นภาษาคนอ่านง่าย พร้อมเหตุผลและเปอร์เซ็นต์การเปลี่ยนแปลง ห้ามโชว์ชื่อฟังก์ชันหรือโค้ด]"
        elif any(kw in user_lower for kw in SCREENER_CRYPTO_KEYWORDS):
            override = "[MANDATORY OVERRIDE: ผู้ใช้ถามเรื่อง crypto ให้เรียก get_market_opportunities(asset_class='CRYPTO') ทันที จากนั้นสรุปเหรียญที่เด่นที่สุดเป็นภาษาคนอ่านง่าย พร้อม momentum และเปอร์เซ็นต์การเปลี่ยนแปลง ห้ามโชว์ชื่อฟังก์ชันหรือโค้ด]"
        elif any(kw in user_lower for kw in SCREENER_ALL_KEYWORDS):
            override = "[MANDATORY OVERRIDE: ผู้ใช้ถามภาพรวมตลาดกว้างๆ ให้เรียก get_market_opportunities(asset_class='ALL') ทันที จากนั้นสรุปภาพรวมตลาดและตัวที่เด่นที่สุดเป็นภาษาคนอ่านง่าย ห้ามโชว์ชื่อฟังก์ชันหรือโค้ด]"
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
            if ("ทอง" in user_input or "GOLD" in user_input.upper()) and asks_for_analysis and not asks_for_broad_info:
                target_sym, tv_symbol, intent = "GOLD", "TVC:GOLD", "ANALYZE"
                recommended_symbols.append(tv_symbol)
            elif any(kw in user_input.upper() for kw in ["BTC", "ETH", "CRYPTO", "เหรียญ"]) and asks_for_analysis and not asks_for_broad_info:
                target_sym, tv_symbol, intent = "BTC", "BINANCE:BTCUSDT", "ANALYZE"
                recommended_symbols.append(tv_symbol)
            elif any(kw in user_input.upper() for kw in ["หุ้น", "STOCK", "NASDAQ", "NYSE", "SPY", "SET"]) and asks_for_analysis and not asks_for_broad_info:
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
                    yield json.dumps({
                        "type": "status",
                        "content": f"กำลังดึงข้อมูลจากเครื่องมือ {fn_name}..."
                    }) + "\n"

                    if fn_name == "get_historical_stock_rankings":
                        requested_years = int(fn_args.get("years") or 10)
                        requested_direction = str(fn_args.get("direction") or "top")
                        requested_limit = int(fn_args.get("limit") or 10)
                        requested_universe = str(fn_args.get("universe") or "COMBINED")
                        requested_full_window = bool(fn_args.get("full_window_only", True))
                        from intelligence.tools.market_tools import get_historical_stock_rankings

                        yield json.dumps({
                            "type": "status",
                            "content": f"กำลังคำนวณอันดับหุ้นย้อนหลัง {requested_years} ปี..."
                        }) + "\n"
                        ranking_out = await asyncio.to_thread(
                            get_historical_stock_rankings,
                            requested_years,
                            requested_direction,
                            requested_limit,
                            requested_universe,
                            requested_full_window,
                        )
                        yield json.dumps({
                            "type": "metadata",
                            "sql_query": None,
                            "has_data": ranking_out.get("status") == "SUCCESS",
                            "intent": "GENERAL",
                            "tv_symbol": None,
                            "tv_symbols": [],
                        }) + "\n"
                        yield json.dumps({
                            "type": "chunk",
                            "content": _format_historical_stock_rankings(ranking_out, req.language),
                        }) + "\n"
                        yield json.dumps({"type": "done", "intent": "GENERAL", "tvSymbol": None}) + "\n"
                        return

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
                screener_asset_class = None
                if any(kw in user_lower for kw in SCREENER_STOCK_KEYWORDS):
                    screener_asset_class = "STOCK"
                elif any(kw in user_lower for kw in SCREENER_CRYPTO_KEYWORDS):
                    screener_asset_class = "CRYPTO"
                elif any(kw in user_lower for kw in SCREENER_ALL_KEYWORDS):
                    screener_asset_class = "ALL"

                if screener_asset_class:
                    logger.info(f"🔄 Gemini skipped screener tool call — auto-fetching market opportunities for {screener_asset_class}")
                    yield json.dumps({"type": "tool_call", "tool": "get_market_opportunities", "symbol": screener_asset_class}) + "\n"
                    yield json.dumps({
                        "type": "status",
                        "content": f"กำลังสแกนโอกาสในตลาด {screener_asset_class}..."
                    }) + "\n"
                    tool_out = await run_agent_tool_async("get_market_opportunities", {
                        "asset_class": screener_asset_class,
                    })
                    tool_results_parts.append(types.Part(
                        function_response=types.FunctionResponse(name="get_market_opportunities", response=tool_out)
                    ))

                    if isinstance(tool_out, dict):
                        if tool_out.get("hero_symbol"):
                            target_sym = tool_out["hero_symbol"]
                            best_ex = tool_out.get("hero_exchange")
                            tv_symbol = _resolve_tv_symbol(target_sym, exchange=best_ex)
                            intent = "ANALYZE"
                            recommended_symbols.insert(0, tv_symbol)
                        elif screener_asset_class == "STOCK":
                            target_sym, tv_symbol, intent = "SPY", "AMEX:SPY", "ANALYZE"
                        elif screener_asset_class == "CRYPTO":
                            target_sym, tv_symbol, intent = "BTC", "BINANCE:BTCUSDT", "ANALYZE"
                        elif screener_asset_class == "ALL":
                            intent = "GENERAL"

                # Disambiguation: If 'lot' is followed by a number, don't treat 'LOT' as a ticker
                if not tool_results_parts and not asks_for_concept and not broad_stock_history_query:
                    cleaned_input = re.sub(r'lot\s*\d+\.?\d*', '', user_input.lower())
                    # Extract uppercase word(s) that look like a ticker (2-6 chars, letters only)
                    ticker_candidates = re.findall(r'\b([A-Z]{2,6})\b', cleaned_input.upper())
                    auto_sym = next((t for t in ticker_candidates if t not in SKIP_WORDS), None)

                    if auto_sym:
                        logger.info(f"🔄 Gemini skipped tool call — auto-fetching {auto_sym}")
                        asset_class = _resolve_asset_class(auto_sym)
                        yield json.dumps({"type": "tool_call", "tool": "get_market_analysis", "symbol": auto_sym}) + "\n"
                        yield json.dumps({
                            "type": "status",
                            "content": f"กำลังวิเคราะห์ {auto_sym} จากข้อมูลตลาดล่าสุด..."
                        }) + "\n"
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
                yield json.dumps({
                    "type": "status",
                    "content": "รวบรวมข้อมูลเสร็จแล้ว กำลังสรุปคำตอบ..."
                }) + "\n"
                # Add tool calls and responses to history
                history_contents.append(agent_res.candidates[0].content)
                # Append language reminder alongside tool results so Gemini sees it right before generating
                yield json.dumps({
                    "type": "status",
                    "content": "กำลังร่างคำตอบ..."
                }) + "\n"
                lang_reminder = (
                    f"Now write your full analysis directly in {target_lang}. "
                    f"Do NOT start with 'Final Answer in {target_lang}:' or any preamble. "
                    f"Just write the response immediately in {target_lang}. "
                    f"Do NOT output code blocks, Python, or tool-call syntax."
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
                blocked_internal_reply = False
                final_iter = final_stream.__aiter__()
                while True:
                    try:
                        chunk = await asyncio.wait_for(final_iter.__anext__(), timeout=15.0)
                    except StopAsyncIteration:
                        break
                    except asyncio.TimeoutError:
                        logger.warning("Final Gemini stream stalled after tool execution; attempting non-stream recovery")
                        retry_text = await _retry_plain_language_answer(
                            f"Write the final user-facing answer now in {target_lang}. "
                            "Use the tool results you already have. "
                            "Be concise, plain-language, and do not show code, function calls, or tool syntax."
                        )
                        if retry_text:
                            if has_yielded_text:
                                yield json.dumps({"type": "chunk", "content": "\n\n" + retry_text}) + "\n"
                            else:
                                has_yielded_text = True
                                yield json.dumps({"type": "chunk", "content": retry_text}) + "\n"
                        elif has_yielded_text:
                            yield json.dumps({"type": "chunk", "content": "\n\n(การวิเคราะห์ส่วนที่เหลือหยุดกลางทาง แต่ข้อมูลหลักถูกดึงมาแล้วครับ)"} ) + "\n"
                        else:
                            yield json.dumps({"type": "chunk", "content": "ผมดึงข้อมูลตลาดได้แล้ว แต่ข้อความสรุปจาก AI ค้างกลางทางครับ ลองส่งคำถามเดิมอีกครั้งได้เลย หรือพิมพ์ให้ผมสรุปแบบสั้นแทนได้ครับ"}) + "\n"
                        break
                    try:
                        # Skip thinking tokens (Gemini 2.5 thinking model)
                        if chunk.candidates:
                            parts = chunk.candidates[0].content.parts if chunk.candidates[0].content else []
                            if any(getattr(p, 'thought', False) for p in parts):
                                continue
                        if chunk.text:
                            if not has_yielded_text and _looks_like_internal_tool_or_code_reply(chunk.text):
                                blocked_internal_reply = True
                                logger.warning("Blocked raw code/tool reply after tool execution; retrying in plain language")
                                continue
                            has_yielded_text = True
                            yield json.dumps({"type": "chunk", "content": chunk.text}) + "\n"
                    except ValueError:
                        has_yielded_text = True
                        yield json.dumps({"type": "chunk", "content": "⚠️ ถูกบล็อกโดยระบบรักษาความปลอดภัย (Safety Filter) ไม่สามารถแสดงผลได้"}) + "\n"
                
                if blocked_internal_reply and not has_yielded_text:
                    retry_text = await _retry_plain_language_answer(
                        f"Rewrite the answer for an end user in {target_lang}. "
                        "Use plain language only. Do not show code, function calls, or tool syntax."
                    )
                    if retry_text:
                        has_yielded_text = True
                        yield json.dumps({"type": "chunk", "content": retry_text}) + "\n"

                if not has_yielded_text:
                    yield json.dumps({"type": "chunk", "content": "*(AI ประมวลผลสำเร็จ แต่อาจถูกจำกัดการอธิบายข้อความ กรุณาอ้างอิงข้อมูลจากหน้าจอและผลลัพธ์การสแกนครับ)*"}) + "\n"
            else:
                # No tool calls and no ticker detected — stream a language-enforced response
                lang_reminder = (
                    f"Now write your response directly in {target_lang}. "
                    f"Do NOT use any other language. Write immediately without preamble. "
                    f"Do NOT output code blocks, Python, or tool-call syntax."
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
                    no_tool_iter = no_tool_stream.__aiter__()
                    blocked_internal_reply = False
                    while True:
                        try:
                            chunk = await asyncio.wait_for(no_tool_iter.__anext__(), timeout=15.0)
                        except StopAsyncIteration:
                            break
                        except asyncio.TimeoutError:
                            logger.warning("Final Gemini stream stalled without tool execution; attempting non-stream recovery")
                            retry_text = await _retry_plain_language_answer(
                                f"Write the final user-facing answer now in {target_lang}. "
                                "Use plain language only and answer directly without code, function calls, or tool syntax."
                            )
                            if retry_text:
                                yield json.dumps({"type": "chunk", "content": retry_text}) + "\n"
                            else:
                                yield json.dumps({"type": "chunk", "content": "AI เริ่มตอบแล้วแต่ stream ค้างกลางทางครับ ลองส่งคำถามอีกครั้งได้เลย"}) + "\n"
                            break
                        try:
                            if chunk.candidates:
                                parts = chunk.candidates[0].content.parts if chunk.candidates[0].content else []
                                if any(getattr(p, 'thought', False) for p in parts):
                                    continue
                            if chunk.text:
                                if _looks_like_internal_tool_or_code_reply(chunk.text):
                                    blocked_internal_reply = True
                                    logger.warning("Blocked raw code/tool reply without tool execution; retrying in plain language")
                                    continue
                                yield json.dumps({"type": "chunk", "content": chunk.text}) + "\n"
                        except ValueError:
                            pass
                    if blocked_internal_reply:
                        retry_text = await _retry_plain_language_answer(
                            f"Rewrite the answer for an end user in {target_lang}. "
                            "Use plain language only. Do not show code, function calls, or tool syntax."
                        )
                        if retry_text:
                            yield json.dumps({"type": "chunk", "content": retry_text}) + "\n"
                except Exception:
                    # Fallback to first-pass text
                    if agent_res.text:
                        yield json.dumps({"type": "chunk", "content": agent_res.text}) + "\n"

        except Exception as e:
            logging.error(f"Agent Workflow Error: {e}")
            if (
                _is_stock_top_performer_history_question(user_input)
                or _is_ranked_stock_history_query(user_input)
                or _is_explicit_stock_ranking_request(user_input)
            ):
                try:
                    async for chunk in _stream_historical_stock_rankings(
                        _extract_historical_years(user_input, default=10),
                        _extract_stock_history_direction(user_input),
                        _extract_stock_history_universe(user_input),
                        10,
                        True,
                    ):
                        yield chunk
                    return
                except Exception as fallback_exc:
                    logging.error(f"Historical ranking fallback failed: {fallback_exc}")
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


@app.get("/api/system/readiness")
def system_readiness():
    """Return truthful readiness across core data systems and external integrations."""
    return build_system_readiness()

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

def _filter_signal_rows(
    signals: list[dict],
    min_confidence: int = 0,
    actionable_only: bool = False,
    tradeable_only: bool = False,
    grade: str | None = None,
) -> list[dict]:
    return _helper_filter_signal_rows(
        signals,
        min_confidence=min_confidence,
        actionable_only=actionable_only,
        tradeable_only=tradeable_only,
        grade=grade,
    )


@app.get("/api/signals")
def get_signals(
    timeframe: str = "15m",
    min_confidence: int = 0,
    actionable_only: bool = False,
    tradeable_only: bool = False,
    grade: str | None = None,
    limit: int = 12,
):
    """
    [UPGRADED] Multi-Agent signals using technical indicators (RSI/MACD/ADX).
    Falls back to price-delta method if Intelligence Layer unavailable.
    """
    cache_key = (
        f"signals_v2:{timeframe}:{min_confidence}:"
        f"{int(actionable_only)}:{int(tradeable_only)}:{(grade or '').upper()}:{limit}"
    )
    cached = _cache_get(cache_key)
    if cached:
        return cached
    # ── Try Intelligence Layer first ──────────────────────────────────────────
    if INTELLIGENCE_AVAILABLE and crypto_intel:
        try:
            import concurrent.futures

            symbols = ["BTC", "ETH", "SOL", "XRP", "GOLD", "SILVER"]  # MT5-verified XM broker symbols only
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(crypto_intel.get_quick_signals, symbols, timeframe=timeframe)
                signals = future.result(timeout=6)
            signals = _filter_signal_rows(
                signals,
                min_confidence=min_confidence,
                actionable_only=actionable_only,
                tradeable_only=tradeable_only,
                grade=grade,
            )
            signals = signals[: max(1, min(int(limit), 50))]

            if signals:
                logging.info(f"✅ Intelligence signals: {len(signals)} symbols")
                for signal in signals:
                    try:
                        _record_signal_snapshot(signal, source="api_signals_multi_agent", timeframe=timeframe)
                    except Exception as exc:
                        logger.debug(f"Signal snapshot skipped: {exc}")
                payload = {
                    "signals": signals,
                    "source": "multi_agent_indicators",
                    "filters": {
                        "timeframe": timeframe,
                        "min_confidence": min_confidence,
                        "actionable_only": actionable_only,
                        "tradeable_only": tradeable_only,
                        "grade": grade,
                        "limit": limit,
                    },
                }
                _cache_set(cache_key, payload)
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

        signals = _helper_build_price_delta_fallback_signals(rows)
        signals = _filter_signal_rows(
            signals,
            min_confidence=min_confidence,
            actionable_only=actionable_only,
            tradeable_only=tradeable_only,
            grade=grade,
        )
        payload = {
            "signals": signals[: max(1, min(int(limit), 50))],
            "source": "price_delta_fallback",
            "filters": {
                "timeframe": timeframe,
                "min_confidence": min_confidence,
                "actionable_only": actionable_only,
                "tradeable_only": tradeable_only,
                "grade": grade,
                "limit": limit,
            },
        }
        for signal in payload["signals"]:
            try:
                _record_signal_snapshot(signal, source="api_signals_fallback", timeframe=timeframe)
            except Exception as exc:
                logger.debug(f"Fallback signal snapshot skipped: {exc}")
        _cache_set(cache_key, payload)
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
    return await _run_cached_thread_task(
        "market_sentiment_v1",
        _build_market_sentiment_payload,
        timeout=6.0,
        fallback=lambda: _with_data_quality(
            _default_sentiment_payload("Sentiment engine is temporarily unavailable."),
            cache_key="market_sentiment_v1",
            status="degraded",
            data_quality="unavailable",
            source="fallback",
            error="Sentiment engine is temporarily unavailable.",
        ),
        label="Sentiment API",
    )

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


@app.get("/api/status/data-quality")
def data_quality_status():
    return _cache_health_summary([
        "market_sentiment_v1",
        "dxy_news_v1",
        "market_indices_v5",
        "market_stocks_v2",
        "etf_flows_v1",
        "market_calendar_v1:7",
        "market_calendar_v1:14",
        "market_calendar_v1:30",
        "crypto_fg_v2",
        "cnn_fg_v2",
    ])


# ==========================================
# Market Data Proxy Endpoints (Sentiment Hub)
# Caches are refreshed on each call with TTL logic
# ==========================================

_market_cache: dict = {}  # { key: { data: ..., ts: float } }
PERSISTENT_MARKET_CACHE_KEYS = {
    "market_sentiment_v1",
    "dxy_news_v1",
    "market_indices_v5",
    "market_stocks_v2",
    "etf_flows_v1",
    "market_calendar_v1",
    "crypto_fg_v2",
    "cnn_fg_v2",
}
MARKET_CACHE_SNAPSHOT_DIR = os.path.join(tempfile.gettempdir(), "crypto-stream-ai", "market-cache")
MARKET_CACHE_TTL = 300  # 5 minutes
MARKET_CACHE_TTL_RULES = {
    "market_sentiment_v1": 180,
    "dxy_news_v1": 180,
    "signals_v1": 30,
    "crypto_fg_v2": 900,
    "cnn_fg_v2": 900,
    "market_indices_v5": 180,
    "market_pulse_v1": 180,
    "market_stocks_v2": 120,
    "market_calendar_v1": 900,
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


def _cache_get(key: str, ttl: Optional[int] = None, allow_stale: bool = False):
    entry = _cache_get_entry(key, ttl=ttl, allow_stale=allow_stale)
    return entry["data"] if entry else None

def _cache_get_entry(key: str, ttl: Optional[int] = None, allow_stale: bool = False):
    entry = _market_cache.get(key)
    if not entry:
        entry = _read_market_cache_snapshot(key)
        if entry:
            _market_cache[key] = entry
    if not entry:
        return None
    effective_ttl = _cache_ttl_for(key, ttl=ttl if ttl is not None else entry.get("ttl"))
    if allow_stale or (time.time() - entry["ts"]) < effective_ttl:
        return entry
    return None

def _cache_get_stale(key: str):
    return _cache_get(key, allow_stale=True)

def _cache_get_stale_entry(key: str):
    return _cache_get_entry(key, allow_stale=True)

def _cache_set(key: str, data, ttl: Optional[int] = None):
    _market_cache[key] = {"data": data, "ts": time.time(), "ttl": ttl}
    _write_market_cache_snapshot(key, data, ttl=ttl)

def _cache_delete(key: str):
    _market_cache.pop(key, None)




def _utc_now_iso() -> str:
    return _helper_utc_now_iso()


def _payload_updated_at(payload: Any, fallback_ts: Optional[float] = None) -> str:
    return _helper_payload_updated_at(payload, fallback_ts=fallback_ts)


def _with_data_quality(
    payload: Any,
    *,
    cache_key: Optional[str],
    status: str,
    data_quality: str,
    source: str,
    warning: Optional[str] = None,
    error: Optional[str] = None,
    fallback_ts: Optional[float] = None,
    details: Optional[dict[str, Any]] = None,
):
    return _helper_with_data_quality(
        payload,
        cache_key=cache_key,
        status=status,
        data_quality=data_quality,
        source=source,
        warning=warning,
        error=error,
        fallback_ts=fallback_ts,
        details=details,
    )


def _has_non_empty_sequence(value: Any) -> bool:
    return _helper_has_non_empty_sequence(value)


def _market_sentiment_has_content(payload: dict) -> bool:
    return _helper_market_sentiment_has_content(payload)


def _market_indices_has_content(payload: dict) -> bool:
    return _helper_market_indices_has_content(payload)


def _market_stocks_has_content(payload: dict) -> bool:
    return _helper_market_stocks_has_content(payload)


def _etf_flows_has_content(payload: dict) -> bool:
    return _helper_etf_flows_has_content(payload)


def _calendar_has_content(payload: dict) -> bool:
    return _helper_calendar_has_content(payload)


def _cache_ttl_for(key: str, ttl: Optional[int] = None) -> int:
    return _helper_cache_ttl_for(
        key,
        ttl=ttl,
        ttl_rules=MARKET_CACHE_TTL_RULES,
        default_ttl=MARKET_CACHE_TTL,
    )


def _is_persistent_market_cache_key(key: str) -> bool:
    return _helper_is_persistent_market_cache_key(key, PERSISTENT_MARKET_CACHE_KEYS)


def _market_cache_snapshot_path(key: str) -> str:
    return _helper_market_cache_snapshot_path(key, MARKET_CACHE_SNAPSHOT_DIR)


def _cache_health_summary(keys: list[str]) -> dict[str, Any]:
    return _helper_cache_health_summary(
        keys,
        get_stale_entry=_cache_get_stale_entry,
        cache_ttl_for=_cache_ttl_for,
        payload_updated_at=_payload_updated_at,
        utc_now_iso=_utc_now_iso,
        time_fn=time.time,
    )


def _read_market_cache_snapshot(key: str):
    return _helper_read_market_cache_snapshot(
        key,
        is_persistent_key=_is_persistent_market_cache_key,
        snapshot_path_for=_market_cache_snapshot_path,
        exists=os.path.exists,
        open_fn=open,
        load_fn=json.load,
        time_fn=time.time,
        warn_fn=logger.warning,
    )


def _write_market_cache_snapshot(key: str, data, ttl: Optional[int] = None):
    return _helper_write_market_cache_snapshot(
        key,
        data,
        ttl=ttl,
        is_persistent_key=_is_persistent_market_cache_key,
        snapshot_dir=MARKET_CACHE_SNAPSHOT_DIR,
        snapshot_path_for=_market_cache_snapshot_path,
        makedirs=os.makedirs,
        open_fn=open,
        dump_fn=json.dump,
        time_fn=time.time,
        warn_fn=logger.warning,
    )
    items = {}
    now_ts = time.time()
    for key in keys:
        entry = _cache_get_stale_entry(key)
        if not entry:
            items[key] = {
                "status": "missing",
                "data_quality": "unavailable",
                "updated_at": None,
                "age_seconds": None,
            }
            continue
        ttl = _cache_ttl_for(key, ttl=entry.get("ttl"))
        age = max(0, int(now_ts - entry["ts"]))
        items[key] = {
            "status": "ok" if age < ttl else "stale",
            "data_quality": "live" if age < ttl else "stale",
            "updated_at": _payload_updated_at(entry["data"], fallback_ts=entry.get("ts")),
            "age_seconds": age,
            "ttl_seconds": ttl,
        }
    return {
        "updated_at": _utc_now_iso(),
        "items": items,
    }


async def _run_cached_thread_task(
    cache_key: Optional[str],
    fn,
    *,
    timeout: float,
    fallback,
    label: str,
):
    try:
        return await asyncio.wait_for(asyncio.to_thread(fn), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("%s timed out after %.1fs", label, timeout)
    except Exception as exc:
        logger.warning("%s failed: %s", label, exc)

    cached_entry = _cache_get_stale_entry(cache_key) if cache_key else None
    if cached_entry is not None:
        return _with_data_quality(
            cached_entry["data"],
            cache_key=cache_key,
            status="ok",
            data_quality="stale",
            source="snapshot_cache",
            warning=f"{label} is temporarily unavailable. Showing the latest verified snapshot.",
            fallback_ts=cached_entry.get("ts"),
        )
    return fallback() if callable(fallback) else fallback


def _default_sentiment_payload(message: str) -> dict:
    return {
        "overall": {
            "sentiment": "NEUTRAL",
            "score": 0,
            "summary": message,
        },
        "articles": [],
    }


def _build_market_sentiment_payload() -> dict:
    cached_entry = _cache_get_entry("market_sentiment_v1")
    if cached_entry:
        return _with_data_quality(
            cached_entry["data"],
            cache_key="market_sentiment_v1",
            status="ok",
            data_quality="live",
            source="fresh_cache",
            fallback_ts=cached_entry.get("ts"),
        )

    client = genai.Client(
        api_key=os.environ.get("GOOGLE_API_KEY") or GEMINI_API_KEY,
        http_options={"api_version": "v1alpha"},
    )
    agent = create_sentiment_agent(client)
    result = agent({"symbol": "Crypto Market"})
    articles = _fetch_rss_news()
    payload = {
        "overall": result.get("sentiment_data", {}),
        "articles": articles[:15],
    }
    if not _market_sentiment_has_content(payload):
        stale_entry = _cache_get_stale_entry("market_sentiment_v1")
        if stale_entry:
            return _with_data_quality(
                stale_entry["data"],
                cache_key="market_sentiment_v1",
                status="ok",
                data_quality="stale",
                source="snapshot_cache",
                warning="Sentiment live feed is incomplete. Showing the latest verified snapshot.",
                fallback_ts=stale_entry.get("ts"),
            )
        return _with_data_quality(
            _default_sentiment_payload("Sentiment engine is temporarily unavailable."),
            cache_key="market_sentiment_v1",
            status="degraded",
            data_quality="unavailable",
            source="fallback",
            error="Sentiment live feed returned no usable data.",
        )
    _cache_set("market_sentiment_v1", payload)
    return _with_data_quality(
        payload,
        cache_key="market_sentiment_v1",
        status="ok",
        data_quality="live",
        source="live_analysis",
    )


def _build_dxy_news_payload() -> dict:
    cached_entry = _cache_get_entry("dxy_news_v1")
    if cached_entry:
        return _with_data_quality(
            cached_entry["data"],
            cache_key="dxy_news_v1",
            status="ok",
            data_quality="live",
            source="fresh_cache",
            fallback_ts=cached_entry.get("ts"),
        )

    client = genai.Client(
        api_key=os.environ.get("GOOGLE_API_KEY") or GEMINI_API_KEY,
        http_options={"api_version": "v1alpha"},
    )
    agent = create_sentiment_agent(client)
    result = agent({"symbol": "DXY", "asset_class": "MACRO"})
    articles = _fetch_rss_news(symbol_hint="DXY")
    payload = {
        "overall": result.get("sentiment_data", {}),
        "articles": articles[:10],
    }
    if not _market_sentiment_has_content(payload):
        stale_entry = _cache_get_stale_entry("dxy_news_v1")
        if stale_entry:
            return _with_data_quality(
                stale_entry["data"],
                cache_key="dxy_news_v1",
                status="ok",
                data_quality="stale",
                source="snapshot_cache",
                warning="DXY live news is incomplete. Showing the latest verified snapshot.",
                fallback_ts=stale_entry.get("ts"),
            )
        return _with_data_quality(
            _default_sentiment_payload("Macro news feed is temporarily unavailable."),
            cache_key="dxy_news_v1",
            status="degraded",
            data_quality="unavailable",
            source="fallback",
            error="DXY live feed returned no usable data.",
        )
    _cache_set("dxy_news_v1", payload)
    return _with_data_quality(
        payload,
        cache_key="dxy_news_v1",
        status="ok",
        data_quality="live",
        source="live_analysis",
    )

def _fetch_crypto_fear_greed_sync():
    cached_entry = _cache_get_entry("crypto_fg_v2")
    if cached_entry:
        return _with_data_quality(
            cached_entry["data"],
            cache_key="crypto_fg_v2",
            status="ok",
            data_quality="live",
            source="fresh_cache",
            fallback_ts=cached_entry.get("ts"),
        )
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
    return _with_data_quality(
        result,
        cache_key="crypto_fg_v2",
        status="ok",
        data_quality="live",
        source="live_api",
    )

def _fetch_cnn_fear_greed_sync():
    cached_entry = _cache_get_entry("cnn_fg_v2")
    if cached_entry:
        return _with_data_quality(
            cached_entry["data"],
            cache_key="cnn_fg_v2",
            status="ok",
            data_quality="live",
            source="fresh_cache",
            fallback_ts=cached_entry.get("ts"),
        )
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
    return _with_data_quality(
        result,
        cache_key="cnn_fg_v2",
        status="ok",
        data_quality="live",
        source="live_api",
    )

def _build_market_indices_payload():
    cached_entry = _cache_get_entry("market_indices_v5")
    if cached_entry:
        return _with_data_quality(
            cached_entry["data"],
            cache_key="market_indices_v5",
            status="ok",
            data_quality="live",
            source="fresh_cache",
            fallback_ts=cached_entry.get("ts"),
        )

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

    if not _market_indices_has_content(result):
        stale_entry = _cache_get_stale_entry("market_indices_v5")
        if stale_entry:
            return _with_data_quality(
                stale_entry["data"],
                cache_key="market_indices_v5",
                status="ok",
                data_quality="stale",
                source="snapshot_cache",
                warning="Market indices live feed is incomplete. Showing the latest verified snapshot.",
                fallback_ts=stale_entry.get("ts"),
            )
    _cache_set("market_indices_v5", result)
    return _with_data_quality(
        result,
        cache_key="market_indices_v5",
        status="ok" if _market_indices_has_content(result) else "degraded",
        data_quality="live" if _market_indices_has_content(result) else "partial",
        source="live_quotes",
        warning=None if _market_indices_has_content(result) else "Some market indices could not be refreshed from live sources.",
    )

@app.get("/api/market/crypto-fear-greed")
async def crypto_fear_greed():
    """Crypto Fear & Greed Index from alternative.me — includes historical data."""
    try:
        return await asyncio.to_thread(_fetch_crypto_fear_greed_sync)
    except Exception as e:
        logger.warning(f"Crypto F&G fetch error: {e}")
        cached_entry = _cache_get_stale_entry("crypto_fg_v2")
        if cached_entry:
            return _with_data_quality(
                cached_entry["data"],
                cache_key="crypto_fg_v2",
                status="ok",
                data_quality="stale",
                source="snapshot_cache",
                warning="Crypto Fear & Greed live feed is unavailable. Showing the latest verified snapshot.",
                fallback_ts=cached_entry.get("ts"),
            )
        return _with_data_quality(
            {
                "value": 50, "label": "Neutral", "timestamp": "",
                "history": {
                    "yesterday": {"value": 50, "label": "Neutral"},
                    "last_week": {"value": 50, "label": "Neutral"},
                    "last_month": {"value": 50, "label": "Neutral"},
                }
            },
            cache_key="crypto_fg_v2",
            status="degraded",
            data_quality="unavailable",
            source="fallback",
            error="Crypto Fear & Greed live feed is unavailable.",
        )

@app.get("/api/market/cnn-fear-greed")
async def cnn_fear_greed():
    """CNN Fear & Greed Index — includes historical data from CNN API."""
    try:
        return await asyncio.to_thread(_fetch_cnn_fear_greed_sync)
    except Exception as e:
        logger.warning(f"CNN F&G fetch error: {e}")
        cached_entry = _cache_get_stale_entry("cnn_fg_v2")
        if cached_entry:
            return _with_data_quality(
                cached_entry["data"],
                cache_key="cnn_fg_v2",
                status="ok",
                data_quality="stale",
                source="snapshot_cache",
                warning="CNN Fear & Greed live feed is unavailable. Showing the latest verified snapshot.",
                fallback_ts=cached_entry.get("ts"),
            )
        return _with_data_quality(
            {
                "value": 50, "label": "Neutral", "timestamp": "",
                "history": {
                    "yesterday": {"value": 50, "label": "Neutral"},
                    "last_week": {"value": 50, "label": "Neutral"},
                    "last_month": {"value": 50, "label": "Neutral"},
                }
            },
            cache_key="cnn_fg_v2",
            status="degraded",
            data_quality="unavailable",
            source="fallback",
            error="CNN Fear & Greed live feed is unavailable.",
        )

@app.get("/api/market/indices")
async def market_indices():
    """Nasdaq Composite (^IXIC), Dow Jones (^DJI), and VIX (^VIX) via Yahoo Finance with Intraday History."""
    return await _run_cached_thread_task(
        "market_indices_v5",
        _build_market_indices_payload,
        timeout=6.0,
        fallback=lambda: _with_data_quality(
            {
                "nasdaq": {"name": "Nasdaq 100", "price": 0, "change_pct": 0, "previous_close": 0, "series": []},
                "dow": {"name": "Dow Jones", "price": 0, "change_pct": 0, "previous_close": 0, "series": []},
                "sp500": {"name": "S&P 500", "price": 0, "change_pct": 0, "previous_close": 0, "series": []},
                "dxy": {"name": "US Dollar Index", "price": 0, "change_pct": 0, "previous_close": 0, "series": []},
                "vix": {"name": "VIX", "price": 0, "change_pct": 0, "previous_close": 0, "series": []},
            },
            cache_key="market_indices_v5",
            status="degraded",
            data_quality="unavailable",
            source="fallback",
            error="Market indices feed is temporarily unavailable.",
        ),
        label="Market indices API",
    )

@app.get("/api/market/dxy-news")
async def get_dxy_news():
    """Returns real-time macro analysis for the US Dollar Index (DXY) using Gemini."""
    return await _run_cached_thread_task(
        "dxy_news_v1",
        _build_dxy_news_payload,
        timeout=6.0,
        fallback=lambda: _with_data_quality(
            _default_sentiment_payload("Macro news feed is temporarily unavailable."),
            cache_key="dxy_news_v1",
            status="degraded",
            data_quality="unavailable",
            source="fallback",
            error="Macro news feed is temporarily unavailable.",
        ),
        label="DXY news API",
    )

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
        cache_key = f"market_calendar_v1:{days}"
        cached_entry = _cache_get_entry(cache_key)
        if cached_entry:
            return _with_data_quality(
                cached_entry["data"],
                cache_key=cache_key,
                status="ok",
                data_quality="live",
                source="fresh_cache",
                fallback_ts=cached_entry.get("ts"),
            )
        try:
            payload = await asyncio.wait_for(
                asyncio.to_thread(get_economic_calendar_v2, days),
                timeout=4.0,
            )
        except asyncio.TimeoutError:
            logger.warning("Market calendar API timed out on live sources; falling back to estimated schedule.")
            payload = await asyncio.to_thread(get_economic_calendar_estimated, days)

        if not isinstance(payload, dict):
            stale_entry = _cache_get_stale_entry(cache_key)
            if stale_entry:
                return _with_data_quality(
                    stale_entry["data"],
                    cache_key=cache_key,
                    status="ok",
                    data_quality="stale",
                    source="snapshot_cache",
                    warning="Calendar engine returned an unexpected payload. Showing the latest verified snapshot.",
                    fallback_ts=stale_entry.get("ts"),
                )
            return _with_data_quality({
                "status": "ERROR",
                "events": [],
                "macro_watch": [],
                "trading_note": "Calendar engine returned an unexpected response.",
                "source_status": "invalid_payload",
            },
            cache_key=cache_key,
            status="degraded",
            data_quality="unavailable",
            source="fallback",
            error="Calendar engine returned an unexpected response.",
            )

        events = payload.get("events") or []
        macro_watch = payload.get("macro_watch") or []
        result = {
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
        source_status = result["source_status"]
        if not _calendar_has_content(result):
            stale_entry = _cache_get_stale_entry(cache_key)
            if stale_entry:
                return _with_data_quality(
                    stale_entry["data"],
                    cache_key=cache_key,
                    status="ok",
                    data_quality="stale",
                    source="snapshot_cache",
                    warning="Calendar live feed is unavailable. Showing the latest verified snapshot.",
                    fallback_ts=stale_entry.get("ts"),
                )
        _cache_set(cache_key, result)
        return _with_data_quality(
            result,
            cache_key=cache_key,
            status="ok" if source_status == "live_feed" else ("degraded" if events or macro_watch else "error"),
            data_quality="live" if source_status == "live_feed" else ("partial" if events or macro_watch else "unavailable"),
            source="calendar_live" if source_status == "live_feed" else "calendar_estimated",
            warning="Calendar is using estimated guidance." if source_status == "watch_only" else None,
            error="Calendar source is currently unavailable." if source_status == "error" and not events and not macro_watch else None,
        )
    except Exception as e:
        logger.error(f"Market calendar API error: {e}")
        stale_entry = _cache_get_stale_entry(f"market_calendar_v1:{max(1, min(int(days), 30))}")
        if stale_entry:
            return _with_data_quality(
                stale_entry["data"],
                cache_key=f"market_calendar_v1:{max(1, min(int(days), 30))}",
                status="ok",
                data_quality="stale",
                source="snapshot_cache",
                warning="Calendar feed failed. Showing the latest verified snapshot.",
                fallback_ts=stale_entry.get("ts"),
            )
        return _with_data_quality({
            "status": "ERROR",
            "events": [],
            "macro_watch": [],
            "trading_note": "Calendar data is unavailable right now.",
            "source_status": "error",
            "error": str(e),
            "updated_at": datetime.utcnow().isoformat(),
        },
        cache_key=f"market_calendar_v1:{max(1, min(int(days), 30))}",
        status="error",
        data_quality="unavailable",
        source="fallback",
        error=str(e),
        )



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


def _build_market_stocks_payload() -> dict:
    cached_entry = _cache_get_entry("market_stocks_v2")
    if cached_entry:
        return _with_data_quality(
            cached_entry["data"],
            cache_key="market_stocks_v2",
            status="ok",
            data_quality="live",
            source="fresh_cache",
            fallback_ts=cached_entry.get("ts"),
        )

    symbols_map = {
        "NVDA": "NVDA",
        "TSLA": "TSLA",
        "AAPL": "AAPL",
        "MSFT": "MSFT",
        "META": "META",
        "GOOGL": "GOOGL",
        "AMD": "AMD",
        "GOLD": "GC=F",
        "OIL": "CL=F",
        "DXY": "DX-Y.NYB",
        "NASDAQ": "^IXIC",
        "SP500": "^GSPC",
        "BTC": "BTC-USD",
        "ETH": "ETH-USD",
        "SOL": "SOL-USD",
    }
    raw = _yahoo_batch_quotes(list(symbols_map.values()))

    result = {}
    for key, ysym in symbols_map.items():
        q = raw.get(ysym, {})
        price = float(q.get("regularMarketPrice") or 0)
        chg = float(q.get("regularMarketChangePercent") or 0)
        prev = float(q.get("regularMarketPreviousClose") or price)
        name = q.get("shortName") or key
        result[key] = {
            "price": round(price, 2),
            "change_pct": round(chg, 4),
            "previous_close": round(prev, 2),
            "name": name,
        }

    if not _market_stocks_has_content(result):
        stale_entry = _cache_get_stale_entry("market_stocks_v2")
        if stale_entry:
            return _with_data_quality(
                stale_entry["data"],
                cache_key="market_stocks_v2",
                status="ok",
                data_quality="stale",
                source="snapshot_cache",
                warning="Ticker feed is incomplete. Showing the latest verified snapshot.",
                fallback_ts=stale_entry.get("ts"),
            )
    _cache_set("market_stocks_v2", result)
    return _with_data_quality(
        result,
        cache_key="market_stocks_v2",
        status="ok" if _market_stocks_has_content(result) else "degraded",
        data_quality="live" if _market_stocks_has_content(result) else "partial",
        source="live_quotes",
        warning=None if _market_stocks_has_content(result) else "Some tickers could not be refreshed from live sources.",
    )


@app.get("/api/market/stocks")
async def market_stocks():
    """Real-time prices for ticker tape symbols (NVDA, TSLA, GOLD, NASDAQ, SP500) via Yahoo Finance batch."""
    return await _run_cached_thread_task(
        "market_stocks_v2",
        _build_market_stocks_payload,
        timeout=6.0,
        fallback=lambda: _with_data_quality(
            {k: {"price": 0, "change_pct": 0} for k in ["NVDA", "TSLA", "GOLD", "NASDAQ", "SP500"]},
            cache_key="market_stocks_v2",
            status="degraded",
            data_quality="unavailable",
            source="fallback",
            error="Ticker feed is temporarily unavailable.",
        ),
        label="Market stocks API",
    )


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
    try:
        with get_persistence_conn() as conn:
            rows = conn.execute("SELECT * FROM tactics_audit_log ORDER BY timestamp DESC LIMIT 100").fetchall()
        payload = {"logs": [dict(r) for r in rows]}
    except Exception as exc:
        logger.warning(f"Tactics audit log read failed: {exc}")
        payload = {"logs": []}
    _cache_set("tactics_audit_logs_v1", payload)
    return payload


def _degraded_tactics_payload(symbol: str, message: str) -> dict:
    return {
        "symbol": symbol,
        "price": 0.0,
        "recommendation": "WATCH",
        "best_persona": "GENERAL_AI",
        "tactics": [
            {
                "name": "Fallback Monitor",
                "style": "Defensive",
                "score": 35,
                "move": "WATCH",
                "trigger": "Wait for backend recovery and fresh market confirmation.",
                "invalidation": "Discard this placeholder once live tactics return.",
                "tp": "No target while degraded.",
                "logic": message,
            }
        ],
        "timestamp": time.time(),
        "status": "DEGRADED",
    }

@app.get("/api/tactics/{symbol}")
async def get_tactics(symbol: str, x_api_key: str = Header(None)):
    """
    [V7-RESTORED] Fetch institutional-grade tactics for a symbol.
    Aggregates indicators and SMC structure into a tactical plan.
    """
    verify_token(
        x_api_key,
        detail="Unauthorized institutional key required.",
        status_code=401,
    )

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
        return await asyncio.wait_for(inflight_task, timeout=8.0)
    except asyncio.TimeoutError:
        logger.warning("Tactics API timed out for %s", normalized_symbol)
        cached_stale = _cache_get_stale(cache_key)
        return cached_stale or _degraded_tactics_payload(
            normalized_symbol,
            "Tactical engine timed out while upstream market sources were slow.",
        )
    except Exception as e:
        logger.error(f"Tactics API error: {e}")
        cached_stale = _cache_get_stale(cache_key)
        return cached_stale or _degraded_tactics_payload(
            normalized_symbol,
            f"Tactical engine error: {str(e)[:160]}",
        )
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


class AlertCreateRequest(BaseModel):
    symbol: str
    condition: str
    price: float
    message: Optional[str] = None
    entry_source: Optional[str] = None
    timeframe: Optional[str] = None
    meta: Optional[dict] = None


class TelegramTestRequest(BaseModel):
    message: Optional[str] = None

@app.get("/api/watchlist")
async def get_watchlist(request: Request):
    """Retrieve the user's priority watchlist with live performance metrics."""
    require_request_api_key(request)

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
    except sqlite3.OperationalError as e:
        logger.warning(f"Watchlist storage unavailable, returning empty state: {e}")
        return {"watchlist": []}
    except Exception as e:
        logger.error(f"Error fetching watchlist: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/watchlist")
async def add_to_watchlist(item: WatchlistItem, request: Request):
    """Add or update a symbol in the surveillance list."""
    require_request_api_key(request)

    try:
        with get_persistence_conn() as conn:
            conn.execute(
                "INSERT INTO watchlist (symbol, note, created_at) VALUES (?, ?, ?) "
                "ON CONFLICT(symbol) DO UPDATE SET note=excluded.note",
                (item.symbol.upper(), item.note, datetime.now(timezone.utc).isoformat())
            )
            conn.commit()
        return {"status": "success", "symbol": item.symbol}
    except sqlite3.OperationalError as e:
        logger.warning(f"Watchlist add skipped due to SQLite issue: {e}")
        return {"status": "degraded", "symbol": item.symbol, "message": "Watchlist storage is temporarily unavailable."}
    except Exception as e:
        logger.error(f"Error adding to watchlist: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/watchlist/{symbol}")
async def remove_from_watchlist(symbol: str, request: Request):
    """Remove a symbol from the surveillance list."""
    require_request_api_key(request)

    try:
        with get_persistence_conn() as conn:
            conn.execute("DELETE FROM watchlist WHERE symbol = ?", (symbol.upper(),))
            conn.commit()
        return {"status": "deleted", "symbol": symbol}
    except sqlite3.OperationalError as e:
        logger.warning(f"Watchlist delete skipped due to SQLite issue: {e}")
        return {"status": "degraded", "symbol": symbol, "message": "Watchlist storage is temporarily unavailable."}
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
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    entry_source: Optional[str] = None
    entry_reason: Optional[str] = None
    ml_score: Optional[float] = None
    signal_grade: Optional[str] = None
    macro_bias: Optional[str] = None
    features: Optional[dict] = None


class AutoPaperConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    shadow_labeling_enabled: Optional[bool] = None
    shadow_min_probability: Optional[float] = None
    shadow_label_max_age_minutes: Optional[int] = None
    confidence_threshold: Optional[float] = None
    volume: Optional[float] = None
    cooldown_minutes: Optional[int] = None
    max_open_positions: Optional[int] = None
    scan_interval_seconds: Optional[int] = None
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
    return _helper_serialize_paper_trade(row)


def _num(value: Any, default: float = 0.0) -> float:
    return _helper_num(value, default)


def _paper_summary(open_trades: list[dict], closed_trades: list[dict]) -> dict:
    return _helper_paper_summary(open_trades, closed_trades)


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
            "SELECT id, symbol, side, current_price, entry_price FROM paper_trades WHERE status = 'OPEN'"
        ).fetchall()
        for open_row in open_rows:
            try:
                latest_price = _get_live_price(open_row["symbol"])
            except Exception:
                latest_price = _telegram_resolve_paper_entry_price(
                    open_row["symbol"],
                    open_row["side"],
                    open_row["current_price"] or open_row["entry_price"],
                )
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
    summary = _paper_summary(open_trades, closed_trades)
    return {
        "open_trades": open_trades,
        "closed_trades": closed_trades,
        "summary": summary,
        "total_simulated_pnl": round(summary["closed_pnl_usd"], 2),
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
    _refresh_user_price_alerts()
    with get_persistence_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM alerts ORDER BY datetime(created_at) DESC LIMIT 200"
        ).fetchall()
    payload = {"alerts": [dict(row) for row in rows]}
    _cache_set("alerts_payload_v1", payload)
    return payload


def _normalize_alert_condition(condition: str) -> str:
    normalized = str(condition or "").strip().lower()
    if normalized not in {"above", "below"}:
        raise HTTPException(status_code=400, detail="Alert condition must be 'above' or 'below'")
    return normalized


NEWS_WATCH_POLL_SECONDS = max(30, int(os.getenv("NEWS_WATCH_POLL_SECONDS", "90")))


def _news_watch_aliases(symbol: str) -> list[str]:
    return _helper_news_watch_aliases(symbol)


def _extract_news_watch_symbol(text: str, default: str = "BTC") -> str:
    return _helper_extract_news_watch_symbol(
        text,
        default=default,
        trade_symbol_aliases=TRADE_SYMBOL_ALIASES,
        fallback_extractor=_telegram_extract_symbol,
    )


def _estimate_news_bias(headlines: list[str]) -> tuple[str, str]:
    return _helper_estimate_news_bias(headlines)


def _score_news_watch_article(article: dict, symbol: str) -> tuple[int, list[str]]:
    return _helper_score_news_watch_article(article, symbol, aliases=_news_watch_aliases(symbol))


def _make_news_watch_hash(article: dict) -> str:
    return _helper_make_news_watch_hash(article)


def _create_news_watch_alert(symbol: str, original_text: str, language: str = "th") -> dict[str, Any]:
    import sqlite3

    normalized_symbol = _telegram_extract_symbol(symbol, default=symbol or "BTC").upper().strip()
    if normalized_symbol in {"BTCUSD", "BTCUSDT"}:
        normalized_symbol = "BTC"
    elif normalized_symbol in {"ETHUSD", "ETHUSDT"}:
        normalized_symbol = "ETH"

    for attempt in range(4):
        try:
            existing = None
            with get_persistence_conn() as conn:
                existing = conn.execute(
                    """
                    SELECT * FROM alerts
                    WHERE user_id = 'chat_news_watch'
                      AND symbol = ?
                      AND condition = 'news'
                      AND status = 'ACTIVE'
                    ORDER BY datetime(created_at) DESC
                    LIMIT 1
                    """,
                    (normalized_symbol,),
                ).fetchone()
                if existing:
                    return {"status": "exists", "alert": dict(existing)}

                created_at = datetime.now(timezone.utc).isoformat()
                meta = {
                    "watch_type": "news",
                    "symbol_aliases": _news_watch_aliases(normalized_symbol),
                    "importance_threshold": 5,
                    "seen_hashes": [],
                    "created_from": "chat",
                    "language": language,
                    "original_text": original_text[:500],
                    "notify_channel": "telegram",
                }
                message = (
                    f"News watcher active for {normalized_symbol}. "
                    f"Telegram will notify when a high-impact headline appears."
                )
                cursor = conn.execute(
                    """
                    INSERT INTO alerts (
                        user_id,
                        symbol,
                        condition,
                        price,
                        timeframe,
                        entry_source,
                        message,
                        meta_json,
                        status,
                        created_at
                    )
                    VALUES (?, ?, 'news', 0, 'news', 'chat_news_watch', ?, ?, 'ACTIVE', ?)
                    """,
                    (
                        "chat_news_watch",
                        normalized_symbol,
                        message,
                        json.dumps(meta, ensure_ascii=False),
                        created_at,
                    ),
                )
                conn.commit()
                alert_id = int(cursor.lastrowid)
                row = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
            _cache_delete("alerts_payload_v1")
            return {"status": "created", "alert": dict(row) if row else {"id": alert_id, "symbol": normalized_symbol}}
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == 3:
                raise
            time.sleep(0.75 * (attempt + 1))
    raise RuntimeError("unable to create news watch alert")


def _scan_news_watch_alerts(limit: int = 25) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    try:
        with get_persistence_conn() as conn:
            rows = conn.execute(
                """
                SELECT id, symbol, meta_json, message, created_at
                FROM alerts
                WHERE status = 'ACTIVE'
                  AND condition = 'news'
                  AND user_id = 'chat_news_watch'
                ORDER BY datetime(created_at) DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        for row in rows:
            meta = {}
            try:
                meta = json.loads(row["meta_json"] or "{}")
            except Exception:
                meta = {}
            seen_hashes = set(meta.get("seen_hashes") or [])
            importance_threshold = int(meta.get("importance_threshold", 5) or 5)
            symbol = str(row["symbol"] or "").upper().strip()
            articles = _fetch_rss_news(symbol_hint=symbol)
            for article in articles[:10]:
                article_hash = _make_news_watch_hash(article)
                if article_hash in seen_hashes:
                    continue
                score, reasons = _score_news_watch_article(article, symbol)
                if score < importance_threshold:
                    continue
                hits.append({
                    "alert_id": int(row["id"]),
                    "symbol": symbol,
                    "article_hash": article_hash,
                    "article": article,
                    "score": score,
                    "reasons": reasons,
                })
                break
    except Exception as exc:
        logger.warning(f"Unable to scan news watch alerts: {exc}")
    return hits


def _ack_news_watch_hit(alert_id: int, article_hash: str, article: dict, score: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_persistence_conn() as conn:
        row = conn.execute("SELECT meta_json FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        meta = {}
        try:
            meta = json.loads((row["meta_json"] if row else "{}") or "{}")
        except Exception:
            meta = {}
        seen_hashes = list(meta.get("seen_hashes") or [])
        if article_hash not in seen_hashes:
            seen_hashes.append(article_hash)
        meta["seen_hashes"] = seen_hashes[-80:]
        meta["last_triggered_at"] = now
        meta["last_triggered_title"] = article.get("title")
        meta["last_triggered_link"] = article.get("link")
        meta["last_importance_score"] = score
        conn.execute(
            """
            UPDATE alerts
            SET meta_json = ?, triggered_at = ?, message = ?
            WHERE id = ?
            """,
            (
                json.dumps(meta, ensure_ascii=False),
                now,
                f"Latest high-impact news for {article.get('title') or 'watcher'}",
                alert_id,
            ),
        )
        conn.commit()
    _cache_delete("alerts_payload_v1")


async def news_watch_poller_task():
    while True:
        try:
            hits = await asyncio.to_thread(_scan_news_watch_alerts)
            for hit in hits:
                article = hit["article"]
                symbol = hit["symbol"]
                title = str(article.get("title") or "Untitled headline").strip()
                summary = str(article.get("summary") or "").strip()
                source = str(article.get("source") or "RSS").strip()
                link = str(article.get("link") or "").strip()
                reasons = ", ".join(hit.get("reasons") or ["high impact"])
                message = (
                    f"Breaking news watch triggered for {symbol}\n"
                    f"Headline: {title}\n"
                    f"Source: {source}\n"
                    f"Importance score: {hit['score']} ({reasons})"
                )
                if summary:
                    message += f"\nSummary: {summary[:220]}"
                if link:
                    message += f"\nLink: {link}"
                sent = await notifier.send_telegram_alert(message)
                if sent:
                    await asyncio.to_thread(
                        _ack_news_watch_hit,
                        hit["alert_id"],
                        hit["article_hash"],
                        article,
                        hit["score"],
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(f"news_watch_poller_task error: {exc}")
        await asyncio.sleep(NEWS_WATCH_POLL_SECONDS)


def _refresh_user_price_alerts() -> dict[str, int]:
    triggered = 0
    checked = 0
    now = datetime.now(timezone.utc).isoformat()

    try:
        with get_persistence_conn() as conn:
            rows = conn.execute(
                """
                SELECT id, symbol, condition, price, timeframe, entry_source
                FROM alerts
                WHERE status = 'ACTIVE'
                  AND user_id = 'signal_feed_ui'
                  AND condition IN ('above', 'below')
                ORDER BY datetime(created_at) DESC
                LIMIT 200
                """
            ).fetchall()

            for row in rows:
                target_price = float(row["price"] or 0.0)
                if target_price <= 0:
                    continue

                checked += 1
                live_price = _get_live_price(str(row["symbol"] or ""))
                if live_price <= 0:
                    continue

                condition = str(row["condition"] or "").lower()
                hit = (condition == "above" and live_price >= target_price) or (
                    condition == "below" and live_price <= target_price
                )
                if not hit:
                    continue

                conn.execute(
                    """
                    UPDATE alerts
                    SET status = 'FIRED', triggered_at = ?
                    WHERE id = ?
                    """,
                    (now, row["id"]),
                )
                triggered += 1

                try:
                    timeframe = str(row["timeframe"] or "15m").upper()
                    entry_source = str(row["entry_source"] or "signal_feed_analysis").replace("_", " ")
                    condition_label = "above" if condition == "above" else "below"
                    message = (
                        f"Price alert fired for {row['symbol']}\n"
                        f"Condition: {condition_label} ${target_price:,.2f}\n"
                        f"Live price: ${live_price:,.2f}\n"
                        f"Timeframe: {timeframe}\n"
                        f"Source: {entry_source}"
                    )
                    asyncio.run(notifier.send_telegram_alert(message))
                except Exception as notify_error:
                    logger.warning(f"Unable to send Telegram alert for {row['symbol']}: {notify_error}")

            if triggered:
                conn.commit()
                _cache_delete("alerts_payload_v1")
            elif checked:
                conn.commit()
    except Exception as e:
        logger.warning(f"Unable to refresh user price alerts: {e}")

    return {"checked": checked, "triggered": triggered}

async def _run_alert_refresh():
    global _alerts_refresh_task
    try:
        await asyncio.to_thread(_upsert_ml_alerts_from_signals)
        await asyncio.to_thread(_refresh_user_price_alerts)
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
    return _helper_is_eth_address(address)


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

    assets, total_usd = _helper_build_eth_assets(payload)
    result = _helper_build_eth_portfolio_result(
        address=normalized,
        explorer_url=explorer_url,
        assets=assets,
        total_usd=total_usd,
        identity=identity,
    )
    _cache_set(cache_key, result)
    return result


@app.get("/api/whales/all")
async def whales_all(request: Request):
    require_request_api_key(request)
    return {"data": await asyncio.to_thread(_fetch_binance_whales)}


@app.get("/api/market/funding-rates")
async def market_funding_rates(request: Request):
    require_request_api_key(request)
    return await asyncio.to_thread(_fetch_funding_rates_sync)


@app.get("/api/market/etf-flows")
async def market_etf_flows(request: Request):
    require_request_api_key(request)

    cached_entry = _cache_get_entry("etf_flows_v1")
    if cached_entry:
        return _with_data_quality(
            cached_entry["data"],
            cache_key="etf_flows_v1",
            status="ok",
            data_quality="live",
            source="fresh_cache",
            fallback_ts=cached_entry.get("ts"),
        )

    etf_symbols = ["SPY", "QQQ", "IBIT", "ETHA", "GLD", "TLT", "ARKK", "SOXL"]
    flows = []
    try:
        import yfinance as yf
        data = await asyncio.wait_for(
            asyncio.to_thread(
                yf.download,
                " ".join(etf_symbols),
                period="1mo",
                interval="1d",
                progress=False,
                group_by="ticker",
                auto_adjust=False,
            ),
            timeout=6.0,
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
    if not _etf_flows_has_content(payload):
        stale_entry = _cache_get_stale_entry("etf_flows_v1")
        if stale_entry:
            return _with_data_quality(
                stale_entry["data"],
                cache_key="etf_flows_v1",
                status="ok",
                data_quality="stale",
                source="snapshot_cache",
                warning="ETF flow feed is incomplete. Showing the latest verified snapshot.",
                fallback_ts=stale_entry.get("ts"),
            )
    _cache_set("etf_flows_v1", payload)
    return _with_data_quality(
        payload,
        cache_key="etf_flows_v1",
        status="ok" if _etf_flows_has_content(payload) else "degraded",
        data_quality="live" if _etf_flows_has_content(payload) else "unavailable",
        source="live_quotes",
        error=None if _etf_flows_has_content(payload) else "ETF flow feed returned no usable data.",
    )


@app.get("/api/portfolio/wallet")
async def portfolio_wallet(address: str, request: Request):
    require_request_api_key(request)
    return await asyncio.to_thread(_build_eth_portfolio_payload, address)


@app.get("/api/alerts")
async def get_alerts(request: Request):
    require_request_api_key(request)
    _schedule_alert_refresh_if_needed()
    return await asyncio.to_thread(_read_alert_rows)


@app.post("/api/alerts")
async def create_alert(payload: AlertCreateRequest, request: Request):
    require_request_api_key(request)

    symbol = str(payload.symbol or "").upper().strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="Alert symbol is required")

    price = float(payload.price or 0.0)
    if price <= 0:
        raise HTTPException(status_code=400, detail="Alert price must be greater than 0")

    condition = _normalize_alert_condition(payload.condition)
    timeframe = str(payload.timeframe or "15m").strip()
    entry_source = str(payload.entry_source or "signal_feed_analysis").strip()
    created_at = datetime.now(timezone.utc).isoformat()
    meta_json = json.dumps(payload.meta or {}, ensure_ascii=False)
    message = (
        payload.message
        or f"Alert when {symbol} moves {condition} ${price:,.2f} on {timeframe.upper()}."
    )

    with get_persistence_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO alerts (
                user_id,
                symbol,
                condition,
                price,
                timeframe,
                entry_source,
                message,
                meta_json,
                status,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?)
            """,
            (
                "signal_feed_ui",
                symbol,
                condition,
                price,
                timeframe,
                entry_source,
                message,
                meta_json,
                created_at,
            ),
        )
        conn.commit()
        alert_id = int(cursor.lastrowid)
        row = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()

    _cache_delete("alerts_payload_v1")
    return {"status": "created", "alert": dict(row) if row else {"id": alert_id}}


@app.post("/api/notifications/telegram/test")
async def test_telegram_notification(payload: TelegramTestRequest, request: Request):
    require_request_api_key(request)

    message = (
        payload.message
        or "Telegram test from CryptoStream AI\nIf you received this, your bot token and chat id are configured correctly."
    )
    sent = await notifier.send_telegram_alert(message)
    if not sent:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Telegram test failed. Check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in your environment.",
                "telegram_error": notifier.telegram_status().get("last_error"),
            },
        )
    return {"status": "sent", "message": message}


@app.get("/api/notifications/telegram/status")
async def telegram_notification_status(request: Request):
    require_request_api_key(request)
    status = notifier.telegram_status()
    status["bot_polling_enabled"] = str(os.getenv("TELEGRAM_BOT_POLLING_ENABLED", "1")).strip().lower() not in {"0", "false", "no", "off"}
    status["last_update_id"] = notifier.last_update_id
    status["commands"] = [
        "/start", "/help", "/status", "/best", "/signals", "/signal", "/mt5", "/paper", "/feedback",
        "/bestalt", "/why", "/whybest", "/beststats", "/riskguard", "/rag", "/alerts", "/audit", "/profile", "/watch", "/setlot", "/setrisk", "/trade",
        "/alert",
    ]
    return status


@app.post("/api/notifications/telegram/bot/test")
async def test_telegram_bot_menu(request: Request):
    require_request_api_key(request)
    sent = await notifier.send_telegram_message(
        notifier.default_chat_id,
        _telegram_help_text(),
        reply_markup=_telegram_keyboard(),
    )
    if not sent:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Telegram bot menu test failed.",
                "telegram_error": notifier.telegram_status().get("last_error"),
            },
        )
    return {
        "status": "sent",
        "commands": [
            "/start", "/status", "/best", "/bestalt", "/signals", "/signal BTC", "/mt5", "/paper", "/feedback",
            "/why BTC BUY", "/whybest", "/beststats", "/riskguard", "/rag", "/alerts", "/audit", "/profile", "/watch BTC GOLD", "/setlot 0.01", "/setrisk 1",
            "/alert GOLD above 4700",
        ],
    }


@app.delete("/api/alerts/{alert_id}")
async def dismiss_alert(alert_id: int, request: Request):
    require_request_api_key(request)
    with get_persistence_conn() as conn:
        conn.execute("UPDATE alerts SET status = 'DISMISSED' WHERE id = ?", (alert_id,))
        conn.commit()
    _cache_delete("alerts_payload_v1")
    _append_audit_event("DQ_ERROR", f"Alert {alert_id} dismissed")
    return {"status": "dismissed", "id": alert_id}


@app.delete("/api/alerts/ml/stale")
async def purge_stale_ml_alerts(request: Request):
    require_request_api_key(request)
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
    require_request_api_key(request)
    _ensure_trade_review_snapshots()
    with get_persistence_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM trade_reviews ORDER BY datetime(created_at) DESC LIMIT 25"
        ).fetchall()
    return {"reviews": [dict(row) for row in rows]}


@app.get("/api/paper-trades")
async def get_paper_trades(request: Request):
    require_request_api_key(request)
    return await asyncio.to_thread(_paper_trade_snapshot)


@app.get("/api/paper-trades/summary")
async def get_paper_trades_summary(request: Request):
    require_request_api_key(request)
    snapshot = await asyncio.to_thread(_paper_trade_snapshot)
    return {
        "summary": snapshot.get("summary", {}),
        "recent_open_trades": snapshot.get("open_trades", [])[:8],
        "recent_closed_trades": snapshot.get("closed_trades", [])[:8],
    }


@app.get("/api/paper-trades/scorecard")
async def get_paper_trades_scorecard(request: Request):
    require_request_api_key(request)

    def _build():
        from intelligence.ml.performance_feedback import get_feedback_snapshot

        feedback = get_feedback_snapshot(force_refresh=True)
        return {
            "strategy": feedback.get("strategy", {}),
            "symbol": feedback.get("symbol", {}),
            "symbol_side": feedback.get("symbol_side", {}),
            "recommendations": feedback.get("recommendations", []),
        }

    return await asyncio.to_thread(_build)


@app.get("/api/paper-trades/side-scorecard")
async def get_paper_trades_side_scorecard(request: Request, limit: int = 50):
    require_request_api_key(request)

    def _build():
        from intelligence.ml.paper_analytics import build_side_scorecard

        return build_side_scorecard(limit=limit)

    return await asyncio.to_thread(_build)


@app.get("/api/best-setup")
async def get_best_setup(request: Request, force_refresh: bool = False):
    require_request_api_key(request)

    def _build():
        return _build_best_setup_payload(use_cache=not force_refresh)

    payload = await asyncio.to_thread(_build)
    payload["scanner"] = {
        "last_run_at": _best_setup_state.get("last_run_at"),
        "last_error": _best_setup_state.get("last_error"),
        "scan_interval_seconds": BEST_SETUP_SCAN_INTERVAL_SECONDS,
    }
    payload["model_trust"] = payload.get("model_trust") or _ml_model_trust_snapshot()
    return payload


@app.get("/api/best-setup/metrics")
async def get_best_setup_metrics(request: Request, limit: int = 500, evaluate: bool = False):
    require_request_api_key(request)
    return await asyncio.to_thread(_best_setup_metrics, min(max(int(limit), 50), 2000), bool(evaluate))


@app.get("/api/risk/daily-guard")
async def get_daily_risk_guard(request: Request, chat_id: str | None = None):
    require_request_api_key(request)
    return await asyncio.to_thread(_daily_risk_guard, chat_id)


@app.post("/api/rag/trade-memory/sync")
async def sync_rag_trade_memory(request: Request, force: bool = False):
    require_request_api_key(request)
    result = await asyncio.to_thread(_sync_trade_memory_to_rag, force)
    if result.get("status") == "ERROR":
        raise HTTPException(status_code=500, detail=result)
    return result


@app.get("/api/rag/pre-graph-readiness")
async def rag_pre_graph_readiness(request: Request):
    require_request_api_key(request)
    return await asyncio.to_thread(_pre_graph_rag_readiness)


@app.post("/api/rag/graph/build")
async def build_rag_trade_graph(request: Request, limit: int = 1000):
    require_request_api_key(request)
    readiness = await asyncio.to_thread(_pre_graph_rag_readiness)
    if readiness.get("blockers"):
        return {
            "status": "BUILT_WITH_WARNINGS",
            "readiness": readiness,
            "graph": await asyncio.to_thread(_build_trade_knowledge_graph, limit),
        }
    return await asyncio.to_thread(_build_trade_knowledge_graph, limit)


@app.get("/api/rag/graph/status")
async def get_rag_trade_graph_status(request: Request):
    require_request_api_key(request)
    return await asyncio.to_thread(_trade_graph_status)


@app.get("/api/rag/graph/query")
async def query_rag_trade_graph(
    request: Request,
    symbol: str | None = None,
    side: str | None = None,
    limit: int = 25,
):
    require_request_api_key(request)
    return await asyncio.to_thread(_query_trade_graph, symbol, side, limit)


@app.get("/api/rag/graph/guard")
async def get_rag_trade_graph_guard(
    request: Request,
    symbol: str,
    side: str,
):
    require_request_api_key(request)
    return await asyncio.to_thread(_trade_graph_guard, symbol, side)


@app.get("/api/symbols/resolve")
async def api_resolve_trade_symbol(request: Request, symbol: str):
    require_request_api_key(request)
    return resolve_trade_symbol(symbol)


@app.get("/api/signals/memory")
async def get_signal_memory(request: Request, limit: int = 1000, evaluate: bool = False):
    require_request_api_key(request)
    return await asyncio.to_thread(_signal_snapshot_metrics, limit, evaluate)


@app.get("/api/decision/why")
async def get_decision_why(request: Request, symbol: str, side: str = "BUY"):
    require_request_api_key(request)
    return {
        "symbol_resolution": resolve_trade_symbol(symbol),
        "graph_guard": await asyncio.to_thread(_trade_graph_guard, symbol, side),
        "signal_memory": await asyncio.to_thread(_signal_snapshot_metrics, 1000, False),
        "daily_guard": await asyncio.to_thread(_daily_risk_guard, None),
        "market_regime": _current_market_regime(),
    }


@app.get("/api/decision/best-alternative")
async def get_decision_best_alternative(request: Request, chat_id: str | None = None):
    require_request_api_key(request)
    return await asyncio.to_thread(_best_alternative_candidates, chat_id)


@app.post("/api/decision/open-best-paper")
async def post_decision_open_best_paper(
    request: Request,
    chat_id: str | None = None,
    volume: float | None = None,
):
    require_request_api_key(request)
    return await asyncio.to_thread(_open_best_paper_evidence, chat_id, volume)


@app.get("/api/paper-trades/auto")
async def get_auto_paper_status(request: Request):
    require_request_api_key(request)
    return _auto_paper_status()


@app.post("/api/paper-trades/auto")
async def update_auto_paper_status(payload: AutoPaperConfigUpdate, request: Request):
    require_request_api_key(request)
    try:
        if payload.enabled is not None:
            _auto_paper_state["enabled"] = bool(payload.enabled)
        if payload.shadow_labeling_enabled is not None:
            _auto_paper_state["shadow_labeling_enabled"] = bool(payload.shadow_labeling_enabled)
        if payload.confidence_threshold is not None:
            _auto_paper_state["confidence_threshold"] = min(max(float(payload.confidence_threshold), 0.5), 0.95)
        if payload.shadow_min_probability is not None:
            _auto_paper_state["shadow_min_probability"] = min(max(float(payload.shadow_min_probability), 0.30), 0.75)
        if payload.shadow_label_max_age_minutes is not None:
            _auto_paper_state["shadow_label_max_age_minutes"] = max(int(payload.shadow_label_max_age_minutes), 30)
        if payload.volume is not None:
            _auto_paper_state["volume"] = max(float(payload.volume), 0.001)
        if payload.cooldown_minutes is not None:
            _auto_paper_state["cooldown_minutes"] = max(int(payload.cooldown_minutes), 5)
        if payload.max_open_positions is not None:
            _auto_paper_state["max_open_positions"] = max(int(payload.max_open_positions), 1)
        if payload.scan_interval_seconds is not None:
            _auto_paper_state["scan_interval_seconds"] = max(int(payload.scan_interval_seconds), 10)
        if payload.symbols is not None:
            cleaned = [str(symbol).upper().strip() for symbol in payload.symbols if str(symbol).strip()]
            _auto_paper_state["symbols"] = cleaned or list(AUTO_PAPER_DEFAULTS["symbols"])

        try:
            _append_audit_event(
                "AUTO_PAPER",
                (
                    f"Updated auto paper config | enabled={_auto_paper_state['enabled']} | "
                    f"shadow={_auto_paper_state['shadow_labeling_enabled']} | "
                    f"symbols={','.join(_auto_paper_state['symbols'])}"
                ),
            )
        except Exception as audit_error:
            logger.warning(f"Auto paper audit log failed: {audit_error}")
        return _auto_paper_status()
    except Exception as e:
        logger.exception(f"Auto paper config update failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/paper-trades/auto/run")
async def run_auto_paper_once(request: Request):
    require_request_api_key(request)

    try:
        loop = asyncio.get_event_loop()
        summary = await loop.run_in_executor(None, _auto_paper_cycle_sync)
        _auto_paper_state["last_run_at"] = datetime.now(timezone.utc).isoformat()
        _auto_paper_state["last_summary"] = summary
        _auto_paper_state["last_error"] = None
        return {"status": "completed", "summary": summary, "config": _auto_paper_status()}
    except sqlite3.OperationalError as exc:
        if "locked" not in str(exc).lower():
            raise
        _auto_paper_state["last_run_at"] = datetime.now(timezone.utc).isoformat()
        _auto_paper_state["last_error"] = str(exc)
        return {
            "status": "deferred",
            "message": "Paper scan deferred because SQLite is busy. The background scanner will retry automatically.",
            "error": str(exc),
            "config": _auto_paper_status(),
        }


@app.post("/api/paper-trades")
async def create_paper_trade(payload: PaperTradeCreateRequest, request: Request):
    require_request_api_key(request)
    _assert_daily_risk_guard_allows("api_paper_trade")
    opened = _open_paper_trade_internal(
        symbol=payload.symbol,
        side=payload.side,
        volume=float(payload.volume or 1.0),
        price=payload.price,
        entry_source=payload.entry_source or "manual_ui",
        entry_reason=payload.entry_reason or "Manual paper trade",
    )
    if payload.stop_loss is not None or payload.take_profit is not None or payload.features:
        try:
            from intelligence.ml.outcome_tracker import attach_sl_tp_features

            stop_loss = float(payload.stop_loss) if payload.stop_loss is not None else None
            take_profit = float(payload.take_profit) if payload.take_profit is not None else None
            attach_sl_tp_features(
                opened["trade_id"],
                stop_loss,
                take_profit,
                payload.features or {},
                payload.ml_score,
                payload.signal_grade,
                payload.macro_bias,
            )
            opened["custom_levels_attached"] = True
        except Exception as e:
            logger.warning(f"Failed to attach custom paper trade metadata: {e}")
            opened["custom_levels_attached"] = False
            opened["custom_levels_error"] = str(e)
    return opened


@app.post("/api/paper-trades/{trade_id}/close")
async def close_paper_trade(trade_id: str, payload: PaperTradeCloseRequest, request: Request):
    require_request_api_key(request)

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
    require_request_api_key(request)
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


def _int_env(name: str, default: int, minimum: int) -> int:
    try:
        return max(int(os.getenv(name, str(default))), minimum)
    except Exception:
        return default


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


AUTO_PAPER_DEFAULTS = {
    "enabled": _bool_env("AUTO_PAPER_ENABLED", True),
    "shadow_labeling_enabled": _bool_env("AUTO_PAPER_SHADOW_LABELING_ENABLED", True),
    "symbols": [
        "BTCUSD",
        "ETHUSD",
        "SOLUSDT",
        "XRPUSDT",
        "BNBUSD",
    ],
    "confidence_threshold": 0.68,
    "shadow_min_probability": 0.35,
    "shadow_label_max_age_minutes": _int_env("AUTO_PAPER_SHADOW_LABEL_MAX_AGE_MINUTES", 240, 30),
    "volume": 0.01,
    "cooldown_minutes": _int_env("AUTO_PAPER_COOLDOWN_MINUTES", 5, 5),
    "max_open_positions": _int_env("AUTO_PAPER_MAX_OPEN_POSITIONS", 12, 1),
    "scan_interval_seconds": _int_env("AUTO_PAPER_SCAN_INTERVAL_SECONDS", 30, 10),
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
        "shadow_labeling_enabled": bool(_auto_paper_state["shadow_labeling_enabled"]),
        "symbols": list(_auto_paper_state["symbols"]),
        "confidence_threshold": float(_auto_paper_state["confidence_threshold"]),
        "shadow_min_probability": float(_auto_paper_state["shadow_min_probability"]),
        "shadow_label_max_age_minutes": int(_auto_paper_state["shadow_label_max_age_minutes"]),
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


def _auto_paper_performance_gate(symbol: str, side: str, entry_source: str) -> dict:
    try:
        from intelligence.ml.performance_feedback import paper_entry_performance_gate

        return paper_entry_performance_gate(symbol=symbol, side=side, entry_source=entry_source)
    except Exception as exc:
        return {"ok": True, "blockers": [], "warnings": [f"performance_gate_unavailable:{exc}"]}


def _expire_stale_paper_labels(max_age_minutes: int) -> dict:
    """Close stale automated paper labels with the current mark price."""
    max_age = max(int(max_age_minutes or AUTO_PAPER_DEFAULTS["shadow_label_max_age_minutes"]), 30)
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=max_age)).isoformat()
    closed_at = datetime.now(timezone.utc).isoformat()
    close_reason = f"time_expiry_{max_age}m"
    summary = {
        "max_age_minutes": max_age,
        "close_reason": close_reason,
        "closed_count": 0,
        "closed": [],
        "skipped": [],
        "auto_retrain": {"checked": False},
    }

    with get_persistence_conn() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM paper_trades
            WHERE status = 'OPEN'
              AND entry_source IN ('shadow_label', 'auto_paper')
              AND datetime(opened_at) <= datetime(?)
            ORDER BY datetime(opened_at) ASC
            LIMIT 25
            """,
            (cutoff,),
        ).fetchall()

        for row in rows:
            trade_id = row["id"]
            symbol = str(row["symbol"]).upper().strip()
            side = str(row["side"]).upper().strip()
            exit_price = _get_live_price(symbol)
            if exit_price <= 0:
                exit_price = float(row["current_price"] or row["entry_price"] or 0.0)
            if exit_price <= 0:
                summary["skipped"].append({"trade_id": trade_id, "symbol": symbol, "reason": "no_exit_price"})
                continue

            entry_price = float(row["entry_price"] or 0.0)
            quantity = float(row["quantity"] or row["volume"] or 0.0)
            direction = 1 if side == "BUY" else -1
            pnl_usd = direction * (exit_price - entry_price) * quantity
            outcome = "WIN" if pnl_usd > 0 else "LOSS"

            conn.execute(
                """
                UPDATE paper_trades
                SET current_price = ?, exit_price = ?, pnl = ?, pnl_usd = ?, outcome = ?,
                    status = 'CLOSED', closed_at = ?, close_reason = ?, label_source = ?
                WHERE id = ?
                """,
                (
                    exit_price,
                    exit_price,
                    pnl_usd,
                    pnl_usd,
                    outcome,
                    closed_at,
                    close_reason,
                    "time_expiry",
                    trade_id,
                ),
            )
            summary["closed_count"] += 1
            summary["closed"].append(
                {
                    "trade_id": trade_id,
                    "symbol": symbol,
                    "side": side,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "pnl_usd": round(pnl_usd, 6),
                    "outcome": outcome,
                    "entry_source": row["entry_source"],
                }
            )

        if summary["closed_count"]:
            conn.commit()

    if summary["closed_count"]:
        try:
            _append_audit_event(
                "AUTO_PAPER",
                f"Closed {summary['closed_count']} stale paper label(s) via {close_reason}",
            )
        except Exception as audit_error:
            logger.warning(f"Paper label expiry audit failed: {audit_error}")
        _ensure_trade_review_snapshots()
        summary["auto_retrain"] = _maybe_trigger_auto_retrain("paper_label_time_expiry")

    return summary


def _quick_signal_symbol(symbol: str) -> str:
    return str(resolve_trade_symbol(symbol).get("quick_symbol") or symbol).upper()


def _shadow_label_cycle_sync(
    status: dict,
    summary: dict,
    open_symbols: set[str],
    open_position_count: int,
) -> int:
    """Open paper-only labels from gated signal candidates so the model can learn."""
    if not status.get("shadow_labeling_enabled"):
        return open_position_count
    if not INTELLIGENCE_AVAILABLE or not crypto_intel:
        summary["skipped"].append({"symbol": "*", "reason": "shadow:intelligence_unavailable"})
        return open_position_count

    min_prob = float(status.get("shadow_min_probability") or 0.35)
    for symbol in status["symbols"]:
        paper_symbol = str(symbol).upper().strip()
        if paper_symbol not in summary["checked_symbols"]:
            summary["checked_symbols"].append(paper_symbol)
        if open_position_count >= status["max_open_positions"]:
            summary["skipped"].append({"symbol": paper_symbol, "reason": "shadow:max_open_positions"})
            break
        if paper_symbol in open_symbols:
            summary["skipped"].append({"symbol": paper_symbol, "reason": "shadow:already_open"})
            continue
        if _recent_trade_exists(paper_symbol, status["cooldown_minutes"]):
            summary["skipped"].append({"symbol": paper_symbol, "reason": "shadow:cooldown_active"})
            continue

        quick_symbol = _quick_signal_symbol(paper_symbol)
        try:
            signals = crypto_intel.get_quick_signals([quick_symbol], timeframe="15m")
        except Exception as exc:
            summary["skipped"].append({"symbol": paper_symbol, "reason": f"shadow:signal_error:{exc}"})
            continue
        if not signals:
            summary["skipped"].append({"symbol": paper_symbol, "reason": "shadow:no_signal"})
            continue

        signal = signals[0]
        side = str(signal.get("candidate_direction") or signal.get("direction") or "").upper()
        probability = float(signal.get("ml_win_prob") or 0.0)
        if side not in {"BUY", "SELL"}:
            summary["skipped"].append({"symbol": paper_symbol, "reason": f"shadow:candidate:{side or 'NONE'}"})
            continue
        if probability < min_prob:
            summary["skipped"].append({"symbol": paper_symbol, "reason": f"shadow:probability:{probability:.4f}"})
            continue
        if signal.get("tradeable"):
            summary["skipped"].append({"symbol": paper_symbol, "reason": "shadow:already_tradeable"})
            continue
        perf_gate = _auto_paper_performance_gate(paper_symbol, side, "shadow_label")
        if not perf_gate.get("ok", True):
            summary["skipped"].append(
                {
                    "symbol": paper_symbol,
                    "reason": "shadow:performance_block",
                    "detail": perf_gate.get("blockers", [])[:3],
                }
            )
            continue
        graph_guard = _trade_graph_guard(paper_symbol, side)
        if graph_guard.get("blockers"):
            summary["skipped"].append(
                {
                    "symbol": paper_symbol,
                    "reason": "shadow:graph_guard_block",
                    "detail": graph_guard.get("blockers", [])[:3],
                }
            )
            continue

        gate = signal.get("quality_gate") or {}
        blockers = ",".join((gate.get("blockers") or [])[:4])
        reason = (
            f"ShadowLabel {side} | win_prob {probability:.4f} | "
            f"gate={gate.get('mode', 'unknown')} | blockers={blockers or 'none'}"
        )
        price = float(signal.get("price") or 0.0) or None
        try:
            opened = _open_paper_trade_internal(
                symbol=paper_symbol,
                side=side,
                volume=max(float(status["volume"]) / 10.0, 0.001),
                price=price,
                entry_source="shadow_label",
                entry_reason=reason,
            )
        except Exception as exc:
            summary["skipped"].append({"symbol": paper_symbol, "reason": f"shadow:open_error:{exc}"})
            continue

        summary.setdefault("shadow_opened", []).append(
            {
                "symbol": paper_symbol,
                "side": side,
                "trade_id": opened["trade_id"],
                "ml_win_prob": round(probability, 4),
                "price": opened["entry_price"],
                "ml_snapshot_attached": opened.get("ml_snapshot_attached"),
            }
        )
        open_symbols.add(paper_symbol)
        open_position_count += 1
    return open_position_count


def _auto_paper_cycle_sync() -> dict:
    from intelligence.tools.market_tools import get_trading_tactics

    status = _auto_paper_status()
    summary = {
        "checked_symbols": [],
        "opened": [],
        "shadow_opened": [],
        "expired_labels": None,
        "skipped": [],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    summary["expired_labels"] = _expire_stale_paper_labels(status["shadow_label_max_age_minutes"])

    with get_persistence_conn() as conn:
        open_rows = conn.execute("SELECT symbol FROM paper_trades WHERE status = 'OPEN'").fetchall()
    open_symbols = {str(row["symbol"]).upper() for row in open_rows}
    open_position_count = len(open_rows)

    if not status["enabled"]:
        _shadow_label_cycle_sync(status, summary, open_symbols, open_position_count)
        return summary

    for symbol in status["symbols"]:
        summary["checked_symbols"].append(symbol)

        if open_position_count >= status["max_open_positions"]:
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
        perf_gate = _auto_paper_performance_gate(symbol, recommendation, "auto_paper")
        if not perf_gate.get("ok", True):
            summary["skipped"].append(
                {
                    "symbol": symbol,
                    "reason": "performance_block",
                    "detail": perf_gate.get("blockers", [])[:3],
                }
            )
            continue
        graph_guard = _trade_graph_guard(symbol, recommendation)
        if graph_guard.get("blockers"):
            summary["skipped"].append(
                {
                    "symbol": symbol,
                    "reason": "graph_guard_block",
                    "detail": graph_guard.get("blockers", [])[:3],
                }
            )
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
        open_position_count += 1

    _shadow_label_cycle_sync(status, summary, open_symbols, open_position_count)
    return summary


async def auto_paper_trader_task():
    logger.info("Auto Paper Trader Task started.")
    await asyncio.sleep(10)

    while True:
        try:
            if _auto_paper_state["enabled"] or _auto_paper_state["shadow_labeling_enabled"]:
                loop = asyncio.get_event_loop()

                # Scan and close finished trades first — notify per closed trade
                try:
                    from intelligence.ml.outcome_tracker import scan_and_update
                    close_summary = await loop.run_in_executor(None, scan_and_update)
                    for ct in close_summary.get("closed_trades", []):
                        try:
                            pnl = ct.get("pnl_usd")
                            asyncio.create_task(notifier.notify_paper_trade_closed(
                                symbol=ct.get("symbol", "?"),
                                outcome=ct.get("outcome", "?"),
                                close_reason=ct.get("close_reason", ""),
                                exit_price=float(ct.get("exit_price") or 0),
                                pnl_usd=float(pnl) if pnl is not None else None,
                            ))
                        except Exception:
                            pass
                except Exception as e:
                    logger.debug(f"Auto-paper close scan: {e}")

                summary = await loop.run_in_executor(None, _auto_paper_cycle_sync)
                _auto_paper_state["last_run_at"] = datetime.now(timezone.utc).isoformat()
                _auto_paper_state["last_summary"] = summary
                _auto_paper_state["last_error"] = None
                opened_count = len(summary.get("opened", []))
                shadow_count = len(summary.get("shadow_opened", []))
                if opened_count or shadow_count:
                    _append_audit_event(
                        "AUTO_PAPER",
                        (
                            f"Opened {opened_count} auto paper trade(s), "
                            f"{shadow_count} shadow label(s): "
                            + ", ".join(
                                f"{item['side']} {item['symbol']}"
                                for item in (summary.get("opened", []) + summary.get("shadow_opened", []))
                            )
                        ),
                    )
                    # Notify Telegram for each opened auto-paper trade
                    for item in summary.get("opened", []):
                        try:
                            asyncio.create_task(notifier.notify_paper_trade_opened(
                                symbol=item["symbol"],
                                side=item["side"],
                                price=float(item.get("price", 0)),
                                confidence=float(item.get("confidence", 0)),
                                trade_id=item.get("trade_id", ""),
                            ))
                        except Exception:
                            pass
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
    if entry_source not in {"shadow_label"}:
        _assert_daily_risk_guard_allows(f"paper_trade:{entry_source}")
        _assert_trade_graph_guard_allows(symbol, side, f"paper_trade:{entry_source}")

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
    from intelligence.ml.signal_model import MODEL_PATH, ML_CORE_SYMBOLS, ML_SUFFICIENCY_TARGETS, get_auto_retrain_status, get_live_sufficiency_status, get_paper_label_quality_report
    from intelligence.ml.paper_analytics import build_side_scorecard
    from intelligence.ml.performance_feedback import get_feedback_snapshot
    from intelligence.ml.readiness import evaluate_readiness
    from intelligence.ml.reporting import build_promotion_summary
    from intelligence.ml.symbol_policy import get_symbol_policy_snapshot
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

    def _safe(label: str, fn, fallback):
        try:
            return fn()
        except Exception as exc:
            logger.warning(f"/api/ml/stats degraded while loading {label}: {exc}")
            if isinstance(fallback, dict):
                payload = dict(fallback)
                payload.setdefault("status", "error")
                payload.setdefault("error", str(exc))
                return payload
            return fallback

    feedback_snapshot = _safe("performance_feedback", lambda: get_feedback_snapshot(), {"items": [], "status": "error"})
    readiness = _safe("readiness", lambda: evaluate_readiness(require_mt5_audit=False), {"status": "error"})
    promotion_summary = _safe("promotion_history", lambda: build_promotion_summary(limit=12), {"items": [], "summary": {}, "status": "error"})
    symbol_policy = _safe("symbol_policy", lambda: get_symbol_policy_snapshot(force_refresh=True), {"items": [], "summary": {}, "status": "error"})
    side_analytics = _safe("side_analytics", lambda: build_side_scorecard(limit=12), {"available": False, "side_scorecard": [], "weak_slices": [], "status": "error"})

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
            "paper_label_quality": bundle.get("paper_label_quality") or get_paper_label_quality_report(force_refresh=True),
            "calibration": bundle.get("calibration"),
            "walk_forward": bundle.get("walk_forward"),
            "sufficiency": get_live_sufficiency_status(bundle if model_exists else None),
            "auto_retrain": get_auto_retrain_status(bundle if model_exists else None),
        },
        "paper_trades": _ml_paper_trade_stats(),
        "performance_feedback": feedback_snapshot,
        "side_analytics": side_analytics,
        "readiness": readiness,
        "promotion_history": promotion_summary,
        "symbol_policy": symbol_policy,
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
            "paper_label_quality": bundle.get("paper_label_quality"),
            "calibration": bundle.get("calibration"),
            "sufficiency": bundle.get("sufficiency"),
        }
    except Exception as e:
        return {"available": False, "report": [], "walk_forward": None, "error": str(e)}


@app.get("/api/ml/paper-label-quality")
async def ml_paper_label_quality():
    def _build():
        from intelligence.ml.signal_model import get_paper_label_quality_report

        return get_paper_label_quality_report(force_refresh=True)

    return await asyncio.to_thread(_build)


@app.get("/api/ml/promotion-history")
async def ml_promotion_history(limit: int = 20):
    def _build():
        from intelligence.ml.reporting import build_promotion_summary

        return build_promotion_summary(limit=limit)

    return await asyncio.to_thread(_build)


@app.get("/api/ml/policies")
async def ml_policies():
    def _build():
        from intelligence.ml.symbol_policy import get_symbol_policy_snapshot

        return get_symbol_policy_snapshot(force_refresh=True)

    return await asyncio.to_thread(_build)


@app.get("/api/ml/policy-overrides")
async def ml_policy_overrides():
    def _build():
        from intelligence.ml.symbol_policy import list_symbol_policy_overrides

        return {"items": list_symbol_policy_overrides()}

    return await asyncio.to_thread(_build)


@app.post("/api/ml/policy-overrides")
async def upsert_ml_policy_override(payload: "SymbolPolicyOverrideRequest"):
    def _build():
        from intelligence.ml.symbol_policy import upsert_symbol_policy_override

        return upsert_symbol_policy_override(
            payload.symbol,
            payload.side,
            payload.action,
            size_multiplier=payload.size_multiplier,
            note=payload.note or "",
        )

    result = await asyncio.to_thread(_build)
    return {"status": "ok", "item": result}


@app.delete("/api/ml/policy-overrides")
async def clear_ml_policy_override(symbol: str, side: str):
    def _build():
        from intelligence.ml.symbol_policy import upsert_symbol_policy_override

        return upsert_symbol_policy_override(symbol, side, "allow")

    result = await asyncio.to_thread(_build)
    return {"status": "ok", "item": result}


@app.get("/api/ml/readiness-report")
async def ml_readiness_report():
    def _build():
        from intelligence.ml.readiness import evaluate_readiness

        return evaluate_readiness(require_mt5_audit=False)

    return await asyncio.to_thread(_build)


@app.get("/api/ml/ops-report")
async def ml_ops_report():
    def _build():
        from intelligence.ml.performance_feedback import get_feedback_snapshot
        from intelligence.ml.paper_analytics import build_side_scorecard
        from intelligence.ml.readiness import evaluate_readiness
        from intelligence.ml.reporting import build_promotion_summary
        from intelligence.ml.signal_model import get_paper_label_quality_report
        from intelligence.ml.symbol_policy import get_symbol_policy_snapshot
        from intelligence.ml.watchdog import build_watchdog_report

        return {
            "readiness": evaluate_readiness(require_mt5_audit=False),
            "paper_label_quality": get_paper_label_quality_report(force_refresh=True),
            "performance_feedback": get_feedback_snapshot(force_refresh=True),
            "promotion_history": build_promotion_summary(limit=20),
            "symbol_policy": get_symbol_policy_snapshot(force_refresh=True),
            "side_analytics": build_side_scorecard(limit=20),
            "watchdog": build_watchdog_report(),
        }

    return await asyncio.to_thread(_build)


@app.get("/api/ml/weak-slices")
async def ml_weak_slices(limit: int = 20):
    def _build():
        from intelligence.ml.paper_analytics import build_side_scorecard

        scorecard = build_side_scorecard(limit=limit)
        return {
            "available": scorecard.get("available", False),
            "weak_slices": scorecard.get("weak_slices", []),
        }

    return await asyncio.to_thread(_build)


@app.get("/api/ml/watchdog")
async def ml_watchdog():
    def _build():
        from intelligence.ml.watchdog import build_watchdog_report, write_watchdog_report

        report = build_watchdog_report()
        write_watchdog_report()
        return report

    return await asyncio.to_thread(_build)


def _build_ml_diagnostics() -> dict[str, Any]:
    import pickle as _pickle
    from intelligence.ml.performance_feedback import get_feedback_snapshot
    from intelligence.ml.signal_model import MODEL_PATH, get_paper_label_quality_report

    bundle: dict[str, Any] = {}
    if MODEL_PATH.exists():
        try:
            with open(MODEL_PATH, "rb") as f:
                bundle = _pickle.load(f)
        except Exception as exc:
            bundle = {"load_error": str(exc)}

    dataset_report = bundle.get("dataset_report") or []
    slice_rows: dict[str, dict[str, Any]] = {}
    for row in dataset_report:
        symbol = str(row.get("symbol") or "")
        asset_class = _symbol_asset_class(symbol)
        target = slice_rows.setdefault(
            asset_class,
            {"samples": 0, "wins": 0, "losses": 0, "symbols": set(), "timeframes": set(), "weak_slices": []},
        )
        samples = int(row.get("samples", 0) or 0)
        wins = int(row.get("wins", 0) or 0)
        losses = int(row.get("losses", 0) or 0)
        target["samples"] += samples
        target["wins"] += wins
        target["losses"] += losses
        target["symbols"].add(symbol)
        target["timeframes"].add(str(row.get("timeframe") or "unknown"))
        win_rate = float(row.get("win_rate", 0.0) or 0.0)
        if samples < 100 or win_rate < 0.35 or win_rate > 0.75:
            target["weak_slices"].append(row)

    slices = {}
    for key, value in slice_rows.items():
        total = max(int(value["wins"]) + int(value["losses"]), 1)
        slices[key] = {
            "samples": int(value["samples"]),
            "win_rate": round(float(value["wins"]) / total, 4),
            "symbols": sorted(value["symbols"]),
            "timeframes": sorted(value["timeframes"]),
            "weak_slices": sorted(value["weak_slices"], key=lambda item: int(item.get("samples", 0) or 0))[:12],
        }

    feedback = get_feedback_snapshot(force_refresh=True)
    paper_quality = get_paper_label_quality_report(force_refresh=True)
    weak_symbols = []
    strong_symbols = []
    for symbol, stats in (feedback.get("symbol") or {}).items():
        row = {"symbol": symbol, **stats}
        if int(stats.get("trades", 0) or 0) < 3:
            continue
        if float(stats.get("pnl", 0.0) or 0.0) < 0 or float(stats.get("avg_pnl", 0.0) or 0.0) < 0:
            weak_symbols.append(row)
        else:
            strong_symbols.append(row)
    weak_symbols.sort(key=lambda item: float(item.get("pnl", 0.0) or 0.0))
    strong_symbols.sort(key=lambda item: float(item.get("pnl", 0.0) or 0.0), reverse=True)

    recommendations = []
    trust = _ml_model_trust_snapshot()
    if not trust.get("trusted"):
        recommendations.append("Keep ML win probability out of /best ranking until model trust passes stricter thresholds.")
    if paper_quality.get("excluded", 0):
        recommendations.append("Continue pruning noisy paper labels before retraining.")
    human_feedback = _setup_feedback_summary(limit=200)
    if human_feedback.get("total", 0):
        recommendations.extend((human_feedback.get("recommendations") or [])[:2])
    if weak_symbols:
        recommendations.append("Throttle or paper-only weak symbols: " + ", ".join(row["symbol"] for row in weak_symbols[:5]))
    if slices:
        recommendations.append("Train/evaluate separate slice models for CRYPTO, MACRO/FOREX, and INDEX instead of one global model.")

    return {
        "model_trust": trust,
        "model": {
            "n_samples": bundle.get("n_samples"),
            "accuracy": bundle.get("accuracy"),
            "roc_auc": bundle.get("roc_auc"),
            "trained_at": bundle.get("trained_at"),
            "promotion_gate": bundle.get("promotion_gate"),
            "walk_forward": bundle.get("walk_forward"),
        },
        "slices": slices,
        "paper_label_quality": paper_quality,
        "human_feedback": human_feedback,
        "performance": {
            "weak_symbols": weak_symbols[:10],
            "strong_symbols": strong_symbols[:10],
            "strategy": feedback.get("strategy", {}),
            "symbol_side": feedback.get("symbol_side", {}),
        },
        "recommendations": recommendations,
    }


@app.get("/api/ml/diagnostics")
async def ml_diagnostics(request: Request):
    require_request_api_key(request)
    return await asyncio.to_thread(_build_ml_diagnostics)


@app.get("/api/setup-feedback")
async def setup_feedback(request: Request, chat_id: str | None = None):
    require_request_api_key(request)
    return await asyncio.to_thread(_setup_feedback_summary, chat_id, 500)


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


@app.get("/api/ml/trading-readiness")
async def ml_trading_readiness(symbol: str | None = None, force_refresh: bool = False):
    def _build():
        from intelligence.ml.trading_quality_gate import get_trading_quality_gate
        from intelligence.ml.readiness import evaluate_readiness

        gate = get_trading_quality_gate(
            symbol=symbol,
            entry_source="signal_feed_analysis",
            force_refresh=force_refresh,
        )
        readiness = evaluate_readiness(require_mt5_audit=False)
        return gate, readiness

    gate, readiness = await asyncio.to_thread(_build)
    return {
        "ready_for_live_ai_trading": bool(gate.get("live_ready")),
        "signal_mode": gate.get("mode"),
        "quality_gate": gate,
        "readiness": {
            "passed": bool(readiness.get("passed")),
            "blockers": readiness.get("blockers", []),
            "thresholds": readiness.get("thresholds", {}),
            "model": readiness.get("model", {}),
            "paper": readiness.get("paper", {}),
        },
        "message": (
            "AI signals are live-trading ready."
            if gate.get("live_ready")
            else "AI signals are restricted to observe/paper mode until model and paper-trade evidence improves."
        ),
    }


_retrain_task: asyncio.Task | None = None


def _start_ml_retrain_task(trigger_reason: str = "manual") -> bool:
    global _retrain_task
    if _retrain_task and not _retrain_task.done():
        return False

    async def _run():
        from intelligence.ml.reporting import record_promotion_event
        from intelligence.ml.train_v8 import train
        import intelligence.ml.signal_model as _sm
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, train)
        history_row = await loop.run_in_executor(None, record_promotion_event, result, trigger_reason)
        _sm._MODEL_CACHE = None  # invalidate in-memory cache so next load picks up new model
        _append_audit_event(
            "ML_RETRAIN",
            f"{trigger_reason} -> {result.get('status')} auc={result.get('roc_auc')} acc={result.get('accuracy')}",
        )
        logger.info(f"[ML-Retrain] done ({trigger_reason}): {result}")
        try:
            summary_lines = [
                f"ML retrain: {result.get('status')}",
                f"Trigger: {trigger_reason}",
                f"AUC: {result.get('roc_auc')}",
                f"Accuracy: {result.get('accuracy')}",
                f"WF AUC: {((result.get('walk_forward') or {}).get('summary') or {}).get('avg_roc_auc')}",
                f"Paper labels: {(result.get('paper_label_quality') or {}).get('included')}",
                f"History row: {history_row.get('id')}",
            ]
            override_reason = ((result.get("promotion_gate") or {}).get("override_reason") or "").strip()
            if override_reason:
                summary_lines.append(f"Override: {override_reason}")
            blockers = (result.get("promotion_gate") or {}).get("blockers") or []
            if blockers:
                summary_lines.append("Blockers: " + ", ".join(str(item) for item in blockers[:3]))
            await notifier.send_telegram_alert("\n".join(summary_lines))
        except Exception as exc:
            logger.warning(f"[ML-Retrain] notification failed: {exc}")

    _retrain_task = asyncio.create_task(_run())
    logger.info(f"[ML-Retrain] started ({trigger_reason})")
    return True


def _maybe_trigger_auto_retrain(trigger_source: str) -> dict:
    from intelligence.ml.signal_model import get_auto_retrain_status

    status = get_auto_retrain_status()
    if not status.get("recommended"):
        return {"checked": True, "recommended": False, "started": False, "reasons": status.get("reasons", [])}

    reasons = status.get("reasons", [])
    outcome_reasons = [reason for reason in reasons if reason != "model_age"]
    if not outcome_reasons:
        return {
            "checked": True,
            "recommended": True,
            "started": False,
            "reasons": reasons,
            "deferred": "model_age_only_waiting_for_closed_labels",
        }

    started = _start_ml_retrain_task(f"auto:{trigger_source}")
    return {
        "checked": True,
        "recommended": True,
        "started": started,
        "reasons": reasons,
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
    require_request_api_key(request)

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
    require_request_api_key(request)

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


class SymbolPolicyOverrideRequest(BaseModel):
    symbol: str
    side: str
    action: str
    size_multiplier: Optional[float] = None
    note: Optional[str] = ""

@app.post("/api/history")
async def save_history(session: ChatSessionSave, request: Request):
    """Save or update a chat session and its full message history."""
    require_request_api_key(request)

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
    require_request_api_key(request)

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
