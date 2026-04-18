import os
import logging
import json
import psycopg2
from datetime import datetime
from typing import Dict, Any

logger = logging.getLogger(__name__)

def _get_db_conn():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "crypto_stream_db"),
        user=os.getenv("DB_USER", "user"),
        password=os.getenv("DB_PASS", "password"),
    )

def initialize_snapshot_table():
    """Create the account_snapshots table if it doesn't exist."""
    conn = None
    try:
        conn = _get_db_conn()
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS account_snapshots (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    balance DECIMAL(18, 2),
                    equity DECIMAL(18, 2),
                    margin_level DECIMAL(10, 2),
                    total_pnl DECIMAL(18, 2),
                    position_count INTEGER,
                    asset_breakdown JSONB
                );
            """)
        conn.commit()
        logger.info("Account snapshot table initialized.")
        return True
    except Exception as e:
        logger.error(f"Failed to initialize snapshot table: {e}")
        return False
    finally:
        if conn:
            conn.close()

def take_account_snapshot() -> Dict[str, Any]:
    """Capture current MT5 account state and save to database."""
    conn = None
    try:
        from intelligence.mt5_connector import get_mt5_account_info, initialize_mt5
        import MetaTrader5 as mt5
        
        if not initialize_mt5():
            return {"error": "Failed to connect to MT5"}
            
        account = get_mt5_account_info()
        positions = mt5.positions_get()
        
        balance = account.get("balance", 0)
        equity = account.get("equity", 0)
        margin_level = account.get("margin_level", 0)
        total_pnl = account.get("profit", 0)
        pos_count = len(positions) if positions else 0
        
        # Build asset breakdown
        breakdown = {}
        if positions:
            for p in positions:
                symbol = p.symbol
                breakdown[symbol] = breakdown.get(symbol, 0) + p.volume

        conn = _get_db_conn()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO account_snapshots 
                (balance, equity, margin_level, total_pnl, position_count, asset_breakdown)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id;
            """, (balance, equity, margin_level, total_pnl, pos_count, json.dumps(breakdown)))
            snapshot_id = cur.fetchone()[0]
        conn.commit()
        
        logger.info(f"Account snapshot captured. ID: {snapshot_id}")
        return {
            "status": "SUCCESS",
            "snapshot_id": snapshot_id,
            "equity": equity,
            "positions": pos_count
        }
    except Exception as e:
        logger.error(f"Error taking snapshot: {e}")
        return {"error": str(e)}
    finally:
        if conn:
            conn.close()
