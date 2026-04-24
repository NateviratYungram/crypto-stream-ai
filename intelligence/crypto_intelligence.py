"""
CryptoStream AI — Crypto Intelligence Orchestrator
Main entry point that runs the full Multi-Agent pipeline sequentially.

Pipeline order:
  1. Technical Engine → OHLCV + indicators from Postgres
  2. Chart Generator → candlestick + trend charts (base64)
  3. Confluence Agent → multi-timeframe RSI/MACD/ADX/EMA (pure Python, no LLM)
  4. Indicator Agent → RSI/MACD/Stoch analysis
  5. Pattern Agent (Vision) → chart pattern detection
  6. Trend Agent (Vision) → trendline channel analysis
  7. Sentiment Agent → RSS news scoring
  8. Decision Agent → LONG/SHORT/HOLD with entry/SL/TP
  9. Master Agent → final weighted gate with safety rules

Usage:
    from intelligence.crypto_intelligence import CryptoIntelligence
    
    intel = CryptoIntelligence(gemini_client)
    result = intel.analyze("BTC", "15m")
    print(result["master_report"])
"""

import logging
import time
from typing import Optional
from google import genai

from intelligence.technical_engine import get_kline_data, compute_indicators, get_indicator_summary
from intelligence.chart_generator import generate_kline_chart, generate_trend_chart
from intelligence.agents.confluence_agent import create_confluence_agent
from intelligence.agents.indicator_agent import create_indicator_agent
from intelligence.agents.pattern_agent import create_pattern_agent
from intelligence.agents.trend_agent import create_trend_agent
from intelligence.agents.sentiment_agent import create_sentiment_agent
from intelligence.agents.decision_agent import create_decision_agent
from intelligence.agents.master_agent import create_master_agent

logger = logging.getLogger(__name__)


class CryptoIntelligence:
    """
    Multi-Agent intelligence system for CryptoStream AI.
    Mirrors QuantAgent's TradingGraph but uses Gemini instead of LangGraph/OpenAI.
    """

    def __init__(self, client: genai.Client, config: dict = None):
        self.client = client
        self.config = config or {}

        # Instantiate all agents
        self.confluence_agent = create_confluence_agent()          # pure Python, no LLM
        self.indicator_agent  = create_indicator_agent(client)
        self.pattern_agent    = create_pattern_agent(client)
        self.trend_agent      = create_trend_agent(client)
        self.sentiment_agent  = create_sentiment_agent(client)
        self.decision_agent   = create_decision_agent(client)
        self.master_agent     = create_master_agent(client, config)

        logger.info("CryptoIntelligence: All agents initialized ✅")

    def analyze(
        self,
        symbol: str,
        timeframe: str = "15m",
        limit: int = 60,
        include_charts: bool = True,
        asset_class: str = "CRYPTO"
    ) -> dict:
        """
        Run the full multi-agent analysis pipeline.

        Args:
            symbol:        Crypto symbol, e.g. "BTC", "ETH", "BTCUSDT"
            timeframe:     Candle timeframe, e.g. "1m", "15m", "1h", "4h"
            limit:         Number of candles to fetch
            include_charts: Whether to generate chart images for Vision agents
            asset_class:   "CRYPTO", "STOCK", "MACRO"

        Returns:
            Final state dict with all agent reports and master_decision.
        """
        t_start = time.time()
        sym = symbol.upper().replace("USDT", "")  # normalise to "BTC", "ETH"

        logger.info(f"CryptoIntelligence: Starting analysis for {sym} ({timeframe})")

        # ── Step 0: Initialise state ──────────────────────────────────────────
        state: dict = {
            "symbol":    sym,
            "timeframe": timeframe,
            "asset_class": asset_class
        }

        # ── Step 1: Technical Engine ──────────────────────────────────────────
        logger.info("Step 1/8: Fetching OHLCV + computing indicators...")
        df_raw = get_kline_data(sym, timeframe, limit, asset_class)

        if df_raw is None or df_raw.empty:
            logger.warning(f"No OHLCV data for {sym}. Falling back to partial analysis.")
            state["kline_data"] = None
            state["indicator_summary"] = {}
        else:
            df = compute_indicators(df_raw)
            state["kline_data"] = df
            state["indicator_summary"] = get_indicator_summary(df, sym)
            logger.info(f"  → {len(df)} candles, indicators computed")

        # ── Step 2: Chart Generation ──────────────────────────────────────────
        if include_charts and state.get("kline_data") is not None:
            logger.info("Step 2/9: Generating charts...")
            df = state["kline_data"]
            state["kline_chart_b64"]  = generate_kline_chart(df, sym)
            state["trend_chart_b64"]  = generate_trend_chart(df, sym)
            logger.info(f"  → Charts generated ({'OK' if state['kline_chart_b64'] else 'FAILED'})")
        else:
            state["kline_chart_b64"] = ""
            state["trend_chart_b64"] = ""
            logger.info("Step 2/9: Skipping charts (no data or disabled)")

        # ── Step 3: Confluence Agent (Multi-Timeframe, pure Python) ───────────
        logger.info("Step 3/9: Confluence Agent (Multi-TF)...")
        state.update(self.confluence_agent(state))
        logger.info(
            f"  → Confluence: {state.get('confluence_score', 0):.0f}/100 "
            f"({state.get('confluence_data', {}).get(timeframe, {}).get('direction', '?')} base TF)"
        )

        # ── Step 4: Indicator Agent ───────────────────────────────────────────
        logger.info("Step 4/9: Indicator Agent...")
        state.update(self.indicator_agent(state))
        logger.info(f"  → Bias: {state.get('indicator_bias','?')}, Confidence: {state.get('indicator_confidence','?')}%")

        # ── Step 5: Pattern Agent (Vision) ────────────────────────────────────
        logger.info("Step 5/9: Pattern Agent (Chart Vision)...")
        state.update(self.pattern_agent(state))
        logger.info(f"  → Pattern: {state.get('detected_pattern','?')}, Bias: {state.get('pattern_bias','?')}")

        # ── Step 6: Trend Agent (Vision) ──────────────────────────────────────
        logger.info("Step 6/9: Trend Agent (Chart Vision)...")
        state.update(self.trend_agent(state))
        logger.info(f"  → Direction: {state.get('trend_direction','?')}, Bias: {state.get('trend_bias','?')}")

        # ── Step 7: Sentiment Agent ───────────────────────────────────────────
        logger.info("Step 7/9: Sentiment Agent (RSS News)...")
        state.update(self.sentiment_agent(state))
        logger.info(f"  → Sentiment: {state.get('sentiment_label','?')} ({state.get('sentiment_score',0):+.0f})")

        # ── Step 8: Decision Agent ────────────────────────────────────────────
        logger.info("Step 8/9: Decision Agent (LONG/SHORT/HOLD)...")
        state.update(self.decision_agent(state))
        logger.info(f"  → Decision: {state.get('trade_decision','?')}, Confidence: {state.get('decision_confidence','?')}%")

        # ── Step 9: Master Agent (Final Gate) ─────────────────────────────────
        logger.info("Step 9/9: Master Agent (Final weighted vote)...")
        state.update(self.master_agent(state))
        logger.info(f"  → MASTER: {state.get('master_decision','?')} @ {int(state.get('master_confidence',0)*100)}%")

        elapsed = time.time() - t_start
        state["analysis_time_seconds"] = round(elapsed, 2)
        logger.info(f"CryptoIntelligence: Analysis complete in {elapsed:.1f}s ✅")

        return state

    def analyze_and_trade(
        self,
        symbol: str,
        timeframe: str = "15m",
        limit: int = 60,
        asset_class: str = "CRYPTO",
        dry_run: bool = True,
        risk_pct: float = 1.0,
        account_balance: float = None,
        confirmation_required: bool = True,
        cb_config: dict = None,
        guard_config: dict = None,
    ) -> dict:
        """
        Full pipeline: Analysis → Guard → CircuitBreaker → MT5 execution.

        Args:
            symbol               : e.g. "BTC", "ETH", "GOLD"
            timeframe            : "15m", "1h", "4h"
            dry_run              : True = analyse only, never sends to MT5
                                   False = live execution (use with caution!)
            risk_pct             : % of balance risked per trade (default 1%)
            account_balance      : Override account balance for position sizing
            confirmation_required: True = return DRAFT (user confirms via chat)
                                   False = execute immediately after guard/CB pass
            cb_config / guard_config: Override defaults for CircuitBreaker/GuardLayer

        Returns:
            {
              "analysis":   full state from analyze()
              "execution":  result from execution_bridge.execute_signal()
            }
        """
        # Step 1: Run full AI analysis pipeline
        state = self.analyze(symbol, timeframe, limit, asset_class=asset_class)

        # Step 2: Pass to execution bridge
        from intelligence.execution_bridge import execute_signal
        execution = execute_signal(
            state=state,
            dry_run=dry_run,
            risk_pct=risk_pct,
            account_balance=account_balance,
            cb_config=cb_config,
            guard_config=guard_config,
            confirmation_required=confirmation_required,
        )

        logger.info(
            f"CryptoIntelligence.analyze_and_trade: {symbol} "
            f"decision={state.get('master_decision','?')} "
            f"execution_status={execution.get('status','?')}"
        )

        return {
            "analysis":  state,
            "execution": execution,
        }

    def get_quick_signals(self, symbols: list, timeframe: str = "15m") -> list:
        """
        Lightweight signal generation for multiple symbols.
        Uses only indicators (no Vision) for speed.

        Returns:
            List of signal dicts with symbol, bias, confidence, key metrics.
        """
        signals = []
        for sym in symbols:
            try:
                # Need at least 2 candles for delta calculation
                df_raw = get_kline_data(sym, timeframe, limit=30)
                if df_raw is None or len(df_raw) < 10:
                    continue

                df = compute_indicators(df_raw)
                summary = get_indicator_summary(df, sym)

                rsi   = float(summary.get("rsi", {}).get("value", 50))
                macd_data = summary.get("macd", {})
                macd_sig  = macd_data.get("signal", "")
                price = float(summary.get("price", 0))
                adx   = float(summary.get("adx", {}).get("value", 0))

                # ── Calculate Real Delta ──────────────────────────────────────
                # Compare latest close with previous close
                cur_close = float(df["Close"].iloc[-1])
                prev_close = float(df["Close"].iloc[-2]) if len(df) > 1 else cur_close
                delta_pct = ((cur_close - prev_close) / (prev_close if prev_close != 0 else 1)) * 100

                # ── Calculate Real Volume Surge ─────────────────────────────────
                # Ratio of latest bar volume vs 20-period average
                try:
                    vol_col = "Volume" if "Volume" in df.columns else "volume"
                    if vol_col in df.columns and len(df) >= 5:
                        cur_vol = float(df[vol_col].iloc[-1])
                        avg_vol = float(df[vol_col].tail(20).mean())
                        vol_surge = round(cur_vol / avg_vol, 2) if avg_vol > 0 else 1.0
                    else:
                        vol_surge = 1.0
                except Exception:
                    vol_surge = 1.0

                # ── Apply Trained ML Model (Ensemble + Neural) ────────────────
                from intelligence.ml.signal_model import predict_with_neural_consensus
                asset_cls = "MACRO" if sym in ["GOLD", "SILVER", "OIL", "EURUSD", "GBPUSD", "USDJPY"] else "CRYPTO"
                
                # We evaluate the probability of a WIN for both LONG and SHORT scenarios
                idx = len(df) - 1
                try:
                    buy_ml  = predict_with_neural_consensus(df, idx, side="BUY", symbol=sym, asset_class=asset_cls)
                    sell_ml = predict_with_neural_consensus(df, idx, side="SELL", symbol=sym, asset_class=asset_cls)
                    
                    if buy_ml.get("available") and sell_ml.get("available"):
                        b_prob = buy_ml.get("win_probability", 0.5)
                        s_prob = sell_ml.get("win_probability", 0.5)
                        
                        if b_prob >= s_prob:
                            best_prob = b_prob
                            best_dir = "BUY"
                            rationale = buy_ml.get("rationale", [])
                        else:
                            best_prob = s_prob
                            best_dir = "SELL"
                            rationale = sell_ml.get("rationale", [])
                            
                        # Set thresholds: > 52% is considered an actionable edge
                        if best_prob > 0.52:
                            direction = best_dir
                            # Scale confidence from 50%-100% to 0-100% UI meter
                            confidence = min(98, int((best_prob - 0.50) * 2.0 * 100))
                        else:
                            direction = "HOLD"
                            confidence = min(98, int((best_prob - 0.50) * 2.0 * 100) if best_prob > 0.50 else int((0.50 - best_prob) * 2.0 * 100))
                            
                        # Generate reasoning
                        if rationale:
                            reason = f"ML Focus: {' ∙ '.join(rationale)} (WinProb: {best_prob*100:.1f}%)"
                        else:
                            reason = f"ML WinProb: {best_prob*100:.1f}%"
                    else:
                        raise ValueError("Model unavailable")
                except Exception as ml_err:
                    import traceback
                    logger.error(f"ML evaluation failed for {sym}: {ml_err}\n{traceback.format_exc()}")
                    # Fallback to basic heuristics
                    rsi_score = ((50 - rsi) / 30.0) * 40
                    macd_score = 25 if "Bullish" in macd_sig else -25 if "Bearish" in macd_sig else 0
                    total_raw = (rsi_score + macd_score) * (1.0 + (min(adx, 50) / 100.0)) + (abs(delta_pct) * 5)
                    direction = "BUY" if total_raw > 15 else "SELL" if total_raw < -15 else "HOLD"
                    confidence = min(98, max(5, int(abs(total_raw))))
                    reason = f"RSI={rsi:.1f}, MACD={macd_sig}, ADX={adx:.1f}"

                macro_list = ["GOLD", "SILVER", "OIL", "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "NZDUSD"]
                display_sym = sym if sym in macro_list else f"{sym}USDT"

                signals.append({
                    "symbol": display_sym,
                    "direction": direction,
                    "confidence": confidence,
                    "price": price,
                    "rsi": round(rsi, 1),
                    "macd_signal": macd_sig,
                    "adx": round(adx, 1),
                    "reason": reason,
                    "timeframe": timeframe,
                    "delta_pct": round(delta_pct, 4),
                    "vol_surge": vol_surge,
                })
            except Exception as e:
                logger.warning(f"QuickSignal error for {sym}: {e}")
                continue

        signals.sort(key=lambda x: x["confidence"], reverse=True)
        return signals
