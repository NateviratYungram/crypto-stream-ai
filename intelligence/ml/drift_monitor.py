"""
CryptoStream AI — ML Drift Shield
Institutional data stability monitor for Intelligence V5.
Detects when live market features are significantly uncoupled from training distributions.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Mocked baseline - in a production environment, these would be loaded from a
# 'training_stats.json' generated during signal_model.train_model()
BASELINE_STATS = {
    "rsi": {"mean": 50.4, "std": 14.2, "weight": 1.0},
    "atr_pct": {"mean": 0.012, "std": 0.005, "weight": 2.0},  # Volatility is more critical
    "macd": {"mean": 0.0, "std": 0.8, "weight": 1.0},
    "volume_zscore": {"mean": 0.0, "std": 1.2, "weight": 1.5},
}

class DriftMonitor:
    def __init__(self, baseline: Dict[str, Dict] = None):
        self.baseline = baseline or BASELINE_STATS
        self.feature_history = {k: [] for k in self.baseline.keys()}
        self.history_limit = 100

    def check_drift(self, current_features: Dict[str, Any]) -> Dict[str, Any]:
        """
        Computes Z-scores for current features vs baseline.
        Returns a 'Data Integrity' score (0-100).
        """
        drift_warnings = []
        total_z = 0
        weight_sum = 0

        for feat, stats in self.baseline.items():
            val = current_features.get(feat)
            if val is None:
                continue

            # Simple Z-score check
            z = abs((val - stats["mean"]) / stats["std"])
            total_z += z * stats["weight"]
            weight_sum += stats["weight"]

            if z > 3.0:
                drift_warnings.append(f"OUTLIER: {feat} is {z:.1f} std devs from baseline.")

            # Update history for rolling drift
            self.feature_history[feat].append(val)
            if len(self.feature_history[feat]) > self.history_limit:
                self.feature_history[feat].pop(0)

        # Integrity Score calculation: 100 - (Avg Z * 10)
        avg_z = (total_z / weight_sum) if weight_sum > 0 else 0
        integrity_score = max(0, min(100, int(100 - (avg_z * 12))))

        status = "STABLE"
        if integrity_score < 70:
            status = "WARNING"
        if integrity_score < 40:
            status = "CRITICAL_DRIFT"

        return {
            "integrity_score": integrity_score,
            "status": status,
            "warnings": drift_warnings,
            "avg_z_score": round(avg_z, 2),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

# Singleton instance
drift_shield = DriftMonitor()

def get_drift_report(features: Dict[str, Any]) -> Dict[str, Any]:
    """Tool wrapper for decision agents to check data integrity."""
    return drift_shield.check_drift(features)
