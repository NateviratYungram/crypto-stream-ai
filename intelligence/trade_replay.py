"""
CryptoStream AI — Trade Replay
Uses Gemini to analyze recent losing trades and extract actionable lessons.

Ported from QuantAgent trade_replay.py — adapted for CryptoStream:
  - Replaced LangChain llm.invoke() with Gemini client.models.generate_content()
  - Uses TradeLogger (intelligence/trade_logger.py) instead of raw JSON path
  - Returns structured JSON lessons in addition to free-text analysis
  - Added get_trade_summary_for_display() for frontend trade history panel

Usage:
    from intelligence.trade_replay import analyze_past_trades, get_trade_summary

    # Full AI analysis of recent losers (requires Gemini client)
    report = analyze_past_trades(client, num_trades=5)
    print(report["analysis"])     # free text
    print(report["lessons"])      # structured list

    # Quick summary without AI (no LLM call)
    summary = get_trade_summary(count=20)
"""

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)
MODEL_ID = os.environ.get("MODEL_ID", "gemini-2.5-flash")


def analyze_past_trades(
    client,
    num_trades: int = 5,
    log_file: Optional[str] = None,
) -> dict:
    """
    Load recent losing trades from TradeLogger, send to Gemini, get lessons.

    Args:
        client     : google.genai.Client instance
        num_trades : how many recent losing trades to include in the prompt
        log_file   : optional override path for trade_history.json

    Returns:
        {
          "analysis":       str   — free-text AI report
          "lessons":        list  — structured [{rule, reason, action}]
          "trades_analyzed": int
          "error":          str | None
        }
    """
    # ── Load trade history ─────────────────────────────────────────────────────
    try:
        from intelligence.trade_logger import get_trade_logger
        tl = get_trade_logger({"trade_log_file": log_file} if log_file else None)
        history = tl._load()
    except Exception as e:
        logger.error(f"TradeReplay: failed to load trade history: {e}")
        return {"analysis": f"Cannot load trade history: {e}", "lessons": [], "trades_analyzed": 0, "error": str(e)}

    if not history:
        return {
            "analysis":        "No trade history available for analysis.",
            "lessons":         [],
            "trades_analyzed": 0,
            "error":           None,
        }

    # ── Find losing trades ────────────────────────────────────────────────────
    losing_trades = [
        t for t in history
        if t.get("status") in ("EXECUTED", "DRY_RUN")
        and float(t.get("profit") or t.get("pnl") or 0) < 0
    ]

    if not losing_trades:
        return {
            "analysis":        "No losing trades to analyze — great performance!",
            "lessons":         [],
            "trades_analyzed": 0,
            "error":           None,
        }

    recent_losers = losing_trades[-num_trades:]

    # ── Build prompt ───────────────────────────────────────────────────────────
    trades_text = ""
    for i, trade in enumerate(recent_losers, 1):
        pnl = float(trade.get("profit") or trade.get("pnl") or 0)
        trades_text += f"""
Trade #{i}:
  Symbol    : {trade.get("symbol", "N/A")}
  Action    : {trade.get("action", trade.get("direction", "N/A"))}
  Confidence: {trade.get("confidence", "N/A")}%
  Entry     : {trade.get("entry_price", "N/A")}
  SL        : {trade.get("sl", "N/A")}
  TP        : {trade.get("tp", "N/A")}
  P/L       : ${pnl:.2f}
  Reasoning : {str(trade.get("reasoning", "N/A"))[:250]}
  Timestamp : {trade.get("timestamp", "N/A")}
"""

    prompt = f"""You are a professional trading coach reviewing losing trades for a crypto AI trading system.
Analyze the following {len(recent_losers)} losing trades and provide actionable lessons.

{trades_text}

Respond ONLY with valid JSON in this exact format:
{{
  "common_patterns": "<string: 1-2 sentences on shared patterns across the losses>",
  "specific_mistakes": [
    {{"trade": 1, "mistake": "<what went wrong>"}}
  ],
  "lessons": [
    {{"rule": "<rule name>", "reason": "<why this matters>", "action": "<specific parameter or behavior change>"}}
  ],
  "suggested_improvements": "<string: 2-3 concrete changes to the strategy (thresholds, filters, etc.)>",
  "overall_assessment": "IMPROVABLE" | "RANDOM_NOISE" | "SYSTEMIC_ISSUE"
}}

Focus on: entry timing, confidence thresholds, market regime at time of trade, SL placement.
Keep lessons actionable and specific (e.g. "raise min_confidence from 60% to 70%" not "be more careful").
"""

    try:
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=prompt,
            config={"response_mime_type": "application/json"},
        )
        data = json.loads(response.text)

        # ── Format free-text report ────────────────────────────────────────────
        lines = [
            f"Trade Replay Analysis ({len(recent_losers)} losing trades)",
            "=" * 40,
            "",
            f"Common Patterns: {data.get('common_patterns', '')}",
            "",
            "Specific Mistakes:",
        ]
        for m in data.get("specific_mistakes", []):
            lines.append(f"  Trade #{m.get('trade')}: {m.get('mistake')}")

        lines += ["", "Lessons Learned:"]
        for i, lesson in enumerate(data.get("lessons", []), 1):
            lines.append(f"  {i}. [{lesson.get('rule')}] {lesson.get('reason')}")
            lines.append(f"     Action: {lesson.get('action')}")

        lines += ["", f"Suggested Improvements: {data.get('suggested_improvements', '')}"]
        lines += [f"Overall Assessment: {data.get('overall_assessment', '')}"]

        return {
            "analysis":        "\n".join(lines),
            "lessons":         data.get("lessons", []),
            "common_patterns": data.get("common_patterns", ""),
            "improvements":    data.get("suggested_improvements", ""),
            "assessment":      data.get("overall_assessment", ""),
            "trades_analyzed": len(recent_losers),
            "error":           None,
        }

    except Exception as e:
        logger.error(f"TradeReplay: Gemini error: {e}")
        return {
            "analysis":        f"Analysis failed: {str(e)[:200]}",
            "lessons":         [],
            "trades_analyzed": len(recent_losers),
            "error":           str(e)[:200],
        }


def get_trade_summary(count: int = 20) -> list:
    """
    Return a formatted trade summary list for the frontend (no LLM, instant).
    Each entry: emoji, symbol, action, pnl, confidence, timestamp, status.
    """
    try:
        from intelligence.trade_logger import get_trade_logger
        tl = get_trade_logger()
        recent = tl.get_recent_trades(count=count)
    except Exception as e:
        logger.error(f"get_trade_summary: {e}")
        return []

    summaries = []
    for trade in recent:
        pnl  = float(trade.get("profit") or trade.get("pnl") or 0)
        summaries.append({
            "win":        pnl > 0,
            "symbol":     trade.get("symbol", "N/A"),
            "action":     trade.get("action", trade.get("direction", "N/A")),
            "pnl":        round(pnl, 2),
            "confidence": trade.get("confidence", 0),
            "status":     trade.get("status", "N/A"),
            "timestamp":  trade.get("timestamp", "N/A"),
            "volume":     trade.get("volume", "N/A"),
            "entry":      trade.get("entry_price", "N/A"),
            "sl":         trade.get("sl", "N/A"),
            "tp":         trade.get("tp", "N/A"),
        })
    return summaries
