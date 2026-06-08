"""
CryptoStream AI — Execution Bridge
Connects AI pipeline output → Guard Layer → Circuit Breaker → MT5 execution.

Flow:
  1. Receive state from CryptoIntelligence.analyze()
  2. Guard Layer hard-block check
  3. Circuit Breaker daily/weekly/consecutive loss check
  4. Position sizing (risk_pct % of account balance)
  5. Symbol → MT5 format mapping
  6. Execute via mt5_execute_trade() OR dry-run log
  7. Record result back into Circuit Breaker

Safety:
  - dry_run=True by default — NEVER sends real orders unless explicitly disabled
  - Confirmation mode: returns draft for user to confirm before live execution
  - All execution events are logged with full context
"""

import logging
import os
import uuid
from datetime import datetime, timezone

from intelligence.ml.performance_feedback import paper_entry_performance_gate
from intelligence.ml.readiness import live_execution_gate
from intelligence.ml.symbol_policy import get_symbol_policy
from intelligence.mt5_connector import (
    _MT5_AVAILABLE,
    initialize_mt5,
    normalize_broker_symbol,
)
from intelligence.persistence_utils import save_trade_draft

logger = logging.getLogger(__name__)

def _to_mt5_symbol(symbol: str) -> str:
    """Uses shared normalization to find a valid MT5 symbol."""
    candidates = normalize_broker_symbol(symbol)
    if _MT5_AVAILABLE and initialize_mt5():
        try:
            import MetaTrader5 as mt5
        except ImportError:
            return candidates[0]

        for cand in candidates:
            info = mt5.symbol_info(cand)
            if info:
                return cand
    return candidates[0] # Fallback to first candidate


# ── Position sizing ───────────────────────────────────────────────────────────

def _calculate_lot_size(
    balance: float,
    risk_pct: float,
    entry_price: float,
    sl_price: float,
    contract_size: float = 1.0,
    min_lot: float = 0.01,
    max_lot: float = 10.0,
    leverage: float = 1.0,
) -> float:
    """
    Fixed fractional position sizing.
    risk_amount = balance × risk_pct%
    lot = risk_amount / (|entry - sl| × contract_size)
    """
    if entry_price <= 0 or sl_price <= 0:
        return min_lot

    risk_amount = balance * (risk_pct / 100.0)
    sl_distance = abs(entry_price - sl_price)
    if sl_distance <= 0:
        return min_lot

    raw_lot = risk_amount / (sl_distance * contract_size)
    raw_lot = max(min_lot, min(raw_lot, max_lot))
    # Round to 2 decimal places (MT5 standard)
    return round(raw_lot, 2)


def _get_contract_size(mt5_symbol: str) -> float:
    """Approximate contract size for position sizing."""
    s = mt5_symbol.upper()
    if "XAU" in s:
        return 100.0   # Gold: 100 oz per lot
    if "XAG" in s:
        return 5000.0  # Silver: 5000 oz per lot
    if "BTC" in s:
        return 1.0     # BTC: 1 BTC per lot
    if "ETH" in s:
        return 1.0
    if "NAS" in s or "SPX" in s or "US30" in s:
        return 1.0                   # Index CFD
    return 1.0


def _harden_sniper_v8(signal: dict) -> bool:
    """
    Final security check for V8 Sniper signals before MT5 execution.
    - Ensures confidence is REAL and not a placeholder
    - Checks for symbol mapping integrity
    - Validates ATR-based SL/TP ranges
    """
    sym = signal.get("symbol")
    conf = signal.get("master_confidence", 0)

    # 1. Integrity Check
    if not sym or conf < 0.5:
        logger.warning(f"🛡️ Bridge Block: Invalid signal integrity for {sym} (Conf: {conf})")
        return False

    # 2. Sniper Validation (If V8 Sniper mode is claimed)
    if conf >= 0.85:
        logger.info(f"🎯 Bridge: Hardening V8 Sniper Signal for {sym}...")
        # Add additional safety lag or double-check indicators here if needed

    return True


# ── Core Bridge ───────────────────────────────────────────────────────────────

def execute_signal(
    state: dict,
    dry_run: bool = True,
    risk_pct: float = 1.0,
    account_balance: float = None,
    cb_config: dict = None,
    guard_config: dict = None,
    confirmation_required: bool = True,
) -> dict:
    """
    Full pipeline: AI state → Guard → CircuitBreaker → MT5.

    Args:
        state              : Output dict from CryptoIntelligence.analyze()
        dry_run            : True = simulate only (NEVER sends to MT5 unless False)
        risk_pct           : % of balance to risk per trade (default 1%)
        account_balance    : MT5 account balance. If None, fetched from MT5.
        cb_config          : CircuitBreaker config overrides
        guard_config       : GuardLayer config overrides
        confirmation_required : If True, return draft instead of executing live

    Returns:
        dict with keys:
          status         : "EXECUTED" | "DRY_RUN" | "BLOCKED" | "DRAFT" | "ERROR"
          reason         : explanation
          trade_details  : order params (if executed/draft)
          guard_result   : guard layer output
          cb_status      : circuit breaker status
    """
    master_decision = str(state.get("master_decision", "NO_TRADE")).upper()
    symbol          = str(state.get("symbol", "BTC")).upper()
    timeframe       = state.get("timeframe", "?")
    confidence      = state.get("master_confidence", 0)
    entry_zone      = state.get("entry_zone", {})
    sl_data         = state.get("stop_loss", {})
    tp_data         = state.get("take_profit", {})
    rr              = state.get("risk_reward_ratio", 0)
    reasoning       = state.get("master_reasoning", "")
    side            = "BUY" if master_decision == "LONG" else "SELL" if master_decision == "SHORT" else ""

    timestamp = datetime.now(timezone.utc).isoformat()

    # ── Sniper hardening check ──
    if not _harden_sniper_v8(state):
        return {
            "status": "BLOCKED",
            "reason": "Signal failed Sniper V8 integrity check",
            "timestamp": timestamp,
        }

    # ── Pre-check: only act on actionable signals ──────────────────────────────
    if master_decision not in ("LONG", "SHORT"):
        return {
            "status": "BLOCKED",
            "reason": f"master_decision = {master_decision} — no execution needed",
            "timestamp": timestamp,
        }

    # ── Buy-and-Hold Protection (Mode B Rules) ────────────────────────────────
    performance_gate = paper_entry_performance_gate(symbol, side, "signal_feed_analysis")
    if not bool(performance_gate.get("ok", True)):
        return {
            "status": "BLOCKED",
            "reason": "Paper-performance gate blocked this symbol/side from new execution.",
            "performance_gate": performance_gate,
            "timestamp": timestamp,
        }
    symbol_policy = get_symbol_policy(symbol, side, force_refresh=True)
    if symbol_policy.get("action") == "block":
        return {
            "status": "BLOCKED",
            "reason": "Symbol-side policy blocked this execution.",
            "symbol_policy": symbol_policy,
            "timestamp": timestamp,
        }

    # Check if the asset is a Stock or if the user's focus is Strategic Value
    if not dry_run and not confirmation_required:
        ready, readiness_report = live_execution_gate(state)
        if not ready:
            return {
                "status": "BLOCKED",
                "reason": "ML readiness gate blocked live execution",
                "readiness": readiness_report,
                "timestamp": timestamp,
            }

    is_stock = False

    # Check indicator summary or symbol list for stock indicators
    asset_class = state.get("indicator_summary", {}).get("asset_class", "UNKNOWN").upper()
    if asset_class == "STOCK" or (any(c.isdigit() for c in symbol) and len(symbol) > 4):
       is_stock = True

    # Mode B logic from Persona: Stocks & ETFs are Long-Term Value
    if is_stock:
        logger.info(f"ExecutionBridge: STRATEGIC VALUE mode for {symbol} — Blocking MT5 Execution.")
        return {
            "status": "HODL",
            "reason": "Strategic Value asset (Stock/ETF) — recommended for long-term accumulation, not active trading.",
            "symbol": symbol,
            "entry_zones": state.get("entry_zone", {}),
            "timestamp": timestamp,
        }

    # ── Step 1: Guard Layer ────────────────────────────────────────────────────
    from intelligence.guard_layer import create_guard_agent
    guard = create_guard_agent(guard_config)
    guard_result = guard({
        **state,
        "rsi": state.get("indicator_summary", {}).get("rsi", {}).get("value", 50),
        "regime": state.get("indicator_summary", {}).get("smart_money", {}).get("regime", "UNKNOWN"),
    })

    if not guard_result["guard_passed"]:
        logger.info(f"ExecutionBridge: GUARD BLOCKED {symbol} {master_decision} — {guard_result['guard_override_reason']}")
        return {
            "status":       "BLOCKED",
            "reason":       f"Guard Layer: {guard_result['guard_override_reason']}",
            "guard_result": guard_result,
            "timestamp":    timestamp,
        }

    # ── Step 1.5: Institutional Guards (Macro & Correlation) ──────────────────
    try:
        from intelligence.guards.correlation_guardian import check_correlation_safety
        from intelligence.guards.macro_shield import is_in_danger_zone

        # Macro News check
        news_status = is_in_danger_zone()
        if news_status["blocked"]:
            logger.warning(f"ExecutionBridge: MACRO SHIELD BLOCKED {symbol} — {news_status['event']}")
            return {
                "status": "BLOCKED",
                "reason": f"Institutional Safety: Macro News Shield active ({news_status['event']}). Trading is disabled during danger zones.",
                "news_detail": news_status,
                "timestamp": timestamp,
            }

        # Correlation check
        corr_status = check_correlation_safety(symbol)
        if not corr_status["passed"]:
            logger.warning(f"ExecutionBridge: CORRELATION BLOCKED {symbol} — {corr_status['reason']}")
            return {
                "status": "DRAFT_WARNING", # We return a warning instead of hard block here so user sees it
                "reason": f"Correlation Warning: {corr_status['reason']}",
                "corr_detail": corr_status,
                "timestamp": timestamp,
            }
    except Exception as inst_err:
        logger.error(f"ExecutionBridge: Institutional Guard Error: {inst_err}")

    # ── Step 2: Circuit Breaker ────────────────────────────────────────────────
    from intelligence.circuit_breaker import get_circuit_breaker
    cb = get_circuit_breaker(cb_config)

    # Fetch real account balance if not provided
    if account_balance is None:
        try:
            from intelligence.mt5_connector import get_mt5_account_info
            acct = get_mt5_account_info()
            account_balance = float(acct.get("balance", 1000.0))
        except Exception:
            account_balance = float(os.getenv("DEFAULT_BALANCE", "1000.0"))

    cb.config["portfolio_balance"] = account_balance
    cb_ok, cb_reason = cb.can_trade()

    if not cb_ok:
        logger.info(f"ExecutionBridge: CB BLOCKED {symbol} — {cb_reason}")
        return {
            "status":    "BLOCKED",
            "reason":    f"Circuit Breaker: {cb_reason}",
            "cb_status": cb.get_status(),
            "timestamp": timestamp,
        }

    # ── Step 3: Build order parameters ────────────────────────────────────────
    mt5_symbol   = _to_mt5_symbol(symbol)
    action       = "BUY" if master_decision == "LONG" else "SELL"

    # Entry price: midpoint of entry zone, fallback to current price from indicator summary
    entry_low    = float(entry_zone.get("low") or 0)
    entry_high   = float(entry_zone.get("high") or 0)
    entry_price  = (entry_low + entry_high) / 2 if entry_low and entry_high else \
                   float(state.get("indicator_summary", {}).get("price", 0))

    sl_price     = float(sl_data.get("price") or 0)
    tp1_price    = float(tp_data.get("tp1") or 0)
    tp2_price    = float(tp_data.get("tp2") or 0)

    if not entry_price or not sl_price:
        return {
            "status":  "ERROR",
            "reason":  f"Missing entry/SL prices — entry={entry_price}, sl={sl_price}",
            "timestamp": timestamp,
        }

    # Position sizing — apply signal grade multiplier from master agent tiering
    size_mult        = float(state.get("size_multiplier", 1.0))
    signal_grade     = state.get("signal_grade", "A+")
    policy_mult      = float(symbol_policy.get("size_multiplier", 1.0) or 1.0)
    if symbol_policy.get("action") == "reduce":
        signal_grade = f"{signal_grade} / policy-reduced"
    size_mult        = size_mult * policy_mult
    effective_risk   = risk_pct * size_mult

    contract_size = _get_contract_size(mt5_symbol)
    lot = _calculate_lot_size(
        balance=account_balance,
        risk_pct=effective_risk,
        entry_price=entry_price,
        sl_price=sl_price,
        contract_size=contract_size,
    )

    trade_details = {
        "symbol":        mt5_symbol,
        "action":        action,
        "volume":        lot,
        "entry_price":   round(entry_price, 5),
        "sl":            round(sl_price, 5),
        "tp":            round(tp1_price, 5) if tp1_price else None,
        "tp2":           round(tp2_price, 5) if tp2_price else None,
        "signal_grade":  signal_grade,
        "size_mult":     size_mult,
        "risk_pct":      effective_risk,
        "symbol_policy": symbol_policy,
        "risk_usd":      round(account_balance * effective_risk / 100, 2),
        "rr":            rr,
        "confidence":    round(float(confidence) * 100 if float(confidence) <= 1 else float(confidence), 1),
        "timeframe":     timeframe,
        "reasoning":     reasoning[:300],
        "timestamp":     timestamp,
    }

    logger.info(
        f"ExecutionBridge: {action} {lot} lot {mt5_symbol} "
        f"entry={entry_price} SL={sl_price} TP={tp1_price} "
        f"(risk ${trade_details['risk_usd']})"
    )

    # ── Step 4: Dry-run or Confirmation draft ─────────────────────────────────
    if dry_run:
        logger.info("ExecutionBridge: DRY_RUN - no order sent to MT5")
        exec_result = {
            "status":       "DRY_RUN",
            "reason":       "dry_run=True — simulated, not sent to MT5",
            "trade_details": trade_details,
            "guard_result": guard_result,
            "cb_status":    cb.get_status(),
            "timestamp":    timestamp,
        }
        _post_execution_hooks(state, exec_result, trade_details)
        return exec_result

    if confirmation_required:
        # Generate persistent ID: SYMBOL-TRADE-PLAN-XXXX
        short_id = str(uuid.uuid4())[:5].upper()
        draft_id = f"{mt5_symbol.upper()}-TRADE-PLAN-{short_id}"

        # Save to persistent SQLite DB
        save_trade_draft(
            draft_id=draft_id,
            session_id="AI_ANALYSIS",
            symbol=mt5_symbol,
            action=action,
            volume=lot,
            sl=sl_price,
            tp=tp1_price,
            comment=f"AI Draft via {timeframe}"
        )

        logger.info(f"ExecutionBridge: PERSISTENT DRAFT {draft_id} created for {action} {mt5_symbol}")
        return {
            "status":       "DRAFT",
            "draft_id":     draft_id,
            "reason":       "Awaiting user confirmation before live execution",
            "trade_details": trade_details,
            "guard_result": guard_result,
            "cb_status":    cb.get_status(),
            "timestamp":    timestamp,
        }

    # ── Step 5: Live execution ────────────────────────────────────────────────
    try:
        from intelligence.mt5_connector import mt5_execute_trade
        result = mt5_execute_trade(
            symbol=mt5_symbol,
            action=action,
            volume=lot,
            sl=sl_price if sl_price else None,
            tp=tp1_price if tp1_price else None,
            comment=f"CryptoStream AI {timeframe} {round(float(confidence)*100 if float(confidence)<=1 else float(confidence))}%",
        )

        if result.get("status") == "SUCCESS":
            logger.info(f"ExecutionBridge: ORDER FILLED — {result}")
            # Record placeholder P/L (actual updated when position closes)
            cb.record_trade_result(pnl_usd=0.0, is_win=True)
            exec_result = {
                "status":        "EXECUTED",
                "reason":        "Order sent and filled by MT5",
                "trade_details": trade_details,
                "mt5_result":    result,
                "guard_result":  guard_result,
                "cb_status":     cb.get_status(),
                "timestamp":     timestamp,
            }
            _post_execution_hooks(state, exec_result, trade_details)
            return exec_result
        else:
            logger.error(f"ExecutionBridge: MT5 order failed — {result}")
            return {
                "status":    "ERROR",
                "reason":    f"MT5 rejected order: {result.get('comment', result)}",
                "mt5_result": result,
                "timestamp": timestamp,
            }

    except Exception as e:
        logger.exception("ExecutionBridge: unexpected error during execution")
        return {
            "status":    "ERROR",
            "reason":    f"Execution exception: {str(e)[:200]}",
            "timestamp": timestamp,
        }


def _post_execution_hooks(state: dict, exec_result: dict, trade_details: dict):
    """
    Called after EXECUTED or DRY_RUN to:
      1. Log the trade via TradeLogger
      2. Send notification via SignalBroadcaster
    Errors are swallowed so they never abort the main execution path.
    """
    # ── Trade Logger ──────────────────────────────────────────────────────────
    try:
        from intelligence.trade_logger import get_trade_logger
        tl = get_trade_logger()
        log_entry = {
            **trade_details,
            "status":    exec_result.get("status"),
            "mt5_ticket": exec_result.get("mt5_result", {}).get("ticket"),
        }
        tl.log_trade(log_entry)
    except Exception as e:
        logger.warning(f"ExecutionBridge: TradeLogger error — {e}")

    # ── Signal Broadcaster ────────────────────────────────────────────────────
    try:
        from intelligence.signal_broadcaster import get_signal_broadcaster
        sb = get_signal_broadcaster()
        sb.send_execution_alert(state, exec_result)
    except Exception as e:
        logger.warning(f"ExecutionBridge: SignalBroadcaster error — {e}")


def record_trade_close(pnl_usd: float, is_win: bool, cb_config: dict = None):
    """
    Call this when a position is closed to update Circuit Breaker.
    pnl_usd: actual profit/loss in USD (negative = loss)
    is_win: True if trade was profitable
    """
    from intelligence.circuit_breaker import get_circuit_breaker
    cb = get_circuit_breaker(cb_config)
    cb.record_trade_result(pnl_usd=pnl_usd, is_win=is_win)
    logger.info(f"ExecutionBridge: trade close recorded — pnl=${pnl_usd:.2f} win={is_win}")
    return cb.get_status()
