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
import os

from intelligence.agents.reflector_agent import get_reflexive_context
from intelligence.ml.drift_monitor import drift_shield
from intelligence.risk_manager import risk_manager

logger = logging.getLogger(__name__)
MODEL_ID = os.environ.get("MODEL_ID", "gemini-2.5-flash")

# Regime-based weight presets — only for MT5-tradeable assets (CRYPTO / MACRO)
_REGIME_WEIGHTS = {
    "RISK_ON":  {"tech": 0.60, "sent": 0.10, "conf": 0.30},  # trend dominates
    "RISK_OFF": {"tech": 0.40, "sent": 0.30, "conf": 0.30},  # news/fear matters more
    "NEUTRAL":  {"tech": 0.55, "sent": 0.15, "conf": 0.30},  # baseline
}


def _get_market_regime() -> str:
    """Fetch latest regime from market_regime table. Falls back to NEUTRAL."""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            dbname=os.getenv("DB_NAME", "crypto_stream_db"),
            user=os.getenv("DB_USER", "user"),
            password=os.getenv("DB_PASS", "password"),
        )
        with conn.cursor() as cur:
            cur.execute("SELECT regime FROM market_regime ORDER BY date DESC LIMIT 1")
            row = cur.fetchone()
        conn.close()
        return row[0] if row else "NEUTRAL"
    except Exception:
        return "NEUTRAL"


def _compute_agent_conflict(state: dict) -> dict:
    """
    Detect hard disagreement between vision/indicator agents.
    Returns: has_conflict, bull_votes, bear_votes
    """
    biases = [
        str(state.get("indicator_bias", "NEUTRAL")).upper(),
        str(state.get("pattern_bias",   "NEUTRAL")).upper(),
        str(state.get("trend_bias",     "NEUTRAL")).upper(),
    ]
    bull = sum(1 for b in biases if "BULL" in b)
    bear = sum(1 for b in biases if "BEAR" in b)
    # Conflict: true tie only — 2:1 majority is NOT a conflict
    conflict = bull >= 1 and bear >= 1 and bull == bear
    return {"has_conflict": conflict, "bull_votes": bull, "bear_votes": bear}

# Safety thresholds (can be overridden via config)
DEFAULT_CONFIG = {
    "master_weight_technical": 0.55,
    "master_weight_sentiment": 0.15,
    "master_weight_confluence": 0.30,
    "master_confidence_threshold": 0.62,  # Single effective gate (was split across 58% + 80% sniper)
    "sentiment_contradiction_threshold": 65,
    "confluence_minimum": 33,
    "sniper_mode": False,                  # Disabled — 80% threshold was blocking all valid setups
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
        state.get("pattern_report", "")
        state.get("trend_report", "")
        sentiment_score  = float(state.get("sentiment_score", 0))
        sentiment_label  = state.get("sentiment_label", "NEUTRAL")
        sentiment_report = state.get("sentiment_report", "NEUTRAL")

        # Reflector Agent Integration
        reflexive = get_reflexive_context(client, MODEL_ID)
        lessons = reflexive.get("lessons", "No reflexive lessons ready.")
        bias_adj = reflexive.get("bias_adjustments", {})

        # Agent conflict detection (before weight computation)
        conflict_info = _compute_agent_conflict(state)

        # Dynamic regime weights — STOCK always uses NEUTRAL (not MT5-tradeable)
        asset_class = state.get("asset_class", "CRYPTO")
        regime_key  = _get_market_regime() if asset_class != "STOCK" else "NEUTRAL"
        rw = _REGIME_WEIGHTS[regime_key]

        # Reflexive adjustment on top of regime base weights
        w_tech = rw["tech"] * bias_adj.get("tech_weight", 1.0)
        w_sent = rw["sent"] * bias_adj.get("sent_weight", 1.0)
        w_conf = rw["conf"] * bias_adj.get("conf_weight", 1.0)

        # Normalize so weights always sum to 1.0
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

        # Intermarket context from Step 1.5
        im           = state.get("intermarket", {})
        macro_bias   = im.get("macro_bias", "NEUTRAL")
        dxy_trend    = im.get("dxy", {}).get("trend", "UNKNOWN")
        dxy_val      = im.get("dxy", {}).get("value", "?")
        vix_level    = im.get("vix", {}).get("level", "UNKNOWN")
        vix_val      = im.get("vix", {}).get("value", "?")
        fear_greed   = im.get("fear_greed", {})
        btc_dom      = im.get("btc_dominance", {}).get("value", "?")
        funding      = im.get("funding", {})
        forex_ctx    = im.get("forex_context", "")
        metals_ctx   = im.get("metals_context", "")
        forex_sess   = state.get("forex_session", "")
        sess_quality = state.get("session_quality", "")

        prompt = f"""You are the Master Risk Gate for a Smart Money / ICT hedge fund system.
Your ONLY job: CONFIRM or REJECT the signal from Decision Agent using ICT kill conditions.
You are a FILTER, not a generator.

=== SIGNAL TO REVIEW ===
Decision: {trade_decision} (confidence: {decision_conf}%)
Composite Score: {composite:.1f}

=== INTERMARKET CONTEXT ===
Macro Bias: {macro_bias} | DXY: {dxy_val} ({dxy_trend}) | VIX: {vix_val} ({vix_level})
Fear & Greed: {fear_greed.get('value','?')} ({fear_greed.get('label','?')}) | BTC Dominance: {btc_dom}%
Funding Rate: {funding.get('rate_pct','?')}% ({funding.get('bias','?')})
{forex_ctx}{metals_ctx}
{f"Forex Session: {forex_sess} — Quality: {sess_quality}" if forex_sess else ""}
*RISK_OFF + weak signal → reduce size. RISK_ON → full size allowed.

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
Market Regime: {regime_key} | Agent Conflict: {"YES — bull_votes=" + str(conflict_info["bull_votes"]) + " bear_votes=" + str(conflict_info["bear_votes"]) if conflict_info["has_conflict"] else "NO"}
Directional Correlation: {json.dumps(state.get("directional_correlation", {"confirmed": True, "score": 1.0}))}

=== SIGNAL TIERING (size is auto-adjusted in code — you focus on CONFIRM/REJECT) ===
Grade A+ (≥75%): full size | Grade A (62-74%): half size | Grade B (50-61%): quarter size (RISK_ON only)
Confidence < 50% → NO_TRADE regardless.
RISK_OFF regime shifts each grade down one level (A+ → A, A → B, B → NO_TRADE).

=== ICT KILL CONDITIONS (any one → NO_TRADE) ===
1. Regime = CHAOS → NO_TRADE always
2. Session = ASIA and asset contains GOLD/XAU → NO_TRADE
3. HTF and LTF structure completely opposed (e.g. HTF BEARISH + LTF LONG) AND no CHOCH → NO_TRADE
4. Confidence < {min_conf*100:.0f}% AND no strong OB/FVG/sweep confirmation → NO_TRADE
5. ML Data Integrity Score < 40 (CRITICAL_DRIFT) → NO_TRADE
6. Sentiment contradicts by > {cfg['sentiment_contradiction_threshold']} points → NO_TRADE
7. Confluence < {cfg['confluence_minimum']} AND no OB/FVG confirmation → NO_TRADE
8. Equity Protection = BLOCKED (Daily Loss Limit) → NO_TRADE
9. Forex Session = ASIA_THIN → prefer NO_TRADE (low liquidity)

=== CONFIRMATION BOOSTERS (increase confidence) ===
+ Liquidity sweep occurred before entry signal
+ Price at/near a valid OB or FVG
+ HTF and LTF bias aligned
+ Session = LONDON or NEW_YORK
+ Macro Bias = RISK_ON aligns with trade direction
+ VIX = LOW (low fear, trending environment)
+ Funding rate contrarian to direction (shorts paying → LONG setup)

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
                # Apply reflexive scaling then signal grade multiplier
                kelly_size *= bias_adj.get("risk_scale", 1.0)
                kelly_size *= size_mult

        except Exception as e:
            logger.error(f"MasterAgent LLM error: {e}")
            master_decision = "NO_TRADE"
            confidence      = 0.0
            reasoning       = f"Master agent error: {str(e)[:100]}"
            risk_factors    = []
            entry_type      = "LIMIT"

        # ── Signal Tiering — grade by confidence + macro regime ──────────────
        macro_bias_live = state.get("intermarket", {}).get("macro_bias", "NEUTRAL")
        signal_grade = "N/A"
        size_mult    = 0.0

        if master_decision in ("LONG", "SHORT"):
            if confidence >= 0.75:
                signal_grade, size_mult = "A+", 1.0
            elif confidence >= 0.62:
                signal_grade, size_mult = "A",  0.5
            elif confidence >= 0.50:
                signal_grade, size_mult = "B",  0.25
            else:
                signal_grade, size_mult = "REJECT", 0.0

            # RISK_OFF shifts grade down one level
            if macro_bias_live == "RISK_OFF":
                if signal_grade == "A+":
                    signal_grade, size_mult = "A",      0.5
                elif signal_grade == "A":
                    signal_grade, size_mult = "B",      0.25
                elif signal_grade in ("B", "REJECT"):
                    signal_grade, size_mult = "REJECT", 0.0

            if signal_grade == "REJECT":
                master_decision = "NO_TRADE"
                reasoning = (
                    f"TIERED REJECT: confidence={confidence:.0%} insufficient "
                    f"in {macro_bias_live} regime. " + reasoning
                )

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

        # Agent conflict: hard disagreement among indicator/pattern/trend agents
        if master_decision in ("LONG", "SHORT") and conflict_info["has_conflict"]:
            master_decision = "NO_TRADE"
            reasoning = (
                f"BLOCKED: Agent conflict — {conflict_info['bull_votes']} bull vs "
                f"{conflict_info['bear_votes']} bear (no clear consensus). " + reasoning
            )

        # Directional correlation: peer assets contradict direction
        dir_corr = state.get("directional_correlation", {})
        if master_decision in ("LONG", "SHORT") and not dir_corr.get("confirmed", True):
            master_decision = "NO_TRADE"
            reasoning = (
                f"BLOCKED: Directional correlation failed — score={dir_corr.get('score', 0):.2f}, "
                f"conflicts={dir_corr.get('conflicts', [])}. " + reasoning
            )

        # ── Format final report ───────────────────────────────────────────────
        dec_emoji = {"LONG": "🚀", "SHORT": "🔻", "NO_TRADE": "🛑"}.get(master_decision, "🛑")
        conf_pct  = int(confidence * 100)

        grade_emoji = {"A+": "🥇", "A": "🥈", "B": "🥉", "REJECT": "🚫", "N/A": "—"}.get(signal_grade, "—")
        report = f"""🧠 **MASTER DECISION — {symbol}USDT ({timeframe})**

**Final Signal:** {dec_emoji} **{master_decision}** (Confidence: {conf_pct}%)
**Signal Grade:** {grade_emoji} {signal_grade} | Size Multiplier: {size_mult:.0%} | Entry Type: {entry_type}

**Weighted Scores:**
- Technical ({w_tech*100:.0f}%): {trade_decision} @ {decision_conf}%
- Sentiment  ({w_sent*100:.0f}%): {sentiment_label} ({sentiment_score:+.0f}/100)
- Confluence ({w_conf*100:.0f}%): {confluence_score:.0f}/100
- ML Integrity: {integrity_score}/100 ({drift_status})
- **Composite:** {composite:.1f}
- **Macro Regime:** {macro_bias_live} | VIX: {vix_level} | DXY: {dxy_trend}
- **Portfolio Health:** {portfolio_risk.get('status')} (Max Corr: {portfolio_risk.get('max_corr')})
- **Neural Size (Kelly × Grade):** {kelly_size*100:.2f}% risk

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
            "signal_grade":       signal_grade,
            "size_multiplier":    size_mult,
            "macro_bias":         macro_bias_live,
            "portfolio_health":   portfolio_risk.get("status"),
        }

    return master_agent_node
