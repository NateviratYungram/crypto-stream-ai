from __future__ import annotations

import json
import os
from typing import Any


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _serialize_paper_trade(row) -> dict:
    current_price = float(row["current_price"] or row["entry_price"] or 0.0)
    entry_price = float(row["entry_price"] or 0.0)
    volume = float(row["volume"] or row["quantity"] or 0.0)
    if row["status"] == "OPEN":
        direction = 1 if row["side"] == "BUY" else -1
        pnl_usd = direction * (current_price - entry_price) * volume
    else:
        pnl_usd = float(row["pnl_usd"] if row["pnl_usd"] is not None else row["pnl"] or 0.0)

    features_payload = None
    try:
        raw_features = row["features_json"] if "features_json" in row.keys() else None
        if raw_features:
            features_payload = json.loads(raw_features)
    except Exception:
        features_payload = None

    return {
        "id": row["id"],
        "symbol": row["symbol"],
        "side": row["side"],
        "quantity": volume,
        "volume": volume,
        "entry_price": entry_price,
        "current_price": current_price,
        "exit_price": row["exit_price"],
        "pnl": pnl_usd,
        "pnl_usd": pnl_usd,
        "status": row["status"],
        "opened_at": row["opened_at"],
        "closed_at": row["closed_at"],
        "ml_score": row["ml_score"],
        "outcome": row["outcome"],
        "stop_loss": float(row["sl"]) if "sl" in row.keys() and row["sl"] is not None else None,
        "take_profit": float(row["tp"]) if "tp" in row.keys() and row["tp"] is not None else None,
        "signal_grade": row["signal_grade"] if "signal_grade" in row.keys() else None,
        "macro_bias": row["macro_bias"] if "macro_bias" in row.keys() else None,
        "features": features_payload,
        "entry_source": row["entry_source"] if "entry_source" in row.keys() else None,
        "entry_reason": row["entry_reason"] if "entry_reason" in row.keys() else None,
        "close_reason": row["close_reason"] if "close_reason" in row.keys() else None,
        "label_source": row["label_source"] if "label_source" in row.keys() else None,
    }


def _paper_summary(open_trades: list[dict], closed_trades: list[dict]) -> dict:
    labeled = [t for t in closed_trades if str(t.get("outcome") or "").upper() in {"WIN", "LOSS"}]
    wins = [t for t in labeled if str(t.get("outcome") or "").upper() == "WIN" or _num(t.get("pnl_usd")) > 0]
    losses = [t for t in labeled if str(t.get("outcome") or "").upper() == "LOSS" or _num(t.get("pnl_usd")) <= 0]
    gross_profit = sum(max(_num(t.get("pnl_usd")), 0.0) for t in labeled)
    gross_loss = abs(sum(min(_num(t.get("pnl_usd")), 0.0) for t in labeled))
    closed_pnl = sum(_num(t.get("pnl_usd")) for t in closed_trades)
    open_unrealized = sum(_num(t.get("pnl_usd")) for t in open_trades)
    profit_factor = None
    if gross_loss > 0:
        profit_factor = round(gross_profit / gross_loss, 4)
    elif gross_profit > 0:
        profit_factor = 999.0

    label_target = int(os.getenv("ML_READY_MIN_PAPER_LABELS", "100"))
    label_count = len(labeled)
    source_counts: dict[str, int] = {}
    symbol_counts: dict[str, int] = {}
    for trade in closed_trades + open_trades:
        source = str(trade.get("entry_source") or "manual_ui")
        symbol = str(trade.get("symbol") or "UNKNOWN").upper()
        source_counts[source] = source_counts.get(source, 0) + 1
        symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1

    return {
        "open_count": len(open_trades),
        "closed_count": len(closed_trades),
        "label_count": label_count,
        "label_target": label_target,
        "labels_remaining": max(label_target - label_count, 0),
        "label_progress_ratio": round(min(1.0, label_count / max(label_target, 1)), 4),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / label_count, 4) if label_count else None,
        "gross_profit": round(gross_profit, 4),
        "gross_loss": round(gross_loss, 4),
        "profit_factor": profit_factor,
        "expectancy_usd": round(closed_pnl / len(closed_trades), 4) if closed_trades else None,
        "closed_pnl_usd": round(closed_pnl, 4),
        "open_unrealized_pnl_usd": round(open_unrealized, 4),
        "top_sources": sorted(source_counts.items(), key=lambda item: item[1], reverse=True)[:6],
        "top_symbols": sorted(symbol_counts.items(), key=lambda item: item[1], reverse=True)[:8],
    }
