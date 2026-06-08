import os
import sqlite3
import time
from contextlib import contextmanager
from typing import Any

from intelligence.ml.performance_feedback import get_feedback_snapshot

_CACHE_TTL_SECONDS = 60
_policy_cache: dict[str, Any] = {"loaded_at": 0.0, "payload": None}
_POLICY_DB = os.getenv("PAPER_TRADE_DB", "persistence.db")


@contextmanager
def _connect() -> Any:
    conn = sqlite3.connect(_POLICY_DB)
    try:
        yield conn
    finally:
        conn.close()


def _normalize_symbol(symbol: str) -> str:
    normalized = str(symbol or "").upper().strip()
    if normalized.endswith("USDT"):
        normalized = normalized[:-4]
    return normalized


def _normalize_side(side: str) -> str:
    return str(side or "").upper().strip()


def _parse_block_overrides(raw: str) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for item in str(raw or "").split(","):
        token = item.strip()
        if not token or ":" not in token:
            continue
        symbol, side = token.split(":", 1)
        symbol = _normalize_symbol(symbol)
        side = _normalize_side(side)
        if symbol and side:
            pairs.add((symbol, side))
    return pairs


def _parse_reduce_overrides(raw: str) -> dict[tuple[str, str], float]:
    pairs: dict[tuple[str, str], float] = {}
    for item in str(raw or "").split(","):
        token = item.strip()
        if not token:
            continue
        parts = token.split(":")
        if len(parts) != 3:
            continue
        symbol = _normalize_symbol(parts[0])
        side = _normalize_side(parts[1])
        try:
            multiplier = max(0.0, min(float(parts[2]), 1.0))
        except Exception:
            continue
        if symbol and side:
            pairs[(symbol, side)] = multiplier
    return pairs


def _ensure_override_table() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ml_symbol_policy_overrides (
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                action TEXT NOT NULL,
                size_multiplier REAL,
                note TEXT,
                updated_at TEXT,
                PRIMARY KEY(symbol, side)
            )
            """
        )
        conn.commit()


def _db_overrides() -> tuple[set[tuple[str, str]], dict[tuple[str, str], float], dict[tuple[str, str], str]]:
    _ensure_override_table()
    block_pairs: set[tuple[str, str]] = set()
    reduce_pairs: dict[tuple[str, str], float] = {}
    notes: dict[tuple[str, str], str] = {}
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT symbol, side, action, size_multiplier, note FROM ml_symbol_policy_overrides").fetchall()
    for row in rows:
        symbol = _normalize_symbol(row["symbol"])
        side = _normalize_side(row["side"])
        action = str(row["action"] or "").strip().lower()
        note = str(row["note"] or "").strip()
        if note:
            notes[(symbol, side)] = note
        if action == "block":
            block_pairs.add((symbol, side))
        elif action == "reduce":
            try:
                reduce_pairs[(symbol, side)] = max(0.0, min(float(row["size_multiplier"] or 0.5), 1.0))
            except Exception:
                reduce_pairs[(symbol, side)] = 0.5
    return block_pairs, reduce_pairs, notes


def _derive_policy(snapshot: dict[str, Any]) -> dict[str, Any]:
    block_overrides = _parse_block_overrides(os.getenv("ML_SYMBOL_SIDE_BLOCKLIST", ""))
    reduce_overrides = _parse_reduce_overrides(os.getenv("ML_SYMBOL_SIDE_REDUCE", ""))
    db_block_overrides, db_reduce_overrides, db_notes = _db_overrides()
    block_overrides |= db_block_overrides
    reduce_overrides = {**reduce_overrides, **db_reduce_overrides}

    rows: list[dict[str, Any]] = []
    symbol_side = snapshot.get("symbol_side") or {}

    for key, stats in symbol_side.items():
        symbol, _, side = str(key).partition(":")
        symbol = _normalize_symbol(symbol)
        side = _normalize_side(side)
        trades = int(stats.get("trades", 0) or 0)
        win_rate = float(stats.get("win_rate", 0.0) or 0.0)
        pnl = float(stats.get("pnl", 0.0) or 0.0)
        avg_pnl = float(stats.get("avg_pnl", 0.0) or 0.0)

        action = "allow"
        size_multiplier = 1.0
        reasons: list[str] = []

        if (symbol, side) in block_overrides:
            action = "block"
            size_multiplier = 0.0
            reasons.append("manual_block_override")
        elif (symbol, side) in reduce_overrides:
            action = "reduce"
            size_multiplier = reduce_overrides[(symbol, side)]
            reasons.append("manual_reduce_override")
        elif trades >= 3:
            if pnl < 0 and (win_rate < 40.0 or avg_pnl <= -0.25):
                action = "block"
                size_multiplier = 0.0
                reasons.append("weak_symbol_side_block")
            elif pnl < 0 or win_rate < 50.0 or avg_pnl < 0:
                action = "reduce"
                size_multiplier = 0.5 if pnl < -1.0 else 0.7
                reasons.append("weak_symbol_side_reduce")

        rows.append(
            {
                "key": f"{symbol}:{side}",
                "symbol": symbol,
                "side": side,
                "action": action,
                "size_multiplier": round(float(size_multiplier), 3),
                "trades": trades,
                "win_rate": round(win_rate, 4),
                "pnl": round(pnl, 6),
                "avg_pnl": round(avg_pnl, 6),
                "reasons": reasons,
                "note": db_notes.get((symbol, side), ""),
            }
        )

    rows.sort(key=lambda row: ({"block": 0, "reduce": 1, "allow": 2}.get(row["action"], 3), row["symbol"], row["side"]))
    summary = {
        "blocked": len([row for row in rows if row["action"] == "block"]),
        "reduced": len([row for row in rows if row["action"] == "reduce"]),
        "allowed": len([row for row in rows if row["action"] == "allow"]),
        "manual_block_overrides": len(block_overrides),
        "manual_reduce_overrides": len(reduce_overrides),
    }
    return {
        "available": True,
        "updated_at": time.time(),
        "rows": rows,
        "summary": summary,
        "overrides": {
            "block": sorted(f"{symbol}:{side}" for symbol, side in block_overrides),
            "reduce": {
                f"{symbol}:{side}": multiplier for (symbol, side), multiplier in sorted(reduce_overrides.items())
            },
        },
    }


def get_symbol_policy_snapshot(force_refresh: bool = False) -> dict[str, Any]:
    now = time.time()
    if (
        not force_refresh
        and _policy_cache["payload"] is not None
        and now - float(_policy_cache["loaded_at"] or 0.0) < _CACHE_TTL_SECONDS
    ):
        return _policy_cache["payload"]

    snapshot = get_feedback_snapshot(force_refresh=force_refresh)
    payload = _derive_policy(snapshot)
    _policy_cache["loaded_at"] = now
    _policy_cache["payload"] = payload
    return payload


def get_symbol_policy(symbol: str, side: str, force_refresh: bool = False) -> dict[str, Any]:
    normalized_symbol = _normalize_symbol(symbol)
    normalized_side = _normalize_side(side)
    snapshot = get_symbol_policy_snapshot(force_refresh=force_refresh)
    for row in snapshot.get("rows", []):
        if row.get("symbol") == normalized_symbol and row.get("side") == normalized_side:
            return row
    db_block_overrides, db_reduce_overrides, db_notes = _db_overrides()
    key = (normalized_symbol, normalized_side)
    if key in db_block_overrides:
        return {
            "key": f"{normalized_symbol}:{normalized_side}",
            "symbol": normalized_symbol,
            "side": normalized_side,
            "action": "block",
            "size_multiplier": 0.0,
            "trades": 0,
            "win_rate": 0.0,
            "pnl": 0.0,
            "avg_pnl": 0.0,
            "reasons": ["manual_block_override"],
            "note": db_notes.get(key, ""),
        }
    if key in db_reduce_overrides:
        return {
            "key": f"{normalized_symbol}:{normalized_side}",
            "symbol": normalized_symbol,
            "side": normalized_side,
            "action": "reduce",
            "size_multiplier": round(float(db_reduce_overrides[key]), 3),
            "trades": 0,
            "win_rate": 0.0,
            "pnl": 0.0,
            "avg_pnl": 0.0,
            "reasons": ["manual_reduce_override"],
            "note": db_notes.get(key, ""),
        }
    return {
        "key": f"{normalized_symbol}:{normalized_side}",
        "symbol": normalized_symbol,
        "side": normalized_side,
        "action": "allow",
        "size_multiplier": 1.0,
        "trades": 0,
        "win_rate": 0.0,
        "pnl": 0.0,
        "avg_pnl": 0.0,
        "reasons": [],
        "note": "",
    }


def refresh_symbol_policy_cache() -> dict[str, Any]:
    return get_symbol_policy_snapshot(force_refresh=True)


def upsert_symbol_policy_override(symbol: str, side: str, action: str, size_multiplier: float | None = None, note: str = "") -> dict[str, Any]:
    normalized_symbol = _normalize_symbol(symbol)
    normalized_side = _normalize_side(side)
    action = str(action or "").strip().lower()
    if action not in {"block", "reduce", "allow"}:
        raise ValueError("action must be block, reduce, or allow")
    _ensure_override_table()
    with _connect() as conn:
        if action == "allow":
            conn.execute(
                "DELETE FROM ml_symbol_policy_overrides WHERE symbol = ? AND side = ?",
                (normalized_symbol, normalized_side),
            )
        else:
            conn.execute(
                """
                INSERT INTO ml_symbol_policy_overrides (symbol, side, action, size_multiplier, note, updated_at)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(symbol, side) DO UPDATE SET
                    action=excluded.action,
                    size_multiplier=excluded.size_multiplier,
                    note=excluded.note,
                    updated_at=excluded.updated_at
                """,
                (
                    normalized_symbol,
                    normalized_side,
                    action,
                    None if action == "block" else max(0.0, min(float(size_multiplier if size_multiplier is not None else 0.5), 1.0)),
                    note,
                ),
            )
        conn.commit()
    return get_symbol_policy(normalized_symbol, normalized_side, force_refresh=True)


def list_symbol_policy_overrides() -> list[dict[str, Any]]:
    _ensure_override_table()
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT symbol, side, action, size_multiplier, note, updated_at FROM ml_symbol_policy_overrides ORDER BY symbol, side"
        ).fetchall()
    return [dict(row) for row in rows]
