"""
CryptoStream AI — Trade Logger
Records all trade events and generates performance reports.

Ported from QuantAgent trade_logger.py — adapted for CryptoStream:
  - Works with execution_bridge.execute_signal() output format
  - Reads P/L from "profit" or "pnl" key (both formats accepted)
  - Added get_session_heatmap() for hour-of-day analysis
  - Added get_weekly_report() for LINE/Telegram summary
  - JSON file persisted alongside persistence.db

Usage:
    from intelligence.trade_logger import TradeLogger

    tl = TradeLogger()

    # After execution_bridge returns EXECUTED or DRY_RUN:
    tl.log_trade({
        "symbol":     "BTCUSD",
        "action":     "BUY",
        "volume":     0.01,
        "entry_price": 65000.0,
        "sl":          64000.0,
        "tp":          67000.0,
        "status":     "EXECUTED",
        "profit":     0.0,          # fill in on close
        "timestamp":  "2025-01-01T10:00:00+00:00",
    })

    stats = tl.get_statistics(days=30)
    report = tl.get_weekly_report()
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_LOG_FILE = Path("trade_history.json")


class TradeLogger:
    """
    Logs trade events to a JSON file and computes performance statistics.

    JSON schema per entry:
      symbol, action, volume, entry_price, sl, tp, status,
      profit (float, filled on close), timestamp, logged_at
    """

    def __init__(self, config: dict = None):
        self.config   = config or {}
        self.log_file = Path(self.config.get("trade_log_file", _DEFAULT_LOG_FILE))
        self._ensure_file()

    # ── Persistence ────────────────────────────────────────────────────────────

    def _ensure_file(self):
        if not self.log_file.exists():
            with open(self.log_file, "w", encoding="utf-8") as f:
                json.dump([], f)

    def _load(self) -> list:
        try:
            with open(self.log_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"TradeLogger._load error: {e}")
            return []

    def _save(self, data: list):
        try:
            with open(self.log_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"TradeLogger._save error: {e}")

    # ── Core API ───────────────────────────────────────────────────────────────

    def log_trade(self, trade_data: dict):
        """
        Append a trade record to the log.

        trade_data should contain at minimum:
          symbol, action, status, timestamp
        All other keys are stored as-is for future analysis.
        """
        history = self._load()
        entry   = {**trade_data, "logged_at": datetime.now().isoformat()}
        history.append(entry)
        self._save(history)
        logger.info(
            f"TradeLogger: logged {entry.get('status','?')} "
            f"{entry.get('action','?')} {entry.get('symbol','?')}"
        )

    def update_trade_close(self, ticket_or_timestamp: str, profit: float, is_win: bool):
        """
        Update an existing trade record when the position closes.

        Args:
            ticket_or_timestamp : MT5 ticket (int as str) or entry timestamp
            profit              : Actual P/L in account currency
            is_win              : Whether the trade was profitable
        """
        history = self._load()
        for trade in reversed(history):  # most-recent-first search
            match = (
                str(trade.get("ticket")) == str(ticket_or_timestamp) or
                trade.get("timestamp", "") == ticket_or_timestamp
            )
            if match:
                trade["profit"]    = round(profit, 2)
                trade["is_win"]    = is_win
                trade["closed_at"] = datetime.now().isoformat()
                self._save(history)
                logger.info(f"TradeLogger: updated close pnl=${profit:.2f}")
                return True
        logger.warning(f"TradeLogger: no trade found for {ticket_or_timestamp}")
        return False

    # ── Statistics ─────────────────────────────────────────────────────────────

    def get_statistics(self, days: int = None) -> dict:
        """
        Compute performance statistics over the last N days (or all time).

        Returns dict with:
          total_trades, wins, losses, win_rate, total_pnl, avg_pnl,
          best_trade, worst_trade, max_consecutive_losses
        """
        history = self._load()

        if days:
            cutoff  = (datetime.now() - timedelta(days=days)).isoformat()
            history = [t for t in history if t.get("timestamp", "") >= cutoff]

        if not history:
            return {
                "total_trades":          0,
                "wins":                  0,
                "losses":                0,
                "win_rate":              0.0,
                "total_pnl":             0.0,
                "avg_pnl":               0.0,
                "best_trade":            0.0,
                "worst_trade":           0.0,
                "max_consecutive_losses": 0,
            }

        # Only count executed/dry-run trades with a recorded P/L
        pnls = []
        for t in history:
            if t.get("status") in ("EXECUTED", "DRY_RUN"):
                pnl = float(t.get("profit") or t.get("pnl") or 0)
                pnls.append(pnl)

        if not pnls:
            pnls = [0.0]

        wins    = len([p for p in pnls if p > 0])
        losses  = len([p for p in pnls if p < 0])
        total   = len(pnls)

        # Max consecutive losses
        max_consec = cur_consec = 0
        for p in pnls:
            if p < 0:
                cur_consec += 1
                max_consec  = max(max_consec, cur_consec)
            else:
                cur_consec  = 0

        return {
            "total_trades":          total,
            "wins":                  wins,
            "losses":                losses,
            "win_rate":              round(wins / total * 100, 1) if total else 0.0,
            "total_pnl":             round(sum(pnls), 2),
            "avg_pnl":               round(sum(pnls) / total, 2) if total else 0.0,
            "best_trade":            round(max(pnls), 2),
            "worst_trade":           round(min(pnls), 2),
            "max_consecutive_losses": max_consec,
        }

    def get_weekly_report(self) -> str:
        """Generate a text report for the last 7 days (suitable for LINE/Telegram)."""
        stats   = self.get_statistics(days=7)
        balance = float(self.config.get("portfolio_balance", 1000.0))
        pnl_pct = (stats["total_pnl"] / balance * 100) if balance > 0 else 0

        return (
            f"Weekly Report ({datetime.now().strftime('%d %b %Y')})\n"
            f"{'━'*24}\n"
            f"Total Trades: {stats['total_trades']}\n"
            f"Win/Loss: {stats['wins']}W / {stats['losses']}L ({stats['win_rate']}%)\n"
            f"Net P/L: ${stats['total_pnl']:+.2f} ({pnl_pct:+.1f}%)\n"
            f"Best Trade: ${stats['best_trade']:+.2f}\n"
            f"Worst Trade: ${stats['worst_trade']:+.2f}\n"
            f"Max Consecutive Losses: {stats['max_consecutive_losses']}\n"
            f"{'━'*24}"
        )

    def get_recent_trades(self, count: int = 10) -> list:
        """Return the most recent N trade records."""
        history = self._load()
        return history[-count:] if history else []

    def get_session_heatmap(self) -> list:
        """
        Build an hour-of-day heatmap from all recorded trades.
        Returns a list of 24 dicts (one per UTC hour) with:
          hour, trades, wins, losses, pnl, win_rate
        """
        history = self._load()
        buckets = [
            {"hour": h, "trades": 0, "wins": 0, "losses": 0, "pnl": 0.0}
            for h in range(24)
        ]
        for t in history:
            ts  = t.get("timestamp", "")
            pnl = float(t.get("profit") or t.get("pnl") or 0)
            try:
                h = datetime.fromisoformat(ts).hour
            except Exception:
                continue
            b = buckets[h]
            b["trades"] += 1
            b["pnl"]    += pnl
            if pnl > 0:
                b["wins"]   += 1
            elif pnl < 0:
                b["losses"] += 1

        for b in buckets:
            b["pnl"]      = round(b["pnl"], 2)
            b["win_rate"] = round(b["wins"] / b["trades"] * 100, 1) if b["trades"] else 0.0

        return buckets


# ── Module-level singleton ─────────────────────────────────────────────────────
_tl_instance: TradeLogger | None = None


def get_trade_logger(config: dict = None) -> TradeLogger:
    """Return (or create) the process-wide TradeLogger singleton."""
    global _tl_instance
    if _tl_instance is None:
        _tl_instance = TradeLogger(config=config)
    return _tl_instance
