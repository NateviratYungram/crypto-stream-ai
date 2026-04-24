import os
import json
import logging
from datetime import datetime
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Institutional Audit Path
EVENT_LOG_FILE = "data/audit/system_events.jsonl"

class AuditLogger:
    """
    Append-only persistent event log for institutional audibility.
    Tracks critical system transitions, errors, and trade attempts.
    """
    def __init__(self, log_path: str = EVENT_LOG_FILE):
        self.log_path = log_path
        # Ensure directories exist
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)

    def log_event(self, event_type: str, payload: Dict[str, Any]):
        """Append a structured JSON event to the audit log."""
        entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "type": event_type,
            "payload": payload
        }

        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
            logger.info(f"Audit: Logged event '{event_type}'")
        except Exception as e:
            logger.error(f"Audit: Failed to write event log: {e}")

# Global instance for easy access
audit_log = AuditLogger()

def log_trade_attempt(symbol: str, action: str, volume: float, reason: str):
    audit_log.log_event("trade.attempt", {
        "symbol": symbol,
        "action": action,
        "volume": volume,
        "reason": reason
    })

def log_guard_failure(guard_name: str, message: str):
    audit_log.log_event("safety.guard_failure", {
        "guard": guard_name,
        "reason": message
    })

def log_security_threat(source: str, pattern: str):
    audit_log.log_event("security.threat_detected", {
        "source": source,
        "pattern": pattern
    })
