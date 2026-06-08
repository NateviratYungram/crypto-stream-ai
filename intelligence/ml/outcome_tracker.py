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
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)

PAPER_DB = os.getenv("PAPER_TRADE_DB", "persistence.db")

_CRYPTO_ASSET_HINTS = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "MATIC", "LINK"]


def _connect():
    return sqlite3.connect(PAPER_DB)


@contextmanager
def _managed_connection() -> Iterator[sqlite3.Connection]:
    con = _connect()
    try:
        yield con
    finally:
        con.close()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_asset_class(symbol: str) -> str:
    upper = str(symbol or "").upper()
    return "CRYPTO" if any(token in upper for token in _CRYPTO_ASSET_HINTS) else "MACRO"


def _evaluate_trade_outcome(side: str, price: float, sl: Optional[float], tp: Optional[float]) -> tuple[Optional[str], str]:
    if side == "BUY":
        if sl is not None and price <= sl:
            return "LOSS", f"SL hit @ {price}"
        if tp is not None and price >= tp:
            return "WIN", f"TP hit @ {price}"
    elif side == "SELL":
        if sl is not None and price >= sl:
            return "LOSS", f"SL hit @ {price}"
        if tp is not None and price <= tp:
            return "WIN", f"TP hit @ {price}"
    return None, ""


def _refresh_policy_caches() -> None:
    from intelligence.ml.symbol_threshold import refresh_threshold_cache
    from intelligence.ml.symbol_policy import refresh_symbol_policy_cache

    refresh_threshold_cache()
    refresh_symbol_policy_cache()


def migrate_schema():
    """Add sl, tp, outcome, features_json columns if they don't exist."""
    with _managed_connection() as con:
        cur = con.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_trades (
                id TEXT PRIMARY KEY,
                symbol TEXT, side TEXT, volume REAL,
                entry_price REAL, current_price REAL,
                pnl_usd REAL, status TEXT,
                opened_at TEXT, closed_at TEXT
            )
            """
        )
        for col, typedef in [
            ("sl", "REAL"),
            ("tp", "REAL"),
            ("exit_price", "REAL"),
            ("outcome", "TEXT"),
            ("features_json", "TEXT"),
            ("ml_score", "REAL"),
            ("close_reason", "TEXT"),
            ("label_source", "TEXT"),
            ("signal_grade", "TEXT"),
            ("macro_bias", "TEXT"),
        ]:
            try:
                cur.execute(f"ALTER TABLE paper_trades ADD COLUMN {col} {typedef}")
            except sqlite3.OperationalError:
                pass
        con.commit()


def get_open_trades() -> List[Dict]:
    migrate_schema()
    with _managed_connection() as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute("SELECT * FROM paper_trades WHERE status='OPEN'")
        return [dict(r) for r in cur.fetchall()]


def _fetch_price(symbol: str) -> Optional[float]:
    try:
        from intelligence.technical_engine import get_kline_data

        df = get_kline_data(symbol, timeframe="1m", limit=2, asset_class=_resolve_asset_class(symbol))
        if df is not None and not df.empty:
            return float(df["Close"].iloc[-1])
    except Exception as e:
        logger.warning("[OutcomeTracker] price fetch failed for %s: %s", symbol, e)
    return None


def _close_trade(trade_id: str, current_price: float, outcome: str, reason: str):
    with _managed_connection() as con:
        cur = con.cursor()
        cur.execute(
            """
            UPDATE paper_trades
            SET status='CLOSED', closed_at=?, current_price=?, outcome=?,
                exit_price=?, close_reason=?, label_source='auto_tracker',
                pnl_usd=CASE
                    WHEN side='BUY'  THEN (? - entry_price) * volume
                    WHEN side='SELL' THEN (entry_price - ?) * volume
                    ELSE 0
                END
            WHERE id=?
            """,
            (
                _utc_now_iso(),
                current_price,
                outcome,
                current_price,
                reason,
                current_price,
                current_price,
                trade_id,
            ),
        )
        con.commit()
    logger.info("[OutcomeTracker] Trade %s closed -> %s (%s) @ %s", trade_id, outcome, reason, current_price)


def scan_and_update(fetch_price=None, close_trade=None, refresh_caches: bool = True) -> Dict:
    """
    Check all OPEN paper trades. Auto-close any that have hit SL or TP.
    Returns a summary of actions taken.
    """
    migrate_schema()
    trades = get_open_trades()
    price_fetcher = fetch_price or _fetch_price
    close_trade_fn = close_trade or _close_trade
    closed_win = 0
    closed_loss = 0
    errors = 0
    closed_trades: List[Dict] = []

    for trade in trades:
        tid = trade["id"]
        sym = trade["symbol"]
        side = trade["side"]
        sl = trade.get("sl")
        tp = trade.get("tp")

        if sl is None and tp is None:
            continue

        price = price_fetcher(sym)
        if price is None:
            errors += 1
            continue

        outcome, reason = _evaluate_trade_outcome(side, price, sl, tp)
        if not outcome:
            continue

        close_trade_fn(tid, price, outcome, reason)
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
        "scanned": len(trades),
        "closed_win": closed_win,
        "closed_loss": closed_loss,
        "errors": errors,
        "closed_trades": closed_trades,
        "timestamp": _utc_now_iso(),
    }
    logger.info("[OutcomeTracker] scan_and_update: %s", summary)

    if refresh_caches and (closed_win + closed_loss) > 0:
        try:
            _refresh_policy_caches()
        except Exception as e:
            logger.warning("[OutcomeTracker] threshold update failed: %s", e)

    return summary


def attach_sl_tp_features(
    trade_id: str,
    sl: Optional[float],
    tp: Optional[float],
    features: Dict,
    ml_score: Optional[float] = None,
    signal_grade: Optional[str] = None,
    macro_bias: Optional[str] = None,
):
    """
    Store SL, TP, ML features and predicted win probability on an existing OPEN paper trade.
    Call this right after opening a paper trade so outcome_tracker can evaluate it.
    """
    migrate_schema()
    with _managed_connection() as con:
        cur = con.cursor()
        cur.execute(
            """
            UPDATE paper_trades
            SET sl=?, tp=?, features_json=?, ml_score=?, signal_grade=?, macro_bias=?
            WHERE id=? AND status='OPEN'
            """,
            (sl, tp, json.dumps(features), ml_score, signal_grade, macro_bias, trade_id),
        )
        con.commit()


def get_ml_stats() -> Dict:
    """Return win rate and trade counts from closed labeled paper trades."""
    migrate_schema()
    with _managed_connection() as con:
        cur = con.cursor()
        cur.execute(
            """
            SELECT outcome, COUNT(*) as cnt
            FROM paper_trades
            WHERE status='CLOSED' AND outcome IS NOT NULL
            GROUP BY outcome
            """
        )
        rows = dict(cur.fetchall())
    wins = rows.get("WIN", 0)
    losses = rows.get("LOSS", 0)
    total = wins + losses
    return {
        "total_labeled": total,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / total, 4) if total > 0 else None,
    }
