"""
CryptoStream AI — Trend Agent
Uses Gemini Vision to analyze trendline charts (support/resistance channels).
Ported from QuantAgent trend_agent.py pattern.
"""

import json
import logging
import os

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)
MODEL_ID = os.environ.get("MODEL_ID", "gemini-2.5-flash")


def create_trend_agent(client: genai.Client):
    """
    Returns a trend_agent_node function.
    Requires trend chart image (base64) in state["trend_chart_b64"].
    """

    def trend_agent_node(state: dict) -> dict:
        symbol = state.get("symbol", "BTC")
        timeframe = state.get("timeframe", "15m")
        trend_chart_b64 = state.get("trend_chart_b64", "")
        indicator_summary = state.get("indicator_summary", {})

        adx_val = indicator_summary.get("adx", {}).get("value", 0)
        adx_signal = indicator_summary.get("adx", {}).get("signal", "Unknown")

        if not trend_chart_b64:
            return {
                "trend_report": "⚠️ No trend chart available — skipping trend analysis.",
                "trend_direction": "UNKNOWN",
                "trend_bias": "NEUTRAL",
            }

        prompt = f"""You are a technical trend analyst for {symbol}USDT on {timeframe} timeframe.

This chart shows candlesticks with:
- GREEN line = Support trendline (drawn along price lows)
- RED line = Resistance trendline (drawn along price highs)
Optional: Orange = EMA20, Purple = EMA50

ADX from indicators: {adx_val:.1f} ({adx_signal})

Your analysis tasks:
1. Channel type: Ascending / Descending / Horizontal / Expanding / Contracting
2. Price position: Is price near support, resistance, or mid-channel?
3. Channel slope strength: Steep? Gradual? Flat?
4. Breakout risk: Is price breaking out of the channel?
5. Consolidation zones: Any tight-range sideways movement?

Respond ONLY with valid JSON:
{{
  "channel_type": "ASCENDING" | "DESCENDING" | "HORIZONTAL" | "EXPANDING" | "CONTRACTING",
  "trend_direction": "UPTREND" | "DOWNTREND" | "SIDEWAYS",
  "price_position": "NEAR_SUPPORT" | "NEAR_RESISTANCE" | "MID_CHANNEL" | "BREAKING_OUT" | "BREAKING_DOWN",
  "channel_slope": "STEEP" | "GRADUAL" | "FLAT",
  "trend_strength": "STRONG" | "MODERATE" | "WEAK",
  "trend_bias": "BULLISH" | "BEARISH" | "NEUTRAL",
  "confidence": <integer 0-100>,
  "support_level": "<approximate price or description>",
  "resistance_level": "<approximate price or description>",
  "summary": "<2-3 sentence trend analysis in English>"
}}
"""

        try:
            import base64
            image_bytes = base64.b64decode(trend_chart_b64)

            response = client.models.generate_content(
                model=MODEL_ID,
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
                    prompt,
                ],
                config={"response_mime_type": "application/json"},
            )

            data = json.loads(response.text)
            channel = data.get("channel_type", "HORIZONTAL")
            trend_dir = data.get("trend_direction", "SIDEWAYS")
            position = data.get("price_position", "MID_CHANNEL")
            slope = data.get("channel_slope", "FLAT")
            strength = data.get("trend_strength", "MODERATE")
            bias = data.get("trend_bias", "NEUTRAL")
            confidence = int(data.get("confidence", 50))
            support = data.get("support_level", "N/A")
            resistance = data.get("resistance_level", "N/A")
            summary = data.get("summary", "")

            dir_emoji = {"UPTREND": "📈", "DOWNTREND": "📉", "SIDEWAYS": "➡️"}.get(trend_dir, "➡️")

            report = f"""📈 **TREND ANALYSIS — {symbol}USDT ({timeframe})**

**Channel:** {channel} | **Direction:** {dir_emoji} {trend_dir}
**Price Position:** {position} | **Slope:** {slope}
**Trend Strength:** {strength} (ADX: {adx_val:.1f})
**Bias:** {bias} (Confidence: {confidence}%)

**Key Levels:**
- Support: {support}
- Resistance: {resistance}

**Analysis:** {summary}"""

            return {
                "trend_report": report,
                "trend_direction": trend_dir,
                "trend_bias": bias,
                "trend_confidence": confidence,
                "trend_data": data,
            }

        except Exception as e:
            logger.error(f"TrendAgent error: {e}")
            return {
                "trend_report": f"⚠️ Trend analysis failed: {str(e)[:100]}",
                "trend_direction": "UNKNOWN",
                "trend_bias": "NEUTRAL",
                "trend_confidence": 0,
            }

    return trend_agent_node
