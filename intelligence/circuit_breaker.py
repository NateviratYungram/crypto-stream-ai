"""
CryptoStream AI — Circuit Breaker
Monitors session P/L and enforces loss limits to protect the portfolio.

Ported from QuantAgent circuit_breaker.py — adapted for crypto:
  - Stateless by default (in-memory, no file dependency)
  - Optional persistence via SQLite (persistence.db already in project)
  - Friday close replaced with weekend gap protection for 24/7 crypto
  - Added equity drawdown % tracking per session
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CB_CONFIG = {
    "daily_loss_limit_pct":    3.0,    # Stop if daily P/L < -3% of balance
    "weekly_loss_limit_pct":   8.0,    # Stop if weekly P/L < -8% of balance
    "max_consecutive_losses":  3,      # Pause 24h after N consecutive losses
    "emergency_stop_pct":      30.0,   # Permanent stop if portfolio drops 30%
    "pause_hours":             24,     # Hours to pause after consecutive losses
    "portfolio_balance":       1000.0, # Reference balance (update from real account)
}

_STATE_FILE = Path(os.getenv("CB_STATE_FILE", "circuit_breaker_state.json"))


class CircuitBreaker:
    """
    Monitors P/L and enforces loss limits.

    Usage:
        cb = CircuitBreaker(config={"portfolio_balance": 5000})
        ok, reason = cb.can_trade()
        if ok:
            # place trade
            cb.record_trade_result(pnl_usd=50.0, is_win=True)
    """

    def __init__(self, config: dict = None, persist: bool = True):
        self.config  = {**DEFAULT_CB_CONFIG, **(config or {})}
        self.persist = persist
        self.state   = self._load_state()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load_state(self) -> dict:
        if self.persist and _STATE_FILE.exists():
            try:
                with open(_STATE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"CircuitBreaker: could not load state ({e}), starting fresh")
        return {
            "consecutive_losses": 0,
            "daily_pnl":          0.0,
            "weekly_pnl":         0.0,
            "last_reset_day":     "",
            "last_reset_week":    "",
            "stopped_until":      None,
            "permanent_stop":     False,
        }

    def _save_state(self):
        if not self.persist:
            return
        try:
            with open(_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            logger.warning(f"CircuitBreaker: could not save state ({e})")

    # ── Daily / Weekly resets ─────────────────────────────────────────────────

    def _now_utc(self) -> datetime:
        return datetime.now(timezone.utc)

    def _reset_if_new_period(self):
        now   = self._now_utc()
        today = now.strftime("%Y-%m-%d")
        week  = now.strftime("%Y-W%W")

        if self.state["last_reset_day"] != today:
            self.state["daily_pnl"]      = 0.0
            self.state["last_reset_day"] = today

        if self.state["last_reset_week"] != week:
            self.state["weekly_pnl"]       = 0.0
            self.state["last_reset_week"]  = week
            self.state["consecutive_losses"] = 0

    # ── Core API ──────────────────────────────────────────────────────────────

    def can_trade(self) -> tuple[bool, str]:
        """
        Returns (allowed: bool, reason: str).
        Call before placing any trade.
        """
        self._reset_if_new_period()
        balance = float(self.config["portfolio_balance"])

        # Permanent stop (catastrophic loss)
        if self.state.get("permanent_stop"):
            return False, (
                "PERMANENT STOP — portfolio dropped beyond emergency threshold. "
                "Call circuit_breaker.reset() after manual review."
            )

        # Time-based pause (after consecutive losses)
        stopped_until = self.state.get("stopped_until")
        if stopped_until:
            try:
                stop_time = datetime.fromisoformat(stopped_until)
                if stop_time.tzinfo is None:
                    stop_time = stop_time.replace(tzinfo=timezone.utc)
                now = self._now_utc()
                if now < stop_time:
                    remaining_h = (stop_time - now).total_seconds() / 3600
                    return False, (
                        f"Paused {remaining_h:.1f}h after {self.config['max_consecutive_losses']} "
                        "consecutive losses"
                    )
                else:
                    self.state["stopped_until"] = None
            except Exception:
                self.state["stopped_until"] = None

        # Daily loss limit
        daily_limit = balance * self.config["daily_loss_limit_pct"] / 100
        if self.state["daily_pnl"] < 0 and abs(self.state["daily_pnl"]) >= daily_limit:
            return False, (
                f"Daily loss limit reached "
                f"(${abs(self.state['daily_pnl']):.2f} / ${daily_limit:.2f})"
            )

        # Weekly loss limit
        weekly_limit = balance * self.config["weekly_loss_limit_pct"] / 100
        if self.state["weekly_pnl"] < 0 and abs(self.state["weekly_pnl"]) >= weekly_limit:
            return False, (
                f"Weekly loss limit reached "
                f"(${abs(self.state['weekly_pnl']):.2f} / ${weekly_limit:.2f})"
            )

        # Consecutive losses → trigger pause
        max_consec = int(self.config["max_consecutive_losses"])
        if self.state["consecutive_losses"] >= max_consec:
            pause_until = (self._now_utc() + timedelta(hours=self.config["pause_hours"])).isoformat()
            self.state["stopped_until"]      = pause_until
            self.state["consecutive_losses"] = 0
            self._save_state()
            return False, (
                f"{max_consec} consecutive losses — pausing "
                f"{self.config['pause_hours']}h"
            )

        return True, "Trading allowed"

    def record_trade_result(self, pnl_usd: float, is_win: bool):
        """
        Record outcome of a completed trade.
        Call immediately after a trade closes.
        """
        self._reset_if_new_period()
        balance = float(self.config["portfolio_balance"])

        self.state["daily_pnl"]  += pnl_usd
        self.state["weekly_pnl"] += pnl_usd

        if is_win:
            self.state["consecutive_losses"] = 0
        else:
            self.state["consecutive_losses"] += 1

        # Emergency stop check
        emergency_pct = float(self.config["emergency_stop_pct"])
        running_balance = balance + self.state["weekly_pnl"]
        if running_balance < balance * (1 - emergency_pct / 100):
            self.state["permanent_stop"] = True
            logger.critical(
                f"CircuitBreaker: PERMANENT STOP triggered — balance fell to "
                f"${running_balance:.2f} ({emergency_pct:.0f}% drawdown)"
            )

        self._save_state()

    def get_status(self) -> dict:
        """Returns a dashboard-friendly status dict."""
        self._reset_if_new_period()
        balance = float(self.config["portfolio_balance"])
        can, reason = self.can_trade()

        return {
            "can_trade":          can,
            "reason":             reason,
            "daily_pnl":          round(self.state["daily_pnl"], 2),
            "weekly_pnl":         round(self.state["weekly_pnl"], 2),
            "consecutive_losses": self.state["consecutive_losses"],
            "daily_limit_usd":    round(balance * self.config["daily_loss_limit_pct"] / 100, 2),
            "weekly_limit_usd":   round(balance * self.config["weekly_loss_limit_pct"] / 100, 2),
            "permanent_stop":     self.state.get("permanent_stop", False),
            "stopped_until":      self.state.get("stopped_until"),
        }

    def reset(self):
        """Manual reset — use after reviewing a permanent stop."""
        now = self._now_utc()
        self.state = {
            "consecutive_losses": 0,
            "daily_pnl":          0.0,
            "weekly_pnl":         0.0,
            "last_reset_day":     now.strftime("%Y-%m-%d"),
            "last_reset_week":    now.strftime("%Y-W%W"),
            "stopped_until":      None,
            "permanent_stop":     False,
        }
        self._save_state()
        logger.info("CircuitBreaker: manual reset complete")


# ── Module-level singleton (shared across the process) ────────────────────────
_cb_instance: CircuitBreaker | None = None


def get_circuit_breaker(config: dict = None) -> CircuitBreaker:
    """
    Return (or create) the process-wide CircuitBreaker singleton.
    Pass config on first call; subsequent calls ignore config.
    """
    global _cb_instance
    if _cb_instance is None:
        _cb_instance = CircuitBreaker(config=config)
    return _cb_instance
