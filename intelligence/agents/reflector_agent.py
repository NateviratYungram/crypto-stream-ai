"""
CryptoStream AI — Reflector Agent
Institutional reflexive memory engine for Intelligence V5.
Analyzes past outcomes to improve future decision confidence.
"""

import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List

logger = logging.getLogger(__name__)
PAPER_DB = os.getenv("PAPER_TRADE_DB", "persistence.db")


@contextmanager
def _connect_paper_db() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(PAPER_DB)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def get_recent_outcomes(limit: int = 10) -> List[Dict[str, Any]]:
    """Retrieves the last N closed trades with their outcomes and metadata."""
    try:
        if not os.path.exists(PAPER_DB):
            return []

        with _connect_paper_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT symbol, side, entry_price, current_price, outcome, pnl_usd, ml_score, closed_at, features_json
                FROM paper_trades
                WHERE status = 'CLOSED' AND outcome IS NOT NULL
                ORDER BY closed_at DESC
                LIMIT ?
            """, (limit,))
            return [dict(r) for r in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Reflector: Failed to fetch outcomes: {e}")
        return []

def generate_reflexive_lessons(client, model_id: str) -> str:
    """
    Analyzes the last 10 trades and generates a concise 'Lessons Learned' summary.
    This context is injected into the Master Agent's decision loop.
    """
    outcomes = get_recent_outcomes(10)
    if not outcomes:
        return "No recent trade history available for reflection. Strategy focus: Baseline ICT/SMC compliance."

    # Summarize stats
    wins = sum(1 for o in outcomes if o['outcome'] == 'WIN')
    losses = sum(1 for o in outcomes if o['outcome'] == 'LOSS')
    win_rate = (wins / len(outcomes)) if outcomes else 0
    total_pnl = sum(o['pnl_usd'] for o in outcomes if o['pnl_usd'] is not None)

    history_summary = []
    for o in outcomes:
        history_summary.append(
            f"- {o['symbol']} {o['side']}: {o['outcome']} (PnL: ${o['pnl_usd']:.2f}, ML Score: {o.get('ml_score','?')})"
        )

    prompt = f"""You are the Institutional Reflector Agent for CryptoStream AI (Intelligence V5).
Your task is to review the last {len(outcomes)} trades and extract 3 sharp, actionable lessons.
Identify patterns in failures (e.g., 'Entering too early in Asia session', 'Ignoring VIX spikes') or successes.

=== RECENT TRADE HISTORY ===
Stats: {wins}W / {losses}L (Win Rate: {win_rate:.1%}) | Net PnL: ${total_pnl:.2f}

{chr(10).join(history_summary)}

=== INSTRUCTIONS ===
1. Be brutally clinical.
2. Focus on RECURRING mistakes or strengths.
3. Output ONLY a concise bulleted list of 3 lessons for the Master Agent.
4. If there is a shift in market regime (e.g. recent losses in trending markets), call it out.

Format:
* LESSON 1: ...
* LESSON 2: ...
* LESSON 3: ...
"""

    try:
        response = client.models.generate_content(
            model=model_id,
            contents=prompt,
        )
        return response.text.strip()
    except Exception as e:
        logger.error(f"Reflector: LLM generation failed: {e}")
        return f"Reflexive analysis failed. Quick Stats: {wins}W/{losses}L. Focus on rigorous risk management."

def get_bias_adjustments(outcomes: List[Dict[str, Any]] = None) -> Dict[str, float]:
    """
    Calculates suggested weighting shifts for the Master Agent.
    If recent performance is poor, it suggests reducing technical weights.
    """
    if outcomes is None:
        outcomes = get_recent_outcomes(10)

    if not outcomes:
        return {"tech_weight": 1.0, "sent_weight": 1.0, "conf_weight": 1.0, "risk_scale": 1.0}

    # Simple logic: If win rate < 40%, reduce technical weight & scale down risk
    wins = sum(1 for o in outcomes if o['outcome'] == 'WIN')
    win_rate = wins / len(outcomes)

    adj = {
        "tech_weight": 1.0,
        "sent_weight": 1.0,
        "conf_weight": 1.0,
        "risk_scale": 1.0
    }

    if win_rate < 0.4:
        logger.info(f"🧠 Reflector CORE: Recent Win Rate {win_rate:.1%} is LOW. Applying defensive adjustments.")
        adj["tech_weight"] = 0.8  # Trust technicals 20% less
        adj["risk_scale"] = 0.5   # Scale down Kelly size by 50%
    elif win_rate > 0.7:
        logger.info(f"🧠 Reflector CORE: Recent Win Rate {win_rate:.1%} is HIGH. Applying opportunistic adjustments.")
        adj["risk_scale"] = 1.2   # 20% boost to sizing (with caution)

    return adj

def get_symbol_outcomes(symbol: str, timeframe: str = None, limit: int = 5) -> List[Dict[str, Any]]:
    """Last N closed trades for a specific symbol (optionally filtered by timeframe)."""
    try:
        if not os.path.exists(PAPER_DB):
            return []
        with _connect_paper_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT symbol, side, entry_price, outcome, pnl_usd,
                       ml_score, closed_at, signal_grade, macro_bias
                FROM paper_trades
                WHERE status='CLOSED' AND outcome IS NOT NULL AND symbol=?
                ORDER BY closed_at DESC LIMIT ?
            """, (symbol.upper(), limit))
            return [dict(r) for r in cursor.fetchall()]
    except Exception as e:
        logger.warning(f"Reflector: symbol outcomes failed for {symbol}: {e}")
        return []


def format_symbol_memory(symbol: str, timeframe: str = None, limit: int = 5) -> str:
    """Compact symbol-specific trade history block for LLM context injection."""
    rows = get_symbol_outcomes(symbol, timeframe, limit)
    if not rows:
        return f"No closed {symbol} trade history on record — treat as first encounter."
    wins = sum(1 for r in rows if str(r.get("outcome", "")).upper() == "WIN")
    losses = len(rows) - wins
    total_pnl = sum(float(r.get("pnl_usd") or 0) for r in rows)
    wr = wins / len(rows)
    lines = [
        f"{symbol} last {len(rows)} trades: {wins}W/{losses}L ({wr:.0%}) | net PnL {total_pnl:+.2f} USD"
    ]
    for r in rows:
        outcome = str(r.get("outcome", "?")).upper()
        side    = str(r.get("side", "?")).upper()
        grade   = r.get("signal_grade", "?") or "?"
        pnl     = float(r.get("pnl_usd") or 0)
        macro   = r.get("macro_bias", "?") or "?"
        closed  = str(r.get("closed_at", ""))[:10]
        tag     = "WIN" if outcome == "WIN" else "LOSS"
        lines.append(f"  [{tag}] {side} grade={grade} macro={macro} pnl={pnl:+.2f} [{closed}]")
    return "\n".join(lines)


def get_reflexive_context(client, model_id: str) -> Dict[str, Any]:
    """Wraps lessons, stats, and bias adjustments for the decision pipeline."""
    outcomes = get_recent_outcomes(10)
    lessons = generate_reflexive_lessons(client, model_id)
    bias_adj = get_bias_adjustments(outcomes)

    return {
        "lessons": lessons,
        "bias_adjustments": bias_adj,
        "recent_performance": {
            "wins": sum(1 for o in outcomes if o['outcome'] == 'WIN'),
            "losses": sum(1 for o in outcomes if o['outcome'] == 'LOSS'),
            "win_rate": sum(1 for o in outcomes if o['outcome'] == 'WIN') / len(outcomes) if outcomes else 0
        },
        "reflexive_timestamp": datetime.now(timezone.utc).isoformat()
    }
