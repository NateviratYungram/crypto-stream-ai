"""
CryptoStream AI — Pattern Agent
Uses Gemini Vision to analyze candlestick chart images and detect patterns.
Ported from QuantAgent pattern_agent.py, adapted for Gemini Vision API.
"""

import json
import logging
import os

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)
MODEL_ID = os.environ.get("MODEL_ID", "gemini-2.5-flash")


def create_pattern_agent(client: genai.Client):
    """
    Returns a pattern_agent_node function.
    Requires chart image (base64) in state["kline_chart_b64"].
    """

    def pattern_agent_node(state: dict) -> dict:
        symbol = state.get("symbol", "BTC")
        timeframe = state.get("timeframe", "15m")
        chart_b64 = state.get("kline_chart_b64", "")
        indicator_summary = state.get("indicator_summary", {})

        # ── Text-based pattern fallback (used when no chart image) ──────────────
        if not chart_b64:
            patterns_data = indicator_summary.get("patterns", {})
            trend_data    = indicator_summary.get("trend_analysis", {})
            sm            = indicator_summary.get("smart_money", {})
            detected      = patterns_data.get("detected", ["None"])
            observation   = patterns_data.get("observation", "")
            primary_trend = trend_data.get("primary_trend", "N/A")
            market_phase  = trend_data.get("market_phase", "N/A")
            levels        = trend_data.get("levels", {})

            # ── ICT pattern detection from SMC data ──────────────────────────
            ict_patterns = []
            bias_score   = 0  # positive = bullish, negative = bearish

            _struct  = sm.get("structure") or {}
            _ob      = sm.get("nearest_ob") or {}
            _fvg     = sm.get("nearest_fvg") or {}
            _sweeps  = sm.get("sweeps") or {}

            # 1. CHoCH / MSS — structure shift (strongest ICT signal)
            if _struct.get("choch"):
                struct_dir = str(_struct.get("structure", "")).upper()
                if struct_dir == "BULLISH":
                    ict_patterns.append("CHoCH → Bullish MSS")
                    bias_score += 2
                elif struct_dir == "BEARISH":
                    ict_patterns.append("CHoCH → Bearish MSS")
                    bias_score -= 2

            # 2. BOS confirmation
            _bos = str(_struct.get("last_bos") or "").upper()
            if "BULLISH" in _bos:
                ict_patterns.append("Bullish BOS Confirmed")
                bias_score += 1
            elif "BEARISH" in _bos:
                ict_patterns.append("Bearish BOS Confirmed")
                bias_score -= 1

            # 3. OB Reaction — price inside OB zone
            if _ob:
                ob_type = str(_ob.get("type", "")).upper()
                ob_top  = float(_ob.get("top", 0) or 0)
                ob_bot  = float(_ob.get("bottom", 0) or 0)
                if ob_top > 0 and ob_bot > 0:
                    # "price inside OB" not directly available — use dist ≈ 0 proxy
                    ob_mid  = (ob_top + ob_bot) / 2.0
                    ob_half = (ob_top - ob_bot) / 2.0
                    if "BULLISH" in ob_type:
                        ict_patterns.append("Bullish OB Reaction")
                        bias_score += 2
                    elif "BEARISH" in ob_type:
                        ict_patterns.append("Bearish OB Reaction")
                        bias_score -= 2

            # 4. FVG Fill — price near FVG
            if _fvg:
                fvg_type = str(_fvg.get("type", "")).upper()
                if "BULLISH" in fvg_type:
                    ict_patterns.append("Bullish FVG Fill")
                    bias_score += 1
                elif "BEARISH" in fvg_type:
                    ict_patterns.append("Bearish FVG Fill")
                    bias_score -= 1

            # 5. Liquidity sweep
            if _sweeps.get("sweep_detected"):
                sw_type = str(_sweeps.get("type") or "").upper()
                if "BULLISH" in sw_type:
                    ict_patterns.append("Buy-Side Liquidity Sweep")
                    bias_score += 2
                elif "BEARISH" in sw_type:
                    ict_patterns.append("Sell-Side Liquidity Sweep")
                    bias_score -= 2

            # ── Classic candlestick patterns ─────────────────────────────────
            bullish_classic = {"Bullish Engulfing", "Hammer / Bullish Pin Bar",
                               "Morning Star", "Double Bottom", "Bullish Flag"}
            bearish_classic = {"Bearish Engulfing", "Shooting Star / Bearish Pin Bar",
                               "Evening Star", "Double Top", "Head & Shoulders"}
            detected_set = set(detected)
            if detected_set & bullish_classic:
                bias_score += 1
            elif detected_set & bearish_classic:
                bias_score -= 1

            # ── Determine final bias ─────────────────────────────────────────
            all_patterns = ict_patterns + [p for p in detected if p != "None"]
            if bias_score >= 2:
                bias = "BULLISH"
                confidence = min(55 + bias_score * 5, 82)
            elif bias_score <= -2:
                bias = "BEARISH"
                confidence = min(55 + abs(bias_score) * 5, 82)
            elif bias_score == 1:
                bias = "BULLISH"
                confidence = 55
            elif bias_score == -1:
                bias = "BEARISH"
                confidence = 55
            else:
                bias = "BULLISH" if primary_trend == "UP" else "BEARISH" if primary_trend == "DOWN" else "NEUTRAL"
                confidence = 40 if bias != "NEUTRAL" else 30

            ict_line = f"**ICT Patterns:** {', '.join(ict_patterns)}" if ict_patterns else "**ICT Patterns:** None"
            report = f"""🕯️ **PATTERN ANALYSIS — {symbol} ({timeframe})**

**Detected Patterns:** {', '.join(detected)}
{ict_line}
**Trend Direction:** {primary_trend} | **Market Phase:** {market_phase}
**Pattern Bias:** {bias} (Confidence: {confidence}%)
**Support:** {levels.get('support', 'N/A')} | **Resistance:** {levels.get('resistance', 'N/A')}
**Note:** {observation}"""

            return {
                "pattern_report": report,
                "detected_pattern": (ict_patterns[0] if ict_patterns else detected[0]) if (ict_patterns or detected) else "None",
                "pattern_bias": bias,
                "pattern_confidence": confidence,
            }

        prompt = f"""You are an expert ICT/SMC technical analyst for {symbol}USDT ({timeframe} timeframe).

Analyze this candlestick chart carefully and identify:

1. **Chart Pattern** — Look for ICT/SMC patterns FIRST, then classic patterns:
   ICT/SMC Bullish: Bullish OB Reaction, Bullish FVG Fill, Buy-Side Sweep, CHoCH → Bullish MSS, Bullish BOS
   ICT/SMC Bearish: Bearish OB Reaction, Bearish FVG Fill, Sell-Side Sweep, CHoCH → Bearish MSS, Bearish BOS
   Classic Bullish: Bullish Flag, Cup & Handle, Inverse Head & Shoulders, Double Bottom, Ascending Triangle, Morning Star, Hammer
   Classic Bearish: Head & Shoulders, Double Top, Descending Triangle, Bearish Flag, Evening Star, Shooting Star
   Neutral: Symmetrical Triangle, Consolidation Range, Doji Cluster

2. **Pattern Completion Status** — Is the pattern forming, near completion, or fully formed?

3. **Breakout Direction** — If a breakout is likely, which direction?

4. **Key Price Levels** visible on chart

Respond ONLY with valid JSON:
{{
  "pattern_name": "<pattern name or NONE>",
  "pattern_type": "BULLISH" | "BEARISH" | "NEUTRAL" | "NONE",
  "completion_status": "FORMING" | "NEAR_COMPLETE" | "COMPLETE",
  "breakout_direction": "UP" | "DOWN" | "UNCLEAR" | "N/A",
  "confidence": <integer 0-100>,
  "key_levels": {{
    "support": "<price or description>",
    "resistance": "<price or description>",
    "breakout_target": "<price or N/A>"
  }},
  "summary": "<2-3 sentence analyst note>"
}}

Rules:
- Only report patterns you can CLEARLY see — don't guess
- If no clear pattern: pattern_name="CONSOLIDATION" or "UNCLEAR TREND"
- Completion < 50%: status=FORMING, confidence should be low
- A confirmed breakout bar = COMPLETE
"""

        try:
            import base64
            image_bytes = base64.b64decode(chart_b64)

            response = client.models.generate_content(
                model=MODEL_ID,
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
                    prompt,
                ],
                config={"response_mime_type": "application/json"},
            )

            data = json.loads(response.text)
            pattern_name = data.get("pattern_name", "UNCLEAR")
            pattern_type = data.get("pattern_type", "NEUTRAL")
            completion = data.get("completion_status", "FORMING")
            direction = data.get("breakout_direction", "UNCLEAR")
            confidence = int(data.get("confidence", 50))
            key_levels = data.get("key_levels", {})
            summary = data.get("summary", "")

            type_emoji = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "⚪", "NONE": "⚫"}.get(pattern_type, "⚪")

            report = f"""🕯️ **PATTERN ANALYSIS — {symbol}USDT ({timeframe})**

**Pattern:** {type_emoji} {pattern_name} ({pattern_type})
**Status:** {completion} | **Breakout Target:** {direction}
**Confidence:** {confidence}%

**Key Price Levels:**
- Support: {key_levels.get('support', 'N/A')}
- Resistance: {key_levels.get('resistance', 'N/A')}
- Target if breakout: {key_levels.get('breakout_target', 'N/A')}

**Analysis:** {summary}"""

            return {
                "pattern_report": report,
                "detected_pattern": pattern_name,
                "pattern_bias": pattern_type,
                "pattern_confidence": confidence,
                "pattern_data": data,
            }

        except Exception as e:
            logger.error(f"PatternAgent error: {e}")
            return {
                "pattern_report": f"⚠️ Pattern analysis failed: {str(e)[:100]}",
                "detected_pattern": "UNKNOWN",
                "pattern_bias": "NEUTRAL",
                "pattern_confidence": 0,
            }

    return pattern_agent_node
