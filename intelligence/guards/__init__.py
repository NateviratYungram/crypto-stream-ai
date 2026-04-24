import json
import logging
import os
import time
from typing import Any, Dict, List, Tuple

from .institutional_guard import InstitutionalGuard as InstitutionalGuard

logger = logging.getLogger(__name__)

class GuardResult:
    def __init__(self, passed: bool, message: str, severity: str = "INFO"):
        self.passed = passed
        self.message = message
        self.severity = severity

class BaseGuard:
    def validate(self, order_params: Dict[str, Any], account_info: Dict[str, Any]) -> GuardResult:
        raise NotImplementedError("Guards must implement validate()")

class MaxPositionSizeGuard(BaseGuard):
    def __init__(self, max_equity_pct: float = 2.0):
        self.max_equity_pct = max_equity_pct

    def validate(self, order_params: Dict[str, Any], account_info: Dict[str, Any]) -> GuardResult:
        account_info.get("equity", account_info.get("balance", 0))
        lot_size = order_params.get("volume", 0)
        if lot_size > 10.0:
            return GuardResult(False, f"Lot size {lot_size} exceeds safety cap (10.0).", "CRITICAL")
        return GuardResult(True, "Position size within limits.")

class CooldownGuard(BaseGuard):
    def __init__(self, cooldown_seconds: int = 300):
        self.cooldown_seconds = cooldown_seconds
        self.history_file = "trade_history.json"

    def validate(self, order_params: Dict[str, Any], account_info: Dict[str, Any]) -> GuardResult:
        symbol = order_params.get("symbol", "").upper()
        if not os.path.exists(self.history_file):
            return GuardResult(True, "No trade history found.")
        try:
            with open(self.history_file, 'r') as f:
                history = json.load(f)
                if not isinstance(history, list):
                    history = []
        except Exception:
            return GuardResult(True, "Could not read trade history.")
        same_symbol_trades = [t for t in history if t.get("symbol", "").upper() == symbol]
        if not same_symbol_trades:
            return GuardResult(True, f"No previous trades for {symbol}.")
        last_trade = same_symbol_trades[-1]
        elapsed = time.time() - last_trade.get("time", 0)
        if elapsed < self.cooldown_seconds:
            wait_remaining = int(self.cooldown_seconds - elapsed)
            return GuardResult(False, f"Cooldown active for {symbol}. Wait {wait_remaining}s.", "WARNING")
        return GuardResult(True, "Cooldown expired.")

class GuardPipeline:
    def __init__(self, guards: List[BaseGuard]):
        self.guards = guards

    def run(self, order_params: Dict[str, Any], account_info: Dict[str, Any]) -> Tuple[bool, List[str]]:
        results = []
        all_passed = True
        for guard in self.guards:
            res = guard.validate(order_params, account_info)
            if not res.passed:
                all_passed = False
                results.append(f"[{res.severity}] {res.message}")
            else:
                results.append(f"[OK] {res.message}")
        return all_passed, results
