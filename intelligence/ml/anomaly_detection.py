"""Adaptive anomaly detection for market data quality and operations.

The detector is deliberately framework-free so it can run inside Airflow,
unit tests, and lightweight local demos. It uses rolling statistical baselines
for price returns, candle range, volume spikes, and missing candle gaps.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import mean, median, pstdev
from typing import Any, Dict, Iterable, List, Optional

TIMEFRAME_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1_800,
    "1h": 3_600,
    "4h": 14_400,
    "1d": 86_400,
}

CONTINUOUS_CRYPTO_SYMBOLS = {
    "ADAUSD",
    "ATOMUSD",
    "AVAXUSD",
    "BNBUSD",
    "BTC-USD",
    "BTCUSD",
    "DOGEUSD",
    "DOTUSD",
    "ETH-USD",
    "ETHUSD",
    "LINKUSD",
    "MATICUSD",
    "SOL-USD",
    "SOLUSD",
    "XRPUSD",
}

ASSET_CLASS_PROFILES = {
    "CRYPTO": {
        "return_z_threshold": 4.0,
        "absolute_return_threshold": 0.08,
        "volume_z_threshold": 4.0,
        "volume_ratio_threshold": 8.0,
        "range_ratio_threshold": 5.0,
        "gap_multiplier": 2.5,
    },
    "EQUITY_INDEX": {
        "return_z_threshold": 5.0,
        "absolute_return_threshold": 0.04,
        "volume_z_threshold": 5.0,
        "volume_ratio_threshold": 6.0,
        "range_ratio_threshold": 6.0,
        "gap_multiplier": 999.0,
    },
    "FUTURES": {
        "return_z_threshold": 5.0,
        "absolute_return_threshold": 0.04,
        "volume_z_threshold": 5.0,
        "volume_ratio_threshold": 8.0,
        "range_ratio_threshold": 6.0,
        "gap_multiplier": 999.0,
    },
    "FOREX": {
        "return_z_threshold": 5.0,
        "absolute_return_threshold": 0.015,
        "volume_z_threshold": 99.0,
        "volume_ratio_threshold": 99.0,
        "range_ratio_threshold": 5.0,
        "gap_multiplier": 999.0,
    },
    "DEFAULT": {
        "return_z_threshold": 4.0,
        "absolute_return_threshold": 0.08,
        "volume_z_threshold": 4.0,
        "volume_ratio_threshold": 5.0,
        "range_ratio_threshold": 5.0,
        "gap_multiplier": 999.0,
    },
}


@dataclass(frozen=True)
class OhlcvPoint:
    symbol: str
    timeframe: str
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = None


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise TypeError(f"Unsupported timestamp value: {value!r}")


def normalize_ohlcv_rows(rows: Iterable[Dict[str, Any]]) -> List[OhlcvPoint]:
    points = [
        OhlcvPoint(
            symbol=str(row["symbol"]).upper(),
            timeframe=str(row["timeframe"]),
            ts=_as_datetime(row["ts"]),
            open=_as_float(row["open"]),
            high=_as_float(row["high"]),
            low=_as_float(row["low"]),
            close=_as_float(row["close"]),
            volume=_as_float(row.get("volume")) if row.get("volume") is not None else None,
        )
        for row in rows
    ]
    return sorted(points, key=lambda point: (point.symbol, point.timeframe, point.ts))


def _zscore(value: float, baseline: List[float]) -> float:
    if len(baseline) < 5:
        return 0.0
    sigma = pstdev(baseline)
    if sigma <= 0:
        return 0.0
    return (value - mean(baseline)) / sigma


def _severity(score: float) -> str:
    abs_score = abs(score)
    if abs_score >= 6:
        return "CRITICAL"
    if abs_score >= 4:
        return "HIGH"
    if abs_score >= 3:
        return "MEDIUM"
    return "LOW"


def _event_key(
    symbol: str,
    timeframe: str,
    event_ts: datetime,
    anomaly_type: str,
) -> str:
    return f"{symbol}:{timeframe}:{event_ts.isoformat()}:{anomaly_type}"


def is_continuous_market_symbol(symbol: str) -> bool:
    """Return True for symbols expected to trade continuously."""
    normalized = symbol.upper()
    return normalized in CONTINUOUS_CRYPTO_SYMBOLS


def classify_asset_class(symbol: str) -> str:
    normalized = symbol.upper()
    if normalized in CONTINUOUS_CRYPTO_SYMBOLS:
        return "CRYPTO"
    if normalized.startswith("^"):
        return "EQUITY_INDEX"
    if normalized.endswith("=F"):
        return "FUTURES"
    if len(normalized) == 6 and normalized.isalpha():
        return "FOREX"
    return "DEFAULT"


def threshold_profile(symbol: str) -> Dict[str, float]:
    return ASSET_CLASS_PROFILES[classify_asset_class(symbol)]


def _build_event(
    point: OhlcvPoint,
    anomaly_type: str,
    severity: str,
    score: float,
    metric_value: float,
    baseline_value: Optional[float],
    details: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "event_key": _event_key(point.symbol, point.timeframe, point.ts, anomaly_type),
        "symbol": point.symbol,
        "timeframe": point.timeframe,
        "event_ts": point.ts,
        "anomaly_type": anomaly_type,
        "severity": severity,
        "score": round(float(score), 4),
        "metric_value": round(float(metric_value), 8),
        "baseline_value": (
            round(float(baseline_value), 8) if baseline_value is not None else None
        ),
        "details": details,
    }


def detect_market_anomalies(
    rows: Iterable[Dict[str, Any]] | Iterable[OhlcvPoint],
    lookback: int = 30,
    min_baseline: int = 12,
    return_z_threshold: Optional[float] = None,
    absolute_return_threshold: Optional[float] = None,
    volume_z_threshold: Optional[float] = None,
    volume_ratio_threshold: Optional[float] = None,
    range_ratio_threshold: Optional[float] = None,
    gap_multiplier: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Detect adaptive anomalies in OHLCV candles.

    Returns event dictionaries ready to persist into data_anomaly_events.
    """
    raw_rows = list(rows)
    if not raw_rows:
        return []

    if isinstance(raw_rows[0], OhlcvPoint):
        points = sorted(raw_rows, key=lambda point: (point.symbol, point.timeframe, point.ts))
    else:
        points = normalize_ohlcv_rows(raw_rows)  # type: ignore[arg-type]

    events: List[Dict[str, Any]] = []
    groups: Dict[tuple[str, str], List[OhlcvPoint]] = {}
    for point in points:
        groups.setdefault((point.symbol, point.timeframe), []).append(point)

    for (_symbol, timeframe), series in groups.items():
        expected_delta = timedelta(seconds=TIMEFRAME_SECONDS.get(timeframe, 0))
        returns: List[float] = []
        volumes: List[float] = []
        ranges: List[float] = []

        previous: Optional[OhlcvPoint] = None
        for point in series:
            asset_class = classify_asset_class(point.symbol)
            profile = threshold_profile(point.symbol)
            return_z = return_z_threshold or profile["return_z_threshold"]
            absolute_return = absolute_return_threshold or profile["absolute_return_threshold"]
            volume_z = volume_z_threshold or profile["volume_z_threshold"]
            volume_ratio = volume_ratio_threshold or profile["volume_ratio_threshold"]
            range_ratio = range_ratio_threshold or profile["range_ratio_threshold"]
            gap_limit = gap_multiplier or profile["gap_multiplier"]

            if (
                previous
                and expected_delta.total_seconds() > 0
                and is_continuous_market_symbol(point.symbol)
            ):
                actual_delta = point.ts - previous.ts
                if actual_delta > expected_delta * gap_limit:
                    missing_estimate = max(
                        1,
                        math.floor(actual_delta.total_seconds() / expected_delta.total_seconds()) - 1,
                    )
                    score = actual_delta.total_seconds() / expected_delta.total_seconds()
                    events.append(
                        _build_event(
                            point=point,
                            anomaly_type="missing_candle_gap",
                            severity=_severity(score),
                            score=score,
                            metric_value=actual_delta.total_seconds(),
                            baseline_value=expected_delta.total_seconds(),
                            details={
                                "previous_ts": previous.ts.isoformat(),
                                "expected_seconds": expected_delta.total_seconds(),
                                "actual_seconds": actual_delta.total_seconds(),
                                "estimated_missing_candles": missing_estimate,
                                "asset_class": asset_class,
                            },
                        )
                    )

            if previous and previous.close > 0 and point.close > 0:
                pct_return = (point.close - previous.close) / previous.close
                baseline_returns = returns[-lookback:]
                if len(baseline_returns) >= min_baseline:
                    score = _zscore(pct_return, baseline_returns)
                    absolute_score = abs(pct_return) / absolute_return
                    trigger_score = score if abs(score) >= abs(absolute_score) else absolute_score
                    if (
                        abs(score) >= return_z
                        or abs(pct_return) >= absolute_return
                    ):
                        events.append(
                            _build_event(
                                point=point,
                                anomaly_type="price_return_spike",
                                severity=_severity(trigger_score),
                                score=trigger_score,
                                metric_value=pct_return,
                                baseline_value=mean(baseline_returns),
                                details={
                                    "previous_close": previous.close,
                                    "close": point.close,
                                    "return_pct": pct_return * 100,
                                    "baseline_window": len(baseline_returns),
                                    "asset_class": asset_class,
                                },
                            )
                        )
                returns.append(pct_return)

            candle_range = (point.high - point.low) / point.close if point.close > 0 else 0.0
            baseline_ranges = [value for value in ranges[-lookback:] if value > 0]
            if len(baseline_ranges) >= min_baseline:
                median_range = median(baseline_ranges)
                ratio = candle_range / median_range if median_range > 0 else 0.0
                if ratio >= range_ratio:
                    events.append(
                        _build_event(
                            point=point,
                            anomaly_type="candle_range_spike",
                            severity=_severity(ratio),
                            score=ratio,
                            metric_value=candle_range,
                            baseline_value=median_range,
                            details={
                                "high": point.high,
                                "low": point.low,
                                "close": point.close,
                                "range_pct": candle_range * 100,
                                "range_ratio": ratio,
                                "asset_class": asset_class,
                            },
                        )
                    )
            ranges.append(candle_range)

            if point.volume is not None:
                baseline_volumes = [value for value in volumes[-lookback:] if value > 0]
                if len(baseline_volumes) >= min_baseline:
                    score = _zscore(point.volume, baseline_volumes)
                    volume_median = median(baseline_volumes)
                    ratio = point.volume / volume_median if volume_median > 0 else 0.0
                    trigger_score = max(score, ratio)
                    if score >= volume_z or ratio >= volume_ratio:
                        events.append(
                            _build_event(
                                point=point,
                                anomaly_type="volume_spike",
                                severity=_severity(trigger_score),
                                score=trigger_score,
                                metric_value=point.volume,
                                baseline_value=volume_median,
                                details={
                                    "volume_ratio": ratio,
                                    "baseline_window": len(baseline_volumes),
                                    "asset_class": asset_class,
                                },
                            )
                        )
                if point.volume > 0:
                    volumes.append(point.volume)

            previous = point

    return events
