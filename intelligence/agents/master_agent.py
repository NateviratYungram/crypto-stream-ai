"""
CryptoStream AI — Master Agent
Final weighted voting + safety enforcement before outputting master decision.
Ported from QuantAgent master_agent.py — most critical node in the pipeline.

Weights:
  Technical (decision agent): 50%
  Sentiment:                  20%
  Confluence (multi-tf):      30%
"""

import json
import logging
import re
import os
from intelligence.ml.drift_monitor import drift_shield
from intelligence.agents.reflector_agent import get_reflexive_context
from intelligence.risk_manager import risk_manager
from intelligence.persistence_utils import log_sniper_rejection

logger = logging.getLogger(__name__)
MODEL_ID = os.environ.get("MODEL_ID", "gemini-2.5-flash")

# Safety thresholds (can be overridden via config)
DEFAULT_CONFIG = {
    "master_weight_technical": 0.55,   # Technical analysis is primary signal
    "master_weight_sentiment": 0.15,   # Reduced — crypto news often lags price
    "master_weight_confluence": 0.30,
    "master_confidence_threshold": 0.58,  # Lowered from 0.65 — was blocking valid setups
    "sentiment_contradiction_threshold": 60,  # Only block on extreme contradiction (was 50)
    "confluence_minimum": 33,              # Lowered from 40 — 1/3 agents agreeing = valid
    "sniper_mode": True,                   # Intelligence V7: Sniper Core (Auto-Reject < 80%)
}


def _compute_confluence_score(state: dict) -> float:
    """
    Simple confluence score based on agent agreement.
    Returns 0-100. Higher = more agents agree.
    
    In full QuantAgent, this involves multi-timeframe agreement.
    Here we use multi-agent agreement as a proxy.
    """
    biases = [
        state.get("indicator_bias", "NEUTRAL"),
        state.get("pattern_bias", "NEUTRAL"),
        state.get("trend_bias", "NEUTRAL"),
    ]
    decision = state.get("trade_decision", "HOLD")

    if decision == "LONG":
        agree = sum(1 for b in biases if "BULL" in str(b).upper())
    elif decision == "SHORT":
        agree = sum(1 for b in biases if "BEAR" in str(b).upper())
    else:
        return 30.0  # HOLD → low confluence assumed

    # 3/3 agree → 90, 2/3 → 60, 1/3 → 30, 0/3 → 10
    return {3: 90.0, 2: 60.0, 1: 30.0, 0: 10.0}.get(agree, 30.0)


def create_master_agent(client, config: dict = None):
    """
    Returns a master_agent_node.
    This is the FINAL gate — LLM acts as CONFIRMER, not generator.
    """
    cfg = DEFAULT_CONFIG.copy()
    if config:
        cfg.update(config)

    def master_agent_node(state: dict) -> dict:
        symbol = state.get("symbol", "BTC")
        timeframe = state.get("timeframe", "15m")

        # Gather all signals
        trade_decision   = state.get("trade_decision", "HOLD")
        decision_conf    = state.get("decision_confidence", 50)
        indicator_report = state.get("indicator_report", "")
        pattern_report   = state.get("pattern_report", "")
        trend_report     = state.get("trend_report", "")
        sentiment_score  = float(state.get("sentiment_score", 0))
        sentiment_label  = state.get("sentiment_label", "NEUTRAL")
        sentiment_report = state.get("sentiment_report", "NEUTRAL")

        # Reflector Agent Integration
        reflexive = get_reflexive_context(client, MODEL_ID)
        lessons = reflexive.get("lessons", "No reflexive lessons ready.")
        bias_adj = reflexive.get("bias_adjustments", {})

        # Weights — Dynamic adjustment based on reflexive performance
        w_tech = cfg["master_weight_technical"] * bias_adj.get("tech_weight", 1.0)
        w_sent = cfg["master_weight_sentiment"] * bias_adj.get("sent_weight", 1.0)
        w_conf = cfg["master_weight_confluence"] * bias_adj.get("conf_weight", 1.0)

        # Normalize weights to ensure they sum to ~1.0
        total_w = w_tech + w_sent + w_conf
        w_tech /= total_w
        w_sent /= total_w
        w_conf /= total_w

        # Hurst context
        hurst = state.get("indicator_summary", {}).get("hurst", {})
        h100  = hurst.get("h100", 0.5)
        h_regime = hurst.get("regime", "UNKNOWN")

        # ML Drift Shield
        indicators = state.get("indicator_summary", {})
        drift_report = drift_shield.check_drift(indicators)
        integrity_score = drift_report.get("integrity_score", 100)
        drift_status = drift_report.get("status", "STABLE")

        # Compute confluence
        confluence_score = _compute_confluence_score(state)

        # Intelligence V6: Portfolio Risk Analysis
        portfolio_risk = risk_manager.check_correlation_risk(symbol)
        protection     = risk_manager.check_equity_protection()
        news_shield    = risk_manager.check_news_shield(symbol)

        # Weights
        w_tech = cfg["master_weight_technical"]
        w_sent = cfg["master_weight_sentiment"]
        w_conf = cfg["master_weight_confluence"]

        # Map decision to numeric score
        tech_score = {
            "LONG":  decision_conf,
            "SHORT": -decision_conf,
            "HOLD":  0,
        }.get(trade_decision, 0)

        # Weighted composite score
        composite = (
            (tech_score * w_tech) +
            (sentiment_score * w_sent) +
            (confluence_score * (1 if trade_decision == "LONG" else -1 if trade_decision == "SHORT" else 0) * w_conf)
        )
        # Apply reflexive risk scale to composite if helpful
        composite *= bias_adj.get("risk_scale", 1.0)

        entry_zone = state.get("entry_zone", {})
        stop_loss  = state.get("stop_loss", {})
        take_profit = state.get("take_profit", {})
        rr = state.get("risk_reward_ratio", 0)

        # ── LLM confirmation call ──────────────────────────────────────────────
        # Pull Smart Money context from state
        smc     = state.get("indicator_summary", {}).get("smart_money", {})
        regime  = smc.get("regime", "UNKNOWN")
        ms      = smc.get("structure", {})
        session = smc.get("session", "UNKNOWN")
        near_ob = smc.get("nearest_ob")
        liq     = smc.get("liquidity", {})
        sweeps  = smc.get("sweeps", {})
        htf_data = state.get("indicator_summary", {}).get("higher_timeframe", {})
        htf_bias = htf_data.get("bias", "NEUTRAL")
        fomo     = state.get("retail_fomo", {})

        min_conf = float(cfg["master_confidence_threshold"])

        prompt = f"""You are the Master Risk Gate for a Smart Money / ICT hedge fund system.
Your ONLY job: CONFIRM or REJECT the signal from Decision Agent using ICT kill conditions.
You are a FILTER, not a generator.

=== SIGNAL TO REVIEW ===
Decision: {trade_decision} (confidence: {decision_conf}%)
Composite Score: {composite:.1f}

=== MARKET CONTEXT ===
Regime: {regime} | Session: {session}
Structure: {ms.get('structure','?')} | BOS: {ms.get('last_bos','?')} | CHOCH: {ms.get('choch',False)}
HTF Bias: {htf_bias}
Nearest OB: {near_ob}
Liquidity: buy-side={liq.get('buy_side',[])} | sell-side={liq.get('sell_side',[])}
SMC Sweeps: {json.dumps(sweeps, indent=2)}

=== HURST ANALYTICS ===
H100 (Regime Persistence): {h100} ({h_regime})
*Persistence (H>0.5) = Trends likely continue.
*Anti-Persistence (H<0.5) = Mean reversion / Random walk.

=== RETAIL FOMO (Liquidation Heatmap) ===
Status: {fomo.get('retail_sentiment', 'UNKNOWN')}
Long Ratio: {fomo.get('long_percent', 0)}% | Short Ratio: {fomo.get('short_percent', 0)}%
Institutional Bias: {fomo.get('institutional_bias', 'UNKNOWN')}
*If Retail is EXTREME_LONG_FOMO, look for SHORT traps. If EXTREME_SHORT_FOMO, look for LONG traps.

=== REFLEXIVE MEMORY (Lessons from Past Trades) ===
{lessons}

=== ML DRIFT SHIELD (Data Stability) ===
Score: {integrity_score}/100 | Status: {drift_status}
*If integrity is low, use extreme caution. Model reliability may be degraded.
{chr(10).join(drift_report.get('warnings', []))}

=== PORTFOLIO RISK GUARDIAN (Correlation & Protection) ===
Status: {portfolio_risk.get('status', 'UNKNOWN')} | Max Correlation: {portfolio_risk.get('max_corr', 0)}
Equity Protection: {protection.get('status', 'UNKNOWN')} (Drawdown: {protection.get('current_dd', 0)}%)
News Shield: {news_shield.get('status', 'UNKNOWN')} ({news_shield.get('reason', 'None')})
Conflicts: {json.dumps(portfolio_risk.get('conflicts', []), indent=2)}
*If status = HIGH_CORRELATION, reduce size or skip to avoid overlap.
*If Protection = BLOCKED, NO_TRADE is mandatory.
*If News Shield = BLOCKED, NO_TRADE is mandatory to avoid macro slippage.

=== AGENT REPORTS ===
Technical ({w_tech*100:.0f}%): {indicator_report[:350]}
Sentiment ({w_sent*100:.0f}%): Score {sentiment_score:+.0f}/100 ({sentiment_label}) — {sentiment_report[:150]}
Confluence ({w_conf*100:.0f}%): {confluence_score:.0f}/100

=== ICT KILL CONDITIONS (any one → NO_TRADE) ===
1. Regime = CHAOS → NO_TRADE always
2. Session = ASIA and asset contains GOLD/XAU → NO_TRADE
3. HTF and LTF structure completely opposed (e.g. HTF BEARISH + LTF LONG) AND no CHOCH → NO_TRADE
4. Confidence < {min_conf*100:.0f}% after weighting → NO_TRADE
   ML Data Integrity Score < 40 (CRITICAL_DRIFT) → NO_TRADE
   Sentiment contradicts by > {cfg['sentiment_contradiction_threshold']} points → NO_TRADE
6. Confluence < {cfg['confluence_minimum']} AND no OB/FVG confirmation → NO_TRADE
7. Equity Protection = BLOCKED (Daily Loss Limit) → NO_TRADE
8. Portfolio Correlation Status = HIGH_CORRELATION and Reasoning = "Aggressive overlap" → NO_TRADE

=== CONFIRMATION BOOSTERS (increase confidence) ===
+ Liquidity sweep occurred before entry signal
+ Price at/near a valid OB or FVG
+ HTF and LTF bias aligned
+ Session = LONDON or NEW_YORK

=== EXPERT DEBATE: COUNTER-EVIDENCE ===
Before confirming, you MUST force your mind to find the "Bear Case" (for Longs) or "Bull Case" (for Shorts).
If the counter-evidence is strong (e.g. recent reflexive failure in this regime), REJECT.

Respond ONLY with valid JSON:
{{
  "decision": "LONG" | "SHORT" | "NO_TRADE",
  "confidence": <integer 0-100>,
  "reasoning": "<cite regime + hurst + reflexive lessons + session specifically>",
  "counter_evidence": "<mandatory counter-argument to the signal>",
  "risk_factors": ["<risk1>", "<risk2>"],
  "entry_type": "MARKET" | "LIMIT"
}}
        """
        master_decision = "NO_TRADE"
        confidence      = 0.0
        reasoning       = "Initializing"
        counter_ev      = ""
        risk_factors    = []
        entry_type      = "LIMIT"
        kelly_size      = 0.0

        try:
            response = client.models.generate_content(
                model=MODEL_ID,
                contents=prompt,
                config={"response_mime_type": "application/json"},
            )
            data = json.loads(response.text)

            master_decision = data.get("decision", "NO_TRADE").upper()
            confidence_raw  = float(data.get("confidence", 0))
            confidence      = confidence_raw / 100 if confidence_raw > 1 else confidence_raw
            reasoning       = data.get("reasoning", "")
            counter_ev      = data.get("counter_evidence", "")
            risk_factors    = data.get("risk_factors", [])
            entry_type      = data.get("entry_type", "LIMIT")

            # Neural Kelly Sizing (V6)
            kelly_size = 0.0
            if master_decision in ("LONG", "SHORT"):
                kelly_size = risk_manager.calculate_kelly_size(
                    win_prob=confidence, 
                    rr_ratio=float(rr),
                    balance=100.0 # Standardize to % for now
                )
                # Apply reflexive scaling (e.g. scale down if recent performance is poor)
                kelly_size *= bias_adj.get("risk_scale", 1.0)

        except Exception as e:
            logger.error(f"MasterAgent LLM error: {e}")
            master_decision = "NO_TRADE"
            confidence      = 0.0
            reasoning       = f"Master agent error: {str(e)[:100]}"
            risk_factors    = []
            entry_type      = "LIMIT"

        # ── Safety enforcement (identical to QuantAgent master_agent.py) ──────
        min_conf = float(cfg["master_confidence_threshold"])

        if confidence < min_conf:
            master_decision = "NO_TRADE"
            reasoning = f"BLOCKED: Confidence {confidence:.0%} < threshold {min_conf:.0%}. " + reasoning

        # V7 Sniper Core: Extreme Precision Guard
        if cfg.get("sniper_mode") and confidence < 0.80 and master_decision != "NO_TRADE":
            master_decision = "NO_TRADE"
            sniper_reason = f"REJECTED BY SNIPER CORE: Win Probability ({confidence:.0%}) < 80% Hard Threshold. Target long-term capital preservation."
            
            # Log for the Audit Dashboard
            log_sniper_rejection(
                symbol=symbol,
                confidence=confidence,
                reasoning=reasoning,
                price=0.0 # Price not easily available here, logged as 0.0 or could be passed
            )
            
            reasoning = sniper_reason + " | ORIGINAL: " + reasoning

        if master_decision in ("LONG", "SHORT"):
            # Sentiment contradiction
            if master_decision == "LONG" and sentiment_score < -cfg["sentiment_contradiction_threshold"]:
                master_decision = "NO_TRADE"
                reasoning = f"BLOCKED: Technical LONG but Sentiment strongly BEARISH ({sentiment_score:+.0f}). " + reasoning
            elif master_decision == "SHORT" and sentiment_score > cfg["sentiment_contradiction_threshold"]:
                master_decision = "NO_TRADE"
                reasoning = f"BLOCKED: Technical SHORT but Sentiment strongly BULLISH ({sentiment_score:+.0f}). " + reasoning

        if master_decision in ("LONG", "SHORT") and confluence_score < cfg["confluence_minimum"]:
            master_decision = "NO_TRADE"
            reasoning = f"BLOCKED: Confluence {confluence_score:.0f} < minimum {cfg['confluence_minimum']}. " + reasoning

        # V6: Hard Protection Block
        if protection.get("status") == "BLOCKED":
            master_decision = "NO_TRADE"
            reasoning = f"CRITICAL BLOCKED: Equity Protection active ({protection.get('reason')}). Daily DD: {protection.get('current_dd')}%. " + reasoning

        # V9: News Shield Hard Block
        if news_shield.get("status") == "BLOCKED":
            master_decision = "NO_TRADE"
            reasoning = f"NEWS SHIELD BLOCKED: High impact macro news pending. {news_shield.get('reason')}. " + reasoning

        # ── Format final report ───────────────────────────────────────────────
        dec_emoji = {"LONG": "🚀", "SHORT": "🔻", "NO_TRADE": "🛑"}.get(master_decision, "🛑")
        conf_pct  = int(confidence * 100)

        report = f"""🧠 **MASTER DECISION — {symbol}USDT ({timeframe})**

**Final Signal:** {dec_emoji} **{master_decision}** (Confidence: {conf_pct}%)
**Entry Type:** {entry_type}

**Weighted Scores:**
- Technical ({w_tech*100:.0f}%): {trade_decision} @ {decision_conf}%
- Sentiment  ({w_sent*100:.0f}%): {sentiment_label} ({sentiment_score:+.0f}/100)
- Confluence ({w_conf*100:.0f}%): {confluence_score:.0f}/100
- ML Integrity: {integrity_score}/100 ({drift_status})
- **Composite:** {composite:.1f}
- **Portfolio Health:** {portfolio_risk.get('status')} (Max Corr: {portfolio_risk.get('max_corr')})
- **Neural Size (Kelly):** {kelly_size*100:.2f}% risk

**Reasoning:** {reasoning}

**Internal Debate (Counter-Evidence):** {counter_ev}"""

        if risk_factors:
            report += "\n\n**Risk Factors:**\n"
            for r in risk_factors:
                report += f"  ⚠️ {r}\n"

        if master_decision in ("LONG", "SHORT"):
            report += f"""
**Execution Plan:**
| Action | Level | Note |
|---|---|---|
| ENTRY ({entry_type}) | `{entry_zone.get('low','?')} – {entry_zone.get('high','?')}` | {entry_zone.get('note','')} |
| STOP LOSS | `{stop_loss.get('price','?')}` | {stop_loss.get('invalidation','')} |
| TAKE PROFIT | `{take_profit.get('tp1','?')}` / `{take_profit.get('tp2','N/A')}` | R:R 1:{rr:.1f} |"""

        return {
            "master_decision":    master_decision,
            "master_confidence":  confidence,
            "master_report":      report,
            "master_reasoning":   reasoning,
            "confluence_score":   confluence_score,
            "composite_score":    composite,
            "kelly_size":         kelly_size,
            "portfolio_health":   portfolio_risk.get("status"),
        }

    return master_agent_node
