"""
CryptoStream AI — Indicator Agent
Analyzes technical indicators using Gemini and returns a structured report.
Prompt adapts per asset class:
  CRYPTO / MACRO → ICT / Smart Money analysis (OBs, FVGs, liquidity)
  STOCK          → Standard technical analysis (trend, momentum, volume)
"""

import json
import logging
import os

from google import genai

logger = logging.getLogger(__name__)
MODEL_ID = os.environ.get("MODEL_ID", "gemini-2.5-flash")


def create_indicator_agent(client: genai.Client):
    def indicator_agent_node(state: dict) -> dict:
        symbol = state.get("symbol", "BTC")
        timeframe = state.get("timeframe", "15m")
        asset_class = state.get("asset_class", "CRYPTO")
        indicator_summary = state.get("indicator_summary", {})

        if not indicator_summary:
            return {
                "indicator_report": "⚠️ Indicator data unavailable — skipping indicator analysis.",
                "indicator_bias": "NEUTRAL",
                "indicator_confidence": 0,
            }

        price = indicator_summary.get("price", "N/A")

        # Common indicators (all asset classes)
        rsi       = indicator_summary.get("rsi", {})
        macd      = indicator_summary.get("macd", {})
        macd_hist = indicator_summary.get("macd_histogram", {})
        stoch     = indicator_summary.get("stochastic", {})
        willr     = indicator_summary.get("williams_r", {})
        adx       = indicator_summary.get("adx", {})
        atr       = indicator_summary.get("atr", {})
        bb        = indicator_summary.get("bollinger_bands", {})
        ema       = indicator_summary.get("ema", {})
        vwap      = indicator_summary.get("vwap", {})
        vol       = indicator_summary.get("volume", {})
        hurst     = indicator_summary.get("hurst", {})
        patterns  = indicator_summary.get("patterns", {})
        htf       = indicator_summary.get("higher_timeframe", {})

        # Common indicator block (shared across all asset classes)
        common_indicators = f"""
--- TECHNICAL INDICATORS ---
RSI (14)      : {rsi.get('value','N/A')} → {rsi.get('signal','')}
MACD          : {macd.get('value','N/A')} → {macd.get('signal','')}
MACD Histogram: {macd_hist.get('value','N/A')} → {macd_hist.get('signal','')}
Stochastic    : %K={stoch.get('k','N/A')} %D={stoch.get('d','N/A')} → {stoch.get('signal','')}
Williams %R   : {willr.get('value','N/A')} → {willr.get('signal','')}
ADX           : {adx.get('value','N/A')} → {adx.get('signal','')}
ATR           : {atr.get('value','N/A')}
Bollinger     : {bb.get('position','N/A')} | Upper: {bb.get('upper','N/A')} Lower: {bb.get('lower','N/A')}
EMA Signal    : {ema.get('signal','N/A')} | EMA20: {ema.get('ema_20','N/A')} | EMA50: {ema.get('ema_50','N/A')} | EMA200: {ema.get('ema_200','N/A')}
VWAP          : {vwap.get('value','N/A')} → {vwap.get('position','N/A')}
Volume Spike  : {vol.get('spike', False)} | CMF: {vol.get('cmf','N/A')}
Patterns      : {', '.join(patterns.get('detected', ['None']))}
HTF Bias      : {htf.get('bias','?')} ({htf.get('timeframe','?')}) | ADX: {htf.get('adx','?')} | RSI: {htf.get('rsi','?')}
Hurst H100    : {hurst.get('h100','N/A')} ({hurst.get('regime','?')})
"""

        # ── CRYPTO / MACRO: Full ICT / Smart Money prompt ─────────────────────
        if asset_class in ("CRYPTO", "MACRO"):
            smc      = indicator_summary.get("smart_money", {})
            ms       = smc.get("structure", {})
            near_ob  = smc.get("nearest_ob") or {}
            near_fvg = smc.get("nearest_fvg") or {}
            liq      = smc.get("liquidity", {})
            session  = smc.get("session", "UNKNOWN")
            regime   = smc.get("regime", "UNKNOWN")
            htf_regime    = htf.get("regime", "?")
            htf_structure = htf.get("structure", {}).get("structure", "?")

            # Format OB as readable price string
            if near_ob:
                ob_type = near_ob.get("type", "OB")
                ob_top  = near_ob.get("top", "?")
                ob_bot  = near_ob.get("bottom", "?")
                ob_str  = near_ob.get("strength", "?")
                try:
                    _p = float(price)
                    _ot, _ob = float(ob_top), float(ob_bot)
                    ob_relation = "price INSIDE OB ← HIGH PROBABILITY ZONE" if _ob <= _p <= _ot else ("price ABOVE OB → support below" if _p > _ot else "price BELOW OB → resistance above")
                except Exception:
                    ob_relation = ""
                near_ob_str = f"{ob_type} zone {ob_bot}–{ob_top} (strength: {ob_str}) | {ob_relation}"
            else:
                near_ob_str = "None detected"

            # Format FVG as readable price string
            if near_fvg:
                fvg_type = near_fvg.get("type", "FVG")
                fvg_top  = near_fvg.get("top", "?")
                fvg_bot  = near_fvg.get("bottom", "?")
                fvg_gap  = near_fvg.get("gap_size", "?")
                try:
                    _p = float(price)
                    _ft, _fb = float(fvg_top), float(fvg_bot)
                    fvg_relation = "price INSIDE FVG ← imbalance entry zone" if _fb <= _p <= _ft else ("price ABOVE FVG → filled / support" if _p > _ft else "price BELOW FVG → unfilled resistance")
                except Exception:
                    fvg_relation = ""
                near_fvg_str = f"{fvg_type} zone {fvg_bot}–{fvg_top} (gap: {fvg_gap}) | {fvg_relation}"
            else:
                near_fvg_str = "None detected"

            buy_side_str  = ", ".join(str(x) for x in liq.get("buy_side",  [])) or "none"
            sell_side_str = ", ".join(str(x) for x in liq.get("sell_side", [])) or "none"
            sweep_target  = liq.get("nearest_sweep_target", "N/A")

            indicator_text = f"""
=== ICT / SMART MONEY ANALYSIS — {symbol} ({timeframe}) ===

Current Price : {price}
Session       : {session}

--- MARKET REGIME & STRUCTURE ---
LTF Regime    : {regime}
HTF Regime    : {htf_regime} | HTF Structure: {htf_structure} | HTF Bias: {htf.get('bias','?')}
LTF Structure : {ms.get('structure','?')} | Last BOS: {ms.get('last_bos','None')} | CHOCH: {ms.get('choch',False)}
Swing High    : {ms.get('swing_high','N/A')} | Swing Low: {ms.get('swing_low','N/A')}

--- SMART MONEY ZONES (PRICE LEVELS) ---
Nearest OB    : {near_ob_str}
Nearest FVG   : {near_fvg_str}
Buy-side Liq  : {buy_side_str}   ← equal highs, SM stop-hunts these upward
Sell-side Liq : {sell_side_str}  ← equal lows,  SM stop-hunts these downward
Next SM Target: {sweep_target}   ← nearest liquidity pool SM will likely raid
{common_indicators}"""

            prompt = f"""You are an ICT (Inner Circle Trader) / Smart Money analyst at a hedge fund.
Think like Smart Money, NOT retail. Asset: {asset_class}.

{indicator_text}

Core principle: Price moves to LIQUIDITY. Identify where liquidity sits and where SM will move next.

Analyze in this priority order:
1. REGIME CHECK: TREND/RANGE/CHAOS? CHAOS → NEUTRAL always.
2. MULTI-TF ALIGNMENT: Does HTF bias agree with LTF? Aligned = higher confidence.
3. STRUCTURE: HH/HL = bullish. LH/LL = bearish. CHOCH = potential reversal.
4. LIQUIDITY: Which side is targeted? Buy-side sweep = potential SHORT. Sell-side sweep = potential LONG.
5. SMART MONEY ZONES: Price at/near OB or FVG = high-probability entry.
6. INDICATORS: Confirmation only. ADX>20 = valid trend. VWAP = institutional bias.

Rules:
- CHAOS regime → NEUTRAL, confidence ≤ 30
- RANGE → only trade edges (near OB/FVG), confidence capped at 55
- HTF and LTF must align for confidence > 70
- Liquidity sweep BEFORE entry = very high confidence signal

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
}}"""

        # ── STOCK: Standard technical momentum analysis ────────────────────────
        else:
            trend_analysis = indicator_summary.get("trend_analysis", {})
            levels = trend_analysis.get("levels", {})

            indicator_text = f"""
=== TECHNICAL ANALYSIS — {symbol} STOCK ({timeframe}) ===

Current Price : {price}
HTF Bias      : {htf.get('bias','?')} ({htf.get('timeframe','?')})
Market Phase  : {trend_analysis.get('market_phase','?')} | Trend: {trend_analysis.get('primary_trend','?')}
Support       : {levels.get('support','N/A')} | Resistance: {levels.get('resistance','N/A')}
{common_indicators}"""

            prompt = f"""You are a professional equity technical analyst. Analyze {symbol} stock on {timeframe} timeframe.

{indicator_text}

Analysis framework for STOCKS:
1. TREND: Use EMA20/50/200 alignment. Price > EMA200 = long-term bullish. Price < EMA200 = bearish.
2. MOMENTUM: RSI + MACD histogram direction. Bullish cross + RSI 45-65 = ideal entry zone.
3. VOLUME: Confirm moves with volume. Breakout on low volume = weak signal.
4. VWAP: Price above VWAP = institutional buying pressure. Below = selling pressure.
5. VOLATILITY: ADX > 25 = trending, trade with trend. ADX < 20 = ranging, trade support/resistance.
6. HTF ALIGNMENT: LTF signal must agree with HTF bias for higher confidence.

Rules:
- Confidence > 70 ONLY if EMA trend + MACD + RSI all agree
- Confidence capped at 50 if ADX < 15 (no clear trend)
- Volume spike on breakout = HIGH confidence. No volume = LOW.
- Do NOT reference ICT, OBs, FVGs, or liquidity sweeps — not applicable to stocks.

Respond ONLY with valid JSON:
{{
  "bias": "BULLISH" | "BEARISH" | "NEUTRAL",
  "confidence": <integer 0-100>,
  "regime_assessment": "TREND | RANGE | CHAOS",
  "liquidity_target": "<nearest key level price target>",
  "key_signals": [
    {{"indicator": "...", "signal": "...", "weight": "HIGH|MEDIUM|LOW"}},
    ...
  ],
  "momentum_direction": "UPWARD" | "DOWNWARD" | "FLAT",
  "volatility_level": "HIGH" | "MEDIUM" | "LOW",
  "summary": "<2-3 sentences using EMA trend + momentum + volume context>"
}}"""

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

            ticker_suffix = "" if asset_class == "STOCK" else "USDT"
            report = f"""📊 **INDICATOR ANALYSIS — {symbol}{ticker_suffix} ({timeframe}) [{asset_class}]**

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
