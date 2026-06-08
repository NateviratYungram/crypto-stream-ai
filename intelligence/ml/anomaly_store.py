"""Persistence helpers for market data anomaly detection."""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras

TRACKED_TIMEFRAMES = ("1m", "5m", "15m", "1h", "1d")


def db_config() -> Dict[str, Any]:
    return {
        "host": os.getenv("DB_HOST", "postgres"),
        "port": int(os.getenv("DB_PORT", "5432")),
        "dbname": os.getenv("DB_NAME", os.getenv("POSTGRES_DB", "crypto_stream_db")),
        "user": os.getenv("DB_USER", os.getenv("POSTGRES_USER", "user")),
        "password": os.getenv("DB_PASS", os.getenv("POSTGRES_PASSWORD", "password")),
    }


def connect():
    return psycopg2.connect(**db_config())


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def ensure_anomaly_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS data_anomaly_events (
                id             BIGSERIAL PRIMARY KEY,
                event_key      VARCHAR(160) UNIQUE NOT NULL,
                symbol         VARCHAR(30) NOT NULL,
                timeframe      VARCHAR(5) NOT NULL,
                event_ts       TIMESTAMPTZ NOT NULL,
                anomaly_type   VARCHAR(60) NOT NULL,
                severity       VARCHAR(20) NOT NULL,
                score          DECIMAL(18, 6) NOT NULL,
                metric_value   DECIMAL(28, 10),
                baseline_value DECIMAL(28, 10),
                details        JSONB NOT NULL DEFAULT '{}'::jsonb,
                detected_at    TIMESTAMPTZ DEFAULT NOW()
            );
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_data_anomaly_events_recent
                ON data_anomaly_events (detected_at DESC, severity);
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_data_anomaly_events_symbol_ts
                ON data_anomaly_events (symbol, timeframe, event_ts DESC);
            """
        )
    conn.commit()


def fetch_recent_ohlcv(
    conn,
    lookback_hours: int = 72,
    max_rows: int = 15_000,
    timeframes: tuple[str, ...] = TRACKED_TIMEFRAMES,
) -> List[Dict[str, Any]]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT symbol, timeframe, ts, open, high, low, close, volume
            FROM market_ohlcv
            WHERE ts >= NOW() - (%s || ' hours')::interval
              AND timeframe = ANY(%s)
            ORDER BY symbol, timeframe, ts
            LIMIT %s;
            """,
            (lookback_hours, list(timeframes), max_rows),
        )
        return [dict(row) for row in cur.fetchall()]


def persist_anomaly_events_with_details(conn, events: List[Dict[str, Any]]) -> tuple[int, List[Dict[str, Any]]]:
    ensure_anomaly_schema(conn)
    if not events:
        return 0, []

    inserted = 0
    inserted_events: List[Dict[str, Any]] = []
    with conn.cursor() as cur:
        for event in events:
            cur.execute(
                """
                INSERT INTO data_anomaly_events (
                    event_key,
                    symbol,
                    timeframe,
                    event_ts,
                    anomaly_type,
                    severity,
                    score,
                    metric_value,
                    baseline_value,
                    details,
                    detected_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, NOW())
                ON CONFLICT (event_key) DO NOTHING;
                """,
                (
                    event["event_key"],
                    event["symbol"],
                    event["timeframe"],
                    event["event_ts"],
                    event["anomaly_type"],
                    event["severity"],
                    event["score"],
                    event["metric_value"],
                    event["baseline_value"],
                    json.dumps(event["details"], default=json_default),
                ),
            )
            if cur.rowcount:
                inserted += 1
                inserted_events.append(event)
    conn.commit()
    return inserted, inserted_events


def persist_anomaly_events(conn, events: List[Dict[str, Any]]) -> int:
    inserted, _inserted_events = persist_anomaly_events_with_details(conn, events)
    return inserted


def notify_critical_anomalies(events: List[Dict[str, Any]], max_events: int = 5) -> bool:
    """Send a compact Telegram notification for newly inserted CRITICAL anomalies."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    enabled = os.getenv("ANOMALY_NOTIFY_CRITICAL", "1").strip().lower() not in {
        "0",
        "false",
        "no",
    }
    critical_events = [event for event in events if event.get("severity") == "CRITICAL"]
    if not enabled or not token or not chat_id or not critical_events:
        return False

    top_events = sorted(
        critical_events,
        key=lambda event: abs(float(event.get("score") or 0)),
        reverse=True,
    )[:max_events]
    lines = [
        "CryptoStream AI anomaly alert",
        f"New CRITICAL anomalies: {len(critical_events)}",
    ]
    for event in top_events:
        lines.append(
            "- {symbol} {timeframe} {kind} score={score}".format(
                symbol=event["symbol"],
                timeframe=event["timeframe"],
                kind=event["anomaly_type"],
                score=event["score"],
            )
        )
    text = "\n".join(lines)

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode("utf-8")
    try:
        with urllib.request.urlopen(url, data=payload, timeout=5) as response:
            return 200 <= response.status < 300
    except Exception:
        return False


def fetch_anomaly_events(
    conn,
    symbol: Optional[str] = None,
    severity: Optional[str] = None,
    hours: int = 24,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    ensure_anomaly_schema(conn)
    filters = ["detected_at >= NOW() - (%s || ' hours')::interval"]
    params: List[Any] = [max(1, min(int(hours), 168))]

    if symbol:
        filters.append("symbol = %s")
        params.append(symbol.upper())
    if severity:
        filters.append("severity = %s")
        params.append(severity.upper())

    params.append(max(1, min(int(limit), 100)))
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT
                symbol,
                timeframe,
                event_ts,
                anomaly_type,
                severity,
                score,
                metric_value,
                baseline_value,
                details,
                detected_at
            FROM data_anomaly_events
            WHERE {" AND ".join(filters)}
            ORDER BY detected_at DESC, score DESC
            LIMIT %s;
            """,
            params,
        )
        rows = [dict(row) for row in cur.fetchall()]

    for row in rows:
        for key in ("event_ts", "detected_at"):
            if row.get(key):
                row[key] = row[key].isoformat()
        for key in ("score", "metric_value", "baseline_value"):
            if row.get(key) is not None:
                row[key] = float(row[key])
    return rows


def fetch_anomaly_summary(conn, hours: int = 24) -> Dict[str, Any]:
    ensure_anomaly_schema(conn)
    bounded_hours = max(1, min(int(hours), 168))
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE severity = 'CRITICAL') AS critical,
                COUNT(*) FILTER (WHERE severity = 'HIGH') AS high,
                COUNT(*) FILTER (WHERE anomaly_type = 'price_return_spike') AS price_spikes,
                COUNT(*) FILTER (WHERE anomaly_type = 'volume_spike') AS volume_spikes,
                COUNT(*) FILTER (WHERE anomaly_type = 'candle_range_spike') AS range_spikes,
                COUNT(*) FILTER (WHERE anomaly_type = 'missing_candle_gap') AS missing_gaps,
                MAX(detected_at) AS last_detected_at
            FROM data_anomaly_events
            WHERE detected_at >= NOW() - (%s || ' hours')::interval;
            """,
            (bounded_hours,),
        )
        summary = dict(cur.fetchone())

        cur.execute(
            """
            SELECT symbol, COUNT(*) AS count, MAX(score) AS max_score
            FROM data_anomaly_events
            WHERE detected_at >= NOW() - (%s || ' hours')::interval
            GROUP BY symbol
            ORDER BY count DESC, max_score DESC
            LIMIT 8;
            """,
            (bounded_hours,),
        )
        symbols = [dict(row) for row in cur.fetchall()]

    if summary.get("last_detected_at"):
        summary["last_detected_at"] = summary["last_detected_at"].isoformat()
    for key in ("total", "critical", "high", "price_spikes", "volume_spikes", "range_spikes", "missing_gaps"):
        summary[key] = int(summary.get(key) or 0)
    for row in symbols:
        row["count"] = int(row.get("count") or 0)
        row["max_score"] = float(row.get("max_score") or 0)

    return {"hours": bounded_hours, "summary": summary, "top_symbols": symbols}
