"""
CryptoStream AI — Indicator Agent
Analyzes technical indicators using Gemini and returns a structured report.
Ported from QuantAgent indicator_agent.py pattern, adapted for Gemini API.
"""

import json
import logging
import os
from google import genai

logger = logging.getLogger(__name__)
MODEL_ID = os.environ.get("MODEL_ID", "gemini-2.5-flash")


def create_indicator_agent(client: genai.Client):
    """
    Returns an indicator_agent_node function.

    The node reads indicator_summary from state and calls Gemini to produce
    a human-readable indicator report with buy/sell/hold bias and key values.
    """

    def indicator_agent_node(state: dict) -> dict:
        symbol = state.get("symbol", "BTC")
        timeframe = state.get("timeframe", "15m")
        indicator_summary = state.get("indicator_summary", {})
        kline_data = state.get("kline_data")  # DataFrame (optional)

        if not indicator_summary:
            return {
                "indicator_report": "⚠️ Indicator data unavailable — skipping indicator analysis.",
                "indicator_bias": "NEUTRAL",
                "indicator_confidence": 0,
            }

        price = indicator_summary.get("price", "N/A")

        # Build compact indicator text
        rsi = indicator_summary.get("rsi", {})
        macd = indicator_summary.get("macd", {})
        macd_hist = indicator_summary.get("macd_histogram", {})
        stoch = indicator_summary.get("stochastic", {})
        willr = indicator_summary.get("williams_r", {})
        adx = indicator_summary.get("adx", {})
        atr = indicator_summary.get("atr", {})
        bb = indicator_summary.get("bollinger_bands", {})
        ema = indicator_summary.get("ema", {})

        # Pull Smart Money data from indicator_summary if available
        smc      = indicator_summary.get("smart_money", {})
        htf      = indicator_summary.get("higher_timeframe", {})
        regime   = smc.get("regime", "UNKNOWN")
        ms       = smc.get("structure", {})
        near_ob  = smc.get("nearest_ob")
        near_fvg = smc.get("nearest_fvg")
        liq      = smc.get("liquidity", {})
        session  = smc.get("session", "UNKNOWN")

        htf_regime    = htf.get("regime", "?")
        htf_structure = htf.get("structure", {}).get("structure", "?")
        htf_bias      = htf.get("bias", "?")

        indicator_text = f"""
=== ICT / SMART MONEY ANALYSIS — {symbol} ({timeframe}) ===

Current Price : {price}
Session       : {session}

--- MARKET REGIME & STRUCTURE ---
LTF Regime    : {regime}
HTF Regime    : {htf_regime} | HTF Structure: {htf_structure} | HTF Bias: {htf_bias}
LTF Structure : {ms.get('structure','?')} | Last BOS: {ms.get('last_bos','None')} | CHOCH: {ms.get('choch',False)}
Swing High    : {ms.get('swing_high','N/A')} | Swing Low: {ms.get('swing_low','N/A')}

--- SMART MONEY ZONES ---
Nearest OB    : {near_ob}
Nearest FVG   : {near_fvg}
Buy-side Liq  : {liq.get('buy_side',[])}   (equal highs — SM targets these)
Sell-side Liq : {liq.get('sell_side',[])}  (equal lows  — SM targets these)
Nearest Sweep Target: {liq.get('nearest_sweep_target','N/A')}

--- TECHNICAL INDICATORS ---
RSI (14)      : {rsi.get('value','N/A')} → {rsi.get('signal','')}
MACD          : {macd.get('value','N/A')} → {macd.get('signal','')}
MACD Histogram: {macd_hist.get('value','N/A')} → {macd_hist.get('signal','')}
Stochastic    : %K={stoch.get('k','N/A')} %D={stoch.get('d','N/A')} → {stoch.get('signal','')}
Williams %R   : {willr.get('value','N/A')} → {willr.get('signal','')}
ADX           : {adx.get('value','N/A')} → {adx.get('signal','')}
ATR           : {atr.get('value','N/A')}
Bollinger     : {bb.get('position','N/A')} | Upper: {bb.get('upper','N/A')} Lower: {bb.get('lower','N/A')}
EMA Signal    : {ema.get('signal','N/A')} | EMA20: {ema.get('ema_20','N/A')} | EMA50: {ema.get('ema_50','N/A')}
"""

        prompt = f"""You are an ICT (Inner Circle Trader) / Smart Money analyst at a hedge fund.
Think like Smart Money, NOT retail.

{indicator_text}

Core principle: Price moves to LIQUIDITY. Your job is to identify where liquidity sits and where SM will move next.

Analyze using this priority order:
1. REGIME CHECK: Is it TREND/RANGE/CHAOS? CHAOS → NEUTRAL always.
2. MULTI-TF ALIGNMENT: Does HTF bias agree with LTF? Aligned = higher confidence.
3. STRUCTURE: HH/HL = bullish structure. LH/LL = bearish. CHOCH = potential reversal.
4. LIQUIDITY: Which side is being targeted? Buy-side (equal highs) = SM may sweep up then reverse. Sell-side (equal lows) = SM may sweep down then reverse.
5. SMART MONEY ZONES: Is price at/near an OB or FVG? These are high-probability entries.
6. INDICATORS: Use as CONFIRMATION only, not primary signal. ADX>20 = valid trend.

Respond ONLY with valid JSON:
{{
  "bias": "BULLISH" | "BEARISH" | "NEUTRAL",
  "confidence": <integer 0-100>,
  "regime_assessment": "TREND | RANGE | CHAOS",
  "liquidity_target": "<where SM is likely going next>",
  "key_signals": [
    {{"indicator": "...", "signal": "...", "weight": "HIGH|MEDIUM|LOW"}},
    ...
  ],
  "momentum_direction": "UPWARD" | "DOWNWARD" | "FLAT",
  "volatility_level": "HIGH" | "MEDIUM" | "LOW",
  "summary": "<2-3 sentences from Smart Money perspective>"
}}

Rules:
- CHAOS regime → bias must be NEUTRAL, confidence ≤ 30
- RANGE regime → only trade edges (near OB/FVG), confidence capped at 55
- HTF and LTF must align for confidence > 70
- A liquidity sweep BEFORE entry = very high confidence signal
"""

        try:
            response = client.models.generate_content(
                model=MODEL_ID,
                contents=prompt,
                config={"response_mime_type": "application/json"},
            )
            data = json.loads(response.text)
            bias = data.get("bias", "NEUTRAL")
            confidence = int(data.get("confidence", 50))
            summary = data.get("summary", "")
            key_signals = data.get("key_signals", [])
            momentum = data.get("momentum_direction", "FLAT")
            volatility = data.get("volatility_level", "MEDIUM")

            report = f"""📊 **INDICATOR ANALYSIS — {symbol}USDT ({timeframe})**

**Overall Bias:** {bias} (Confidence: {confidence}%)
**Momentum:** {momentum} | **Volatility:** {volatility}

**Key Signals:**
"""
            for sig in key_signals:
                weight_emoji = "🔴" if sig.get("weight") == "HIGH" else "🟡" if sig.get("weight") == "MEDIUM" else "⚪"
                report += f"  {weight_emoji} {sig.get('indicator', '')}: {sig.get('signal', '')}\n"

            report += f"\n**Summary:** {summary}"

            return {
                "indicator_report": report,
                "indicator_bias": bias,
                "indicator_confidence": confidence,
                "indicator_data": data,
            }

        except Exception as e:
            logger.error(f"IndicatorAgent error: {e}")
            return {
                "indicator_report": f"⚠️ Indicator analysis failed: {str(e)[:100]}",
                "indicator_bias": "NEUTRAL",
                "indicator_confidence": 0,
            }

    return indicator_agent_node
