"""
CryptoStream AI — Decision Agent
Synthesizes reports from Indicator, Pattern, and Trend agents to produce a trade decision.
Ported from QuantAgent decision_agent.py — adapted for crypto spot/futures.
"""

import json
import logging
import os

logger = logging.getLogger(__name__)
MODEL_ID = os.environ.get("MODEL_ID", "gemini-2.5-flash")


def create_decision_agent(client):
    """
    Returns a decision_agent_node.
    Reads: indicator_report, pattern_report, trend_report from state.
    Outputs: trade_decision (LONG/SHORT/HOLD), entry/SL/TP zones, risk_reward.
    """

    def decision_agent_node(state: dict) -> dict:
        symbol = state.get("symbol", "BTC")
        timeframe = state.get("timeframe", "15m")
        indicator_report = state.get("indicator_report", "No indicator data.")
        pattern_report   = state.get("pattern_report", "No pattern data.")
        trend_report     = state.get("trend_report", "No trend data.")
        indicator_bias   = state.get("indicator_bias", "NEUTRAL")
        pattern_bias     = state.get("pattern_bias", "NEUTRAL")
        trend_bias       = state.get("trend_bias", "NEUTRAL")
        price            = state.get("indicator_summary", {}).get("price", 0)
        atr              = state.get("indicator_summary", {}).get("atr", {}).get("value", 0)
        hurst            = state.get("indicator_summary", {}).get("hurst", {})
        h100             = hurst.get("h100", 0.5)
        h30              = hurst.get("h30", 0.5)
        h_regime         = hurst.get("regime", "UNKNOWN")

        # Quick consensus check pre-LLM (speeds up; if all NEUTRAL, likely HOLD)
        biases = [indicator_bias, pattern_bias, trend_bias]
        bullish_count = sum(1 for b in biases if "BULL" in str(b).upper())
        bearish_count = sum(1 for b in biases if "BEAR" in str(b).upper())

        # Extract Smart Money context from indicator_summary (passed through state)
        smc      = state.get("indicator_summary", {}).get("smart_money", {})
        htf_data = state.get("indicator_summary", {}).get("higher_timeframe", {})
        regime   = smc.get("regime", "UNKNOWN")
        ms       = smc.get("structure", {})
        near_ob  = smc.get("nearest_ob")
        near_fvg = smc.get("nearest_fvg")
        liq      = smc.get("liquidity", {})
        session  = smc.get("session", "UNKNOWN")
        choch    = ms.get("choch", False)
        last_bos = ms.get("last_bos", "None")
        htf_bias = htf_data.get("bias", "NEUTRAL")
        htf_regime = htf_data.get("regime", "UNKNOWN")

        prompt = f"""You are a Smart Money / ICT institutional trader. Make a trade decision for {symbol} on {timeframe}.

CURRENT PRICE : {price}
ATR           : {atr}
SESSION       : {session}
REGIME (LTF)  : {regime}
REGIME (HTF)  : {htf_regime}
HURST (H100)  : {h100} ({h_regime})
HURST (H30)   : {h30} (Scalping Persistence)
HTF BIAS      : {htf_bias}
STRUCTURE     : {ms.get('structure','?')} | BOS: {last_bos} | CHOCH: {choch}
NEAREST OB    : {near_ob}
NEAREST FVG   : {near_fvg}
LIQUIDITY     : Buy-side={liq.get('buy_side',[])} | Sell-side={liq.get('sell_side',[])}
SWEEP TARGET  : {liq.get('nearest_sweep_target','?')}

=== AGENT REPORTS ===
{indicator_report}
{pattern_report}
{trend_report}

Agent Consensus: {bullish_count}/3 bullish | {bearish_count}/3 bearish

=== ICT DECISION PIPELINE (follow in order) ===

STEP 1 — KILL CONDITIONS (if any → HOLD):
  × Regime = CHAOS
  × Hurst H100 < 0.48 AND strategy = Trend Following → HOLD (Mean Reverting focus needed)
  × Session = ASIA and asset is GOLD (avoid Asian session for Gold)
  × HTF and LTF structure completely opposed with no CHOCH

STEP 2 — ENTRY MODEL:
  For LONG:
    ✓ Liquidity sweep of sell-side (equal lows) just occurred, OR
    ✓ Price retested a Bullish OB / Bullish FVG, OR
    ✓ CHOCH from bearish to bullish + BOS confirmation
    AND: HTF bias BULLISH or NEUTRAL + session is London/NY

  For SHORT:
    ✓ Liquidity sweep of buy-side (equal highs) just occurred, OR
    ✓ Price retested a Bearish OB / Bearish FVG, OR
    ✓ CHOCH from bullish to bearish + BOS confirmation
    AND: HTF bias BEARISH or NEUTRAL + session is London/NY

  HOLD: No confirmed sweep, no OB/FVG retest, no structure break

STEP 3 — RISK (structure-based, not just ATR):
  For LONG:  SL = below nearest swing low or below OB bottom
  For SHORT: SL = above nearest swing high or above OB top
  Minimum R:R = 1:2. If R:R < 1:2 with structure-based SL → HOLD

STEP 4 — HURST ALIGNMENT:
  × If H100 > 0.55: Favor trend continuation (BUY on dips, SELL on rallies)
  × If H100 < 0.45: Favor mean-reversion (Trade range extremes ONLY)

Respond ONLY with valid JSON:
{{
  "decision": "LONG" | "SHORT" | "HOLD",
  "confidence": <integer 0-100>,
  "entry_zone": {{"low": <price>, "high": <price>, "note": "<condition>"}},
  "stop_loss": {{"price": <price>, "invalidation": "<structure reason>"}},
  "take_profit": {{"tp1": <price>, "tp2": <price or null>, "note": "<liquidity target>"}},
  "risk_reward_ratio": <float>,
  "forecast_horizon": "<timeframe>",
  "justification": "<cite regime + hurst + structure + OB/FVG + session specifically>",
  "warnings": ["<risk1>", "<risk2>"]
}}
"""

        try:
            response = client.models.generate_content(
                model=MODEL_ID,
                contents=prompt,
                config={"response_mime_type": "application/json"},
            )
            data = json.loads(response.text)
            decision = data.get("decision", "HOLD").upper()
            confidence = int(data.get("confidence", 50))
            entry = data.get("entry_zone", {})
            sl = data.get("stop_loss", {})
            tp = data.get("take_profit", {})

            rr_val = data.get("risk_reward_ratio")
            rr = float(rr_val) if rr_val is not None else 1.5

            horizon = data.get("forecast_horizon", "N/A")
            justification = data.get("justification", "")
            warnings = data.get("warnings", [])

            dec_emoji = {"LONG": "🟢", "SHORT": "🔴", "HOLD": "⚪"}.get(decision, "⚪")

            report = f"""🎯 **DECISION AGENT — {symbol}USDT ({timeframe})**

**Decision:** {dec_emoji} **{decision}** (Confidence: {confidence}%)
**Horizon:** {horizon}

**Strategy Map:**
| Action | Zone / Level | Note |
|---|---|---|
| **ENTRY** | `{entry.get('low', 'N/A')} – {entry.get('high', 'N/A')}` | {entry.get('note', '')} |
| **STOP LOSS** | `{sl.get('price', 'N/A')}` | {sl.get('invalidation', '')} |
| **TAKE PROFIT 1** | `{tp.get('tp1', 'N/A')}` | {tp.get('note', '')} |
| **TAKE PROFIT 2** | `{tp.get('tp2', 'N/A')}` | Final target |

**Risk:Reward:** 1:{rr:.1f}

**Justification:** {justification}"""

            if warnings:
                report += "\n\n**⚠️ Warnings:**\n"
                for w in warnings:
                    report += f"  • {w}\n"

            return {
                "trade_decision": decision,
                "decision_report": report,
                "decision_confidence": confidence,
                "entry_zone": entry,
                "stop_loss": sl,
                "take_profit": tp,
                "risk_reward_ratio": rr,
                "decision_data": data,
            }

        except Exception as e:
            logger.error(f"DecisionAgent error: {e}")
            return {
                "trade_decision": "HOLD",
                "decision_report": f"⚠️ Decision analysis failed: {str(e)[:100]}. Defaulting to HOLD.",
                "decision_confidence": 0,
                "risk_reward_ratio": 0,
            }

    return decision_agent_node
