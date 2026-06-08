from __future__ import annotations

import json
import os
import re
import tempfile
import time
from typing import Any, Optional


DEFAULT_MARKET_CACHE_SNAPSHOT_DIR = os.path.join(tempfile.gettempdir(), "crypto-stream-ai", "market-cache")


def _cache_ttl_for(
    key: str,
    ttl: Optional[int] = None,
    *,
    ttl_rules: Optional[dict[str, int]] = None,
    default_ttl: int = 300,
) -> int:
    if ttl is not None:
        return ttl
    for prefix, configured_ttl in (ttl_rules or {}).items():
        if key == prefix or key.startswith(prefix):
            return configured_ttl
    return default_ttl


def _is_persistent_market_cache_key(key: str, persistent_keys: set[str] | None = None) -> bool:
    return any(key == prefix or key.startswith(prefix) for prefix in (persistent_keys or set()))


def _market_cache_snapshot_path(key: str, snapshot_dir: str = DEFAULT_MARKET_CACHE_SNAPSHOT_DIR) -> str:
    safe_key = re.sub(r"[^A-Za-z0-9_.-]+", "_", key)
    return os.path.join(snapshot_dir, f"{safe_key}.json")


def _read_market_cache_snapshot(
    key: str,
    *,
    is_persistent_key,
    snapshot_path_for,
    exists=os.path.exists,
    open_fn=open,
    load_fn=json.load,
    time_fn=time.time,
    warn_fn=None,
):
    if not is_persistent_key(key):
        return None
    path = snapshot_path_for(key)
    if not exists(path):
        return None
    try:
        with open_fn(path, "r", encoding="utf-8") as fh:
            payload = load_fn(fh)
        if not isinstance(payload, dict) or "data" not in payload:
            return None
        return {
            "data": payload.get("data"),
            "ts": float(payload.get("ts") or time_fn()),
            "ttl": payload.get("ttl"),
        }
    except Exception as exc:
        if warn_fn:
            warn_fn("Market cache snapshot read failed for %s: %s", key, exc)
        return None


def _write_market_cache_snapshot(
    key: str,
    data,
    *,
    ttl: Optional[int] = None,
    is_persistent_key,
    snapshot_dir: str = DEFAULT_MARKET_CACHE_SNAPSHOT_DIR,
    snapshot_path_for=None,
    makedirs=os.makedirs,
    open_fn=open,
    dump_fn=json.dump,
    time_fn=time.time,
    warn_fn=None,
):
    if not is_persistent_key(key):
        return
    try:
        makedirs(snapshot_dir, exist_ok=True)
        path_for = snapshot_path_for or (lambda value: _market_cache_snapshot_path(value, snapshot_dir))
        with open_fn(path_for(key), "w", encoding="utf-8") as fh:
            dump_fn({"data": data, "ts": time_fn(), "ttl": ttl}, fh, ensure_ascii=False)
    except Exception as exc:
        if warn_fn:
            warn_fn("Market cache snapshot write failed for %s: %s", key, exc)


def _cache_health_summary(
    keys: list[str],
    *,
    get_stale_entry,
    cache_ttl_for,
    payload_updated_at,
    utc_now_iso,
    time_fn=time.time,
) -> dict[str, Any]:
    items = {}
    now_ts = time_fn()
    for key in keys:
        entry = get_stale_entry(key)
        if not entry:
            items[key] = {
                "status": "missing",
                "data_quality": "unavailable",
                "updated_at": None,
                "age_seconds": None,
            }
            continue
        ttl = cache_ttl_for(key, ttl=entry.get("ttl"))
        age = max(0, int(now_ts - entry["ts"]))
        items[key] = {
            "status": "ok" if age < ttl else "stale",
            "data_quality": "live" if age < ttl else "stale",
            "updated_at": payload_updated_at(entry["data"], fallback_ts=entry.get("ts")),
            "age_seconds": age,
            "ttl_seconds": ttl,
        }
    return {
        "updated_at": utc_now_iso(),
        "items": items,
    }
