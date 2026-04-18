import logging
import pandas as pd
import numpy as np
import yfinance as yf
from typing import List, Dict, Any, Optional
from intelligence.mt5_connector import get_mt5_account_info
from intelligence.persistence_utils import get_active_trades

logger = logging.getLogger(__name__)

class RiskManager:
    """
    Intelligence V6: Institutional Risk Manager.
    Handles Kelly Criterion sizing, Portfolio Correlation, and Equity Protection.
    """
    
    def __init__(self, max_daily_loss_pct: float = 3.0, max_correlation: float = 0.85):
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_correlation = max_correlation

    def calculate_kelly_size(self, win_prob: float, rr_ratio: float, balance: float, leverage: float = 1.0) -> float:
        """
        Calculates position size using the Kelly Criterion.
        formula: f = (p * (b + 1) - 1) / b
        where p = win_prob, b = RR ratio (net odds)
        We use a fractional Kelly (0.5) to maintain institutional safety.
        """
        if rr_ratio <= 0: return 0.01 # Fallback to 1%
        
        # Kelly %
        k_pct = (win_prob * (rr_ratio + 1) - 1) / rr_ratio
        
        # Fractional Kelly (Institutional Standard is 0.25 to 0.5)
        safe_k = max(0, k_pct * 0.5) 
        
        # Cap at 5% per trade for hard safety
        final_risk_pct = min(safe_k, 0.05)
        
        # Convert risk % to volume (simplified, should ideally account for SL distance)
        # For now, return the risk percentage to be used by the caller
        return final_risk_pct

    def check_correlation_risk(self, symbol: str, lookback_days: int = 30) -> Dict[str, Any]:
        """
        Checks if the new symbol is too correlated with currently active trades.
        """
        active_trades = get_active_trades()
        if not active_trades:
            return {"status": "SAFE", "max_corr": 0, "conflicts": []}
        
        active_symbols = list(set([t['symbol'] for t in active_trades]))
        all_symbols = active_symbols + [symbol]
        
        try:
            # Fetch returns for correlation check
            # Note: This is a heavy operation, in a real system we'd use a cached matrix
            data = yf.download(all_symbols, period=f"{lookback_days}d", interval="1d", progress=False)['Close']
            if len(all_symbols) == 1:
                return {"status": "SAFE", "max_corr": 0, "conflicts": []}
                
            returns = data.pct_change().dropna()
            corr_matrix = returns.corr()
            
            conflicts = []
            max_corr = 0
            for active in active_symbols:
                c = corr_matrix.loc[symbol, active]
                if c > max_corr: max_corr = c
                if c > self.max_correlation:
                    conflicts.append({"symbol": active, "correlation": round(c, 2)})
            
            if conflicts:
                return {
                    "status": "HIGH_CORRELATION",
                    "max_corr": round(max_corr, 2),
                    "conflicts": conflicts,
                    "message": f"Symbol {symbol} is highly correlated with existing positions."
                }
            
            return {"status": "SAFE", "max_corr": round(max_corr, 2), "conflicts": []}
            
        except Exception as e:
            logger.error(f"RiskManager: Correlation check failed: {e}")
            return {"status": "UNKNOWN", "error": str(e)}

    def check_equity_protection(self) -> Dict[str, Any]:
        """
        Enforces daily drawdown limits and overall account safety.
        """
        acc = get_mt5_account_info()
        if "error" in acc:
            return {"status": "ERROR", "message": acc["error"]}
        
        balance = acc.get("balance", 0)
        equity = acc.get("equity", 0)
        
        # Check current drawdown vs balance
        dd_pct = ((balance - equity) / balance) * 100 if balance > 0 else 0
        
        if dd_pct > self.max_daily_loss_pct:
            return {
                "status": "BLOCKED",
                "reason": "DAILY_LOSS_LIMIT",
                "current_dd": round(dd_pct, 2),
                "limit": self.max_daily_loss_pct
            }
            
        return {"status": "SAFE", "current_dd": round(dd_pct, 2)}

risk_manager = RiskManager()
