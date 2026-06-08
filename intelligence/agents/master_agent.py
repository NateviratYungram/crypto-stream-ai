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

from intelligence.agents.reflector_agent import (
    format_symbol_memory,
    get_reflexive_context,
)
from intelligence.ml.drift_monitor import drift_shield
from intelligence.ml.performance_feedback import score_signal_feedback
from intelligence.ml.signal_cooldown import check as cooldown_check
from intelligence.ml.signal_cooldown import register as cooldown_register
from intelligence.ml.symbol_threshold import get_threshold_for_side
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


def _compute_confluence_score(state: dict) -> tuple:
    """
    SMC-aware confluence score → (float 0-100, breakdown_str).
    6 weighted factors:
      1. Agent vote agreement   (max 20)
      2. Session quality        (max 15)
      3. HTF alignment          (max 20)
      4. OB / FVG zone match    (max 20)
      5. Liquidity sweep        (max 15)
      6. R:R ratio              (max 10)
    """
    decision = state.get("trade_decision", "HOLD")
    if decision == "HOLD":
        return 30.0, "HOLD"

    score = 0.0
    factors = []

    # 1. Agent vote agreement (max 20)
    biases = [
        state.get("indicator_bias", "NEUTRAL"),
        state.get("pattern_bias", "NEUTRAL"),
        state.get("trend_bias", "NEUTRAL"),
    ]
    if decision == "LONG":
        agree = sum(1 for b in biases if "BULL" in str(b).upper())
    else:
        agree = sum(1 for b in biases if "BEAR" in str(b).upper())
    vote_pts = {3: 20.0, 2: 13.0, 1: 6.0, 0: 0.0}.get(agree, 0.0)
    score += vote_pts
    factors.append(f"votes={agree}/3(+{vote_pts:.0f})")

    # 2. Session quality (max 15)
    smc = state.get("indicator_summary", {}).get("smart_money", {})
    session = str(smc.get("session", "")).upper()
    if "LONDON" in session or "NEW_YORK" in session or "NY" in session:
        sess_pts = 15.0
    elif "ASIA" in session:
        sess_pts = 5.0
    else:
        sess_pts = 8.0
    score += sess_pts
    factors.append(f"sess={session[:2] or '?'}(+{sess_pts:.0f})")

    # 3. HTF alignment (max 20)
    htf_bias = str(
        state.get("indicator_summary", {}).get("higher_timeframe", {}).get("bias", "NEUTRAL")
    ).upper()
    if (decision == "LONG" and "BULL" in htf_bias) or (decision == "SHORT" and "BEAR" in htf_bias):
        htf_pts = 20.0
    elif "NEUTRAL" in htf_bias:
        htf_pts = 10.0
    else:
        htf_pts = 0.0
    score += htf_pts
    factors.append(f"htf={htf_pts:.0f}")

    # 4. OB / FVG zone (max 20)
    price = float(state.get("indicator_summary", {}).get("price", 0) or 0)
    near_ob  = smc.get("nearest_ob")  or {}
    near_fvg = smc.get("nearest_fvg") or {}
    zone_points = 0.0
    zone_label  = "zone=0"
    if near_ob and price > 0:
        ob_top  = float(near_ob.get("top",    price) or price)
        ob_bot  = float(near_ob.get("bottom", price) or price)
        ob_type = str(near_ob.get("type", "")).upper()
        matches = (decision == "LONG" and "BULLISH" in ob_type) or (decision == "SHORT" and "BEARISH" in ob_type)
        if ob_bot <= price <= ob_top and matches:
            zone_points = 20.0
            zone_label  = "OB✓inside(+20)"
        elif matches:
            zone_points = 10.0
            zone_label  = "OB✓near(+10)"
    if zone_points < 20.0 and near_fvg and price > 0:
        fvg_top  = float(near_fvg.get("top",    price) or price)
        fvg_bot  = float(near_fvg.get("bottom", price) or price)
        fvg_type = str(near_fvg.get("type", "")).upper()
        matches = (decision == "LONG" and "BULLISH" in fvg_type) or (decision == "SHORT" and "BEARISH" in fvg_type)
        if fvg_bot <= price <= fvg_top and matches:
            zone_points = max(zone_points, 15.0)
            zone_label  = "FVG✓inside(+15)"
        elif matches:
            zone_points = max(zone_points, 8.0)
            zone_label  = "FVG✓near(+8)"
    score += zone_points
    factors.append(zone_label)

    # 5. Liquidity sweep (max 15)
    sweeps = smc.get("sweeps", {})
    if sweeps.get("sweep_detected"):
        sweep_type = str(sweeps.get("type", "")).upper()
        if (decision == "LONG" and "SELL" in sweep_type) or (decision == "SHORT" and "BUY" in sweep_type):
            sweep_pts = 15.0
            factors.append("sweep✓(+15)")
        else:
            sweep_pts = 5.0
            factors.append("sweep⚠(+5)")
        score += sweep_pts
    else:
        factors.append("sweep✗(+0)")

    # 6. R:R ratio (max 10)
    rr = float(state.get("risk_reward_ratio", 0) or 0)
    rr_pts = 0.0
    if rr >= 3.0:
        rr_pts = 10.0
    elif rr >= 2.0:
        rr_pts = 7.0
    elif rr >= 1.5:
        rr_pts = 4.0
    score += rr_pts
    factors.append(f"rr={rr:.1f}(+{rr_pts:.0f})")

    total = min(score, 100.0)
    breakdown = " | ".join(factors)
    return total, breakdown


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

        # Symbol-specific trade memory — last 5 closed trades for this symbol/TF
        symbol_memory = format_symbol_memory(symbol, timeframe, limit=5)

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

        # Confluence: prefer real multi-TF score from confluence agent, fall back to SMC-aware scorer
        _real_conf = state.get("confluence_score")
        if _real_conf is not None:
            confluence_score = float(_real_conf)
            confluence_breakdown = ""
        else:
            confluence_score, confluence_breakdown = _compute_confluence_score(state)

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

        # ML Signal Probability — scale composite ±15% based on ML alignment
        ml_sig = state.get("ml_signal", {})
        ml_available = ml_sig.get("available", False)
        ml_boost = 0.0
        if ml_available and trade_decision in ("LONG", "SHORT"):
            if trade_decision == "LONG":
                ml_prob = ml_sig.get("buy_prob", 0.5)
            else:
                ml_prob = ml_sig.get("sell_prob", 0.5)
            # +15 if ML agrees strongly (>0.65), -15 if ML disagrees strongly (<0.40)
            if ml_prob >= 0.65:
                ml_boost = 15.0 * (ml_prob - 0.5) / 0.5   # scales +15 at 100%
            elif ml_prob <= 0.40:
                ml_boost = -15.0 * (0.5 - ml_prob) / 0.5  # scales -15 at 0%
            composite += ml_boost

        entry_zone = state.get("entry_zone", {})
        stop_loss  = state.get("stop_loss", {})
        take_profit = state.get("take_profit", {})
        rr = state.get("risk_reward_ratio", 0)

        # ── Signal Tiering (pre-computed so size_mult is available for kelly) ──
        macro_bias_live = state.get("intermarket", {}).get("macro_bias", "NEUTRAL")
        signal_grade = "N/A"
        size_mult    = 0.0
        threshold_side = "BUY" if trade_decision == "LONG" else "SELL" if trade_decision == "SHORT" else None
        sym_floor    = get_threshold_for_side(symbol, threshold_side)

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
        liq_data     = im.get("liquidation", {})
        oi_data      = im.get("oi_trend", {})
        forex_sess   = state.get("forex_session", "")
        sess_quality = state.get("session_quality", "")

        # ── Format SMC levels as readable price strings ──────────────────────────
        near_ob  = near_ob or {}
        price_now = state.get("indicator_summary", {}).get("price", 0)
        if near_ob:
            _ob_type = near_ob.get("type", "OB")
            _ob_top  = near_ob.get("top", "?")
            _ob_bot  = near_ob.get("bottom", "?")
            _ob_str  = near_ob.get("strength", "?")
            try:
                _p = float(price_now)
                _ot, _ob2 = float(_ob_top), float(_ob_bot)
                _ob_rel = "price INSIDE OB" if _ob2 <= _p <= _ot else ("ABOVE OB → support" if _p > _ot else "BELOW OB → resistance")
            except Exception:
                _ob_rel = ""
            near_ob_str = f"{_ob_type} zone {_ob_bot}–{_ob_top} (str: {_ob_str}) | {_ob_rel}"
        else:
            near_ob_str = "None"

        buy_side_str  = ", ".join(str(x) for x in liq.get("buy_side",  [])) or "none"
        sell_side_str = ", ".join(str(x) for x in liq.get("sell_side", [])) or "none"
        sweep_target  = liq.get("nearest_sweep_target", "N/A")
        sweep_type    = sweeps.get("type", "none") if sweeps.get("sweep_detected") else "none"
        sweep_level   = sweeps.get("level", "N/A")

        # Decision Agent's SMC-derived SL/TP (already in state — pass through cleanly)
        entry_zone  = state.get("entry_zone", {})
        stop_loss   = state.get("stop_loss", {})
        take_profit = state.get("take_profit", {})
        rr          = state.get("risk_reward_ratio", 0)

        # ── Build asset-class-specific kill conditions & boosters ────────────────
        if asset_class in ("CRYPTO", "MACRO"):
            kill_conditions = f"""=== ICT KILL CONDITIONS (any one → NO_TRADE) ===
1. Regime = CHAOS → NO_TRADE always
2. Session = ASIA and asset contains GOLD/XAU → NO_TRADE
3. HTF and LTF structure completely opposed (HTF BEARISH + LTF LONG) AND no CHOCH → NO_TRADE
4. Confidence < {min_conf*100:.0f}% AND no strong OB/FVG/sweep confirmation → NO_TRADE
5. ML Data Integrity Score < 40 (CRITICAL_DRIFT) → NO_TRADE
6. Sentiment contradicts by > {cfg['sentiment_contradiction_threshold']} points → NO_TRADE
7. Confluence < {cfg['confluence_minimum']} AND no OB/FVG confirmation → NO_TRADE
8. Equity Protection = BLOCKED (Daily Loss Limit) → NO_TRADE
9. Forex Session = ASIA_THIN → prefer NO_TRADE (low liquidity)"""

            confirmation_boosters = """=== CONFIRMATION BOOSTERS (increase confidence) ===
+ Liquidity sweep occurred before entry signal
+ Price at/near a valid OB or FVG zone (price INSIDE OB = highest probability)
+ HTF and LTF bias aligned
+ Session = LONDON or NEW_YORK
+ Macro Bias = RISK_ON aligns with trade direction
+ VIX = LOW (low fear, trending environment)
+ Funding rate contrarian to direction (shorts paying → LONG setup)"""

            market_context = f"""=== MARKET CONTEXT (SMC PRICE LEVELS) ===
Regime: {regime} | Session: {session}
Structure: {ms.get('structure','?')} | BOS: {ms.get('last_bos','?')} | CHOCH: {ms.get('choch',False)}
HTF Bias: {htf_bias}
Nearest OB      : {near_ob_str}
Buy-side Liq    : {buy_side_str}  ← equal highs SM raids (SHORT TP targets)
Sell-side Liq   : {sell_side_str} ← equal lows SM raids (LONG TP targets)
Next SM Target  : {sweep_target}
Last Sweep      : {sweep_type} @ {sweep_level}

=== DECISION AGENT SL/TP (SMC-DERIVED — use these, do not recalculate) ===
Entry Zone : {entry_zone.get('low','?')} – {entry_zone.get('high','?')} | {entry_zone.get('note','')}
Stop Loss  : {stop_loss.get('price','?')} | {stop_loss.get('invalidation','')}
TP1 / TP2  : {take_profit.get('tp1','?')} / {take_profit.get('tp2','N/A')} | R:R 1:{rr:.1f}

=== RETAIL FOMO (Liquidation Heatmap) ===
Status: {fomo.get('retail_sentiment', 'UNKNOWN')}
Long Ratio: {fomo.get('long_percent', 0)}% | Short Ratio: {fomo.get('short_percent', 0)}%
Institutional Bias: {fomo.get('institutional_bias', 'UNKNOWN')}
*EXTREME_LONG_FOMO = SHORT trap likely. EXTREME_SHORT_FOMO = LONG trap likely."""

            reasoning_instruction = "cite regime + hurst + exact OB/FVG prices + session + reflexive lessons"

        else:  # STOCK
            kill_conditions = f"""=== STOCK KILL CONDITIONS (any one → NO_TRADE) ===
1. Regime = CHAOS (extreme ATR spike) → NO_TRADE always
2. HTF and LTF bias directly opposed AND no clear reversal signal → NO_TRADE
3. Confidence < {min_conf*100:.0f}% AND EMA/MACD not confirming → NO_TRADE
4. ML Data Integrity Score < 40 (CRITICAL_DRIFT) → NO_TRADE
5. Sentiment contradicts by > {cfg['sentiment_contradiction_threshold']} points → NO_TRADE
6. Confluence < {cfg['confluence_minimum']} → NO_TRADE
7. Equity Protection = BLOCKED (Daily Loss Limit) → NO_TRADE
8. News Shield = BLOCKED (major event pending) → NO_TRADE
9. Market is closed or pre-market (low liquidity) → NO_TRADE"""

            confirmation_boosters = """=== CONFIRMATION BOOSTERS (increase confidence) ===
+ EMA20 > EMA50 > EMA200 full bullish stack (or full bearish for SHORT)
+ HTF and LTF bias aligned
+ MACD crossover confirmed with volume spike
+ Price above VWAP (bullish) or below VWAP (bearish)
+ Macro Bias = RISK_ON aligns with LONG trade
+ VIX = LOW (low fear, stocks tend to trend)
+ Hurst H100 > 0.55 confirms trend persistence"""

            market_context = f"""=== STOCK TECHNICAL CONTEXT ===
HTF Bias: {htf_bias} | Regime: {regime}
Hurst H100: {h100} ({h_regime})
*H > 0.55 = trend persists → ride the move
*H < 0.45 = mean-reverting → trade range, not breakout"""

            reasoning_instruction = "cite EMA trend + MACD + volume + HTF bias + support/resistance specifically"

        # ── Intermarket context (useful for all asset classes) ────────────────
        intermarket_section = f"""=== INTERMARKET CONTEXT ===
Macro Bias: {macro_bias} | DXY: {dxy_val} ({dxy_trend}) | VIX: {vix_val} ({vix_level})
Fear & Greed: {fear_greed.get('value','?')} ({fear_greed.get('label','?')})
{forex_ctx}{metals_ctx}
{f"Forex Session: {forex_sess} — Quality: {sess_quality}" if forex_sess else ""}
*RISK_OFF + weak signal → reduce size. RISK_ON → full size allowed."""

        # Only show CRYPTO-specific data when relevant
        if asset_class == "CRYPTO":
            intermarket_section += f"""
BTC Dominance: {btc_dom}% | Funding Rate: {funding.get('rate_pct','?')}% ({funding.get('bias','?')})
Liquidations (1h): {liq_data.get('liq_bias','?')} Buy={liq_data.get('buy_liq',0)} Sell={liq_data.get('sell_liq',0)}
Open Interest: {oi_data.get('oi_trend','?')} ({oi_data.get('oi_change_pct','?')}% 1h)"""

        prompt = f"""You are the Master Risk Gate for a {asset_class} trading system.
Your ONLY job: CONFIRM or REJECT the signal from Decision Agent.
You are a FILTER, not a generator.

=== SIGNAL TO REVIEW ===
Asset: {symbol} ({asset_class}) | Timeframe: {timeframe}
Decision: {trade_decision} (confidence: {decision_conf}%)
Composite Score: {composite:.1f}
ML Probability: buy={ml_sig.get('buy_pct','N/A')}% sell={ml_sig.get('sell_pct','N/A')}% | Available: {ml_available} | Neural Align: {ml_sig.get('neural_alignment',False)} | MTF Blocked: {ml_sig.get('mtf_blocked',False)}
*ML prob > 65% aligns = stronger signal. ML prob < 40% = model disagrees, caution.

{intermarket_section}

{market_context}

=== HURST ANALYTICS ===
H100 (Regime Persistence): {h100} ({h_regime})
*H > 0.5 = Trends persist. H < 0.5 = Mean-reverting / Random walk.

=== SYMBOL TRADE MEMORY ({symbol} {timeframe}) ===
{symbol_memory}

=== REFLEXIVE MEMORY (Lessons from Past Trades) ===
{lessons}

=== ML DRIFT SHIELD (Data Stability) ===
Score: {integrity_score}/100 | Status: {drift_status}
*If integrity low → extreme caution. Model reliability degraded.
{chr(10).join(drift_report.get('warnings', []))}

=== PORTFOLIO RISK GUARDIAN ===
Status: {portfolio_risk.get('status', 'UNKNOWN')} | Max Correlation: {portfolio_risk.get('max_corr', 0)}
Equity Protection: {protection.get('status', 'UNKNOWN')} (Drawdown: {protection.get('current_dd', 0)}%)
News Shield: {news_shield.get('status', 'UNKNOWN')} ({news_shield.get('reason', 'None')})
*Protection = BLOCKED → NO_TRADE mandatory.
*News Shield = BLOCKED → NO_TRADE mandatory.

=== AGENT REPORTS ===
Technical ({w_tech*100:.0f}%): {indicator_report[:350]}
Sentiment ({w_sent*100:.0f}%): Score {sentiment_score:+.0f}/100 ({sentiment_label}) — {sentiment_report[:150]}
Confluence ({w_conf*100:.0f}%): {confluence_score:.0f}/100 [{confluence_breakdown}]
Market Regime: {regime_key} | Agent Conflict: {"YES — bull=" + str(conflict_info["bull_votes"]) + " bear=" + str(conflict_info["bear_votes"]) if conflict_info["has_conflict"] else "NO"}

=== SIGNAL TIERING (size auto-adjusted in code — focus on CONFIRM/REJECT) ===
Grade A+ (≥75%): full size | Grade A (62-74%): half size | Grade B (50-61%): quarter size
Confidence < 50% → NO_TRADE regardless.
RISK_OFF shifts grade down one level.

{kill_conditions}

{confirmation_boosters}

=== EXPERT DEBATE: COUNTER-EVIDENCE ===
Before confirming, find the strongest argument AGAINST the signal.
If counter-evidence is strong, REJECT.

Respond ONLY with valid JSON:
{{
  "decision": "LONG" | "SHORT" | "NO_TRADE",
  "confidence": <integer 0-100>,
  "reasoning": "<{reasoning_instruction}>",
  "counter_evidence": "<mandatory counter-argument>",
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
        fb_adj          = 0.0
        fb_notes        = []

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

            # Performance feedback — nudge confidence up/down from realized paper-trade win rates
            fb_adj   = 0.0
            fb_notes = []
            if master_decision in ("LONG", "SHORT"):
                try:
                    fb = score_signal_feedback(symbol, entry_source="signal_feed_analysis")
                    fb_adj   = float(fb.get("probability_adjustment", 0.0) or 0.0)
                    fb_notes = fb.get("notes", [])
                    if fb_adj != 0.0:
                        confidence = max(0.30, min(0.99, confidence + fb_adj))
                        logger.info(
                            f"[MasterAgent] Feedback adj {symbol}: "
                            f"{confidence_raw/100:.2f} → {confidence:.2f} ({fb_adj:+.3f}) | {fb_notes}"
                        )
                except Exception:
                    pass

            # Base Kelly (size_mult applied after signal tiering)
            kelly_size = 0.0
            if master_decision in ("LONG", "SHORT"):
                kelly_size = risk_manager.calculate_kelly_size(
                    win_prob=confidence,
                    rr_ratio=float(rr),
                    balance=100.0
                )
                kelly_size *= bias_adj.get("risk_scale", 1.0)

        except Exception as e:
            logger.error(f"MasterAgent LLM error: {e}")
            master_decision = "NO_TRADE"
            confidence      = 0.0
            reasoning       = f"Master agent error: {str(e)[:100]}"
            risk_factors    = []
            entry_type      = "LIMIT"

        # ── Multi-TF Confidence Adjustment ───────────────────────────────────
        # HTF bias (already computed from the parent timeframe) adjusts confidence
        # BEFORE signal tiering so grade reflects true multi-TF quality.
        # Mapping: 15m→1h, 1h→4h, 4h→1d (set in crypto_intelligence.py)
        mtf_note = ""
        if master_decision in ("LONG", "SHORT"):
            htf_adx    = float(htf_data.get("adx") or 0)
            htf_tf_str = htf_data.get("timeframe", "HTF")
            _htf_upper = str(htf_bias).upper()
            htf_confirmed = (
                (master_decision == "LONG"  and "BULL" in _htf_upper) or
                (master_decision == "SHORT" and "BEAR" in _htf_upper)
            )
            htf_neutral = "NEUTRAL" in _htf_upper

            if htf_confirmed and htf_adx >= 20:
                # Strong trend confirmed on parent TF → small confidence boost
                confidence = min(0.99, confidence + 0.03)
                mtf_note = (
                    f"MTF BOOST: {htf_tf_str} bias={htf_bias} ADX={htf_adx:.0f} aligned — +3%"
                )
                logger.info(f"[MasterAgent] MTF boost {symbol}: +3% (htf={htf_bias} adx={htf_adx:.0f})")
            elif htf_neutral or htf_adx < 15:
                # Parent TF has no clear trend → reduce confidence
                confidence = max(0.30, confidence - 0.05)
                mtf_note = (
                    f"MTF WEAK: {htf_tf_str} bias={htf_bias} ADX={htf_adx:.0f} — -5%"
                )
                logger.info(f"[MasterAgent] MTF penalty {symbol}: -5% (htf={htf_bias} adx={htf_adx:.0f})")

        # ── Funding Rate Pre-Tiering Adjustment (CRYPTO only) ────────────────
        # Extreme funding → crowded side risk. Penalise confidence before tiering
        # so the grade change is reflected in the signal report.
        funding_note = ""
        if master_decision in ("LONG", "SHORT") and asset_class == "CRYPTO":
            _fr = float(funding.get("rate_pct", 0) or 0)
            if master_decision == "LONG" and _fr > 0.08:
                _penalty = 0.06 if _fr > 0.15 else 0.03
                confidence = max(0.30, confidence - _penalty)
                funding_note = f"FUNDING WARN: rate={_fr:.3f}% crowded longs — -{_penalty*100:.0f}%"
                logger.info(f"[MasterAgent] Funding penalty {symbol}: LONG fr={_fr:.3f} -{_penalty:.0%}")
            elif master_decision == "SHORT" and _fr < -0.08:
                _penalty = 0.06 if _fr < -0.15 else 0.03
                confidence = max(0.30, confidence - _penalty)
                funding_note = f"FUNDING WARN: rate={_fr:.3f}% crowded shorts — -{_penalty*100:.0f}%"
                logger.info(f"[MasterAgent] Funding penalty {symbol}: SHORT fr={_fr:.3f} -{_penalty:.0%}")

        # ── Signal Tiering — grade by confidence + macro regime ──────────────
        # sym_floor is checked FIRST so high-floor symbols (poor WR history) can't
        # sneak through at A grade before reaching the threshold check.
        if master_decision in ("LONG", "SHORT"):
            if confidence < sym_floor:
                signal_grade, size_mult = "REJECT", 0.0
            elif confidence >= 0.75:
                signal_grade, size_mult = "A+", 1.0
            elif confidence >= 0.62:
                signal_grade, size_mult = "A",  0.5
            else:
                signal_grade, size_mult = "B",  0.25

            # RISK_OFF shifts grade down one level
            if macro_bias_live == "RISK_OFF":
                if signal_grade == "A+":
                    signal_grade, size_mult = "A",      0.5
                elif signal_grade == "A":
                    signal_grade, size_mult = "B",      0.25
                elif signal_grade in ("B", "REJECT"):
                    signal_grade, size_mult = "REJECT", 0.0

            # R:R Hard Minimum — no signal below 1.5:1 regardless of confidence
            _rr_val = float(rr or 0)
            if signal_grade != "REJECT" and _rr_val < 1.5:
                signal_grade, size_mult = "REJECT", 0.0
                logger.info(f"[MasterAgent] R:R gate {symbol}: R:R={_rr_val:.1f} < 1.5")

            if signal_grade == "REJECT":
                master_decision = "NO_TRADE"
                _rr_msg = f" R:R={_rr_val:.1f}<1.5." if _rr_val < 1.5 else ""
                reasoning = (
                    f"TIERED REJECT: confidence={confidence:.0%}{_rr_msg} insufficient "
                    f"in {macro_bias_live} regime. " + reasoning
                )

        # Quality Gate: paper_only mode → cap size at 25% (paper trade sizing)
        gate_mode = state.get("quality_gate_mode", "observe_only")
        if gate_mode == "paper_only" and size_mult > 0.25:
            size_mult = 0.25
        elif gate_mode == "observe_only":
            # observe_only = model not ready → still show signal but zero live size
            size_mult = 0.0

        # Apply grade multiplier to kelly size now that size_mult is determined
        kelly_size *= size_mult

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

        # ML MTF Block — ML model's multi-timeframe gate (Daily + 4H alignment check)
        if master_decision in ("LONG", "SHORT") and ml_sig.get("mtf_blocked", False):
            master_decision = "NO_TRADE"
            reasoning = f"ML MTF BLOCKED: {ml_sig.get('mtf_reason','Daily/4H not aligned')}. " + reasoning

        # ── Funding Rate Extreme Hard Block (CRYPTO only) ────────────────────
        # When funding is extreme (>0.15%), longs are overcrowded → forced liquidation
        # risk is too high to trade the same direction. Block regardless of confidence.
        if master_decision in ("LONG", "SHORT") and asset_class == "CRYPTO":
            _fr_ext = float(funding.get("rate_pct", 0) or 0)
            if master_decision == "LONG" and _fr_ext > 0.15:
                master_decision = "NO_TRADE"
                reasoning = (
                    f"FUNDING EXTREME BLOCK: rate={_fr_ext:.3f}% — longs severely overcrowded, "
                    f"liquidation cascade risk. " + reasoning
                )
                logger.info(f"[MasterAgent] Funding extreme block {symbol}: LONG fr={_fr_ext:.3f}")
            elif master_decision == "SHORT" and _fr_ext < -0.15:
                master_decision = "NO_TRADE"
                reasoning = (
                    f"FUNDING EXTREME BLOCK: rate={_fr_ext:.3f}% — shorts severely overcrowded, "
                    f"short squeeze risk. " + reasoning
                )
                logger.info(f"[MasterAgent] Funding extreme block {symbol}: SHORT fr={_fr_ext:.3f}")

        # ── HTF Hard Block ───────────────────────────────────────────────────
        # If daily/HTF bias strongly opposes the signal direction and no CHoCH
        # (structure flip) has occurred, block — regardless of LLM confidence
        if master_decision in ("LONG", "SHORT"):
            _htf_bias_upper = str(htf_bias).upper()
            _choch = bool((state.get("indicator_summary", {}).get("smart_money", {})
                          .get("structure", {})).get("choch", False))
            _htf_opposed = (
                (master_decision == "LONG"  and "BEAR" in _htf_bias_upper) or
                (master_decision == "SHORT" and "BULL" in _htf_bias_upper)
            )
            if _htf_opposed and not _choch:
                _orig_dir = master_decision
                master_decision = "NO_TRADE"
                reasoning = (
                    f"HTF HARD BLOCK: HTF bias={htf_bias} directly opposes "
                    f"{_orig_dir} with no CHoCH confirmation. " + reasoning
                )
                logger.info(f"[MasterAgent] HTF hard block — {symbol} htf={htf_bias} dir={_orig_dir}")

        # ── Asia Session Gate ────────────────────────────────────────────────
        # In Asia session (thin liquidity), only A+ grade (≥75%) is allowed.
        # B-grade signals during Asia are systematically weak — block them.
        if master_decision in ("LONG", "SHORT"):
            _sess_upper = str(session).upper()
            _is_asia = "ASIA" in _sess_upper
            if _is_asia and signal_grade in ("B", "REJECT"):
                master_decision = "NO_TRADE"
                reasoning = (
                    f"ASIA SESSION GATE: {signal_grade} grade rejected during Asia session "
                    f"(low liquidity — A+ only). " + reasoning
                )
                logger.info(f"[MasterAgent] Asia session gate blocked {symbol} grade={signal_grade}")

        # ── Chaos/Anomaly Hard Block ─────────────────────────────────────────
        # Enforce Regime=CHAOS block in code, not just in the LLM prompt.
        # Also blocks when ML drift integrity is critically low.
        if master_decision in ("LONG", "SHORT"):
            _regime_upper = str(regime).upper()
            if "CHAOS" in _regime_upper:
                master_decision = "NO_TRADE"
                reasoning = "CHAOS BLOCK: Market regime=CHAOS — no trading allowed. " + reasoning
                logger.info(f"[MasterAgent] Chaos block — {symbol} regime={regime}")
            elif integrity_score < 40:
                master_decision = "NO_TRADE"
                reasoning = (
                    f"DRIFT CRITICAL BLOCK: ML integrity={integrity_score}/100 "
                    f"({drift_status}) — model unreliable. " + reasoning
                )
                logger.info(f"[MasterAgent] Critical drift block — {symbol} integrity={integrity_score}")

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

        # ── Entry Confirmation: candle momentum must agree with direction ────
        entry_confirm_note = ""
        if master_decision in ("LONG", "SHORT"):
            ind = state.get("indicator_summary", {})
            macd_hist = float((ind.get("macd_histogram") or {}).get("value", 0) or 0)
            vwap_pos  = str((ind.get("vwap") or {}).get("position", "")).upper()
            rsi_val   = float((ind.get("rsi") or {}).get("value", 50) or 50)
            ema_sig   = str((ind.get("ema") or {}).get("signal", "")).upper()

            if master_decision == "LONG":
                # At least 2 of 4 momentum signals must be bullish
                bullish_signals = sum([
                    macd_hist > 0,
                    "ABOVE" in vwap_pos,
                    rsi_val > 40,
                    "BULL" in ema_sig,
                ])
                if bullish_signals < 2:
                    confidence = max(0.30, confidence - 0.08)
                    entry_confirm_note = f"ENTRY WARN: weak candle confirmation ({bullish_signals}/4 bullish signals) — confidence reduced"
            else:  # SHORT
                bearish_signals = sum([
                    macd_hist < 0,
                    "BELOW" in vwap_pos,
                    rsi_val < 60,
                    "BEAR" in ema_sig,
                ])
                if bearish_signals < 2:
                    confidence = max(0.30, confidence - 0.08)
                    entry_confirm_note = f"ENTRY WARN: weak candle confirmation ({bearish_signals}/4 bearish signals) — confidence reduced"

        # ── Zone Cooldown: skip if same zone was traded recently ─────────────
        cooldown_note = ""
        if master_decision in ("LONG", "SHORT"):
            _e_low  = float(entry_zone.get("low")  or 0)
            _e_high = float(entry_zone.get("high") or 0)
            _zone_mid = (_e_low + _e_high) / 2 if _e_low and _e_high else 0.0
            cd = cooldown_check(symbol, timeframe, master_decision, _zone_mid)
            if cd["cooling_down"]:
                master_decision = "NO_TRADE"
                cooldown_note   = f"ZONE COOLDOWN: {cd['reason']}"
                reasoning       = cooldown_note + ". " + reasoning
            else:
                # Register this signal so future duplicates are caught
                cooldown_register(symbol, timeframe, master_decision, _zone_mid)

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
- Confluence ({w_conf*100:.0f}%): {confluence_score:.0f}/100 [{confluence_breakdown}]
- ML Integrity: {integrity_score}/100 ({drift_status})
- **ML Probability:** buy={ml_sig.get('buy_pct','N/A')}% sell={ml_sig.get('sell_pct','N/A')}% | Boost: {ml_boost:+.1f} | Neural: {ml_sig.get('neural_alignment',False)}
- **Perf Feedback:** adj={fb_adj:+.3f}{" | " + "; ".join(fb_notes) if fb_notes else ""}
- **Composite:** {composite:.1f}
- **Macro Regime:** {macro_bias_live} | VIX: {vix_level} | DXY: {dxy_trend}
- **Portfolio Health:** {portfolio_risk.get('status')} (Max Corr: {portfolio_risk.get('max_corr')})
- **Neural Size (Kelly × Grade):** {kelly_size*100:.2f}% risk
- **Quality Gate:** {gate_mode} | Live Ready: {state.get('quality_gate',{}).get('live_ready','?')}

**Reasoning:** {reasoning}

**Internal Debate (Counter-Evidence):** {counter_ev}{"" if not entry_confirm_note and not cooldown_note else chr(10) + "**Filters:** " + " | ".join(x for x in [mtf_note, funding_note, entry_confirm_note, cooldown_note] if x)}"""

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

        _filter_notes = [x for x in [mtf_note, funding_note, entry_confirm_note, cooldown_note] if x]
        return {
            "master_decision":    master_decision,
            "master_confidence":  confidence,
            "master_report":      report,
            "master_reasoning":   reasoning,
            "confluence_score":   confluence_score,
            "confluence_breakdown": confluence_breakdown,
            "composite_score":    composite,
            "kelly_size":         kelly_size,
            "signal_grade":       signal_grade,
            "size_multiplier":    size_mult,
            "macro_bias":         macro_bias_live,
            "portfolio_health":   portfolio_risk.get("status"),
            "filter_notes":       _filter_notes,
        }

    return master_agent_node
