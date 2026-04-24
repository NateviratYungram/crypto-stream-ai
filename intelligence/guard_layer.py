"""
CryptoStream AI — Guard Layer
Rule-based hard stop that runs AFTER master_agent.
Can override LLM output and force NO_TRADE.

Ported from QuantAgent guard_layer.py — adapted for crypto:
  - Removed spread_pips check (not applicable to spot/perp crypto)
  - Added CHAOS regime block (crypto-specific)
  - Added consecutive loss daily limit (circuit breaker lite)
  - RSI extreme thresholds adjusted for crypto volatility
"""

import logging

logger = logging.getLogger(__name__)

DEFAULT_GUARD_CONFIG = {
    "min_confidence":          0.58,   # Hard floor — same as master_agent threshold
    "confluence_dead_zone":    35,     # abs(confluence_score) must be above this
    "rsi_long_block":          82,     # Never LONG if RSI > this
    "rsi_short_block":         18,     # Never SHORT if RSI < this
    "chaos_regime_block":      True,   # Block all trades when regime == CHAOS
    "max_consecutive_losses":  4,      # Block after N consecutive losses (session)
}


def create_guard_agent(config: dict = None):
    """
    Returns a guard_agent_node(state) -> dict function.

    Input state keys (all optional — defaults to allow-trade if missing):
      master_decision   : "LONG" | "SHORT" | "NO_TRADE"
      master_confidence : float 0–1 (or 0–100, auto-normalized)
      confluence_score  : float (positive = bullish bias, negative = bearish)
      rsi               : float 0–100 (current RSI of the symbol)
      regime            : str — "TRENDING" | "RANGING" | "TRANSITIONING" | "CHAOS"
      session_losses    : int — consecutive losses this session (0 if not tracked)

    Output:
      guard_passed          : bool
      guard_override_reason : str | None
      master_decision       : str (may be overridden to "NO_TRADE")
    """
    cfg = {**DEFAULT_GUARD_CONFIG, **(config or {})}

    def _normalise_confidence(value) -> float:
        if value is None:
            return 0.0
        try:
            v = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, v / 100.0 if v > 1.0 else v))

    def guard_agent_node(state: dict) -> dict:
        decision    = str(state.get("master_decision", "NO_TRADE")).upper()
        confidence  = _normalise_confidence(state.get("master_confidence", 0))
        confluence  = float(state.get("confluence_score", 0) or 0)
        rsi         = float(state.get("rsi", 50) or 50)
        regime      = str(state.get("regime", "UNKNOWN")).upper()
        sess_losses = int(state.get("session_losses", 0) or 0)

        reasons = []

        # ── Rule 1: CHAOS regime — always block ──────────────────────────────
        if cfg["chaos_regime_block"] and regime == "CHAOS" and decision in ("LONG", "SHORT"):
            reasons.append("CHAOS regime — no trades allowed")

        # ── Rule 2: Confidence floor ──────────────────────────────────────────
        min_conf = float(cfg["min_confidence"])
        if decision in ("LONG", "SHORT") and confidence < min_conf:
            reasons.append(
                f"Confidence too low ({confidence:.0%} < {min_conf:.0%})"
            )

        # ── Rule 3: Confluence dead-zone ─────────────────────────────────────
        dead = float(cfg["confluence_dead_zone"])
        if decision in ("LONG", "SHORT") and abs(confluence) < dead:
            reasons.append(
                f"Confluence in dead-zone (|{confluence:.0f}| < {dead:.0f})"
            )

        # ── Rule 4: RSI extreme blocks ────────────────────────────────────────
        if decision == "LONG"  and rsi > cfg["rsi_long_block"]:
            reasons.append(
                f"RSI overbought hard-block ({rsi:.1f} > {cfg['rsi_long_block']})"
            )
        if decision == "SHORT" and rsi < cfg["rsi_short_block"]:
            reasons.append(
                f"RSI oversold hard-block ({rsi:.1f} < {cfg['rsi_short_block']})"
            )

        # ── Rule 5: Consecutive loss protection ──────────────────────────────
        max_loss = int(cfg["max_consecutive_losses"])
        if sess_losses >= max_loss and decision in ("LONG", "SHORT"):
            reasons.append(
                f"Consecutive losses ({sess_losses}) reached limit ({max_loss}) — pausing"
            )

        # ── Verdict ───────────────────────────────────────────────────────────
        if reasons:
            reason_str = "; ".join(reasons)
            logger.info(f"GuardLayer BLOCKED {decision}: {reason_str}")
            return {
                "guard_passed":          False,
                "guard_override_reason": reason_str,
                "master_decision":       "NO_TRADE",
                "master_reasoning":      f"[Guard Override] {reason_str}",
            }

        logger.debug(f"GuardLayer PASSED for {decision}")
        return {
            "guard_passed":          True,
            "guard_override_reason": None,
        }

    return guard_agent_node


def apply_guard(state: dict, config: dict = None) -> dict:
    """
    Convenience wrapper — applies guard directly and merges result into state.
    Usage:
        state = apply_guard(state)
        if state["master_decision"] == "NO_TRADE":
            ...
    """
    guard = create_guard_agent(config)
    result = guard(state)
    return {**state, **result}
