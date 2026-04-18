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
        # Use patterns + trend already computed in indicator_summary
        if not chart_b64:
            patterns_data = indicator_summary.get("patterns", {})
            trend_data    = indicator_summary.get("trend_analysis", {})
            detected      = patterns_data.get("detected", ["None"])
            observation   = patterns_data.get("observation", "")
            primary_trend = trend_data.get("primary_trend", "N/A")
            market_phase  = trend_data.get("market_phase", "N/A")
            levels        = trend_data.get("levels", {})

            # Determine bias from detected patterns
            bullish_patterns = {"Bullish Engulfing", "Hammer / Bullish Pin Bar",
                                "Morning Star", "Double Bottom", "Bullish Flag"}
            bearish_patterns = {"Bearish Engulfing", "Shooting Star / Bearish Pin Bar",
                                "Evening Star", "Double Top", "Head & Shoulders"}

            detected_set = set(detected)
            if detected_set & bullish_patterns:
                bias = "BULLISH"
                confidence = 65
            elif detected_set & bearish_patterns:
                bias = "BEARISH"
                confidence = 65
            else:
                # Fall back to trend direction as pattern proxy
                bias = "BULLISH" if primary_trend == "UP" else "BEARISH" if primary_trend == "DOWN" else "NEUTRAL"
                confidence = 45 if bias != "NEUTRAL" else 30

            report = f"""🕯️ **PATTERN ANALYSIS — {symbol} ({timeframe})**

**Detected Patterns:** {', '.join(detected)}
**Trend Direction:** {primary_trend} | **Market Phase:** {market_phase}
**Pattern Bias:** {bias} (Confidence: {confidence}%)
**Support:** {levels.get('support', 'N/A')} | **Resistance:** {levels.get('resistance', 'N/A')}
**Note:** {observation}"""

            return {
                "pattern_report": report,
                "detected_pattern": detected[0] if detected else "None",
                "pattern_bias": bias,
                "pattern_confidence": confidence,
            }

        prompt = f"""You are an expert technical analyst specializing in candlestick chart patterns for {symbol}USDT ({timeframe} timeframe).

Analyze this candlestick chart carefully and identify:

1. **Chart Pattern** — Look for CLASSIC patterns:
   Bullish: Bullish Flag, Cup & Handle, Inverse Head & Shoulders, Double Bottom, Ascending Triangle, Morning Star, Hammer
   Bearish: Head & Shoulders, Double Top, Descending Triangle, Bearish Flag, Evening Star, Shooting Star
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
