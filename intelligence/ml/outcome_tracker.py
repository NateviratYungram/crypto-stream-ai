# -*- coding: utf-8 -*-
"""
Paper Trade Outcome Tracker

- Migrates paper_trades table to add sl, tp, outcome, features_json columns
- Scans all OPEN paper trades, fetches current price, auto-closes if SL/TP hit
- Closed trades with features_json feed back into ML training data
"""
import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

PAPER_DB = os.getenv("PAPER_TRADE_DB", "persistence.db")


# ─────────────────────────────────────────────────────────────────────────────
# Schema Migration
# ─────────────────────────────────────────────────────────────────────────────

def migrate_schema():
    """Add sl, tp, outcome, features_json columns if they don't exist."""
    con = sqlite3.connect(PAPER_DB)
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
    # Add new columns safely
    for col, typedef in [
        ("sl",           "REAL"),
        ("tp",           "REAL"),
        ("exit_price",   "REAL"),
        ("outcome",      "TEXT"),
        ("features_json","TEXT"),
        ("ml_score",     "REAL"),
        ("close_reason", "TEXT"),
        ("label_source", "TEXT"),
    ]:
        try:
            cur.execute(f"ALTER TABLE paper_trades ADD COLUMN {col} {typedef}")
        except sqlite3.OperationalError:
            pass  # column already exists
    con.commit()
    con.close()


# ─────────────────────────────────────────────────────────────────────────────
# Open Trade Fetcher
# ─────────────────────────────────────────────────────────────────────────────

def get_open_trades() -> List[Dict]:
    migrate_schema()
    con = sqlite3.connect(PAPER_DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("SELECT * FROM paper_trades WHERE status='OPEN'")
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Price Fetcher
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_price(symbol: str) -> Optional[float]:
    try:
        from intelligence.technical_engine import get_kline_data
        asset_class = (
            "CRYPTO" if any(c in symbol.upper() for c in ["BTC","ETH","SOL","BNB","XRP","DOGE","ADA","AVAX","MATIC","LINK"])
            else "MACRO"
        )
        df = get_kline_data(symbol, timeframe="1m", limit=2, asset_class=asset_class)
        if df is not None and not df.empty:
            return float(df["Close"].iloc[-1])
    except Exception as e:
        logger.warning(f"[OutcomeTracker] price fetch failed for {symbol}: {e}")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Close Trade + Record Outcome
# ─────────────────────────────────────────────────────────────────────────────

def _close_trade(trade_id: str, current_price: float, outcome: str, reason: str):
    con = sqlite3.connect(PAPER_DB)
    cur = con.cursor()
    cur.execute("""
        UPDATE paper_trades
        SET status='CLOSED', closed_at=?, current_price=?, outcome=?,
            exit_price=?, close_reason=?, label_source='auto_tracker',
            pnl_usd=CASE
                WHEN side='BUY'  THEN (? - entry_price) * volume
                WHEN side='SELL' THEN (entry_price - ?) * volume
                ELSE 0
            END
        WHERE id=?
    """, (
        datetime.now(timezone.utc).isoformat(),
        current_price,
        outcome,
        current_price,
        reason,
        current_price, current_price,
        trade_id,
    ))
    con.commit()
    con.close()
    logger.info(f"[OutcomeTracker] Trade {trade_id} closed → {outcome} ({reason}) @ {current_price}")


# ─────────────────────────────────────────────────────────────────────────────
# Main Scan Loop
# ─────────────────────────────────────────────────────────────────────────────

def scan_and_update() -> Dict:
    """
    Check all OPEN paper trades. Auto-close any that have hit SL or TP.
    Returns a summary of actions taken.
    """
    migrate_schema()
    trades = get_open_trades()
    closed_win  = 0
    closed_loss = 0
    errors      = 0
    closed_trades: List[Dict] = []

    for trade in trades:
        tid    = trade["id"]
        sym    = trade["symbol"]
        side   = trade["side"]
        sl     = trade.get("sl")
        tp     = trade.get("tp")
        trade.get("entry_price", 0)

        if sl is None and tp is None:
            continue  # no SL/TP stored — can't evaluate

        price = _fetch_price(sym)
        if price is None:
            errors += 1
            continue

        outcome = None
        reason  = ""

        if side == "BUY":
            if sl is not None and price <= sl:
                outcome, reason = "LOSS", f"SL hit @ {price}"
            elif tp is not None and price >= tp:
                outcome, reason = "WIN", f"TP hit @ {price}"
        elif side == "SELL":
            if sl is not None and price >= sl:
                outcome, reason = "LOSS", f"SL hit @ {price}"
            elif tp is not None and price <= tp:
                outcome, reason = "WIN", f"TP hit @ {price}"

        if outcome:
            _close_trade(tid, price, outcome, reason)
            closed_trades.append(
                {
                    "trade_id": tid,
                    "symbol": sym,
                    "outcome": outcome,
                    "close_reason": reason,
                    "label_source": "auto_tracker",
                    "exit_price": float(price),
                }
            )
            if outcome == "WIN":
                closed_win += 1
            else:
                closed_loss += 1

    summary = {
        "scanned":     len(trades),
        "closed_win":  closed_win,
        "closed_loss": closed_loss,
        "errors":      errors,
        "closed_trades": closed_trades,
        "timestamp":   datetime.now(timezone.utc).isoformat(),
    }
    logger.info(f"[OutcomeTracker] scan_and_update: {summary}")
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# Helper: Attach SL/TP + features when opening a paper trade
# ─────────────────────────────────────────────────────────────────────────────

def attach_sl_tp_features(trade_id: str, sl: float, tp: float, features: Dict, ml_score: Optional[float] = None):
    """
    Store SL, TP, ML features and predicted win probability on an existing OPEN paper trade.
    Call this right after opening a paper trade so outcome_tracker can evaluate it.
    """
    migrate_schema()
    con = sqlite3.connect(PAPER_DB)
    cur = con.cursor()
    cur.execute("""
        UPDATE paper_trades
        SET sl=?, tp=?, features_json=?, ml_score=?
        WHERE id=? AND status='OPEN'
    """, (sl, tp, json.dumps(features), ml_score, trade_id))
    con.commit()
    con.close()


# ─────────────────────────────────────────────────────────────────────────────
# Stats
# ─────────────────────────────────────────────────────────────────────────────

def get_ml_stats() -> Dict:
    """Return win rate and trade counts from closed labeled paper trades."""
    migrate_schema()
    con = sqlite3.connect(PAPER_DB)
    cur = con.cursor()
    cur.execute("""
        SELECT outcome, COUNT(*) as cnt
        FROM paper_trades
        WHERE status='CLOSED' AND outcome IS NOT NULL
        GROUP BY outcome
    """)
    rows = dict(cur.fetchall())
    con.close()
    wins   = rows.get("WIN",  0)
    losses = rows.get("LOSS", 0)
    total  = wins + losses
    return {
        "total_labeled": total,
        "wins":          wins,
        "losses":        losses,
        "win_rate":      round(wins / total, 4) if total > 0 else None,
    }
