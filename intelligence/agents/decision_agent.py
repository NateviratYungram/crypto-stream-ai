"""
CryptoStream AI — Decision Agent
Synthesizes reports from Indicator, Pattern, and Trend agents to produce a trade decision.
Prompt adapts per asset class:
  CRYPTO / MACRO → ICT pipeline (OB/FVG/sweep/session)
  STOCK          → Momentum/trend pipeline (EMA/MACD/volume/breakout)
"""

import json
import logging
import os

logger = logging.getLogger(__name__)
MODEL_ID = os.environ.get("MODEL_ID", "gemini-2.5-flash")


def create_decision_agent(client):
    def decision_agent_node(state: dict) -> dict:
        symbol          = state.get("symbol", "BTC")
        timeframe       = state.get("timeframe", "15m")
        asset_class     = state.get("asset_class", "CRYPTO")
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
        vwap             = state.get("indicator_summary", {}).get("vwap", {})
        ema              = state.get("indicator_summary", {}).get("ema", {})
        trend_analysis   = state.get("indicator_summary", {}).get("trend_analysis", {})

        biases = [indicator_bias, pattern_bias, trend_bias]
        bullish_count = sum(1 for b in biases if "BULL" in str(b).upper())
        bearish_count = sum(1 for b in biases if "BEAR" in str(b).upper())

        smc      = state.get("indicator_summary", {}).get("smart_money", {})
        htf_data = state.get("indicator_summary", {}).get("higher_timeframe", {})
        regime   = smc.get("regime", "UNKNOWN")
        ms       = smc.get("structure", {})
        near_ob  = smc.get("nearest_ob") or {}
        near_fvg = smc.get("nearest_fvg") or {}
        liq      = smc.get("liquidity", {})
        session  = smc.get("session", "UNKNOWN")
        choch    = ms.get("choch", False)
        last_bos = ms.get("last_bos", "None")
        htf_bias   = htf_data.get("bias", "NEUTRAL")
        htf_regime = htf_data.get("regime", "UNKNOWN")

        # Pre-format SMC levels as explicit price strings for the prompt
        ob_top  = near_ob.get("top")
        ob_bot  = near_ob.get("bottom")
        ob_type = near_ob.get("type", "")
        fvg_top  = near_fvg.get("top")
        fvg_bot  = near_fvg.get("bottom")
        fvg_type = near_fvg.get("type", "")
        buy_liq  = liq.get("buy_side",  [])
        sell_liq = liq.get("sell_side", [])
        sweep_tgt = liq.get("nearest_sweep_target")

        def _fmt_ob():
            if not near_ob:
                return "None"
            return f"{ob_type} {ob_bot}–{ob_top} (strength: {near_ob.get('strength','?')})"

        def _fmt_fvg():
            if not near_fvg:
                return "None"
            return f"{fvg_type} {fvg_bot}–{fvg_top} (gap: {near_fvg.get('gap_size','?')})"

        # Derive concrete SL/TP anchors from SMC data
        try:
            _price = float(price)
            # LONG SL anchor: below OB bottom (if bullish OB) or swing low
            long_sl_anchor  = ob_bot if ob_bot and "BULLISH" in ob_type else ms.get("swing_low", "use ATR×1.5 below entry")
            # SHORT SL anchor: above OB top (if bearish OB) or swing high
            short_sl_anchor = ob_top if ob_top and "BEARISH" in ob_type else ms.get("swing_high", "use ATR×1.5 above entry")
            # TP anchors: nearest opposing liquidity pool
            long_tp1  = min(buy_liq)  if buy_liq  else (sweep_tgt or "nearest resistance")
            long_tp2  = max(buy_liq)  if len(buy_liq)  > 1 else "next major high"
            short_tp1 = max(sell_liq) if sell_liq else (sweep_tgt or "nearest support")
            short_tp2 = min(sell_liq) if len(sell_liq) > 1 else "next major low"
        except Exception:
            long_sl_anchor = short_sl_anchor = "ATR-based"
            long_tp1 = long_tp2 = short_tp1 = short_tp2 = "nearest key level"

        json_schema = """{
  "decision": "LONG" | "SHORT" | "HOLD",
  "confidence": <integer 0-100>,
  "entry_zone": {"low": <price>, "high": <price>, "note": "<condition>"},
  "stop_loss": {"price": <price>, "invalidation": "<reason>"},
  "take_profit": {"tp1": <price>, "tp2": <price or null>, "note": "<target>"},
  "risk_reward_ratio": <float>,
  "forecast_horizon": "<timeframe>",
  "justification": "<specific reasoning citing data above>",
  "warnings": ["<risk1>", "<risk2>"]
}"""

        # ── CRYPTO / MACRO: ICT / Smart Money decision pipeline ───────────────
        if asset_class in ("CRYPTO", "MACRO"):
            prompt = f"""You are a Smart Money / ICT institutional trader. Make a trade decision for {symbol} ({asset_class}) on {timeframe}.

CURRENT PRICE : {price}
ATR           : {atr}
SESSION       : {session}
REGIME (LTF)  : {regime}
REGIME (HTF)  : {htf_regime}
HURST (H100)  : {h100} ({h_regime})
HURST (H30)   : {h30} (Scalping Persistence)
HTF BIAS      : {htf_bias}
STRUCTURE     : {ms.get('structure','?')} | BOS: {last_bos} | CHOCH: {choch}
SWING HIGH    : {ms.get('swing_high','N/A')} | SWING LOW: {ms.get('swing_low','N/A')}

--- SMC PRICE LEVELS (use these EXACT prices for entries, SL, TP) ---
NEAREST OB    : {_fmt_ob()}
NEAREST FVG   : {_fmt_fvg()}
BUY-SIDE LIQ  : {', '.join(str(x) for x in buy_liq)  or 'none'}  ← equal highs (SM raids these → SHORT TP)
SELL-SIDE LIQ : {', '.join(str(x) for x in sell_liq) or 'none'}  ← equal lows  (SM raids these → LONG TP)
NEXT SM TARGET: {sweep_tgt or 'N/A'}

--- DERIVED SL/TP ANCHORS ---
LONG  SL anchor : {long_sl_anchor}  (invalidated if price closes below)
SHORT SL anchor : {short_sl_anchor} (invalidated if price closes above)
LONG  TP1 / TP2 : {long_tp1} / {long_tp2}   (sell-side liquidity targets)
SHORT TP1 / TP2 : {short_tp1} / {short_tp2} (buy-side liquidity targets)

=== AGENT REPORTS ===
{indicator_report}
{pattern_report}
{trend_report}

Agent Consensus: {bullish_count}/3 bullish | {bearish_count}/3 bearish

=== ICT DECISION PIPELINE (follow in order) ===

STEP 1 — KILL CONDITIONS (any one → HOLD):
  × Regime = CHAOS
  × H100 < 0.48 AND strategy = Trend Following → HOLD
  × Session = ASIA and asset contains GOLD/XAU
  × HTF and LTF structure completely opposed with no CHOCH

STEP 2 — ENTRY MODEL:
  For LONG:
    ✓ Liquidity sweep of sell-side (equal lows) just occurred, OR
    ✓ Price retested a Bullish OB / Bullish FVG (use OB/FVG bottom–top as entry zone), OR
    ✓ CHOCH from bearish to bullish + BOS confirmation
    AND: HTF bias BULLISH or NEUTRAL + session is London/NY

  For SHORT:
    ✓ Liquidity sweep of buy-side (equal highs) just occurred, OR
    ✓ Price retested a Bearish OB / Bearish FVG (use OB/FVG bottom–top as entry zone), OR
    ✓ CHOCH from bullish to bearish + BOS confirmation
    AND: HTF bias BEARISH or NEUTRAL + session is London/NY

  HOLD: No confirmed sweep, no OB/FVG retest, no structure break.

STEP 3 — RISK (use SMC price anchors above, NOT ATR guesses):
  LONG:  entry_zone = OB/FVG zone | SL = {long_sl_anchor} | TP1 = {long_tp1} | TP2 = {long_tp2}
  SHORT: entry_zone = OB/FVG zone | SL = {short_sl_anchor} | TP1 = {short_tp1} | TP2 = {short_tp2}
  Minimum R:R = 1:2. If R:R < 1:2 → HOLD.

STEP 4 — HURST ALIGNMENT:
  H100 > 0.55 → Favor trend continuation
  H100 < 0.45 → Favor mean-reversion (range extremes only)

Respond ONLY with valid JSON:
{json_schema}

IMPORTANT: Use the EXACT price numbers from SMC PRICE LEVELS and DERIVED SL/TP ANCHORS above.
In justification, cite: regime + hurst + structure + exact OB/FVG prices + session."""

        # ── STOCK: Standard technical momentum decision pipeline ──────────────
        else:
            levels = trend_analysis.get("levels", {})
            prompt = f"""You are a professional equity technical analyst. Make a trade decision for {symbol} stock on {timeframe}.

CURRENT PRICE : {price}
ATR           : {atr}
HTF BIAS      : {htf_bias} ({htf_data.get('timeframe','?')})
EMA TREND     : {ema.get('signal','?')} | EMA20: {ema.get('ema_20','?')} | EMA50: {ema.get('ema_50','?')} | EMA200: {ema.get('ema_200','?')}
VWAP          : {vwap.get('value','?')} → {vwap.get('position','?')}
HURST (H100)  : {h100} ({h_regime})
MARKET PHASE  : {trend_analysis.get('market_phase','?')} | Trend: {trend_analysis.get('primary_trend','?')}
SUPPORT       : {levels.get('support','N/A')} | RESISTANCE: {levels.get('resistance','N/A')}

=== AGENT REPORTS ===
{indicator_report}
{pattern_report}
{trend_report}

Agent Consensus: {bullish_count}/3 bullish | {bearish_count}/3 bearish

=== STOCK DECISION PIPELINE (follow in order) ===

STEP 1 — KILL CONDITIONS (any one → HOLD):
  × Market phase = Consolidating AND ADX < 15 → HOLD (no trend to trade)
  × H100 < 0.45 AND strategy = Trend Following → HOLD
  × HTF and LTF bias directly opposed → HOLD
  × Price at all-time high with RSI > 75 → consider SHORT or HOLD

STEP 2 — ENTRY MODEL:
  For LONG:
    ✓ Price > EMA20 > EMA50 (bullish stack) + HTF also BULLISH, OR
    ✓ Bullish MACD crossover near EMA20/50 support + volume spike, OR
    ✓ RSI bouncing from 40-50 in an uptrend (pullback entry)
    AND: price above VWAP + ADX > 20

  For SHORT:
    ✓ Price < EMA20 < EMA50 (bearish stack) + HTF also BEARISH, OR
    ✓ Bearish MACD crossover near EMA20/50 resistance + volume, OR
    ✓ RSI rejected at 55-65 in a downtrend (rally fade)
    AND: price below VWAP + ADX > 20

  HOLD: No clear EMA stack, conflicting signals, low ADX, no volume confirmation.

STEP 3 — RISK (level-based):
  LONG: SL = below EMA50 or recent support level
  SHORT: SL = above EMA50 or recent resistance level
  Minimum R:R = 1:2. If R:R < 1:2 → HOLD.

STEP 4 — HURST ALIGNMENT:
  H100 > 0.55 → Buy pullbacks to EMA in uptrend, sell rallies in downtrend
  H100 < 0.45 → Trade range extremes only (support/resistance)

Respond ONLY with valid JSON:
{json_schema}

In justification, cite: EMA trend + MACD + volume + HTF bias + support/resistance specifically.
Do NOT mention OBs, FVGs, or liquidity sweeps — not applicable to stocks."""

        try:
            response = client.models.generate_content(
                model=MODEL_ID,
                contents=prompt,
                config={"response_mime_type": "application/json"},
            )
            data = json.loads(response.text)
            decision    = data.get("decision", "HOLD").upper()
            confidence  = int(data.get("confidence", 50))
            entry       = data.get("entry_zone", {})
            sl          = data.get("stop_loss", {})
            tp          = data.get("take_profit", {})
            rr_val      = data.get("risk_reward_ratio")
            rr          = float(rr_val) if rr_val is not None else 1.5
            horizon     = data.get("forecast_horizon", "N/A")
            justification = data.get("justification", "")
            warnings    = data.get("warnings", [])

            dec_emoji    = {"LONG": "🟢", "SHORT": "🔴", "HOLD": "⚪"}.get(decision, "⚪")
            ticker_suffix = "" if asset_class == "STOCK" else "USDT"

            report = f"""🎯 **DECISION AGENT — {symbol}{ticker_suffix} ({timeframe}) [{asset_class}]**

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
