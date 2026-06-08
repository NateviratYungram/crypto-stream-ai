import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)
PERSISTENCE_DB = os.getenv("PAPER_TRADE_DB", "data/persistence.db")


def _connect(row_factory=None):
    conn = sqlite3.connect(PERSISTENCE_DB)
    if row_factory is not None:
        conn.row_factory = row_factory
    return conn


@contextmanager
def _managed_connection(row_factory=None):
    conn = _connect(row_factory=row_factory)
    try:
        yield conn
    finally:
        conn.close()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def save_trade_draft(
    draft_id: str,
    session_id: str,
    symbol: str,
    action: str,
    volume: float,
    sl: Optional[float] = None,
    tp: Optional[float] = None,
    comment: str = "",
) -> bool:
    """Saves a trade draft to the persistent SQLite database."""
    try:
        with _managed_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO trade_drafts (id, session_id, symbol, action, volume, sl, tp, comment, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (draft_id, session_id, symbol, action.upper(), volume, sl, tp, comment, _utc_now_iso()),
            )
            conn.commit()
        logger.info("Persistence: Draft %s saved successfully.", draft_id)
        return True
    except Exception as e:
        logger.error("Persistence: Failed to save draft %s: %s", draft_id, e)
        return False


def get_trade_draft(draft_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves a trade draft from the database."""
    try:
        with _managed_connection(row_factory=sqlite3.Row) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM trade_drafts WHERE UPPER(id) = UPPER(?)", (draft_id,))
            row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        logger.error("Persistence: Error retrieving draft %s: %s", draft_id, e)
        return None


def delete_trade_draft(draft_id: str) -> bool:
    """Deletes a trade draft from the database."""
    try:
        with _managed_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM trade_drafts WHERE UPPER(id) = UPPER(?)", (draft_id,))
            conn.commit()
        return True
    except Exception as e:
        logger.error("Persistence: Error deleting draft %s: %s", draft_id, e)
        return False


def register_active_trade(ticket: int, symbol: str, entry: float, tp1: float, draft_id: str) -> bool:
    """Registers an executed MT5 trade for monitoring (Break-Even, etc.)."""
    try:
        with _managed_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO active_trades (ticket, symbol, entry_price, tp1, be_triggered, draft_id, created_at)
                VALUES (?, ?, ?, ?, 0, ?, ?)
                """,
                (ticket, symbol, entry, tp1, draft_id, _utc_now_iso()),
            )
            conn.commit()
        return True
    except Exception as e:
        logger.error("Persistence: Failed to register active trade %s: %s", ticket, e)
        return False


def get_active_trades() -> List[Dict[str, Any]]:
    """Retrieves all active trades currently being monitored."""
    try:
        with _managed_connection(row_factory=sqlite3.Row) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM active_trades WHERE be_triggered = 0")
            rows = cursor.fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error("Persistence: Error retrieving active trades: %s", e)
        return []


def mark_trade_be_triggered(ticket: int) -> bool:
    """Flags a trade as having its Break-Even stop-loss triggered."""
    try:
        with _managed_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE active_trades SET be_triggered = 1 WHERE ticket = ?", (ticket,))
            conn.commit()
        return True
    except Exception as e:
        logger.error("Persistence: Error marking BE for trade %s: %s", ticket, e)
        return False


def init_v6_tables():
    """Ensures Intelligence V6 specific tables exist."""
    try:
        with _managed_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_performance (
                    date TEXT PRIMARY KEY,
                    balance REAL,
                    equity REAL,
                    drawdown REAL
                )
                """
            )
            conn.commit()
    except Exception as e:
        logger.error("Persistence: Failed to init V6 tables: %s", e)


def _calculate_drawdown(balance: float, equity: float) -> float:
    return ((balance - equity) / balance * 100) if balance > 0 else 0


def log_daily_balance(balance: float, equity: float):
    """Logs the daily balance and equity for drawdown protection."""
    try:
        init_v6_tables()
        with _managed_connection() as conn:
            cursor = conn.cursor()
            today = _utc_now().strftime("%Y-%m-%d")
            dd = _calculate_drawdown(balance, equity)
            cursor.execute(
                """
                INSERT OR REPLACE INTO daily_performance (date, balance, equity, drawdown)
                VALUES (?, ?, ?, ?)
                """,
                (today, balance, equity, dd),
            )
            conn.commit()
        return True
    except Exception as e:
        logger.error("Persistence: Failed to log daily balance: %s", e)
        return False


def log_sniper_rejection(symbol: str, confidence: float, reasoning: str, price: float = 0.0) -> bool:
    """Logs a rejected signal in the Sniper Audit Log for Intelligence V7."""
    try:
        with _managed_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO sniper_audit_log (symbol, confidence, reasoning, price, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (symbol.upper(), confidence, reasoning, price, _utc_now_iso()),
            )
            conn.commit()
        logger.info("Sniper Audit: Logged rejection for %s (%.0f%%)", symbol, confidence * 100.0)
        return True
    except Exception as e:
        logger.error("Sniper Audit: Failed to log rejection: %s", e)
        return False
