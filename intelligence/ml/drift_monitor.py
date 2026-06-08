"""
CryptoStream AI — ML Drift Shield
Institutional data stability monitor for Intelligence V5.
Detects when live market features are significantly uncoupled from training distributions.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

_STATS_PATH = Path(os.getenv("ML_MODEL_PATH", "data/signal_model.pkl")).parent / "training_stats.json"

_DEFAULT_BASELINE = {
    "rsi":             {"mean": 50.4,  "std": 14.2,  "weight": 1.0},
    "atr_pct":         {"mean": 0.012, "std": 0.005, "weight": 2.0},
    "macd_hist_norm":  {"mean": 0.0,   "std": 0.8,   "weight": 1.0},
    "vol_ratio":       {"mean": 1.0,   "std": 1.2,   "weight": 1.5},
}


def _load_baseline(stats_path: Path | None = None) -> Dict[str, Dict]:
    target_path = stats_path or _STATS_PATH
    if target_path.exists():
        try:
            with open(target_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"[DriftMonitor] Could not load training_stats.json: {e}")
    return _DEFAULT_BASELINE


class DriftMonitor:
    def __init__(self, baseline: Dict[str, Dict] = None, history_limit: int = 100, stats_path: Path | None = None):
        self.baseline = baseline if baseline is not None else _load_baseline(stats_path=stats_path)
        self.feature_history = {k: [] for k in self.baseline.keys()}
        self.history_limit = history_limit

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

            z = abs((val - stats["mean"]) / max(stats["std"], 1e-9))
            total_z += z * stats["weight"]
            weight_sum += stats["weight"]

            if z > 3.0:
                drift_warnings.append(f"OUTLIER: {feat} is {z:.1f} std devs from baseline.")

            self.feature_history.setdefault(feat, []).append(val)
            if len(self.feature_history[feat]) > self.history_limit:
                self.feature_history[feat].pop(0)

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
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# Singleton instance — initialised from training_stats.json if available
drift_shield = DriftMonitor()


def get_drift_report(features: Dict[str, Any]) -> Dict[str, Any]:
    """Tool wrapper for decision agents to check data integrity."""
    return drift_shield.check_drift(features)


def update_baseline(stats: Dict[str, Dict]) -> None:
    """Reload drift baseline from freshly computed training stats (called after retrain)."""
    drift_shield.baseline = stats
    drift_shield.feature_history = {k: [] for k in stats.keys()}
    logger.info(f"[DriftMonitor] Baseline updated with {len(stats)} features from training stats")
