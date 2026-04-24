import sqlite3
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)
PERSISTENCE_DB = "persistence.db"

def save_trade_draft(
    draft_id: str,
    session_id: str,
    symbol: str,
    action: str,
    volume: float,
    sl: Optional[float] = None,
    tp: Optional[float] = None,
    comment: str = ""
) -> bool:
    """Saves a trade draft to the persistent SQLite database."""
    try:
        conn = sqlite3.connect(PERSISTENCE_DB)
        cursor = conn.cursor()
        created_at = datetime.now(timezone.utc).isoformat()

        cursor.execute("""
            INSERT INTO trade_drafts (id, session_id, symbol, action, volume, sl, tp, comment, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (draft_id, session_id, symbol, action.upper(), volume, sl, tp, comment, created_at))

        conn.commit()
        conn.close()
        logger.info(f"Persistence: Draft {draft_id} saved successfully.")
        return True
    except Exception as e:
        logger.error(f"Persistence: Failed to save draft {draft_id}: {e}")
        return False

def get_trade_draft(draft_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves a trade draft from the database."""
    try:
        conn = sqlite3.connect(PERSISTENCE_DB)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Support case-insensitive draft_id
        cursor.execute("SELECT * FROM trade_drafts WHERE UPPER(id) = UPPER(?)", (draft_id,))
        row = cursor.fetchone()
        conn.close()

        if row:
            return dict(row)
        return None
    except Exception as e:
        logger.error(f"Persistence: Error retrieving draft {draft_id}: {e}")
        return None

def delete_trade_draft(draft_id: str) -> bool:
    """Deletes a trade draft from the database."""
    try:
        conn = sqlite3.connect(PERSISTENCE_DB)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM trade_drafts WHERE UPPER(id) = UPPER(?)", (draft_id,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Persistence: Error deleting draft {draft_id}: {e}")
        return False

def register_active_trade(ticket: int, symbol: str, entry: float, tp1: float, draft_id: str) -> bool:
    """Registers an executed MT5 trade for monitoring (Break-Even, etc.)."""
    try:
        conn = sqlite3.connect(PERSISTENCE_DB)
        cursor = conn.cursor()
        created_at = datetime.now(timezone.utc).isoformat()
        cursor.execute("""
            INSERT INTO active_trades (ticket, symbol, entry_price, tp1, be_triggered, draft_id, created_at)
            VALUES (?, ?, ?, ?, 0, ?, ?)
        """, (ticket, symbol, entry, tp1, draft_id, created_at))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Persistence: Failed to register active trade {ticket}: {e}")
        return False

def get_active_trades() -> List[Dict[str, Any]]:
    """Retrieves all active trades currently being monitored."""
    try:
        conn = sqlite3.connect(PERSISTENCE_DB)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM active_trades WHERE be_triggered = 0")
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Persistence: Error retrieving active trades: {e}")
        return []

def mark_trade_be_triggered(ticket: int) -> bool:
    """Flags a trade as having its Break-Even stop-loss triggered."""
    try:
        conn = sqlite3.connect(PERSISTENCE_DB)
        cursor = conn.cursor()
        cursor.execute("UPDATE active_trades SET be_triggered = 1 WHERE ticket = ?", (ticket,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Persistence: Error marking BE for trade {ticket}: {e}")
        return False

def init_v6_tables():
    """Ensures Intelligence V6 specific tables exist."""
    try:
        conn = sqlite3.connect(PERSISTENCE_DB)
        cursor = conn.cursor()
        # Daily performance for Equity Protection
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_performance (
                date TEXT PRIMARY KEY,
                balance REAL,
                equity REAL,
                drawdown REAL
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Persistence: Failed to init V6 tables: {e}")

def log_daily_balance(balance: float, equity: float):
    """Logs the daily balance and equity for drawdown protection."""
    try:
        init_v6_tables()
        conn = sqlite3.connect(PERSISTENCE_DB)
        cursor = conn.cursor()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        dd = ((balance - equity) / balance * 100) if balance > 0 else 0
        cursor.execute("""
            INSERT OR REPLACE INTO daily_performance (date, balance, equity, drawdown)
            VALUES (?, ?, ?, ?)
        """, (today, balance, equity, dd))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Persistence: Failed to log daily balance: {e}")
        return False

def log_sniper_rejection(symbol: str, confidence: float, reasoning: str, price: float = 0.0) -> bool:
    """Logs a rejected signal in the Sniper Audit Log for Intelligence V7."""
    try:
        conn = sqlite3.connect(PERSISTENCE_DB)
        cursor = conn.cursor()
        created_at = datetime.now(timezone.utc).isoformat()
        cursor.execute("""
            INSERT INTO sniper_audit_log (symbol, confidence, reasoning, price, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (symbol.upper(), confidence, reasoning, price, created_at))
        conn.commit()
        conn.close()
        logger.info(f"Sniper Audit: Logged rejection for {symbol} ({confidence:.0%})")
        return True
    except Exception as e:
        logger.error(f"Sniper Audit: Failed to log rejection: {e}")
        return False
