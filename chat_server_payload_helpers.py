from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from typing import Any, Optional


def _metric_label(value: Any) -> str:
    text = str(value or "unknown")
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", text)[:80] or "unknown"


def _metric_number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _payload_updated_at(payload: Any, fallback_ts: Optional[float] = None) -> str:
    if isinstance(payload, dict):
        candidate = payload.get("updated_at")
        if isinstance(candidate, str) and candidate.strip():
            return candidate
        meta = payload.get("_meta")
        if isinstance(meta, dict):
            candidate = meta.get("updated_at")
            if isinstance(candidate, str) and candidate.strip():
                return candidate
    if fallback_ts:
        return datetime.fromtimestamp(fallback_ts, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return _utc_now_iso()


def _with_data_quality(
    payload: Any,
    *,
    cache_key: Optional[str],
    status: str,
    data_quality: str,
    source: str,
    warning: Optional[str] = None,
    error: Optional[str] = None,
    fallback_ts: Optional[float] = None,
    details: Optional[dict[str, Any]] = None,
):
    if isinstance(payload, dict):
        result = copy.deepcopy(payload)
    else:
        result = {"data": copy.deepcopy(payload)}
    result["_meta"] = {
        "status": status,
        "data_quality": data_quality,
        "source": source,
        "is_stale": data_quality == "stale",
        "updated_at": _payload_updated_at(payload, fallback_ts=fallback_ts),
        "cache_key": cache_key,
        "warning": warning,
        "error": error,
        "details": details or {},
    }
    result.setdefault("status", status.upper())
    result.setdefault("data_quality", data_quality)
    result.setdefault("updated_at", result["_meta"]["updated_at"])
    if warning and "warning" not in result:
        result["warning"] = warning
    if error and "error" not in result:
        result["error"] = error
    return result


def _has_non_empty_sequence(value: Any) -> bool:
    return isinstance(value, list) and len(value) > 0


def _market_sentiment_has_content(payload: dict) -> bool:
    overall = payload.get("overall") or {}
    score = overall.get("score")
    summary = overall.get("summary")
    return bool(
        _has_non_empty_sequence(payload.get("articles"))
        or (isinstance(summary, str) and summary.strip())
        or isinstance(score, (int, float))
    )


def _market_indices_has_content(payload: dict) -> bool:
    return any((item.get("price") or 0) > 0 for item in payload.values() if isinstance(item, dict))


def _market_stocks_has_content(payload: dict) -> bool:
    return any((item.get("price") or 0) > 0 for item in payload.values() if isinstance(item, dict))


def _etf_flows_has_content(payload: dict) -> bool:
    return _has_non_empty_sequence(payload.get("flows"))


def _calendar_has_content(payload: dict) -> bool:
    return _has_non_empty_sequence(payload.get("events")) or _has_non_empty_sequence(payload.get("macro_watch")) or bool((payload.get("trading_note") or "").strip())
