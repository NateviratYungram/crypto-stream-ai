from __future__ import annotations

from datetime import datetime as dt_datetime
from typing import Any, Dict, Iterable, Optional


def _build_historical_ranking_insert_payload(
    rows: Iterable[dict[str, Any]],
    *,
    years: int,
    universe: str,
    full_window_only: bool,
    source: str = "yfinance",
) -> list[tuple[Any, ...]]:
    return [
        (
            row["symbol"],
            row["yf_symbol"],
            universe,
            years,
            bool(full_window_only),
            row.get("end_date"),
            row.get("start_date"),
            row.get("end_date"),
            row.get("start_price"),
            row.get("end_price"),
            row.get("total_return_pct"),
            row.get("cagr_pct"),
            row.get("max_drawdown_pct"),
            source,
        )
        for row in rows
    ]


def _historical_rankings_are_fresh(
    meta: Dict[str, Any],
    *,
    max_age_hours: int,
    now: Optional[dt_datetime] = None,
) -> bool:
    eligible_count = int(meta.get("eligible_count") or 0)
    if eligible_count <= 0:
        return False

    updated_at = meta.get("updated_at")
    if updated_at is None:
        return False

    clock = now or dt_datetime.utcnow()
    age_hours = (clock - updated_at.replace(tzinfo=None)).total_seconds() / 3600.0
    return age_hours <= max_age_hours


def _serialize_historical_ranking_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw_row in rows:
        row = dict(raw_row)
        for key in ("start_date", "end_date"):
            if hasattr(row.get(key), "isoformat"):
                row[key] = row[key].isoformat()
        for key in ("start_price", "end_price", "total_return_pct", "cagr_pct", "max_drawdown_pct"):
            if row.get(key) is not None:
                row[key] = round(float(row[key]), 2)
        normalized.append(row)
    return normalized


def _build_persisted_historical_rankings_response(
    *,
    meta: Dict[str, Any],
    rows: Iterable[dict[str, Any]],
    years: int,
    direction: str,
    universe: str,
    full_window_only: bool,
) -> Dict[str, Any]:
    as_of = meta.get("as_of_date")
    updated_at = meta.get("updated_at")
    return {
        "status": "SUCCESS",
        "years": years,
        "direction": direction,
        "universe": universe,
        "full_window_only": bool(full_window_only),
        "as_of": as_of.isoformat() if hasattr(as_of, "isoformat") else as_of,
        "results": _serialize_historical_ranking_rows(rows),
        "eligible_count": int(meta.get("eligible_count") or 0),
        "excluded_count": None,
        "source": "postgres_summary",
        "updated_at": updated_at.isoformat() if hasattr(updated_at, "isoformat") else str(updated_at),
    }


def _build_live_historical_rankings_response(
    *,
    rankings: list[dict[str, Any]],
    years: int,
    direction: str,
    universe: str,
    full_window_only: bool,
    as_of: Any,
    eligible_count: Any,
    excluded_count: Any,
    limit: int,
) -> Dict[str, Any]:
    return {
        "status": "SUCCESS",
        "years": years,
        "direction": direction,
        "universe": universe,
        "full_window_only": bool(full_window_only),
        "as_of": as_of,
        "results": rankings[:limit],
        "eligible_count": eligible_count,
        "excluded_count": excluded_count,
        "source": "live_compute",
    }
