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
from datetime import datetime, timezone

from google import genai

from intelligence.agents.confluence_agent import create_confluence_agent
from intelligence.agents.decision_agent import create_decision_agent
from intelligence.agents.indicator_agent import create_indicator_agent
from intelligence.agents.intermarket_agent import create_intermarket_agent
from intelligence.agents.master_agent import create_master_agent
from intelligence.agents.pattern_agent import create_pattern_agent
from intelligence.agents.sentiment_agent import create_sentiment_agent
from intelligence.agents.trend_agent import create_trend_agent
from intelligence.guards.correlation_guardian import check_directional_correlation
from intelligence.chart_generator import generate_kline_chart, generate_trend_chart
from intelligence.technical_engine import (
    compute_indicators,
    get_indicator_summary,
    get_kline_data,
    get_smart_money_analysis,
)
from intelligence.ml.performance_feedback import score_signal_feedback
from intelligence.ml.trading_quality_gate import get_trading_quality_gate

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
        self.intermarket_agent = create_intermarket_agent()        # pure Python, no LLM
        self.confluence_agent  = create_confluence_agent()         # pure Python, no LLM
        self.indicator_agent   = create_indicator_agent(client)
        self.pattern_agent     = create_pattern_agent(client)
        self.trend_agent       = create_trend_agent(client)
        self.sentiment_agent   = create_sentiment_agent(client)
        self.decision_agent    = create_decision_agent(client)
        self.master_agent      = create_master_agent(client, config)

        logger.info("CryptoIntelligence: All agents initialized ✅")

    def analyze(
        self,
        symbol: str,
        timeframe: str = "15m",
        limit: int = 200,
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

        # ── Step 0.5: Trading Quality Gate ───────────────────────────────────
        # Non-STOCK only: check model readiness and paper trade performance
        if asset_class != "STOCK":
            try:
                gate = get_trading_quality_gate(symbol=sym)
                state["quality_gate"] = gate
                mode = gate.get("mode", "observe_only")
                blockers = gate.get("blockers", [])
                logger.info(
                    f"Quality Gate: mode={mode} "
                    f"live_ready={gate.get('live_ready',False)} "
                    f"blockers={blockers}"
                )
                # Store mode so master_agent can use it for sizing decisions
                state["quality_gate_mode"] = mode
            except Exception as e:
                logger.warning(f"Quality gate check failed: {e}")
                state["quality_gate_mode"] = "observe_only"
        else:
            state["quality_gate_mode"] = "tradeable"   # STOCK bypasses ML gate

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

            # ── Step 1a: Retail FOMO (Liquidation Heatmap) — CRYPTO only ─────────
            if asset_class == "CRYPTO":
                try:
                    from intelligence.tools.onchain_tools import onchain_engine
                    fomo = onchain_engine.get_fomo_heatmap(sym)
                    state["retail_fomo"] = fomo
                    logger.info(
                        f"  → FOMO: {fomo.get('retail_sentiment','?')} "
                        f"L={fomo.get('long_percent','?')}% S={fomo.get('short_percent','?')}%"
                    )
                except Exception as e:
                    logger.warning(f"FOMO fetch failed: {e}")

            # ── Step 1b: SMC / ICT Analysis — CRYPTO and MACRO only (not STOCK) ──
            if asset_class in ("CRYPTO", "MACRO"):
                try:
                    smc = get_smart_money_analysis(df)
                    if smc:
                        state["indicator_summary"]["smart_money"] = smc
                        logger.info(
                            f"  → SMC: regime={smc.get('regime','?')} "
                            f"structure={smc.get('structure',{}).get('structure','?')} "
                            f"session={smc.get('session','?')}"
                        )
                except Exception as e:
                    logger.warning(f"SMC analysis failed: {e}")

            # ── Step 1c: Higher-Timeframe Bias ───────────────────────────────────
            _htf_map = {"1m": "15m", "5m": "1h", "15m": "1h", "1h": "4h", "4h": "1d"}
            htf_tf = _htf_map.get(timeframe, "1h")
            try:
                df_htf_raw = get_kline_data(sym, htf_tf, limit=200, asset_class=asset_class)
                if df_htf_raw is not None and not df_htf_raw.empty:
                    df_htf = compute_indicators(df_htf_raw)
                    htf_last = df_htf.iloc[-1]

                    def _fs(v):
                        try:
                            import math
                            val = float(v)
                            return 0.0 if math.isnan(val) else round(val, 4)
                        except Exception:
                            return 0.0

                    htf_close = _fs(htf_last.get("Close"))
                    htf_e20   = _fs(htf_last.get("ema_20"))
                    htf_e50   = _fs(htf_last.get("ema_50"))
                    htf_bias  = (
                        "BULLISH" if htf_close > htf_e20 > htf_e50 else
                        "BEARISH" if htf_close < htf_e20 < htf_e50 else
                        "NEUTRAL"
                    )
                    # SMC structure on HTF only for CRYPTO/MACRO
                    htf_smc = get_smart_money_analysis(df_htf) if asset_class in ("CRYPTO", "MACRO") else {}
                    htf_summary = get_indicator_summary(df_htf, sym)
                    state["indicator_summary"]["higher_timeframe"] = {
                        "timeframe":  htf_tf,
                        "bias":       htf_bias,
                        "adx":        _fs(htf_last.get("adx_14")),
                        "rsi":        _fs(htf_last.get("rsi_14")),
                        "regime":     htf_smc.get("regime", "UNKNOWN"),
                        "structure":  htf_smc.get("structure", {}),
                        "nearest_ob": htf_smc.get("nearest_ob"),
                        "liquidity":  htf_smc.get("liquidity", {}),
                        "hurst":      htf_summary.get("hurst", {}),
                    }
                    logger.info(
                        f"  → HTF ({htf_tf}): bias={htf_bias} "
                        f"regime={htf_smc.get('regime','?')}"
                    )
            except Exception as e:
                logger.warning(f"HTF analysis failed: {e}")

            # ── Step 1d: ML Signal Probability — non-STOCK only (per memory rule) ─
            if asset_class != "STOCK":
                try:
                    from intelligence.ml.signal_model import predict_with_neural_consensus
                    _idx = len(df) - 1
                    ml_buy  = predict_with_neural_consensus(df, _idx, side="BUY",  symbol=sym, asset_class=asset_class)
                    ml_sell = predict_with_neural_consensus(df, _idx, side="SELL", symbol=sym, asset_class=asset_class)
                    buy_prob  = ml_buy.get("win_probability", 0.0)
                    sell_prob = ml_sell.get("win_probability", 0.0)
                    state["ml_signal"] = {
                        "available":        ml_buy.get("available", False),
                        "buy_prob":         round(buy_prob, 4),
                        "sell_prob":        round(sell_prob, 4),
                        "buy_pct":          round(buy_prob * 100, 1),
                        "sell_pct":         round(sell_prob * 100, 1),
                        "direction":        "BUY" if buy_prob > sell_prob else "SELL" if sell_prob > buy_prob else "NEUTRAL",
                        "neural_alignment": ml_buy.get("neural_alignment", False) or ml_sell.get("neural_alignment", False),
                        "mtf_blocked":      ml_buy.get("mtf_blocked", False),
                        "mtf_reason":       ml_buy.get("mtf_reason", ""),
                    }
                    logger.info(
                        f"  → ML: buy={round(buy_prob*100,1)}% sell={round(sell_prob*100,1)}% "
                        f"avail={ml_buy.get('available',False)}"
                    )
                except Exception as e:
                    logger.warning(f"ML prediction failed: {e}")
                    state["ml_signal"] = {"available": False}

        # ── Step 1.5: Intermarket Context (parallel fetch, pure Python) ─────────
        logger.info("Step 1.5/9: Intermarket Agent (DXY/VIX/F&G/Funding)...")
        state.update(self.intermarket_agent(state))
        im = state.get("intermarket", {})
        logger.info(
            f"  → macro={im.get('macro_bias','?')} "
            f"DXY={im.get('dxy',{}).get('trend','?')} "
            f"VIX={im.get('vix',{}).get('level','?')} "
            f"F&G={im.get('fear_greed',{}).get('value','?')}"
        )

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

        # ── Step 7.5: Asset-class session context (code-enforced, not LLM) ──────
        if asset_class == "MACRO":
            import datetime
            utc_h = datetime.datetime.utcnow().hour
            if 7 <= utc_h < 16:
                state["forex_session"] = "LONDON"
                state["session_quality"] = "GOOD"
            elif 13 <= utc_h < 22:
                state["forex_session"] = "NEW_YORK"
                state["session_quality"] = "GOOD"
            else:
                state["forex_session"] = "ASIA_THIN"
                state["session_quality"] = "POOR"
            logger.info(f"  → Forex session: {state['forex_session']} ({state['session_quality']})")

        # ── Step 8: Decision Agent ────────────────────────────────────────────
        logger.info("Step 8/9: Decision Agent (LONG/SHORT/HOLD)...")
        state.update(self.decision_agent(state))
        logger.info(f"  → Decision: {state.get('trade_decision','?')}, Confidence: {state.get('decision_confidence','?')}%")

        # ── Step 8.5: Directional Correlation (MT5 assets only) ──────────────
        trade_side = state.get("trade_decision", "HOLD")
        if trade_side in ("LONG", "SHORT"):
            dir_corr = check_directional_correlation(
                symbol=sym,
                side=trade_side,
                asset_class=asset_class,
            )
            state["directional_correlation"] = dir_corr
            logger.info(
                f"  → Directional corr: confirmed={dir_corr['confirmed']} "
                f"score={dir_corr['score']} conflicts={dir_corr['conflicts']}"
            )
        else:
            state["directional_correlation"] = {"confirmed": True, "score": 1.0, "conflicts": [], "checked": 0}

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
                best_prob = 0.50
                feedback = {"notes": [], "readiness": {}}
                quality_gate = get_trading_quality_gate(sym, entry_source="signal_feed_analysis")
                candidate_direction = "HOLD"

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
                        candidate_direction = best_dir

                        feedback = score_signal_feedback(sym, entry_source="signal_feed_analysis", side=best_dir)
                        quality_gate = get_trading_quality_gate(
                            sym,
                            entry_source="signal_feed_analysis",
                            side=best_dir,
                        )
                        best_prob = max(
                            0.35,
                            min(0.90, best_prob + float(feedback.get("probability_adjustment", 0.0) or 0.0)),
                        )

                        buy_sell_threshold = float(quality_gate.get("minimum_buy_sell_probability") or 0.66)
                        watch_threshold = float(quality_gate.get("minimum_watch_probability") or 0.53)

                        # Dynamic quality gate: no BUY/SELL unless model + paper evidence is ready.
                        if quality_gate.get("allow_buy_sell") and best_prob >= buy_sell_threshold:
                            direction = best_dir
                            confidence = min(99, max(50, int(round(best_prob * 100))))
                        elif best_prob >= watch_threshold:
                            direction = "WATCH"
                            confidence = min(99, max(50, int(round(best_prob * 100))))
                        else:
                            direction = "HOLD"
                            confidence = min(99, max(35, int(round(best_prob * 100))))

                        # Generate reasoning
                        if rationale:
                            reason = f"ML Focus: {' ∙ '.join(rationale)} (WinProb: {best_prob*100:.1f}%)"
                        else:
                            reason = f"ML WinProb: {best_prob*100:.1f}%"
                        if feedback.get("notes"):
                            reason = f"{reason} | Feedback: {'; '.join(feedback['notes'])}"
                        if not quality_gate.get("allow_buy_sell"):
                            blocked = ", ".join(quality_gate.get("blockers", [])[:4])
                            reason = f"{reason} | QualityGate: observe-only ({blocked or 'not live ready'})"
                    else:
                        raise ValueError("Model unavailable")
                except Exception as ml_err:
                    import traceback
                    logger.error(f"ML evaluation failed for {sym}: {ml_err}\n{traceback.format_exc()}")
                    # Fallback to basic heuristics
                    rsi_score = ((50 - rsi) / 30.0) * 40
                    macd_score = 25 if "Bullish" in macd_sig else -25 if "Bearish" in macd_sig else 0
                    total_raw = (rsi_score + macd_score) * (1.0 + (min(adx, 50) / 100.0)) + (abs(delta_pct) * 5)
                    direction = "BUY" if total_raw > 18 else "SELL" if total_raw < -18 else "WATCH" if abs(total_raw) >= 10 else "HOLD"
                    confidence = min(98, max(5, int(abs(total_raw))))
                    reason = f"RSI={rsi:.1f}, MACD={macd_sig}, ADX={adx:.1f}"
                    quality_gate = {
                        "live_ready": False,
                        "allow_buy_sell": False,
                        "mode": "heuristic_fallback",
                        "minimum_buy_sell_probability": 0.68,
                        "minimum_watch_probability": 0.53,
                        "blockers": ["ml_unavailable"],
                    }
                    if direction in ("BUY", "SELL"):
                        candidate_direction = direction
                        direction = "WATCH"

                macro_list = ["GOLD", "SILVER", "OIL", "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "NZDUSD"]
                display_sym = sym if sym in macro_list else f"{sym}USDT"
                signal_grade = "C"
                if direction in ("BUY", "SELL"):
                    if best_prob >= 0.68:
                        signal_grade = "A+"
                    elif best_prob >= 0.62:
                        signal_grade = "A"
                    elif best_prob >= 0.56:
                        signal_grade = "B"
                elif direction == "WATCH" and best_prob >= 0.53:
                    signal_grade = "WATCH"

                actionable = (
                    direction in ("BUY", "SELL")
                    and signal_grade in ("A+", "A", "B")
                    and bool(quality_gate.get("allow_buy_sell"))
                )
                tradeable = (
                    direction in ("BUY", "SELL")
                    and signal_grade in ("A+", "A")
                    and bool(quality_gate.get("live_ready"))
                )

                signals.append({
                    "symbol": display_sym,
                    "direction": direction,
                    "candidate_direction": candidate_direction,
                    "confidence": confidence,
                    "signal_grade": signal_grade,
                    "actionable": actionable,
                    "tradeable": tradeable,
                    "live_ready": bool(quality_gate.get("live_ready")),
                    "quality_gate": quality_gate,
                    "ml_win_prob": round(best_prob, 4),
                    "ml_win_pct": round(best_prob * 100, 1),
                    "feedback_ready": feedback.get("readiness"),
                    "feedback_notes": feedback.get("notes", []),
                    "price": price,
                    "rsi": round(rsi, 1),
                    "macd_signal": macd_sig,
                    "adx": round(adx, 1),
                    "reason": reason,
                    "timeframe": timeframe,
                    "delta_pct": round(delta_pct, 4),
                    "vol_surge": vol_surge,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
            except Exception as e:
                logger.warning(f"QuickSignal error for {sym}: {e}")
                continue

        signals.sort(key=lambda x: x["confidence"], reverse=True)
        return signals
