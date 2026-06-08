from chat_server_cache_helpers import (
    _cache_health_summary,
    _cache_ttl_for,
    _is_persistent_market_cache_key,
    _market_cache_snapshot_path,
    _read_market_cache_snapshot,
    _write_market_cache_snapshot,
)


def test_cache_ttl_for_uses_override_rules_and_default():
    rules = {"market_sentiment_v1": 180, "prefix:": 60}

    assert _cache_ttl_for("x", ttl=5, ttl_rules=rules, default_ttl=300) == 5
    assert _cache_ttl_for("market_sentiment_v1", ttl_rules=rules, default_ttl=300) == 180
    assert _cache_ttl_for("prefix:item", ttl_rules=rules, default_ttl=300) == 60
    assert _cache_ttl_for("other", ttl_rules=rules, default_ttl=300) == 300


def test_is_persistent_market_cache_key_checks_prefixes():
    keys = {"market_sentiment_v1", "market_calendar_v1"}

    assert _is_persistent_market_cache_key("market_sentiment_v1", keys) is True
    assert _is_persistent_market_cache_key("market_calendar_v1:7", keys) is True
    assert _is_persistent_market_cache_key("other", keys) is False


def test_market_cache_snapshot_path_sanitizes_key():
    path = _market_cache_snapshot_path("market/calendar:v1?7", snapshot_dir="C:/tmp")

    assert path.endswith("market_calendar_v1_7.json")


def test_cache_health_summary_reports_missing_live_and_stale():
    entries = {
        "live": {"data": {"updated_at": "2026-05-26T00:00:00Z"}, "ts": 100.0, "ttl": 60},
        "stale": {"data": {}, "ts": 10.0, "ttl": 20},
    }

    result = _cache_health_summary(
        ["missing", "live", "stale"],
        get_stale_entry=lambda key: entries.get(key),
        cache_ttl_for=lambda key, ttl=None: ttl or 30,
        payload_updated_at=lambda payload, fallback_ts=None: payload.get("updated_at") or f"ts:{fallback_ts}",
        utc_now_iso=lambda: "2026-05-26T01:00:00Z",
        time_fn=lambda: 120.0,
    )

    assert result["updated_at"] == "2026-05-26T01:00:00Z"
    assert result["items"]["missing"]["status"] == "missing"
    assert result["items"]["live"]["status"] == "ok"
    assert result["items"]["live"]["ttl_seconds"] == 60
    assert result["items"]["stale"]["status"] == "stale"
    assert result["items"]["stale"]["updated_at"] == "ts:10.0"


def test_read_market_cache_snapshot_handles_missing_and_valid_payload(tmp_path):
    path = tmp_path / "market.json"
    path.write_text('{"data":{"x":1},"ts":10,"ttl":30}', encoding="utf-8")

    missing = _read_market_cache_snapshot(
        "missing",
        is_persistent_key=lambda key: False,
        snapshot_path_for=lambda key: str(path),
    )
    loaded = _read_market_cache_snapshot(
        "valid",
        is_persistent_key=lambda key: True,
        snapshot_path_for=lambda key: str(path),
    )

    assert missing is None
    assert loaded == {"data": {"x": 1}, "ts": 10.0, "ttl": 30}


def test_read_market_cache_snapshot_handles_invalid_payload_and_errors(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"wrong":1}', encoding="utf-8")
    warnings = []

    invalid = _read_market_cache_snapshot(
        "bad",
        is_persistent_key=lambda key: True,
        snapshot_path_for=lambda key: str(bad),
        warn_fn=lambda fmt, key, exc: warnings.append((fmt, key, str(exc))),
    )
    broken = _read_market_cache_snapshot(
        "broken",
        is_persistent_key=lambda key: True,
        snapshot_path_for=lambda key: str(bad),
        open_fn=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        warn_fn=lambda fmt, key, exc: warnings.append((fmt, key, str(exc))),
    )

    assert invalid is None
    assert broken is None
    assert warnings[-1][1] == "broken"


def test_write_market_cache_snapshot_respects_persistence_and_writes_file(tmp_path):
    path = tmp_path / "out.json"

    _write_market_cache_snapshot(
        "valid",
        {"x": 1},
        ttl=30,
        is_persistent_key=lambda key: True,
        snapshot_dir=str(tmp_path),
        snapshot_path_for=lambda key: str(path),
        time_fn=lambda: 55.0,
    )

    assert path.exists()
    assert '"ttl": 30' in path.read_text(encoding="utf-8")


def test_write_market_cache_snapshot_skips_or_warns(tmp_path):
    warnings = []
    skipped = tmp_path / "skipped.json"
    _write_market_cache_snapshot(
        "skip",
        {"x": 1},
        is_persistent_key=lambda key: False,
        snapshot_dir=str(tmp_path),
        snapshot_path_for=lambda key: str(skipped),
    )
    assert not skipped.exists()

    _write_market_cache_snapshot(
        "warn",
        {"x": 1},
        is_persistent_key=lambda key: True,
        snapshot_dir=str(tmp_path),
        snapshot_path_for=lambda key: str(tmp_path / "warn.json"),
        makedirs=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("nope")),
        warn_fn=lambda fmt, key, exc: warnings.append((fmt, key, str(exc))),
    )
    assert warnings[-1][1] == "warn"
