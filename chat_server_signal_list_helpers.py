from __future__ import annotations

from collections import defaultdict
from typing import Any


def _filter_signal_rows(
    signals: list[dict],
    min_confidence: int = 0,
    actionable_only: bool = False,
    tradeable_only: bool = False,
    grade: str | None = None,
) -> list[dict]:
    normalized_grade = (grade or "").strip().upper()
    filtered: list[dict] = []
    for signal in signals:
        confidence = int(signal.get("confidence") or 0)
        if confidence < int(min_confidence):
            continue
        if actionable_only and not bool(signal.get("actionable")):
            continue
        if tradeable_only and not bool(signal.get("tradeable")):
            continue
        if normalized_grade and str(signal.get("signal_grade", "")).upper() != normalized_grade:
            continue
        filtered.append(signal)
    return filtered


def _build_price_delta_fallback_signals(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["symbol"]].append(row)

    signals: list[dict[str, Any]] = []
    for symbol, records in grouped.items():
        if len(records) < 2:
            continue
        latest = records[0]
        previous = records[1]
        price_now = float(latest["avg_price"])
        price_prev = float(previous["avg_price"])
        volume_now = float(latest["total_volume"])
        volume_prev = float(previous["total_volume"])

        delta_pct = ((price_now - price_prev) / price_prev) * 100 if price_prev else 0
        volume_surge = (volume_now / volume_prev) if volume_prev else 1.0

        if delta_pct > 0.1 and volume_surge > 1.2:
            direction = "BUY"
            confidence = min(95, 60 + int(abs(delta_pct) * 10 + volume_surge * 5))
            reason = f"Price +{delta_pct:.2f}% with volume surge x{volume_surge:.1f}"
        elif delta_pct < -0.1 and volume_surge > 1.2:
            direction = "SELL"
            confidence = min(95, 60 + int(abs(delta_pct) * 10 + volume_surge * 5))
            reason = f"Price {delta_pct:.2f}% with volume surge x{volume_surge:.1f}"
        elif abs(delta_pct) < 0.05:
            direction = "HOLD"
            confidence = 50
            reason = "Low momentum, tight range consolidation"
        else:
            direction = "WATCH"
            confidence = 45
            reason = f"Mixed signal: Δ{delta_pct:.2f}%, vol x{volume_surge:.1f}"

        signals.append(
            {
                "symbol": symbol,
                "direction": direction,
                "confidence": confidence,
                "reason": reason,
                "price": price_now,
                "delta_pct": round(delta_pct, 4),
                "vol_surge": round(volume_surge, 2),
                "timestamp": str(latest["window_end"]),
            }
        )

    signals.sort(key=lambda item: item["confidence"], reverse=True)
    return signals
