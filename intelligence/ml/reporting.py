import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

PROMOTION_DB = Path(os.getenv("PAPER_TRADE_DB", "persistence.db"))


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(PROMOTION_DB))
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    conn = _get_conn()
    try:
        yield conn
    finally:
        conn.close()


def ensure_reporting_tables() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ml_promotion_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trigger_reason TEXT,
                status TEXT,
                reason TEXT,
                accuracy REAL,
                roc_auc REAL,
                walk_forward_auc REAL,
                n_samples INTEGER,
                trained_at TEXT,
                override_reason TEXT,
                blockers_json TEXT,
                paper_label_quality_json TEXT,
                result_json TEXT,
                created_at TEXT
            )
            """
        )
        conn.commit()


def record_promotion_event(result: dict[str, Any], trigger_reason: str) -> dict[str, Any]:
    ensure_reporting_tables()
    promotion_gate = result.get("promotion_gate") or {}
    walk_forward_summary = ((result.get("walk_forward") or {}).get("summary") or {})
    row = {
        "trigger_reason": trigger_reason,
        "status": result.get("status"),
        "reason": result.get("reason"),
        "accuracy": result.get("accuracy"),
        "roc_auc": result.get("roc_auc"),
        "walk_forward_auc": walk_forward_summary.get("avg_roc_auc"),
        "n_samples": result.get("n_samples"),
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "override_reason": promotion_gate.get("override_reason"),
        "blockers_json": json.dumps(promotion_gate.get("blockers") or [], ensure_ascii=False),
        "paper_label_quality_json": json.dumps(result.get("paper_label_quality") or {}, ensure_ascii=False),
        "result_json": json.dumps(result, ensure_ascii=False, default=str),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO ml_promotion_history (
                trigger_reason, status, reason, accuracy, roc_auc, walk_forward_auc,
                n_samples, trained_at, override_reason, blockers_json,
                paper_label_quality_json, result_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["trigger_reason"],
                row["status"],
                row["reason"],
                row["accuracy"],
                row["roc_auc"],
                row["walk_forward_auc"],
                row["n_samples"],
                row["trained_at"],
                row["override_reason"],
                row["blockers_json"],
                row["paper_label_quality_json"],
                row["result_json"],
                row["created_at"],
            ),
        )
        conn.commit()
        row["id"] = cursor.lastrowid
    return row


def get_promotion_history(limit: int = 20) -> list[dict[str, Any]]:
    ensure_reporting_tables()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM ml_promotion_history
            ORDER BY id DESC
            LIMIT ?
            """,
            (max(1, min(int(limit), 200)),),
        ).fetchall()
    history: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        for key in ("blockers_json", "paper_label_quality_json", "result_json"):
            try:
                item[key[:-5] if key.endswith("_json") else key] = json.loads(item.get(key) or "null")
            except Exception:
                item[key[:-5] if key.endswith("_json") else key] = item.get(key)
        history.append(item)
    return history


def build_promotion_summary(limit: int = 20) -> dict[str, Any]:
    history = get_promotion_history(limit=limit)
    latest = history[0] if history else None
    promoted = [row for row in history if row.get("status") == "trained"]
    rejected = [row for row in history if row.get("status") == "rejected"]
    return {
        "available": bool(history),
        "count": len(history),
        "trained_count": len(promoted),
        "rejected_count": len(rejected),
        "latest": latest,
        "history": history,
    }
